import json
import re
from datetime import datetime
from pathlib import Path


def convert_forwarded_to_md(json_dir: str, md_dir: str) -> int:
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
            content = _render_message(fwd, f.name, 1)
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
                content = _render_message_with_wall(fwd, wp, f.name)
                file_path = md_path / filename
                with open(file_path, "w", encoding="utf-8") as fp:
                    fp.write(content)
                count += 1

    return count


def _make_filename(fwd: dict, json_stem: str, cid: int, text_override: str = "") -> str:
    source_text = text_override if text_override else (fwd.get("text") or "").strip()
    if source_text:
        first = _first_sentence(source_text)
        if len(first) > 60:
            first = first[:60] + "..."
        name = f"{first}_{cid}.md"
    else:
        name = f"{json_stem}_photo_{cid}.md"
    return _clean_filename(name)


def _first_sentence(text: str) -> str:
    for sep in ("\n", ".", "!", "?"):
        idx = text.find(sep)
        if idx != -1:
            return text[: idx + 1]
    return text


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


def _render_message_with_wall(fwd: dict, wall_att: dict, json_filename: str) -> str:
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
        lines.extend(_render_attachment(att))
    lines.extend(_render_wall(wall_att))

    ref = f"**Исходный файл:** [{json_filename}](../ExtractedOriginalMessages/{json_filename})"
    lines.append("")
    lines.append(ref)

    return "\n".join(lines) + "\n"


def _render_message(fwd: dict, json_filename: str, level: int) -> str:
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
        lines.extend(_render_attachment(attachments[0]))
        lines.append("")
        lines.append(text.replace("\n", "<br>\n"))
        lines.append("")
        ref = f"**Исходный файл:** [{json_filename}](../ExtractedOriginalMessages/{json_filename})"
        lines.append(ref)
    else:
        if text:
            lines.append(text.replace("\n", "<br>\n"))
            lines.append("")

        if attachments or fwd_messages:
            lines.append("## Вложения")
            lines.append("")

            for att in attachments:
                lines.extend(_render_attachment(att))

            ref = f"**Исходный файл:** [{json_filename}](../ExtractedOriginalMessages/{json_filename})"
            lines.append("")
            lines.append(ref)

            if fwd_messages:
                lines.append("")
                lines.append(f"{tag} Пересланные сообщения")
                lines.append("")
                for child in fwd_messages:
                    child_text = _render_message(child, json_filename, level + 2)
                    lines.append(child_text)

    return "\n".join(lines) + "\n"


def _make_heading(fwd: dict, text: str) -> str:
    text = text.strip()
    if text:
        first = _first_sentence(text)
        if len(first) > 60:
            first = first[:60] + "..."
        return first
    return f"Сообщение (id {fwd.get('conversation_message_id', '?')})"


def _render_attachment(att: dict) -> list[str]:
    t = att.get("type")
    if t == "photo":
        return [_render_photo(att)]
    if t in ("video", "short_video"):
        return [_render_video(att)]
    if t == "link":
        return [_render_link(att)]
    if t in ("wall", "post"):
        return _render_wall(att)
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
        return [f"**Стикер:** ![]({url})"]
    return [f"**{t}**"]


def _render_photo(att: dict) -> str:
    photo = att.get("photo", {})
    sizes = photo.get("sizes", [])
    if not sizes:
        return "**Фото:** нет данных"
    biggest = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
    url = biggest.get("url", "")
    return f"**Фото:** ![]({url})"


def _render_video(att: dict) -> str:
    video = att.get("video", {})
    title = video.get("title", "видео")
    player = video.get("player", "")
    imgs = video.get("image", [])
    preview = imgs[-1].get("url", "") if imgs else ""
    parts = [f"**Видео:** [{title}]({player})" if player else f"**Видео:** {title}"]
    if preview:
        parts.append(f"![]({preview})")
    return " ".join(parts)


def _render_link(att: dict) -> str:
    link = att.get("link", {})
    url = link.get("url", "")
    title = link.get("title", "ссылка")
    return f"**Ссылка:** [{title}]({url})"


def _render_wall(att: dict) -> list[str]:
    data = att.get(att.get("type"), {})
    post_url = f"https://vk.com/wall{data.get('owner_id', '')}_{data.get('id', '')}"
    lines = ["", "### Запись на стене", ""]
    lines.append(f"**Ссылка на запись:** [{post_url}]({post_url})")
    lines.append("")
    text = (data.get("text") or "").strip()
    children = data.get("attachments", [])

    if text and len(children) == 1:
        lines.extend(_render_attachment(children[0]))
        lines.append("")
        lines.append(text.replace("\n", "<br>\n"))
        lines.append("")
    else:
        if text:
            lines.append(text.replace("\n", "<br>\n"))
            lines.append("")
        for child in children:
            lines.extend(_render_attachment(child))
    return lines
