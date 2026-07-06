import json
import os
from datetime import datetime
from pathlib import Path

from config import Config


def path_rel(target: str, start: str = os.curdir) -> str:
    return os.path.relpath(target, start).replace("\\", "/")


def load_config(path: str = None) -> Config:
    if path is None:
        path = str(Path(__file__).parent / "config.json")

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    raw_export_root = raw.get("export_root", "")
    if not raw_export_root:
        raw_export_root = str(Path(__file__).resolve().parent / "Temp" / "ExportMessages")

    min_cid = {}
    for k, v in raw.get("min_cid_by_peer_id", {}).items():
        min_cid[int(k)] = int(v)

    min_date = {}
    for k, v in raw.get("min_date_by_peer_id", {}).items():
        min_date[int(k)] = int(datetime.strptime(v, "%Y-%m-%d-%H-%M-%S").timestamp())

    return Config(
        export_root=raw_export_root,
        download_short_video=raw.get("download_short_video", True),
        download_long_video=raw.get("download_long_video", False),
        long_video_threshold=raw.get("long_video_threshold", 180),
        min_cid_by_peer_id=min_cid,
        min_date_by_peer_id=min_date,
    )


config = load_config()
