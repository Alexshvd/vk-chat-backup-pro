import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from download_media import download_file
from config import path_rel


@dataclass
class AuthorInfo:
    author_id: int
    name: str
    screen_name: str
    photo_url: str
    photo_local: str
    author_type: str


def load_authors(data: dict) -> dict[int, AuthorInfo]:

    authors: dict[int, AuthorInfo] = {}

    for p in data.get("profiles", []):
        pid = p.get("id")
        if pid is None:
            continue
        first = p.get("first_name", "")
        last = p.get("last_name", "")
        name = f"{first} {last}".strip()
        screen_name = p.get("screen_name", "") or ""
        photo_url = p.get("photo_100") or p.get("photo_50") or ""
        authors[pid] = AuthorInfo(
            author_id=pid,
            name=name,
            screen_name=screen_name,
            photo_url=photo_url,
            photo_local="",
            author_type="Пользователь",
        )

    for g in data.get("groups", []):
        gid = g.get("id")
        if gid is None:
            continue
        author_id = -gid
        name = g.get("name", "")
        screen_name = g.get("screen_name", "") or ""
        photo_url = g.get("photo_100") or g.get("photo_50") or ""
        authors[author_id] = AuthorInfo(
            author_id=author_id,
            name=name,
            screen_name=screen_name,
            photo_url=photo_url,
            photo_local="",
            author_type="Сообщество",
        )

    return authors


def _get_ext_from_url(url: str) -> str:
    path = urlparse(url).path
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext if ext in ("jpg", "jpeg", "png", "gif", "webp") else "jpg"


def ensure_author_avatars(
    authors: dict[int, AuthorInfo],
    authors_dir: str,
    url_to_relpath: dict[str, str],
    md_dir: str,
) -> None:
    for author_id, info in authors.items():
        if not info.photo_url:
            continue

        if info.photo_url in url_to_relpath:
            info.photo_local = url_to_relpath[info.photo_url]
            continue

        ext = _get_ext_from_url(info.photo_url)
        filename = f"{author_id}.{ext}"
        filepath = Path(authors_dir) / filename

        if filepath.exists():
            relpath = path_rel(str(filepath), md_dir)
            url_to_relpath[info.photo_url] = relpath
            info.photo_local = relpath
            continue

        filepath.parent.mkdir(parents=True, exist_ok=True)
        download_file(info.photo_url, str(filepath))
        relpath = path_rel(str(filepath), md_dir)
        url_to_relpath[info.photo_url] = relpath
        info.photo_local = relpath
