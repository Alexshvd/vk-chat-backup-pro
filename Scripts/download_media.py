from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class DownloadItem:
    url: str
    relpath: str


def download_all(queue: dict[int, list[DownloadItem]], md_dir: str) -> None:
    for cid, items in queue.items():
        print(f"  CID {cid}: {len(items)} файлов")
        for item in items:
            filepath = Path(md_dir) / item.relpath
            filepath.parent.mkdir(parents=True, exist_ok=True)
            resp = requests.get(item.url, timeout=30)
            resp.raise_for_status()
            filepath.write_bytes(resp.content)
