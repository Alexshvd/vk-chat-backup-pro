from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import List, Optional

import requests

from Loggers.base_logger import BaseLogger

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}


@dataclass
class DownloadItem:
    url: str
    relpath: str


class _Progress:
    """Optional local status file; progress reporting must never break a download."""
    def __init__(self, filepath, total=0, received=0, connections=1):
        self.filepath = filepath
        self.total = total
        self.received = received
        self.initial = received
        self.connections = connections
        self.started = time.monotonic()
        self.last_report = 0.0
        self.lock = threading.Lock()

    def add(self, count):
        with self.lock:
            self.received += count
            self.report()

    def report(self, state="downloading", force=False):
        now = time.monotonic()
        destination = os.environ.get("VK_BACKUP_DOWNLOAD_PROGRESS")
        if not destination or (not force and now - self.last_report < 1):
            return
        self.last_report = now
        elapsed = max(now - self.started, 0.001)
        data = {"state": state, "file": self.filepath.name, "message_cid": self.filepath.parent.name,
                "received_bytes": self.received, "total_bytes": self.total,
                "bytes_per_second": max(0, self.received - self.initial) / elapsed,
                "connections": self.connections, "updated_at": time.time()}
        path = Path(destination)
        temporary = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass


def _range_metadata(url, timeout):
    headers = dict(DOWNLOAD_HEADERS, Range="bytes=0-0", **{"Accept-Encoding": "identity"})
    with requests.get(url, timeout=timeout, headers=headers, stream=True) as response:
        response.raise_for_status()
        match = re.fullmatch(r"bytes 0-0/(\d+)", response.headers.get("Content-Range", ""))
        if response.status_code != 206 or not match:
            return None
        if len(next(response.iter_content(1), b"")) != 1:
            return None
        return int(match.group(1)), response.headers.get("ETag", "")


