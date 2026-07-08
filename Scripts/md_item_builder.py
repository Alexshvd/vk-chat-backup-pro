import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from MdItem import (
    BaseAttachmentItem, MdItem,
    PhotoAttachment, VideoAttachment, LinkAttachment,
    DocAttachment, AudioAttachment, StickerAttachment, WallAttachment,
)
from author_resolver import AuthorInfo
from download_media import download_file
from vk_client import get_video_embed_urls
from config import Config
from config_loader import path_rel


def build_md_items(
    fwd: dict,
    json_filename: str,
    md_dir: str,
    little_raw_data_dir: str,
    large_raw_data_dir: str,
    authors: dict[int, AuthorInfo],
    config: Config,
    url_to_relpath: Optional[Dict[str, str]] = None,
) -> List[MdItem]:
    if url_to_relpath is None:
        url_to_relpath = {}

    cid = fwd.get("conversation_message_id")
    if cid is None:
        return []

    text = (fwd.get("text") or "").strip()
    from_id = fwd.get("from_id")
    date = fwd.get("date")
    author = authors.get(from_id) if from_id is not None else None

    raw_attachments = fwd.get("attachments", [])
    resolved_attachments = [
        _resolve_attachment(a, cid, md_dir, little_raw_data_dir, large_raw_data_dir, url_to_relpath, authors, config)
        for a in raw_attachments
    ]

    resolved_forwarded = []
    for child in fwd.get("fwd_messages", []):
        resolved_forwarded.extend(
            build_md_items(child, json_filename, md_dir, little_raw_data_dir, large_raw_data_dir, authors, config, url_to_relpath)
        )

    walls = [a for a in resolved_attachments if isinstance(a, WallAttachment)]
    others = [a for a in resolved_attachments if not isinstance(a, WallAttachment)]
    json_stem = Path(json_filename).stem

    if len(walls) < 2:
        item = _make_item(
            cid, from_id, date, text, resolved_attachments,
            resolved_forwarded, json_filename, author,
        )
        item.heading = _compute_heading(text, cid)

        if len(walls) == 1 and not text:
            wall_text = walls[0].text
            item.filename = _compute_filename(
                text, resolved_attachments, json_stem, cid, wall_text
            )
            if wall_text:
                item.filename = f"Статья.{item.filename}"
        else:
            item.filename = _compute_filename(
                text, resolved_attachments, json_stem, cid
            )

        return [item]

    result = []
    for i, wall in enumerate(walls, 1):
        wall_text = wall.text
        item = _make_item(
            cid, from_id, date, text, others + [wall],
            resolved_forwarded, json_filename, author,
        )
        item.heading = _compute_heading(text, cid)
        item.filename = _compute_filename(
            text, others + [wall], json_stem, cid, wall_text
        )
        base = item.filename[:-3]
        item.filename = f"{base}_part_{i}.md"
        if wall_text:
            item.filename = f"Статья.{item.filename}"
        item.is_wall_split = True
        result.append(item)

    return result


def _make_item(
    cid: int, from_id: Any, date: int, text: str,
    attachments: List[BaseAttachmentItem],
    forwarded: List[MdItem], json_filename: str,
    author: AuthorInfo = None,
) -> MdItem:
    item = MdItem(
        cid=cid,
        from_id=from_id,
        date=date,
        text=text,
        attachments=attachments,
        forwarded=forwarded,
        json_filename=json_filename,
        heading="",
        filename="",
    )
    if author:
        item.author = author
    return item


def _resolve_attachment(
    att: dict,
    cid: int,
    md_dir: str,
    little_raw_data_dir: str,
    large_raw_data_dir: str,
    url_to_relpath: Dict[str, str],
    authors: dict[int, AuthorInfo],
    config: Config,
) -> BaseAttachmentItem:
    t = att.get("type")
    if t == "photo":
        return _resolve_photo(att.get("photo", {}), cid, little_raw_data_dir, md_dir, url_to_relpath)
    if t in ("video", "short_video"):
        return _resolve_video(
            att.get("video", {}), cid, little_raw_data_dir, large_raw_data_dir, md_dir,
            url_to_relpath, config,
            is_short=(t == "short_video"),
        )
    if t == "link":
        return _resolve_link(att.get("link", {}))
    if t in ("wall", "post"):
        return _resolve_wall(att.get(t, {}), cid, md_dir, little_raw_data_dir, large_raw_data_dir, url_to_relpath, authors, config)
    if t == "doc":
        return _resolve_doc(att.get("doc", {}))
    if t == "audio":
        return _resolve_audio(att.get("audio", {}))
    if t == "sticker":
        return _resolve_sticker(att.get("sticker", {}), cid, little_raw_data_dir, md_dir, url_to_relpath)
    return BaseAttachmentItem()


def _resolve_photo(
    photo: dict, cid: int, little_raw_data_dir: str, md_dir: str, url_to_relpath: Dict[str, str],
) -> PhotoAttachment:
    sizes = photo.get("sizes", [])
    if not sizes:
        return PhotoAttachment(original_url="")
    biggest = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
    url = biggest.get("url", "")
    local_path = _download_to_raw(url, cid, little_raw_data_dir, md_dir, url_to_relpath) if url else ""
    return PhotoAttachment(original_url=url, local_path=local_path)


