import json
import os
from datetime import datetime

from config import Config


def path_rel(target: str, start: str = os.curdir) -> str:
    return os.path.relpath(target, start).replace("\\", "/")


def load_config(path: str) -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    export_root = raw.get("export_root", "")
    if not export_root:
        export_root = os.path.join(os.path.dirname(os.path.abspath(path)), "Temp", "ExportMessages")

    min_cid = {int(k): int(v) for k, v in raw.get("min_cid_by_peer_id", {}).items()}
    min_date = {
        int(k): int(datetime.strptime(v, "%Y-%m-%d-%H-%M-%S").timestamp())
        for k, v in raw.get("min_date_by_peer_id", {}).items()
    }

    return Config(
        export_root=export_root,
        download_short_video=raw.get("download_short_video", True),
        download_long_video=raw.get("download_long_video", False),
        long_video_threshold=raw.get("long_video_threshold", 180),
        min_cid_by_peer_id=min_cid,
        min_date_by_peer_id=min_date,
    )
