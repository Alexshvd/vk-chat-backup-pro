"""Repair missing local video links without regenerating saved messages."""
from datetime import datetime
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re

from config_loader import path_rel
from dialog_dirs import collect_dialog_dirs
from download_media import download_file
from md_item_builder import _get_best_video_url, _should_download_video, _video_fallback_urls
from video_cache import VideoCache, video_quality
from Loggers.context_logger import ContextLogger


def walk_videos(node):
    if isinstance(node, list):
        for child in node:
            yield from walk_videos(child)
    elif isinstance(node, dict):
        if node.get("type") in ("video", "short_video") and isinstance(node.get("video"), dict):
            yield node["video"]
            return
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from walk_videos(child)


def is_mp4(path):
    if not path.is_file() or not path.stat().st_size:
        return False
    with path.open("rb") as stream:
        return b"ftyp" in stream.read(64)


def backfill_videos(config, logger, peer_ids=None, video_cache=None):
    if video_cache is None:
        with VideoCache(config.export_root, logger) as cache:
            cache.scan(config)
            yield from _backfill_videos(config, logger, peer_ids, cache)
    else:
        yield from _backfill_videos(config, logger, peer_ids, video_cache)


def _backfill_videos(config, logger, peer_ids, video_cache):
    root = Path(config.export_root)
    backup = root / "ExportMessages/VideoBackups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    saved = failed = 0
    for peer, directory in collect_dialog_dirs(root / "ExportMessages/Dialogs", config).items():
        if peer_ids is not None and peer not in peer_ids:
            continue
        originals = {}
        for original in (directory / "OriginalMessages").glob("*.json"):
            match = re.search(r"_(\d+)\.json$", original.name)
            if match:
                originals[int(match.group(1))] = original
        for path in (directory / "MdFiles").rglob("*.md"):
            match = re.search(r"(?:^|\.)Id(\d+)(?:_part_\d+)?\.md$", path.name)
            if not match or int(match.group(1)) not in originals:
                continue
            cid = int(match.group(1))
            old_text = path.read_text(encoding="utf-8")
            rows = []
            for row in old_text.splitlines():
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if len(cells) != 3 or cells[0] != "Видео":
                    continue
                remote = re.fullmatch(r"\[.*?\]\((https?://.*)\)", cells[2])
                local = re.fullmatch(r"\[.*?\]\((.*)\)", cells[1])
                if remote and (not local or not is_mp4((path.parent / local.group(1)).resolve())):
                    rows.append((row, remote.group(1)))
            if not rows:
                continue
            message = json.loads(originals[cid].read_text(encoding="utf-8"))
            if (cid <= config.min_cid_by_peer_id.get(peer, -1)
                    or message.get("date", 0) <= config.min_date_by_peer_id.get(peer, -1)):
                continue
            videos = {video.get("player"): video for video in walk_videos(message)}
            new_text = old_text
            for row, player in rows:
                video = videos.get(player)
                if not video or not _should_download_video(video.get("duration", 0), config):
                    continue
                files = video.get("files", {})
                url = _get_best_video_url(files)
                target = video_cache.find(video, video_quality(files))
                if not url and target is None:
                    continue
                yield f"Догрузка видео: диалог {peer}, сообщение {cid}…"
                digest = hashlib.sha256(player.encode("utf-8")).hexdigest()[:20]
                if target is None:
                    target = (video_cache.target(video, video_quality(files, url))
                              or root / "LargeRawData" / f"dialog_{peer}" / str(cid) / f"video_{digest}.mp4")
                if not is_mp4(target):
                    temporary = target.with_name(target.stem + ".downloading.mp4")
                    context = ContextLogger(logger, f"Диалог {peer}; сообщение №{cid}; видео: {video.get('title', '')}")
                    if not download_file(url, str(temporary), context, fallback_urls=_video_fallback_urls(url, files)):
                        failed += 1
                        yield f"Сообщение {cid}: видео скачать не удалось."
                        continue
                    if not is_mp4(temporary):
                        temporary.unlink(missing_ok=True)
                        failed += 1
                        logger.LogWarning(f"Сообщение {cid}: сервер вернул файл другого формата вместо MP4.")
                        continue
                    os.replace(temporary, target)
                    video_cache.register(target, video, video_quality(files, url))
                relative = path_rel(str(target), str(path.parent))
                cells = row.split("|")
                cells[2] = f" [{relative}]({relative}) "
                new_text = new_text.replace(row, "|".join(cells))
                tag = f'<video src="{escape(relative, quote=True)}" width="240" controls></video>'
                block = '<details>\n<summary>Смотреть через VK Player</summary>\n<iframe src="' + player + '"'
                if tag not in new_text:
                    if block in new_text:
                        new_text = new_text.replace(block, tag + "\n\n" + block)
                    else:
                        new_text = new_text.rstrip() + "\n\n" + tag + "\n"
                saved += 1
                yield f"Сообщение {cid}: видео сохранено ({target.stat().st_size} байт)."
            if new_text != old_text:
                if path.read_text(encoding="utf-8") != old_text:
                    raise RuntimeError("Сообщение изменилось во время догрузки видео; MD не перезаписан.")
                backup.mkdir(parents=True, exist_ok=True)
                name = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest() + ".md"
                (backup / name).write_text(old_text, encoding="utf-8")
                temporary_md = path.with_suffix(".md.video-tmp")
                temporary_md.write_text(new_text, encoding="utf-8")
                os.replace(temporary_md, path)
    yield f"Догрузка видео завершена. Восстановлено: {saved}; ошибок скачивания: {failed}."
