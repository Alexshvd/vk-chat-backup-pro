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
        parent = os.path.dirname(os.path.abspath(path))
        export_root = f"{parent}/Temp/ExportMessages"

    dialog_names = {int(k): str(v) for k, v in raw.get("dialog_name_by_peer_id", {}).items()}
    peer_id_by_custom_name = {v: k for k, v in dialog_names.items()}
    min_cid = {int(k): int(v) for k, v in raw.get("min_cid_by_peer_id", {}).items()}
    min_date = {
        int(k): int(datetime.strptime(v, "%Y-%m-%d-%H-%M-%S").timestamp())
        for k, v in raw.get("min_date_by_peer_id", {}).items()
    }

    return Config(
        export_root=export_root,
        download_short_video=raw.get("download_short_video", True),
        download_long_video=raw.get("download_long_video", False),
        download_audio=raw.get("download_audio", False),
        download_voice_messages=raw.get("download_voice_messages", True),
        long_video_threshold=raw.get("long_video_threshold", 180),
        overwrite_existing_md=raw.get("overwrite_existing_md", False),
        overwrite_existing_original_message_json=raw.get("overwrite_existing_original_message_json", False),
        dialog_name_by_peer_id=dialog_names,
        peer_id_by_dialog_custom_name=peer_id_by_custom_name,
        min_cid_by_peer_id=min_cid,
        min_date_by_peer_id=min_date,
    )
