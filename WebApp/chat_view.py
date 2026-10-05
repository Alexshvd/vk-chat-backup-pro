"""Read-only conversation view built from the archive's JSON and local media.

No renderer/downloader is called here: opening a conversation cannot start an
export or modify the archive. Markdown source tables connect VK URLs to files.
"""
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from dialog_dirs import collect_dialog_dirs
from audio_media import audio_payload, audio_sources
from media_store import shared_avatars

CID_PATTERN = re.compile(r"(?:^|\.)Id(\d+)(?:_part_\d+)?\.md$")
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "avif"}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        # An export may still be writing a file. It will appear on refresh.
        return {}


def safe_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in ("http", "https") and parsed.netloc else ""


def local_url(path, export_root, large_root):
    path = path.resolve()
    if not path.is_file():
        return ""
    for root, mount in ((export_root, "/export/"), (large_root, "/large/")):
        try:
            relative = path.relative_to(root.resolve())
            return mount + quote(relative.as_posix(), safe="/")
        except ValueError:
            continue
    return ""


def markdown_target(cell):
    match = re.fullmatch(r"\[.*?\]\((.*)\)", cell.strip())
    return match.group(1) if match else ""


def media_index(md_files, export_root, large_root):
    result = {}
    for path in md_files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.startswith("|"):
                continue
            cells = line.strip().strip("|").split("|")
            if len(cells) != 3:
                continue
            relative, remote = markdown_target(cells[1]), markdown_target(cells[2])
            if not relative or not safe_url(remote) or safe_url(relative):
                continue
            url = local_url(path.parent / relative, export_root, large_root)
            if url:
                result[remote] = url
    return result


