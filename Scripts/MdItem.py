from dataclasses import dataclass, field
from typing import Any, List, Optional


class BaseAttachmentItem:
    pass


@dataclass
class PhotoAttachment(BaseAttachmentItem):
    original_url: str
    local_path: str = ""


@dataclass
class VideoAttachment(BaseAttachmentItem):
    is_short: bool = False
    title: str = ""
    player_url: str = ""
    duration: int = 0
    mp4_local_path: str = ""
    mp4_url: str = ""
    preview_local_path: str = ""
    preview_url: str = ""


@dataclass
class LinkAttachment(BaseAttachmentItem):
    url: str = ""
    title: str = ""


@dataclass
class DocAttachment(BaseAttachmentItem):
    url: str = ""
    title: str = ""


@dataclass
class AudioAttachment(BaseAttachmentItem):
    artist: str = ""
    title: str = ""


@dataclass
class StickerAttachment(BaseAttachmentItem):
    original_url: str = ""
    local_path: str = ""


@dataclass
class WallAttachment(BaseAttachmentItem):
    owner_id: Any = None
    id: Any = None
    text: str = ""
    children: List[BaseAttachmentItem] = field(default_factory=list)


@dataclass
class MdItem:
    cid: int
    from_id: Any
    date: Optional[int]
    text: str
    attachments: List[BaseAttachmentItem]
    forwarded: List["MdItem"]
    json_filename: str
    heading: str
    filename: str
    is_wall_split: bool = False
    author_id: int = 0
    author_name: str = ""
    author_screen_name: str = ""
    author_photo_url: str = ""
    author_photo_local: str = ""
    author_type: str = ""
