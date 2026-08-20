from datetime import datetime
from typing import Any, Optional

from MdItem import (
    MdItem,
    PhotoAttachment, VideoAttachment, LinkAttachment,
    DocAttachment, AudioAttachment, StickerAttachment, WallAttachment,
    ArticleAttachment,
    BaseDownloadResult, NoDownloadResult, ErrorDownloadResult, SuccessDownloadResult,
)


def render_md_item(item: MdItem) -> str:
    level = 1
    lines = _build_md_lines(item, level)
    _append_sources_table(lines, item)
    return "\n".join(lines) + "\n"


def _build_md_lines(item: MdItem, level: int) -> list:
    tag = "#" * min(level, 6)
    if item.is_wall_split:
        return _build_md_wall_message_lines(item, tag, level)
    return _build_md_message_lines(item, tag, level)


def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _render_author_compact(from_id: Any, author: Optional = None, date: Optional[int] = None) -> str:
    if not author and not date:
        label = "Сообщество" if (isinstance(from_id, int) and from_id < 0) else "Пользователь"
        return f"**{label}** (Id: {from_id})"
    img_cell = (
        '    <td style="vertical-align:middle">\n'
        f'      <img width="55" height="55" src="{author.photo_local}">\n'
        '    </td>'
    ) if (author and author.photo_local) else ""
    parts = []
    if author:
        if author.name:
            parts.append(f"<b>{author.name}</b> [{author.author_type}]" if author.author_type else author.name)
        elif author.author_type:
            parts.append(f"[{author.author_type}]")
    if date:
        parts.append(f"<b>Дата:</b> {_fmt_date(date)}")
    if author and author.screen_name:
        parts.append(f"<b>Ник:</b> {author.screen_name}")
    parts.append(f"<b>Id:</b> {from_id}")
    text = "<br>\n      ".join(parts)
    return (
        "<table>\n"
        "  <tr>\n"
        f"{img_cell}\n"
        '    <td style="vertical-align:middle">\n'
        f"      {text}\n"
        "    </td>\n"
        "  </tr>\n"
        "</table>"
    )


def _render_author_line(item: MdItem) -> str:
    return _render_author_compact(item.from_id, item.author, item.date)


def _build_md_message_lines(item: MdItem, tag: str, level: int) -> list:
    lines = [
        f"{tag} {item.heading}",
        "",
        _render_author_line(item),
        "",
    ]

    text = item.text
    attachments = item.attachments
    forwarded = item.forwarded

    if item.reply:
        lines.append("## Ответ на сообщение")
        lines.append("")
        for reply_item in item.reply:
            lines.extend(_build_md_lines(reply_item, level + 2))
            lines.append("")

    if text and len(attachments) == 1 and not forwarded and not item.reply:
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
                lines.append("")

            if forwarded:
                lines.append("")
                lines.append(f"{tag} Пересланные сообщения")
                lines.append("")
                for child in forwarded:
                    child_lines = _build_md_lines(child, level + 2)
                    lines.extend(child_lines)
                    lines.append("")

    return lines


def _build_md_wall_message_lines(item: MdItem, tag: str, level: int) -> list:
    walls = [a for a in item.attachments if isinstance(a, WallAttachment)]
    others = [a for a in item.attachments if not isinstance(a, WallAttachment)]

    lines = [
        f"{tag} {item.heading}",
        "",
        _render_author_line(item),
        "",
    ]

    if item.reply:
        lines.append("## Ответ на сообщение")
        lines.append("")
        for reply_item in item.reply:
            lines.extend(_build_md_lines(reply_item, level + 2))
            lines.append("")

    if item.text:
        lines.append(item.text.replace("\n", "<br>\n"))
        lines.append("")

    lines.append("## Вложения")
    lines.append("")

    for att in others:
        lines.extend(_render_attachment(att))
        lines.append("")
    for wall in walls:
        lines.extend(_render_wall(wall))

    return lines


def _rel_cell(result: BaseDownloadResult) -> str:
    if isinstance(result, SuccessDownloadResult):
        return f"[{result.local_path}]({result.local_path})"
    elif isinstance(result, ErrorDownloadResult):
        return "Ошибка скачивания"
    elif isinstance(result, NoDownloadResult):
        return ""
    else:
        raise TypeError(f"Неизвестный тип результата скачивания: {type(result)}")