class ChatArchive:
    def __init__(self, config, peer_id=None):
        self.config = config
        self.root = Path(config.export_root).resolve()
        self.export_root = self.root / "ExportMessages"
        self.large_root = self.root / "LargeRawData"
        self.dirs = collect_dialog_dirs(self.export_root / "Dialogs", config)
        self.messages = {}
        self.authors = {}
        for path in sorted((self.export_root / "Sources").glob("*.json")):
            data = read_json(path)
            if not isinstance(data, dict):
                continue
            pid = data.get("peer_id")
            if isinstance(pid, int) and (peer_id is None or peer_id == pid):
                for item in data.get("items", []):
                    self.add_message(pid, item)
            for item in data.get("profiles", []):
                self.authors[item["id"]] = " ".join(filter(None, [item.get("first_name"), item.get("last_name")]))
            for item in data.get("groups", []):
                self.authors[-item["id"]] = item.get("name", "Сообщество")
        for pid, directory in self.dirs.items():
            if peer_id is not None and peer_id != pid:
                continue
            self.messages.setdefault(pid, {})
            for path in sorted((directory / "OriginalMessages").glob("*.json")):
                self.add_message(pid, read_json(path), replace=False)
        self.avatars = {}
        for path in (self.export_root / "Dialogs" / "AutorImages").glob("*.*"):
            if path.stem.lstrip("-").isdigit() and path.suffix[1:].lower() in IMAGE_EXTENSIONS:
                self.avatars[int(path.stem)] = local_url(path, self.export_root, self.large_root)
        for author_id, path in shared_avatars(self.root).items():
            self.avatars.setdefault(author_id, local_url(path, self.export_root, self.large_root))

    def add_message(self, pid, item, replace=True):
        if not isinstance(item, dict):
            return
        cid = item.get("conversation_message_id")
        if cid is None:
            return
        if cid <= self.config.min_cid_by_peer_id.get(pid, -1):
            return
        if item.get("date", 0) <= self.config.min_date_by_peer_id.get(pid, -1):
            return
        messages = self.messages.setdefault(pid, {})
        if replace or cid not in messages:
            messages[cid] = item

    def author(self, author_id):
        return {"id": author_id, "name": self.authors.get(author_id, "Сообщество" if author_id < 0 else "Участник"),
                "avatar": self.avatars.get(author_id, "")}

    def dialogs(self):
        result = []
        for pid, messages in self.messages.items():
            latest = max(messages.values(), key=lambda m: (m.get("date", 0), m.get("conversation_message_id", 0)), default={})
            result.append({"peer_id": pid, "name": self.config.dialog_name_by_peer_id.get(pid) or self.authors.get(pid) or f"Диалог {pid}",
                           "avatar": self.avatars.get(pid, ""), "count": len(messages), "date": latest.get("date", 0),
                           "last_message_name": latest.get("text", "")[:100] or ("Вложение" if latest else "Пока нет сообщений")})
        return sorted(result, key=lambda d: d["date"], reverse=True)

    def conversation(self, pid):
        if pid not in self.messages:
            return None
        directory = self.dirs.get(pid, self.export_root / "Dialogs" / (self.config.dialog_name_by_peer_id.get(pid) or f"dialog_{pid}"))
        md_by_cid = {}
        for path in sorted((directory / "MdFiles").rglob("*.md")):
            match = CID_PATTERN.search(path.name)
            if match:
                md_by_cid.setdefault(int(match.group(1)), []).append(path)
        messages = []
        for cid, raw in sorted(self.messages[pid].items(), key=lambda pair: (pair[1].get("date", 0), pair[0])):
            assets = media_index(md_by_cid.get(cid, []), self.export_root, self.large_root)
            item = self.message(raw, assets)
            item.update(cid=cid, out=bool(raw.get("out")), converted=cid in md_by_cid)
            messages.append(item)
        status = read_json(Path(__file__).resolve().parents[1] / "Temp" / "continuation-status.json")
        return {"dialog": next(d for d in self.dialogs() if d["peer_id"] == pid), "dialogs": self.dialogs(),
                "messages": messages, "pending": sum(not m["converted"] for m in messages),
                "export_running": status.get("state") == "running"}

    def image(self, sizes, assets):
        for size in sorted(sizes or [], key=lambda s: s.get("width", 0) * s.get("height", 0), reverse=True):
            url = size.get("url") or size.get("src")
            if url in assets:
                return assets[url]
        return ""

    def message(self, raw, assets, depth=0):
        item = {"text": raw.get("text", ""), "date": raw.get("date", 0), "author": self.author(raw.get("from_id", 0)),
                "attachments": [], "forwarded": [], "reply": None}
        if depth >= 8:
            item["text"] = item["text"] or "Вложенная пересылка"
            return item
        item["attachments"] = [self.attachment(a, assets, depth + 1) for a in raw.get("attachments", [])]
        item["forwarded"] = [self.message(m, assets, depth + 1) for m in raw.get("fwd_messages", [])]
        if isinstance(raw.get("reply_message"), dict):
            item["reply"] = self.message(raw["reply_message"], assets, depth + 1)
        if raw.get("action"):
            item["action"] = "Событие беседы: " + raw["action"].get("text", raw["action"].get("type", ""))
        return item

    def attachment(self, attachment, assets, depth):
        kind = attachment.get("type", "unknown")
        data = attachment.get(kind) or {}
        audio = audio_payload(attachment)
        if audio is not None:
            data, voice = audio
            sources = audio_sources(data, voice)
            url = next((url for url, ext in sources if url in assets), sources[0][0] if sources else "")
            return {"type": "audio", "src": assets.get(url, ""), "url": url,
                    "title": "Голосовое сообщение" if voice else " — ".join(filter(None, [data.get("artist"), data.get("title")])) or "Аудиозапись"}
        if kind == "photo":
            return {"type": "photo", "src": self.image(data.get("sizes"), assets), "title": "Фото"}
        if kind in ("video", "short_video"):
            player = safe_url(data.get("player")) or f'https://vk.com/video{data.get("owner_id", 0)}_{data.get("id", 0)}'
            return {"type": "video", "src": assets.get(player, ""), "poster": self.image(data.get("image"), assets),
                    "url": player, "title": data.get("title") or "Видео", "duration": data.get("duration", 0)}
        if kind == "sticker":
            sizes = (data.get("images_with_background") or []) + (data.get("images") or [])
            return {"type": "sticker", "src": self.image(sizes, assets), "title": "Стикер"}
        if kind in ("wall", "wall_reply"):
            post = dict(data)
            post["from_id"] = data.get("from_id") or data.get("owner_id", 0)
            if depth >= 8:
                return {"type": "file", "title": "Вложенный пост", "url": "", "src": ""}
            copies = [dict(p, from_id=p.get("from_id") or p.get("owner_id", 0)) for p in data.get("copy_history", [])]
            return {"type": "post", "message": self.message(post, assets, depth),
                    "copies": [self.message(p, assets, depth + 1) for p in copies],
                    "url": f'https://vk.com/wall{data.get("owner_id", post["from_id"])}_{data.get("id", 0)}'}
        if kind == "doc":
            url = safe_url(data.get("url"))
            ext = str(data.get("ext", "")).lower()
            doc_type = "photo" if ext in IMAGE_EXTENSIONS else ("audio" if ext in ("mp3", "ogg", "wav", "m4a") else "file")
            return {"type": doc_type, "src": assets.get(url, ""), "url": url, "title": data.get("title", "Документ")}
        if kind in ("link", "article"):
            url = safe_url(data.get("url") or data.get("view_url"))
            photo = data.get("photo") or {}
            return {"type": "link", "url": url, "src": self.image(photo.get("sizes"), assets),
                    "title": data.get("title") or url or "Ссылка", "description": data.get("description", "")}
        return {"type": "file", "title": "Вложение: " + kind, "src": "", "url": ""}
