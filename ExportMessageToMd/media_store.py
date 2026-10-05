"""One pathname per identical attachment, with archive-wide link migration."""
from collections import defaultdict
from contextlib import closing
import hashlib
from html import escape, unescape
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from urllib.parse import unquote, urlsplit
import uuid
import zipfile

from config_loader import path_rel
from dialog_dirs import collect_dialog_dirs
from video_cache import source_rows


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, str(stat.st_dev), str(stat.st_ino)


def rewrite_media_links(text, md, mapping):
    def convert(url):
        value = unescape(url)
        if urlsplit(value).scheme or value.startswith(('//', '#')):
            return url
        path = (md.parent / unquote(value.replace('\\', '/'))).resolve()
        return path_rel(str(mapping[path]), str(md.parent)) if path in mapping else url

    def markdown(match):
        label, url = match.groups()
        new = convert(url)
        return '[' + (new if label == url else label) + '](' + new + ')'

    def attribute(match):
        prefix, quote, url = match.groups()
        new = convert(url)
        return prefix + quote + (escape(new, quote=True) if new != url else url) + quote

    pattern = r'[^()\n]*(?:\([^()\n]*\)[^()\n]*)*'
    text = re.sub(r'\[([^\]]*)\]\((' + pattern + r')\)', markdown, text)
    return re.sub(r'((?:src|href)\s*=\s*)([\"\'])(.*?)\2', attribute, text)


def shared_avatars(root):
    root = Path(root).resolve()
    database = root / 'MediaIndex.sqlite3'
    if not database.is_file():
        return {}
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT author_id,path FROM media_avatars').fetchall()
        return {author: root / relative for author, relative in rows
                if (root / relative).resolve().is_relative_to(root) and (root / relative).is_file()}
    except sqlite3.OperationalError:
        return {}


class MediaStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.shared = self.root / 'LargeRawData/SharedMedia'
        self.db = sqlite3.connect(str(self.root / 'MediaIndex.sqlite3'), timeout=30)
        self.db.execute('CREATE TABLE IF NOT EXISTS media_hashes(path TEXT PRIMARY KEY,size INTEGER,mtime INTEGER,device TEXT,inode TEXT,digest TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS media_avatars(author_id INTEGER PRIMARY KEY,path TEXT,url_hash TEXT)')
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def avatar(self, author_id):
        row = self.db.execute('SELECT path FROM media_avatars WHERE author_id=?', (author_id,)).fetchone()
        if row:
            path = (self.root / row[0]).resolve()
            if path.is_relative_to(self.root) and path.is_file():
                return path
        return None

    def set_avatar(self, author_id, path, url=''):
        relative = Path(path).resolve().relative_to(self.root).as_posix()
        self.db.execute('INSERT OR REPLACE INTO media_avatars VALUES (?,?,?)',
                        (author_id, relative, hashlib.sha256(url.encode()).hexdigest() if url else ''))
        self.db.commit()

    def _digest(self, path, snap):
        relative = path.relative_to(self.root).as_posix()
        row = self.db.execute('SELECT size,mtime,device,inode,digest FROM media_hashes WHERE path=?', (relative,)).fetchone()
        if row and tuple(row[:4]) == snap:
            return row[4]
        digest = file_hash(path)
        if signature(path) != snap:
            raise RuntimeError('Медиафайл изменился во время проверки; объединение отменено.')
        self.db.execute('INSERT OR REPLACE INTO media_hashes VALUES (?,?,?,?,?,?)', (relative,) + snap + (digest,))
        return digest

    def _files(self, config):
        bases = [self.root / 'LargeRawData', self.root / 'ExportMessages/Dialogs/AutorImages']
        bases.extend(d / 'RawData' for d in collect_dialog_dirs(self.root / 'ExportMessages/Dialogs', config).values())
        for base in bases:
            for path in base.rglob('*'):
                if not path.is_file() or not path.stat().st_size:
                    continue
                if any(p == '.downloads' or p.startswith('.audio-') for p in path.parts):
                    continue
                if path.name.endswith(('.part', '.tmp', '.copying', '.photo-tmp')) or any(marker in path.name for marker in ('.downloading.', '.photo-upgrade.')):
                    continue
                if path.resolve() != path.absolute() or not path.resolve().is_relative_to(base.resolve()):
                    raise RuntimeError('Путь к медиа выходит за пределы архива.')
                yield path

    def consolidate(self, config):
        by_size = defaultdict(list)
        snapshots = {}
        for path in self._files(config):
            snap = signature(path)
            snapshots[path] = snap
            by_size[snap[0]].append(path)
        groups = []
        hashes = {}
        for paths in by_size.values():
            if len(paths) < 2:
                continue
            by_hash = defaultdict(list)
            for path in paths:
                physical = snapshots[path]
                digest = hashes.get(physical)
                if digest is None:
                    digest = self._digest(path, physical)
                    hashes[physical] = digest
                by_hash[digest].append(path)
            for digest, identical in by_hash.items():
                if len(identical) < 2:
                    continue
                source = min(identical, key=lambda p: (not p.is_relative_to(self.shared), str(p)))
                ext = source.suffix.lower()
                ext = '.jpg' if ext == '.jpeg' else ext
                kind = ('videos' if ext in ('.mp4', '.webm', '.mkv', '.mov') else
                        'images' if ext in ('.jpg', '.png', '.gif', '.webp', '.avif', '.svg', '.ico') else
                        'audio' if ext in ('.mp3', '.m4a', '.ogg', '.wav', '.opus', '.flac') else 'docs')
                target = self.shared / kind / ('sha256_' + digest + ext)
                if target.resolve() != target.absolute() or not target.resolve().is_relative_to(self.shared.resolve()):
                    raise RuntimeError('Общее хранилище находится за пределами архива.')
                if target.exists() and target not in identical:
                    if file_hash(target) != digest:
                        raise RuntimeError('Несовпадение содержимого общего файла.')
                groups.append((identical, source, target, digest))
        mapping = {p: target for paths, source, target, digest in groups for p in paths if p != target}
        self.db.commit()
        if not mapping:
            return {'groups': 0, 'removed_paths': 0, 'changed_markdown': 0}
        edits = []
        avatar_urls = {}
        for directory in collect_dialog_dirs(self.root / 'ExportMessages/Dialogs', config).values():
            for md in (directory / 'MdFiles').rglob('*.md'):
                old = md.read_bytes()
                text = old.decode('utf-8')
                new = rewrite_media_links(text, md, mapping).encode('utf-8')
                for label, local, remote in source_rows(text):
                    if label.startswith('Аватар') and local:
                        avatar_urls[(md.parent / local).resolve()] = remote
                if old != new:
                    edits.append((md, old, new))
        for path in mapping:
            if signature(path) != snapshots[path]:
                raise RuntimeError('Медиафайл изменился; старые пути сохранены.')
        for md, old, new in edits:
            if md.read_bytes() != old:
                raise RuntimeError('Сообщение изменилось; пользовательские правки сохранены.')
        backup = self.root.parent / ('media-links-backup-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.zip')
        manifest = {str(p.relative_to(self.root)): str(t.relative_to(self.root)) for p, t in mapping.items()}
        with zipfile.ZipFile(backup, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for md, old, new in edits:
                archive.writestr(md.relative_to(self.root).as_posix(), old)
            archive.writestr('media-paths.json', json.dumps(manifest, ensure_ascii=False))
        for paths, source, target, digest in groups:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                try:
                    os.link(source, target)
                except OSError:
                    temporary = target.with_suffix('.copying')
                    shutil.copy2(source, temporary)
                    if file_hash(temporary) != digest:
                        raise RuntimeError('Проверка общего файла не пройдена.')
                    os.replace(temporary, target)
            if not os.path.samefile(source, target) and file_hash(target) != digest:
                raise RuntimeError('Проверка общего файла не пройдена.')
        # Preserve avatar lookup even after the ID-named old files are removed.
        avatar_dir = self.root / 'ExportMessages/Dialogs/AutorImages'
        for old, target in mapping.items():
            if old.parent == avatar_dir and old.stem.lstrip('-').isdigit():
                self.set_avatar(int(old.stem), target, avatar_urls.get(old, ''))
        for md, old, new in edits:
            if md.read_bytes() != old:
                raise RuntimeError('Сообщение изменилось; исходные медиа ещё не удалены.')
            temporary = md.with_suffix('.md.shared-tmp')
            temporary.write_bytes(new)
            os.replace(temporary, md)
        for directory in collect_dialog_dirs(self.root / 'ExportMessages/Dialogs', config).values():
            for md in (directory / 'MdFiles').rglob('*.md'):
                text = md.read_bytes().decode('utf-8')
                if rewrite_media_links(text, md, mapping) != text:
                    raise RuntimeError('Осталась ссылка на старый путь; исходные медиа сохранены.')
        for old in mapping:
            if signature(old) != snapshots[old] or old.resolve() != old.absolute() or not old.is_relative_to(self.root):
                raise RuntimeError('Медиа изменилось перед удалением старого пути.')
        has_videos = self.db.execute("SELECT name FROM sqlite_master WHERE name='videos'").fetchone()
        for old, target in mapping.items():
            old_rel = old.relative_to(self.root).as_posix()
            target_rel = target.relative_to(self.root).as_posix()
            stat = target.stat()
            if has_videos:
                self.db.execute('INSERT OR REPLACE INTO videos SELECT identity,?,quality,?,? FROM videos WHERE path=?',
                                (target_rel, stat.st_size, stat.st_mtime_ns, old_rel))
                self.db.execute('DELETE FROM videos WHERE path=?', (old_rel,))
            self.db.execute('UPDATE media_avatars SET path=? WHERE path=?', (target_rel, old_rel))
            old.unlink()
            self.db.execute('DELETE FROM media_hashes WHERE path=?', (old_rel,))
        self.db.commit()
        for paths, source, target, digest in groups:
            self.db.execute('INSERT OR REPLACE INTO media_hashes VALUES (?,?,?,?,?,?)',
                            (target.relative_to(self.root).as_posix(),) + signature(target) + (digest,))
        self.db.commit()
        for base in [self.root / 'LargeRawData'] + [d / 'RawData' for d in collect_dialog_dirs(self.root / 'ExportMessages/Dialogs', config).values()]:
            for directory, children, files in os.walk(base, topdown=False):
                path = Path(directory)
                if path.resolve() != path.absolute() or not path.resolve().is_relative_to(self.root):
                    raise RuntimeError('Папка медиа выходит за пределы архива.')
                if path != base and not any(path.iterdir()):
                    path.rmdir()
        return {'groups': len(groups), 'removed_paths': len(mapping), 'changed_markdown': len(edits), 'markdown_backup': str(backup)}
