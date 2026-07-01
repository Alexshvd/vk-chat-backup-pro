import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from download_media import DownloadItem


_download_queue = None
_url_to_relpath = {}


def _get_ext(url: str) -> str:
    for ext in ("jpg", "jpeg", "png", "gif", "webp"):
        if ext in url.lower():
            return ext
    return "jpg"


def _register_image(url: str, cid: int) -> str:
    if url in _url_to_relpath:
        return _url_to_relpath[url]
    items = _download_queue.setdefault(cid, [])
    n = len(items) + 1
    ext = _get_ext(url)
    relpath = f"RawData/{cid}/{n}.{ext}"
    _url_to_relpath[url] = relpath
    items.append(DownloadItem(url=url, relpath=relpath))
    return relpath


def convert_forwarded_to_md(json_dir: str, md_dir: str, download_queue: Optional[dict[int, list[DownloadItem]]] = None) -> int:
    global _download_queue, _url_to_relpath
    _download_queue = download_queue if download_queue is not None else {}
    _url_to_relpath = {}

    json_path = Path(json_dir)
    md_path = Path(md_dir)
    md_path.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in sorted(json_path.glob("*.json")):
        with open(f, encoding="utf-8") as fp:
            fwd = json.load(fp)

        cid = fwd.get("conversation_message_id")
        if cid is None:
            continue

        attachments = fwd.get("attachments", [])
        wall_posts = [a for a in attachments if a.get("type") in ("wall", "post")]

        if len(wall_posts) < 2:
            wall_text = ""
            if wall_posts and not (fwd.get("text") or "").strip():
                wp_type = wall_posts[0].get("type")
                wall_text = wall_posts[0].get(wp_type, {}).get("text", "") or ""
            filename = _make_filename(fwd, f.stem, cid, wall_text)
            if wall_text:
                filename = "Статья." + filename
            content = _render_message(fwd, f.name, 1, cid)
            file_path = md_path / filename
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write(content)
            count += 1
        else:
            for i, wp in enumerate(wall_posts, 1):
                wp_type = wp.get("type")
                wall_text = wp.get(wp_type, {}).get("text", "") or ""
                filename = _make_filename(fwd, f.stem, cid, wall_text)
                base = filename[:-3]
                filename = f"{base}_part_{i}.md"
                if wall_text:
                    filename = "Статья." + filename
                content = _render_message_with_wall(fwd, wp, f.name, cid)
                file_path = md_path / filename
                with open(file_path, "w", encoding="utf-8") as fp:
                    fp.write(content)
                count += 1

    return count


_type_map = {
    "photo": "Photo",
    "video": "Video",
    "short_video": "ShortVideo",
    "link": "Link",
    "wall": "Article",
    "post": "Article",
    "doc": "Doc",
    "audio": "Audio",
    "sticker": "Sticker",
}


def _get_attachment_types(attachments: list) -> str:
    if not attachments:
        return "Media"
    types = set()
    for att in attachments:
        t = _type_map.get(att.get("type"))
        if t:
            types.add(t)
    if len(types) == 1:
        return list(types)[0]
    return "Media"


def _make_filename(fwd: dict, json_stem: str, cid: int, text_override: str = "") -> str:
    source_text = text_override if text_override else (fwd.get("text") or "").strip()
    if source_text:
        first = _first_sentence(source_text)
        if len(first) > 60:
            first = first[:60] + "..."
        name = f"{first}.Id{cid}.md"
    else:
        prefix = _get_attachment_types(fwd.get("attachments", []))
        date_part = json_stem.rsplit("_", 1)[0] if "_" in json_stem else json_stem
        name = f"{prefix}.{date_part}.Id{cid}.md"
    return _clean_filename(name)


def _first_sentence(text: str) -> str:
    for sep in ("\n", ".", "!", "?"):
        idx = text.find(sep)
        if idx != -1:
            return text[: idx + 1].strip()
    return text.strip()


