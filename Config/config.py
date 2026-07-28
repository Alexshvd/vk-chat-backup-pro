from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Config:
    export_root: str = ""
    download_short_video: bool = True
    download_long_video: bool = False
    long_video_threshold: int = 180
    overwrite_existing_md: bool = False
    overwrite_existing_original_message_json: bool = False
    dialog_name_by_peer_id: Dict[int, str] = field(default_factory=dict)
    peer_id_by_dialog_custom_name: Dict[str, int] = field(default_factory=dict)
    min_cid_by_peer_id: Dict[int, int] = field(default_factory=dict)
    min_date_by_peer_id: Dict[int, int] = field(default_factory=dict)