def _resolve_video(
    video: dict, cid: int,
    little_raw_data_dir: str, large_raw_data_dir: str, md_dir: str,
    url_to_relpath: Dict[str, str],
    config: Config,
    is_short: bool,
) -> VideoAttachment:
    title = video.get("title", "")
    player = video.get("player", "")
    duration = video.get("duration", 0)
    imgs = video.get("image", [])
    preview_url = imgs[-1].get("url", "") if imgs else ""
    files = video.get("files", {})

    owner_id = video.get("owner_id")
    video_id = video.get("id")

    if not player and owner_id and video_id:
        player = (
            f"https://vk.com/video_ext.php?"
            f"oid={owner_id}&id={video_id}"
        )

    preview_local = (
        _download_to_raw(preview_url, cid, little_raw_data_dir, md_dir, url_to_relpath)
        if preview_url else ""
    )

    mp4_url = None

    if owner_id and video_id:
        try:
            embed_files = get_video_embed_urls(owner_id, video_id)
            mp4_url = _get_best_video_url(embed_files)
        except Exception:
            pass

    if not mp4_url:
        mp4_url = _get_best_video_url(files)

    mp4_local = ""
    if mp4_url and _should_download_video(duration, config):
        if mp4_url in url_to_relpath:
            mp4_local = url_to_relpath[mp4_url]
        else:
            try:
                mp4_local = _download_to_raw(
                    mp4_url, cid, large_raw_data_dir, md_dir, url_to_relpath, force_ext="mp4"
                )
            except Exception:
                mp4_local = ""

    return VideoAttachment(
        is_short=is_short,
        title=title,
        player_url=player,
        duration=duration,
        mp4_local_path=mp4_local,
        mp4_url=mp4_url or "",
        preview_local_path=preview_local,
        preview_url=preview_url,
    )


def _resolve_link(link: dict) -> LinkAttachment:
    return LinkAttachment(
        url=link.get("url", ""),
        title=link.get("title", "ссылка"),
    )


def _resolve_doc(doc: dict) -> DocAttachment:
    return DocAttachment(
        url=doc.get("url", ""),
        title=doc.get("title", "документ"),
    )


def _resolve_audio(audio: dict) -> AudioAttachment:
    return AudioAttachment(
        artist=audio.get("artist", ""),
        title=audio.get("title", ""),
    )


def _resolve_sticker(
    sticker: dict, cid: int, little_raw_data_dir: str, md_dir: str, url_to_relpath: Dict[str, str],
) -> StickerAttachment:
    imgs = sticker.get("images", [])
    url = imgs[-1].get("url", "") if imgs else ""
    local_path = _download_to_raw(url, cid, little_raw_data_dir, md_dir, url_to_relpath) if url else ""
    return StickerAttachment(original_url=url, local_path=local_path)


def _resolve_wall(
    data: dict, cid: int, md_dir: str,
    little_raw_data_dir: str, large_raw_data_dir: str,
    url_to_relpath: Dict[str, str],
    authors: dict[int, AuthorInfo],
    config: Config,
) -> WallAttachment:
    owner_id = data.get("owner_id")
    children = [
        _resolve_attachment(a, cid, md_dir, little_raw_data_dir, large_raw_data_dir, url_to_relpath, authors, config)
        for a in data.get("attachments", [])
    ]
    author = authors.get(owner_id) if owner_id is not None else None
    return WallAttachment(
        owner_id=owner_id,
        id=data.get("id"),
        text=(data.get("text") or "").strip(),
        children=children,
        author=author,
    )


def _download_to_raw(
    url: str, cid: int, storage_dir: str,
    md_dir: str, url_to_relpath: Dict[str, str], force_ext: str = "",
) -> str:
    if url in url_to_relpath:
        return url_to_relpath[url]

    ext = force_ext if force_ext else _get_ext(url)
    raw_dir = Path(storage_dir) / str(cid)
    raw_dir.mkdir(parents=True, exist_ok=True)

    n = 1
    while (raw_dir / f"{n}.{ext}").exists():
        n += 1

    filepath = raw_dir / f"{n}.{ext}"
    download_file(url, str(filepath))
    relpath = path_rel(str(filepath), md_dir)
    url_to_relpath[url] = relpath
    return relpath


def _get_ext(url: str) -> str:
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "mp4"):
        return ext
    return "jpg"


def _should_download_video(duration: int, config: Config) -> bool:
    if duration < config.long_video_threshold:
        return config.download_short_video
    return config.download_long_video


def _get_best_video_url(files: dict) -> Optional[str]:
    for key in ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240"):
        if files.get(key):
            return files[key]
    return None


def _compute_heading(text: str, cid: int) -> str:
    if text:
        first = _first_sentence(text)
        if len(first) > 60:
            first = first[:60] + "..."
        return first
    return f"Сообщение (id {cid})"


def _compute_filename(
    text: str,
    attachments: List[BaseAttachmentItem],
    json_stem: str,
    cid: int,
    text_override: str = "",
) -> str:
    source_text = text_override if text_override else text
    if source_text:
        first = _first_sentence(source_text)
        if len(first) > 60:
            first = first[:60] + "..."
        name = f"{first}.Id{cid}.md"
    else:
        prefix = _get_attachment_types(attachments)
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
        "", name,
    )
    name = name.replace("\u2014", "-")
    name = name.replace("\u2013", "-")
    name = name.strip(". ")
    if not name:
        name = "message.md"
    return name


_type_label_map = {
    PhotoAttachment: "Photo",
    LinkAttachment: "Link",
    WallAttachment: "Article",
    DocAttachment: "Doc",
    AudioAttachment: "Audio",
    StickerAttachment: "Sticker",
}


def _get_attachment_label(att: BaseAttachmentItem) -> str:
    if isinstance(att, VideoAttachment):
        return "ShortVideo" if att.is_short else "Video"
    return _type_label_map.get(type(att), "Media")


def _get_attachment_types(attachments: List[BaseAttachmentItem]) -> str:
    if not attachments:
        return "Media"
    types = set()
    for att in attachments:
        types.add(_get_attachment_label(att))
    if len(types) == 1:
        return list(types)[0]
    return "Media"
