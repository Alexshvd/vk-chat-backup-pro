from dataclasses import dataclass
from pathlib import Path

import requests

from Loggers.base_logger import BaseLogger


@dataclass
class DownloadItem:
    url: str
    relpath: str


def download_file(url: str, filepath: str, logger: BaseLogger, timeout: int = 30) -> bool:
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        filepath.write_bytes(resp.content)
        return True
    except Exception as e:
        logger.LogWarning(f"Ошибка скачивания {url}: {e}")
        return False


def download_all(queue: dict[int, list[DownloadItem]], md_dir: str, logger: BaseLogger) -> None:
    for cid, items in queue.items():
        logger.LogWarning(f"CID {cid}: {len(items)} файлов")
        for item in items:
            filepath = Path(md_dir) / item.relpath
            filepath.parent.mkdir(parents=True, exist_ok=True)
            try:
                resp = requests.get(item.url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                filepath.write_bytes(resp.content)
            except Exception as e:
                logger.LogWarning(f"Ошибка скачивания {item.url}: {e}")
