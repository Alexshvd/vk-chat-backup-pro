from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Config:
    export_root: str = ""
    download_short_video: bool = True
    download_long_video: bool = False
    long_video_threshold: int = 180
    min_cid_by_peer_id: Dict[int, int] = field(default_factory=dict)
    min_date_by_peer_id: Dict[int, int] = field(default_factory=dict)