def _clean_filename(name: str) -> str:
    name = name.replace("\n", " ")
    name = name.replace("\r", " ")
    name = re.sub(r'\s+', " ", name).strip()
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF'
        r'\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF'
        r'\u200D\u20E3\u231A-\u23FE\uFE00-\uFE0F]',
        "", name
    )
    name = name.replace("\u2014", "-")
    name = name.replace("\u2013", "-")
    name = name.strip(". ")
    if not name:
        name = "message.md"
    return name


def _render_message_with_wall(fwd: dict, wall_att: dict, json_filename: str, cid: int) -> str:
    tag = "#"
    text = (fwd.get("text") or "").strip()
    ts = fwd.get("date")

    lines = []
    lines.append(f"{tag} {_make_heading(fwd, text)}")
    lines.append("")
    lines.append(f"**От:** {fwd.get('from_id', '?')}")
    if ts:
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"**Дата:** {dt}")
    lines.append("")

    attachments = fwd.get("attachments", [])
    other_attachments = [a for a in attachments if a.get("type") not in ("wall", "post")]

    if text:
        lines.append(text.replace("\n", "<br>\n"))
        lines.append("")

    lines.append("## Вложения")
    lines.append("")

    for att in other_attachments:
        lines.extend(_render_attachment(att, cid))
    lines.extend(_render_wall(wall_att, cid))

    lines.append("")
    lines.append("## Источники")
    lines.append("")
    lines.append("| Тип | Относительная ссылка | Ссылка |")
    lines.append("|-----|---------------------|--------|")
    for label, relpath, url in _collect_urls(fwd, json_filename, cid):
        rel_cell = f"[{relpath}]({relpath})" if relpath else ""
        url_cell = f"[{url}]({url})" if url else ""
        lines.append(f"| {label} | {rel_cell} | {url_cell} |")

    return "\n".join(lines) + "\n"


def _render_message(fwd: dict, json_filename: str, level: int, cid: int) -> str:
    tag = "#" * min(level, 6)
    text = (fwd.get("text") or "").strip()
    ts = fwd.get("date")

    lines = []
    lines.append(f"{tag} {_make_heading(fwd, text)}")
    lines.append("")
    lines.append(f"**От:** {fwd.get('from_id', '?')}")
    if ts:
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"**Дата:** {dt}")
    lines.append("")

    attachments = fwd.get("attachments", [])
    fwd_messages = fwd.get("fwd_messages", [])

    if text and len(attachments) == 1 and not fwd_messages:
        lines.extend(_render_attachment(attachments[0], cid))
        lines.append("")
        lines.append(text.replace("\n", "<br>\n"))
        lines.append("")
    else:
        if text:
            lines.append(text.replace("\n", "<br>\n"))
            lines.append("")

        if attachments or fwd_messages:
            lines.append("## Вложения")
            lines.append("")

            for att in attachments:
                lines.extend(_render_attachment(att, cid))

            if fwd_messages:
                lines.append("")
                lines.append(f"{tag} Пересланные сообщения")
                lines.append("")
                for child in fwd_messages:
                    child_cid = child.get("conversation_message_id") or cid
                    child_text = _render_message(child, json_filename, level + 2, child_cid)
                    lines.append(child_text)

    if attachments or fwd_messages or text:
        lines.append("")
        lines.append("## Источники")
        lines.append("")
        lines.append("| Тип | Относительная ссылка | Ссылка |")
        lines.append("|-----|---------------------|--------|")
        for label, relpath, url in _collect_urls(fwd, json_filename, cid):
            rel_cell = f"[{relpath}]({relpath})" if relpath else ""
            url_cell = f"[{url}]({url})" if url else ""
            lines.append(f"| {label} | {rel_cell} | {url_cell} |")

    return "\n".join(lines) + "\n"


def _make_heading(fwd: dict, text: str) -> str:
    text = text.strip()
    if text:
        first = _first_sentence(text)
        if len(first) > 60:
            first = first[:60] + "..."
        return first
    return f"Сообщение (id {fwd.get('conversation_message_id', '?')})"


