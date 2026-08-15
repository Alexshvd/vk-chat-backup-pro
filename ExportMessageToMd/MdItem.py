from dataclasses import dataclass, field
from typing import Any, List, Optional

from author_resolver import AuthorInfo


class BaseDownloadResult:
    pass


@dataclass
class NoDownloadResult(BaseDownloadResult):
    pass


@dataclass
class ErrorDownloadResult(BaseDownloadResult):
    pass


@dataclass
class SuccessDownloadResult(BaseDownloadResult):
    local_path: str


class BaseAttachmentItem:
    pass


@dataclass
class PhotoAttachment(BaseAttachmentItem):
    original_url: str
    download_result: BaseDownloadResult = field(default_factory=NoDownloadResult)


@dataclass
class VideoAttachment(BaseAttachmentItem):
    is_short: bool = False
    title: str = ""
    player_url: str = ""
    duration: int = 0
    mp4_url: str = ""
    mp4_download_result: BaseDownloadResult = field(default_factory=NoDownloadResult)
    preview_url: str = ""
    preview_download_result: BaseDownloadResult = field(default_factory=NoDownloadResult)


@dataclass
class LinkAttachment(BaseAttachmentItem):
    url: str = ""
    title: str = ""


@dataclass
class DocAttachment(BaseAttachmentItem):
    url: str = ""
    title: str = ""
    download_result: BaseDownloadResult = field(default_factory=NoDownloadResult)


@dataclass
class AudioAttachment(BaseAttachmentItem):
    artist: str = ""
    title: str = ""


@dataclass
class StickerAttachment(BaseAttachmentItem):
    original_url: str = ""
    download_result: BaseDownloadResult = field(default_factory=NoDownloadResult)


@dataclass
class WallAttachment(BaseAttachmentItem):
    owner_id: Any = None
    id: Any = None
    text: str = ""
    children: List[BaseAttachmentItem] = field(default_factory=list)
    author: Optional[AuthorInfo] = None


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
    author: Optional[AuthorInfo] = None
    reply: Optional[List["MdItem"]] = None