def _parallel_download(urls, filepath, metadata, timeout):
    total, etag = metadata
    # Cache completed pieces outside the message folder, which the renderer may
    # recreate on resume. A cache belongs to one exact URL, target and object.
    cache_root = Path(os.environ.get("VK_BACKUP_DOWNLOAD_CACHE", str(filepath.parent / ".downloads")))
    identity = json.dumps([str(filepath.resolve()), urls[0], total, etag]).encode("utf-8")
    try:
        workers = max(1, min(128, int(os.environ.get("VK_BACKUP_DOWNLOAD_CONNECTIONS", "112"))))
    except ValueError:
        workers = 112
    unit = 1024 * 1024
    size = max(unit, min(16 * unit, ((total + workers * unit - 1) // (workers * unit)) * unit))
    if workers <= 8:
        size = 16 * unit
    # Keep the old 16 MiB layout when resuming a download started by the
    # previous version. Completed pieces must not be downloaded again.
    old_cache = cache_root / hashlib.sha256(identity).hexdigest()
    if old_cache.is_dir() and any(old_cache.glob("*.part")):
        cache = old_cache
        size = 16 * unit
    else:
        cache = cache_root / hashlib.sha256(identity + f":{size}".encode("ascii")).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    ranges = [(i, offset, min(offset + size, total) - 1) for i, offset in enumerate(range(0, total, size))]
    finished = {i for i, first, last in ranges if (cache / f"{i}.part").is_file() and (cache / f"{i}.part").stat().st_size == last - first + 1}
    received = sum(last - first + 1 for i, first, last in ranges if i in finished)
    workers = min(workers, max(1, len(ranges) - len(finished)))
    progress = _Progress(filepath, total, received, connections=workers)
    progress.report(force=True)

    def fetch_piece(piece):
        i, first, last = piece
        target = cache / f"{i}.part"
        temporary = cache / f"{i}.tmp"
        last_error = None
        for url in urls:
            count = 0
            started = time.monotonic()
            headers = dict(DOWNLOAD_HEADERS, Range=f"bytes={first}-{last}", **{"Accept-Encoding": "identity"})
            try:
                with requests.get(url, timeout=timeout, headers=headers, stream=True) as response:
                    response.raise_for_status()
                    expected = f"bytes {first}-{last}/{total}"
                    if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                        raise ValueError("CDN returned an incorrect byte range")
                    if etag and response.headers.get("ETag") != etag:
                        raise ValueError("Video changed during download")
                    with temporary.open("wb") as output:
                        for chunk in response.iter_content(64 * 1024):
                            if not chunk:
                                continue
                            if count + len(chunk) > last - first + 1:
                                raise ValueError("CDN returned too much data")
                            output.write(chunk)
                            count += len(chunk)
                            progress.add(len(chunk))
                            if time.monotonic() - started > 180:
                                raise TimeoutError("CDN is too slow for this piece")
                if count != last - first + 1:
                    raise ValueError("Video piece is incomplete")
                os.replace(temporary, target)
                return
            except Exception as error:
                last_error = error
                progress.add(-count)
        raise last_error

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_piece, piece) for piece in ranges if piece[0] not in finished]
            try:
                for future in as_completed(futures):
                    future.result()
            except Exception:
                for future in futures:
                    future.cancel()
                raise
        progress.report(state="assembling", force=True)
        temporary = filepath.with_name(filepath.name + ".part")
        with temporary.open("wb") as output:
            for i, first, last in ranges:
                with (cache / f"{i}.part").open("rb") as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
        if temporary.stat().st_size != total:
            raise ValueError("Assembled video has an incorrect size")
        os.replace(temporary, filepath)
        progress.report(state="complete", force=True)
        # Delete only the exact piece files created for this object.
        for i, first, last in ranges:
            (cache / f"{i}.part").unlink(missing_ok=True)
        try:
            cache.rmdir()
        except OSError:
            pass
    except Exception:
        progress.report(state="failed", force=True)
        raise


def _stream_download(url, filepath, timeout):
    temporary = filepath.with_name(filepath.name + ".part")
    with requests.get(url, timeout=timeout, headers=DOWNLOAD_HEADERS, stream=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", "0")) if not response.headers.get("Content-Encoding") else 0
        progress = _Progress(filepath, total)
        progress.report(force=True)
        with temporary.open("wb") as output:
            for chunk in response.iter_content(64 * 1024):
                if chunk:
                    output.write(chunk)
                    progress.add(len(chunk))
        if total and progress.received != total:
            progress.report(state="failed", force=True)
            raise ValueError("Downloaded file is incomplete")
    os.replace(temporary, filepath)
    progress.report(state="complete", force=True)


def download_file(url: str, filepath: str, logger: BaseLogger, timeout: int = 30,
                  fallback_urls: Optional[List[str]] = None) -> bool:
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    candidates = list(dict.fromkeys([url] + (fallback_urls or [])))
    last_error = None
    if filepath.suffix.lower() == ".mp4":
        for candidate in candidates:
            metadata = None
            try:
                metadata = _range_metadata(candidate, timeout)
                if metadata and metadata[0] >= 4 * 1024 * 1024:
                    _parallel_download([candidate] + [u for u in candidates if u != candidate], filepath, metadata, timeout)
                    return True
                if metadata:
                    break
            except Exception as error:
                last_error = error
                # Preserve completed pieces after a failed parallel attempt.
                if metadata and metadata[0] >= 4 * 1024 * 1024:
                    logger.LogWarning(f"Ошибка скачивания\nФайл: {filepath}\nURL: {url}\nПричина: {last_error}")
                    return False
    for candidate in candidates:
        try:
            _stream_download(candidate, filepath, timeout)
            return True
        except Exception as e:
            last_error = e
    logger.LogWarning(f"Ошибка скачивания\nФайл: {filepath}\nURL: {url}\nПричина: {last_error}")
    return False


def download_all(queue: dict[int, list[DownloadItem]], md_dir: str, logger: BaseLogger) -> None:
    for cid, items in queue.items():
        logger.LogWarning(f"CID {cid}: {len(items)} файлов")
        for item in items:
            filepath = Path(md_dir) / item.relpath
            filepath.parent.mkdir(parents=True, exist_ok=True)
            download_file(item.url, str(filepath), logger)