def _render_attachment(att: dict, cid: int) -> list[str]:
    t = att.get("type")
    if t == "photo":
        return [_render_photo(att, cid)]
    if t in ("video", "short_video"):
        return [_render_video(att, cid)]
    if t == "link":
        return [_render_link(att)]
    if t in ("wall", "post"):
        return _render_wall(att, cid)
    if t == "doc":
        doc = att.get("doc", {})
        url = doc.get("url", "")
        title = doc.get("title", "документ")
        return [f"**Документ:** [{title}]({url})"]
    if t == "audio":
        audio = att.get("audio", {})
        return [f"**Аудио:** {audio.get('artist', '')} — {audio.get('title', '')}"]
    if t == "sticker":
        sticker = att.get("sticker", {})
        imgs = sticker.get("images", [])
        url = imgs[-1].get("url", "") if imgs else ""
        relpath = _register_image(url, cid) if url else ""
        return [f"**Стикер:** ![]({relpath})"]
    return [f"**{t}**"]


def _render_photo(att: dict, cid: int) -> str:
    photo = att.get("photo", {})
    sizes = photo.get("sizes", [])
    if not sizes:
        return "**Фото:** нет данных"
    biggest = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
    url = biggest.get("url", "")
    relpath = _register_image(url, cid) if url else ""
    return f"**Фото:** ![]({relpath})"


def _render_video(att: dict, cid: int) -> str:
    video = att.get("video", {})
    title = video.get("title", "видео")
    player = video.get("player", "")
    imgs = video.get("image", [])
    preview = imgs[-1].get("url", "") if imgs else ""
    parts = [f"**Видео:** [{title}]({player})" if player else f"**Видео:** {title}"]
    if preview:
        relpath = _register_image(preview, cid)
        parts.append(f"![]({relpath})")
    return " ".join(parts)


def _render_link(att: dict) -> str:
    link = att.get("link", {})
    url = link.get("url", "")
    title = link.get("title", "ссылка")
    return f"**Ссылка:** [{title}]({url})"


def _collect_urls(fwd: dict, json_filename: str, cid: int) -> list[tuple[str, str, str]]:
    result = [("Исходный файл", f"../ExtractedOriginalMessages/{json_filename}", "")]
    for att in fwd.get("attachments", []):
        result.extend(_collect_attachment_urls(att, cid))
    for child in fwd.get("fwd_messages", []):
        result.extend(_collect_urls(child, json_filename, cid))
    return result


def _collect_attachment_urls(att: dict, cid: int) -> list[tuple[str, str, str]]:
    t = att.get("type")
    if t == "photo":
        photo = att.get("photo", {})
        sizes = photo.get("sizes", [])
        if sizes:
            biggest = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
            url = biggest["url"]
            return [("Фото", _url_to_relpath.get(url, ""), url)]
    if t in ("video", "short_video"):
        video = att.get("video", {})
        urls = []
        if video.get("player"):
            urls.append(("Видео", "", video["player"]))
        imgs = video.get("image", [])
        if imgs:
            preview = imgs[-1]["url"]
            urls.append(("Превью", _url_to_relpath.get(preview, ""), preview))
        return urls
    if t == "link":
        link = att.get("link", {})
        if link.get("url"):
            return [("Ссылка", "", link["url"])]
        return []
    if t in ("wall", "post"):
        data = att.get(t, {})
        post_url = f"https://vk.com/wall{data.get('owner_id','')}_{data.get('id','')}"
        result = [("Ссылка на пост", "", post_url)]
        for child in data.get("attachments", []):
            result.extend(_collect_attachment_urls(child, cid))
        return result
    if t == "doc":
        doc = att.get("doc", {})
        if doc.get("url"):
            return [("Документ", "", doc["url"])]
        return []
    return []


def _render_wall(att: dict, cid: int) -> list[str]:
    data = att.get(att.get("type"), {})
    post_url = f"https://vk.com/wall{data.get('owner_id', '')}_{data.get('id', '')}"
    lines = ["", "### Запись на стене", ""]
    text = (data.get("text") or "").strip()
    children = data.get("attachments", [])

    if text and len(children) == 1:
        lines.extend(_render_attachment(children[0], cid))
        lines.append("")
        lines.append(text.replace("\n", "<br>\n"))
        lines.append("")
    else:
        if text:
            lines.append(text.replace("\n", "<br>\n"))
            lines.append("")
        for child in children:
            lines.extend(_render_attachment(child, cid))
    return lines
