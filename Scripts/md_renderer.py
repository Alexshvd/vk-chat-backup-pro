from datetime import datetime
from typing import Any, Optional

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


def _render_author_compact(from_id: Any, author: Optional = None) -> str:
    parts = [f"**От:** {from_id}"]
    if author:
        if author.photo_local:
            parts.append(f"![]({author.photo_local})")
        if author.screen_name:
            parts.append(f"@{author.screen_name}")
        if author.name:
            parts.append(f"({author.name})")
        if author.author_type:
            parts.append(f"[{author.author_type}]")
    return " ".join(parts)


def _render_author_line(item: MdItem) -> str:
    return _render_author_compact(item.from_id, item.author)


def _render_message(item: MdItem, tag: str, level: int) -> str:
    lines = [
        f"{tag} {item.heading}",
        "",
        _render_author_line(item),
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
        _render_author_line(item),
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
    lines.append("## Источники")
    lines.append("")
    lines.append("| Тип | Относительная ссылка | Ссылка |")
    lines.append("|-----|---------------------|--------|")

    def _walk(item: MdItem):
        if item.author and item.author.photo_url:
            rel_cell = f"[{item.author.photo_local}]({item.author.photo_local})" if item.author.photo_local else ""
            lines.append(f"| Аватар автора | {rel_cell} | {_url_cell(item.author.photo_url)} |")
        relpath = f"../ExtractedOriginalMessages/{item.json_filename}"
        lines.append(f"| Исходный файл | [{relpath}]({relpath}) | |")
        for att in item.attachments:
            _walk_attachment(att)
        for child in item.forwarded:
            _walk(child)

    def _walk_attachment(att):
        if isinstance(att, PhotoAttachment):
            rel_cell = f"[{att.local_path}]({att.local_path})" if att.local_path else ""
            lines.append(f"| Фото | {rel_cell} | {_url_cell(att.original_url)} |")
        elif isinstance(att, VideoAttachment):
            if att.player_url:
                lines.append(f"| Видео | | {_url_cell(att.player_url)} |")
            if att.preview_url:
                rel_cell = f"[{att.preview_local_path}]({att.preview_local_path})" if att.preview_local_path else ""
                lines.append(f"| Превью | {rel_cell} | {_url_cell(att.preview_url)} |")
            if att.mp4_url:
                rel_cell = f"[{att.mp4_local_path}]({att.mp4_local_path})" if att.mp4_local_path else ""
                lines.append(f"| Видео файл | {rel_cell} | {_url_cell(att.mp4_url)} |")
        elif isinstance(att, LinkAttachment):
            if att.url:
                lines.append(f"| Ссылка | | {_url_cell(att.url)} |")
        elif isinstance(att, WallAttachment):
            if att.author and att.author.photo_url:
                rel_cell = f"[{att.author.photo_local}]({att.author.photo_local})" if att.author.photo_local else ""
                lines.append(f"| Аватар автора поста | {rel_cell} | {_url_cell(att.author.photo_url)} |")
            post_url = f"https://vk.com/wall{att.owner_id}_{att.id}"
            lines.append(f"| Ссылка на пост | | {_url_cell(post_url)} |")
            for child in att.children:
                _walk_attachment(child)
        elif isinstance(att, DocAttachment):
            if att.url:
                lines.append(f"| Документ | | {_url_cell(att.url)} |")

    def _url_cell(url: str) -> str:
        display = url if len(url) <= 80 else "url ссылка"
        return f"[{display}]({url})"

    _walk(item)


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
    lines.append(_render_author_compact(att.owner_id, att.author))
    lines.append("")
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
