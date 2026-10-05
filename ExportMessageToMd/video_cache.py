"""Archive-wide video reuse, with stable shared paths and an incremental index."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
from urllib.parse import parse_qs, urlsplit

from config_loader import path_rel
from dialog_dirs import collect_dialog_dirs


def video_key(video):
    owner, ident = video.get("owner_id"), video.get("id")
    if owner and ident:
        try:
            return "vk-video:%d:%d" % (int(owner), int(ident))
        except (ValueError, TypeError):
            pass
    player = video.get("player") or ""
    try:
        parsed = urlsplit(player)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        if parsed.hostname in ("vk.ru", "vk.com", "www.vk.ru", "www.vk.com", "vkvideo.ru", "vkvideo.com"):
            args = parse_qs(parsed.query)
            if parsed.path == "/video_ext.php":
                return "vk-video:%d:%d" % (int(args["oid"][0]), int(args["id"][0]))
            match = re.fullmatch(r"/video(-?\d+)_(\d+)", parsed.path)
            if match:
                return "vk-video:%s:%s" % match.groups()
    except (ValueError, KeyError, TypeError):
        return ""
    # Legacy exports may contain only an opaque player URL. Compare it exactly.
    return "player:" + hashlib.sha256(player.encode("utf-8")).hexdigest()


def video_quality(files, url=None):
    qualities = []
    for key, value in (files or {}).items():
        match = re.fullmatch(r"mp4_(\d+)", key)
        if match and isinstance(value, str) and (url is None or url == value):
            try:
                parsed = urlsplit(value)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    qualities.append(int(match[1]))
            except ValueError:
                pass
    return max(qualities, default=0)


def mp4_quality(path):
    """Read MP4 track dimensions by seeking over boxes, never reading video data.

    None means malformed/incomplete; 0 means no usable dimension metadata.
    """
    try:
        size = path.stat().st_size
        found_header = False
        qualities = []
        budget = [10000]
        with path.open("rb") as source:
            def walk(first, last, depth=0):
                nonlocal found_header
                offset = first
                while offset < last:
                    budget[0] -= 1
                    if budget[0] < 0 or last - offset < 8:
                        raise ValueError("Incomplete MP4 box")
                    source.seek(offset)
                    length, kind = struct.unpack(">I4s", source.read(8))
                    header = 8
                    if length == 1:
                        length = struct.unpack(">Q", source.read(8))[0]
                        header = 16
                    elif length == 0:
                        length = last - offset
                    end = offset + length
                    if length < header or end > last:
                        raise ValueError("Incomplete MP4 box")
                    if kind == b"ftyp" and depth == 0:
                        found_header = True
                    if kind in (b"moov", b"trak") and depth < 3:
                        walk(offset + header, end, depth + 1)
                    elif kind == b"tkhd" and length >= header + 8:
                        source.seek(end - 8)
                        width, height = struct.unpack(">II", source.read(8))
                        if width and height:
                            qualities.append(min(width >> 16, height >> 16))
                    offset = end
            walk(0, size)
        return max(qualities, default=0) if found_header else None
    except (OSError, ValueError, struct.error):
        return None


def walk_videos(node):
    if isinstance(node, list):
        for child in node:
            yield from walk_videos(child)
    elif isinstance(node, dict):
        if node.get("type") in ("video", "short_video"):
            data = node.get("video") or node.get("short_video")
            if isinstance(data, dict):
                yield data
                return
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from walk_videos(child)


def source_rows(text):
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        local = re.fullmatch(r"\[.*?\]\((.*)\)", cells[1])
        remote = re.fullmatch(r"\[.*?\]\((.*)\)", cells[2])
        yield cells[0], local[1] if local else "", remote[1] if remote else ""


class VideoPaths(dict):
    """Keep the renderer's URL map API while sharing one cache across dialogs."""
    def __init__(self, video_cache):
        super().__init__()
        self.video_cache = video_cache


