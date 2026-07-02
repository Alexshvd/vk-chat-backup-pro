from datetime import datetime

from MdItem import (
    MdItem,
    PhotoAttachment, VideoAttachment, LinkAttachment,
    DocAttachment, AudioAttachment, StickerAttachment, WallAttachment,
)


def render_md_item(item: MdItem, level: int = 1) -> str:
    tag = "#" * min(level, 6)

    if item.is_wall_split:
        return _render_message_with_wall(item, tag, level)

    return _render_message(item, tag, level)


def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _render_message(item: MdItem, tag: str, level: int) -> str:
    lines = [
        f"{tag} {item.heading}",
        "",
        f"**От:** {item.from_id}",
    ]
    if item.date:
        lines.append(f"**Дата:** {_fmt_date(item.date)}")
    lines.append("")

    text = item.text
    attachments = item.attachments
    forwarded = item.forwarded

    if text and len(attachments) == 1 and not forwarded:
        lines.extend(_render_attachment(attachments[0]))
        lines.append("")
        lines.append(text.replace("\n", "<br>\n"))
        lines.append("")
    else:
        if text:
            lines.append(text.replace("\n", "<br>\n"))
            lines.append("")

        if attachments or forwarded:
            lines.append("## Вложения")
            lines.append("")

            for att in attachments:
                lines.extend(_render_attachment(att))

            if forwarded:
                lines.append("")
                lines.append(f"{tag} Пересланные сообщения")
                lines.append("")
                for child in forwarded:
                    child_text = render_md_item(child, level + 2)
                    lines.append(child_text)

    if attachments or forwarded or text:
        lines.append("")
        _append_sources_table(lines, item)

    return "\n".join(lines) + "\n"


def _render_message_with_wall(item: MdItem, tag: str, level: int) -> str:
    walls = [a for a in item.attachments if isinstance(a, WallAttachment)]
    others = [a for a in item.attachments if not isinstance(a, WallAttachment)]

    lines = [
        f"{tag} {item.heading}",
        "",
        f"**От:** {item.from_id}",
    ]
    if item.date:
        lines.append(f"**Дата:** {_fmt_date(item.date)}")
    lines.append("")

    if item.text:
        lines.append(item.text.replace("\n", "<br>\n"))
        lines.append("")

    lines.append("## Вложения")
    lines.append("")

    for att in others:
        lines.extend(_render_attachment(att))
    for wall in walls:
        lines.extend(_render_wall(wall))

    lines.append("")
    _append_sources_table(lines, item)

    return "\n".join(lines) + "\n"


def _append_sources_table(lines: list, item: MdItem) -> None:
    sources = _collect_sources(item)
    lines.append("## Источники")
    lines.append("")
    lines.append("| Тип | Относительная ссылка | Ссылка |")
    lines.append("|-----|---------------------|--------|")
    for label, relpath, url in sources:
        rel_cell = f"[{relpath}]({relpath})" if relpath else ""
        if url:
            display = url if len(url) <= 80 else "url ссылка"
            url_cell = f"[{display}]({url})"
        else:
            url_cell = ""
        lines.append(f"| {label} | {rel_cell} | {url_cell} |")


def _collect_sources(item: MdItem):
    result = [
        ("Исходный файл", f"../ExtractedOriginalMessages/{item.json_filename}", "")
    ]
    for att in item.attachments:
        result.extend(_collect_attachment_sources(att))
    for child in item.forwarded:
        result.extend(_collect_sources(child))
    return result


def _collect_attachment_sources(att):
    if isinstance(att, PhotoAttachment):
        return [("Фото", att.local_path, att.original_url)]

    if isinstance(att, VideoAttachment):
        urls = []
        if att.player_url:
            urls.append(("Видео", "", att.player_url))
        if att.preview_url:
            urls.append(("Превью", att.preview_local_path, att.preview_url))
        if att.mp4_url:
            urls.append(("Видео файл", att.mp4_local_path, att.mp4_url))
        return urls

    if isinstance(att, LinkAttachment):
        return [("Ссылка", "", att.url)] if att.url else []

    if isinstance(att, WallAttachment):
        post_url = f"https://vk.com/wall{att.owner_id}_{att.id}"
        result = [("Ссылка на пост", "", post_url)]
        for child in att.children:
            result.extend(_collect_attachment_sources(child))
        return result

    if isinstance(att, DocAttachment):
        return [("Документ", "", att.url)] if att.url else []

    return []


def _render_attachment(att):
    if isinstance(att, PhotoAttachment):
        return [_render_photo(att)]
    if isinstance(att, VideoAttachment):
        return _render_video(att)
    if isinstance(att, LinkAttachment):
        return [_render_link(att)]
    if isinstance(att, WallAttachment):
        return _render_wall(att)
    if isinstance(att, DocAttachment):
        url = att.url
        title = att.title
        return [f"**Документ:** [{title}]({url})"]
    if isinstance(att, AudioAttachment):
        return [f"**Аудио:** {att.artist} — {att.title}"]
    if isinstance(att, StickerAttachment):
        return [f"**Стикер:** ![]({att.local_path})"]
    return [f"**{type(att).__name__}**"]


def _render_photo(att: PhotoAttachment) -> str:
    if not att.original_url:
        return "**Фото:** нет данных"
    return f"**Фото:** ![]({att.local_path})"


def _render_video(att: VideoAttachment) -> list:
    lines = []
    if att.player_url:
        lines.append(f"**Видео:** [{att.title}]({att.player_url})")
    else:
        lines.append(f"**Видео:** {att.title}")

    if att.preview_local_path:
        lines.append(f"![]({att.preview_local_path})")

    if att.mp4_local_path:
        lines.append(f"\n<video src=\"{att.mp4_local_path}\" controls></video>")

    if att.player_url:
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Смотреть через VK Player</summary>")
        lines.append(
            f"<iframe src=\"{att.player_url}\" "
            f"width=\"640\" height=\"360\" allowfullscreen></iframe>"
        )
        lines.append("</details>")

    return lines


def _render_link(att: LinkAttachment) -> str:
    return f"**Ссылка:** [{att.title}]({att.url})"


def _render_wall(att: WallAttachment) -> list:
    post_url = f"https://vk.com/wall{att.owner_id}_{att.id}"
    lines = ["", "### Запись на стене", ""]
    text = att.text
    children = att.children

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