def _append_sources_table(lines: list, item: MdItem) -> None:
    lines.append("## Источники")
    lines.append("")
    lines.append("| Тип | Относительная ссылка | Ссылка |")
    lines.append("|-----|---------------------|--------|")

    relpath = f"../OriginalMessages/{item.json_filename}"
    lines.append(f"| Исходный файл | [{relpath}]({relpath}) | |")

    seen = set()

    def _add_row(row: str):
        if row not in seen:
            seen.add(row)
            lines.append(row)

    def _walk(item: MdItem):
        if item.author and item.author.photo_url:
            rel_cell = f"[{item.author.photo_local}]({item.author.photo_local})" if item.author.photo_local else ""
            _add_row(f"| Аватар автора | {rel_cell} | {_url_cell(item.author.photo_url)} |")
        for att in item.attachments:
            _walk_attachment(att)
        for child in item.forwarded:
            _walk(child)
        for reply_item in item.reply or []:
            _walk(reply_item)

    def _walk_attachment(att):
        if isinstance(att, PhotoAttachment):
            _add_row(f"| Фото | {_rel_cell(att.download_result)} | {_url_cell(att.original_url)} |")
        elif isinstance(att, VideoAttachment):
            if att.player_url:
                _add_row(f"| Видео | {_rel_cell(att.mp4_download_result)} | {_url_cell(att.player_url)} |")
            if att.preview_url:
                _add_row(f"| Превью | {_rel_cell(att.preview_download_result)} | {_url_cell(att.preview_url)} |")
        elif isinstance(att, LinkAttachment):
            if att.url:
                _add_row(f"| Ссылка | | {_url_cell(att.url)} |")
        elif isinstance(att, WallAttachment):
            if att.author and att.author.photo_url:
                _add_row(f"| Аватар автора поста | | {_url_cell(att.author.photo_url)} |")
            post_url = f"https://vk.com/wall{att.owner_id}_{att.id}"
            _add_row(f"| Ссылка на пост | | {_url_cell(post_url)} |")
            for ow in att.original_walls:
                if ow.author and ow.author.photo_url:
                    _add_row(f"| Аватар автора оригинального поста | | {_url_cell(ow.author.photo_url)} |")
                orig_post_url = f"https://vk.com/wall{ow.owner_id}_{ow.id}"
                _add_row(f"| Ссылка на оригинальный пост | | {_url_cell(orig_post_url)} |")
                for child in ow.children:
                    _walk_attachment(child)
            for child in att.children:
                _walk_attachment(child)
        elif isinstance(att, DocAttachment):
            if att.url:
                _add_row(f"| Документ | {_rel_cell(att.download_result)} | {_url_cell(att.url)} |")
        elif isinstance(att, AudioAttachment):
            _add_row(f"| Аудио | | {att.artist} — {att.title} |")
        elif isinstance(att, StickerAttachment):
            _add_row(f"| Стикер | {_rel_cell(att.download_result)} | {_url_cell(att.original_url)} |")
        elif isinstance(att, ArticleAttachment):
            _add_row(f"| Статья | | {_url_cell(att.url)} |")
            if att.owner_photo_url:
                _add_row(f"| Аватар автора статьи | | {_url_cell(att.owner_photo_url)} |")

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
        if att.ext in ("gif", "png", "jpg", "jpeg", "webp"):
            if isinstance(att.download_result, SuccessDownloadResult):
                return [f'**Фото:** <a href="{att.download_result.local_path}"><img src="{att.download_result.local_path}" width="300" alt="{att.title}"></a>']
            if att.url:
                return [f"**Фото:** [ссылка]({att.url})"]
        title = att.title
        if isinstance(att.download_result, SuccessDownloadResult):
            return [f"**Документ:** [{title}]({att.download_result.local_path})"]
        if att.url:
            return [f"**Документ:** [{title}]({att.url})"]
        return [f"**Документ:** {title}"]
    if isinstance(att, AudioAttachment):
        return [f"**Аудио:** {att.artist} — {att.title}"]
    if isinstance(att, StickerAttachment):
        if isinstance(att.download_result, SuccessDownloadResult):
            return [f"**Стикер:** ![]({att.download_result.local_path})"]
        return [f"**Стикер:**"]
    if isinstance(att, ArticleAttachment):
        lines = []
        if isinstance(att.photo_download_result, SuccessDownloadResult):
            lines.append(f'<a href="{att.url}"><img src="{att.photo_download_result.local_path}" width="300" alt="{att.title}"></a>')
            lines.append("")
        if att.url:
            lines.append(f"**Статья:** [{att.title}]({att.url})")
        else:
            lines.append(f"**Статья:** {att.title}")
        if att.owner_name:
            lines.append("")
            lines.append(f"**Автор:** {att.owner_name}")
        if att.lead_description:
            lines.append("")
            lines.append(f"> {att.lead_description}")
        return lines
    return [f"**{type(att).__name__}**"]


def _render_photo(att: PhotoAttachment) -> str:
    if not att.original_url:
        return "**Фото:** нет данных"
    if isinstance(att.download_result, SuccessDownloadResult):
        return f'**Фото:** <a href="{att.download_result.local_path}"><img src="{att.download_result.local_path}" width="300" alt="Фото"></a>'
    return f"**Фото:** [ссылка]({att.original_url})"


def _render_video(att: VideoAttachment) -> list:
    lines = []
    if att.player_url:
        lines.append(f"**Видео:** [{att.title}]({att.player_url})")
    else:
        lines.append(f"**Видео:** {att.title}")

    if isinstance(att.preview_download_result, SuccessDownloadResult):
        lines.append("")
        lines.append(f'<a href="{att.preview_download_result.local_path}"><img src="{att.preview_download_result.local_path}" width="300" alt="Превью"></a>')

    if isinstance(att.mp4_download_result, SuccessDownloadResult):
        lines.append(f'\n<video src="{att.mp4_download_result.local_path}" width="240" controls></video>')

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
    lines = ["", "### Запись на стене", ""]
    lines.append(_render_author_compact(att.owner_id, att.author))
    lines.append("")

    if att.original_walls:
        lines.append("**Переслано из:**")
        lines.append("")
        for ow in att.original_walls:
            lines.extend(_render_wall(ow))
        return lines

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
            lines.append("")

    return lines