class VideoCache:
    def __init__(self, export_root, logger):
        self.root = Path(export_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.shared = self.root / "LargeRawData/SharedMedia/videos"
        self.logger = logger
        self.reused = self.reused_bytes = 0
        self.db = sqlite3.connect(str(self.root / "MediaIndex.sqlite3"), timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS videos (identity TEXT, path TEXT, quality INTEGER, size INTEGER, mtime INTEGER, PRIMARY KEY(identity,path))")
        self.db.execute("CREATE TABLE IF NOT EXISTS scans (path TEXT PRIMARY KEY, stamp TEXT)")
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def _allowed(self, path):
        path = path.resolve()
        return (path.is_relative_to(self.root / "LargeRawData")
                or path.is_relative_to(self.root / "ExportMessages/Dialogs")) and path.suffix.lower() == ".mp4"

    def register(self, path, video, quality=None, commit=True):
        return self._register(path, video_key(video), quality, commit)

    def _register(self, path, identity, quality=None, commit=True):
        path = Path(path).resolve()
        if not identity or not self._allowed(path):
            return False
        actual = mp4_quality(path)
        if actual is None:
            return False
        # Existing files must have measured quality; never infer it from a
        # newer JSON URL. A fresh, completed download can use its selected tier.
        tier = actual or quality or 0
        info = path.stat()
        self.db.execute("INSERT OR REPLACE INTO videos VALUES (?,?,?,?,?)",
                        (identity, path.relative_to(self.root).as_posix(), tier, info.st_size, info.st_mtime_ns))
        if commit:
            self.db.commit()
        return True

    def scan(self, config):
        changed = 0
        for directory in collect_dialog_dirs(self.root / "ExportMessages/Dialogs", config).values():
            originals = {}
            for original in (directory / "OriginalMessages").glob("*.json"):
                match = re.search(r"_(\d+)\.json$", original.name)
                if match:
                    originals[int(match[1])] = original
            for md in (directory / "MdFiles").rglob("*.md"):
                match = re.search(r"(?:^|\.)Id(\d+)(?:_part_\d+)?\.md$", md.name)
                original = originals.get(int(match[1])) if match else None
                if original is None:
                    continue
                try:
                    m, o = md.stat(), original.stat()
                    stamp = f"{m.st_mtime_ns}:{m.st_size}:{o.st_mtime_ns}:{o.st_size}"
                    relative = md.relative_to(self.root).as_posix()
                    previous = self.db.execute("SELECT stamp FROM scans WHERE path=?", (relative,)).fetchone()
                    if previous and previous[0] == stamp:
                        continue
                    rows = [(local, remote) for label, local, remote in source_rows(md.read_text(encoding="utf-8"))
                            if label == "Видео" and local and remote]
                    if rows:
                        videos = list(walk_videos(json.loads(original.read_text(encoding="utf-8"))))
                        for local, remote in rows:
                            identity = video_key({"player": remote})
                            data = next((v for v in videos if v.get("player") == remote or video_key(v) == identity), None)
                            if data is not None:
                                self.register(md.parent / local, data, commit=False)
                    self.db.execute("INSERT OR REPLACE INTO scans VALUES (?,?)", (relative, stamp))
                    changed += 1
                except (OSError, ValueError):
                    # Partial JSON/MD may still be written by an export. Retry
                    # next time instead of marking it as already indexed.
                    continue
        self.db.commit()
        count = self.db.execute("SELECT COUNT(DISTINCT identity) FROM videos").fetchone()[0]
        return changed, count

    def target(self, video, quality):
        identity = video_key(video)
        if not identity:
            return None
        return self._target(identity, quality)

    def _target(self, identity, quality):
        digest = hashlib.sha256(f"{identity}:{quality}".encode("utf-8")).hexdigest()
        target = (self.shared / (digest + ".mp4")).resolve()
        if not self._allowed(target):
            raise ValueError("Общее хранилище видео находится за пределами архива")
        return target

    def preserve_directory(self, directory):
        """Protect indexed files before the exporter rebuilds a message folder."""
        directory = Path(directory).resolve()
        if not directory.is_relative_to(self.root) or not directory.is_dir():
            return
        prefix = directory.relative_to(self.root).as_posix() + "/"
        rows = self.db.execute("SELECT identity,path,quality FROM videos").fetchall()
        for identity, relative, tier in rows:
            if relative.startswith(prefix):
                source = self.root / relative
                actual = mp4_quality(source)
                if actual is None:
                    continue
                if source.is_file() and self._share(source, identity, actual or tier, source.stat().st_size) is None:
                    raise OSError("Не удалось сохранить видео перед перезаписью сообщения")

    def _share(self, source, identity, tier, size):
        if source.parent == self.shared and source.name.startswith('sha256_'):
            return source if self._register(source, identity, tier) else None
        target = self._target(identity, tier)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            if not target.exists():
                # Same NTFS volume: a second name, no extra video bytes.
                # A copy is needed on filesystems without hard links.
                try:
                    os.link(source, target)
                except FileExistsError:
                    pass
                except OSError:
                    temporary = target.with_suffix(".copying")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
            actual = mp4_quality(target)
            if target.stat().st_size != size or actual is None or (actual and actual < tier):
                return None
            if not self._register(target, identity, tier):
                return None
        return target

    def find(self, video, quality):
        identity = video_key(video)
        if not identity:
            return None
        rows = self.db.execute("SELECT path,quality,size,mtime FROM videos WHERE identity=? ORDER BY quality DESC", (identity,)).fetchall()
        for relative, tier, size, mtime in rows:
            source = (self.root / relative).resolve()
            try:
                info = source.stat()
                if not self._allowed(source) or not size or info.st_size != size or info.st_mtime_ns != mtime:
                    with self.db:
                        self.db.execute("DELETE FROM videos WHERE identity=? AND path=?", (identity, relative))
                    continue
                if tier < quality:
                    continue
                target = self._share(source, identity, tier, size)
                if target is None:
                    continue
                self.reused += 1
                self.reused_bytes += size
                return target
            except OSError as error:
                self.logger.LogWarning("Не удалось повторно использовать сохранённое видео: " + str(error))
        return None
