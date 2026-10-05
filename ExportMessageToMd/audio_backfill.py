"""Add audio to saved messages without rebuilding text or other attachments."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from audio_media import audio_payload, audio_sources, resolve_audio
from dialog_dirs import collect_dialog_dirs
from MdItem import SuccessDownloadResult, ErrorDownloadResult
from md_renderer import audio_source_row, _render_attachment
from Loggers.context_logger import ContextLogger

CID_PATTERN = re.compile(r"(?:^|\.)Id(\d+)(?:_part_\d+)?\.md$")


def walk_audio(node):
    if isinstance(node, list):
        for child in node:
            yield from walk_audio(child)
    elif isinstance(node, dict):
        payload = audio_payload(node)
        if payload is not None:
            yield payload
            return
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from walk_audio(child)


def saved_audio(md_text, md_dir):
    result = {}
    for line in md_text.splitlines():
        if not line.startswith(("| Аудио |", "| Голосовое сообщение |")):
            continue
        cells = line.strip().strip("|").split("|")
        if len(cells) != 3:
            continue
        local = re.fullmatch(r"\[.*?\]\((.*)\)", cells[1].strip())
        remote = re.fullmatch(r"\[.*?\]\((.*)\)", cells[2].strip())
        if local and remote:
            path = (md_dir / local.group(1)).resolve()
            if path.is_file() and path.stat().st_size:
                result[remote.group(1)] = local.group(1)
    return result


def backfill_audio(config, logger, peer_ids=None):
    root = Path(config.export_root)
    directories = collect_dialog_dirs(root / "ExportMessages/Dialogs", config)
    backup = root / "ExportMessages/AudioBackups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    saved = skipped = unavailable = failed = 0
    for peer, directory in directories.items():
        if peer_ids is not None and peer not in peer_ids:
            continue
        md_by_cid = {}
        for path in (directory / "MdFiles").rglob("*.md"):
            match = CID_PATTERN.search(path.name)
            if match:
                md_by_cid.setdefault(int(match.group(1)), []).append(path)
        for original in sorted((directory / "OriginalMessages").glob("*.json")):
            message = json.loads(original.read_text(encoding="utf-8"))
            cid = message.get("conversation_message_id")
            paths = md_by_cid.get(cid, [])
            if not paths or cid <= config.min_cid_by_peer_id.get(peer, -1) or message.get("date", 0) <= config.min_date_by_peer_id.get(peer, -1):
                continue
            entries = [(data, voice) for data, voice in walk_audio(message)
                       if (config.download_voice_messages if voice else config.download_audio)]
            if not entries:
                continue
            for path in paths:
                old_text = path.read_text(encoding="utf-8")
                assets = saved_audio(old_text, path.parent)
                new_text = old_text
                seen = set()
                for data, voice in entries:
                    sources = audio_sources(data, voice)
                    key = (voice, tuple(url for url, ext in sources), data.get("artist"), data.get("title"))
                    if key in seen:
                        continue
                    seen.add(key)
                    if sources and any(url in assets for url, ext in sources):
                        skipped += 1
                        continue
                    yield f"Скачивание аудио в сообщении {cid}…"
                    context = ContextLogger(logger, f"Диалог {peer}; сообщение №{cid}")
                    item = resolve_audio(data, voice, directory / "RawData" / str(cid), path.parent, assets, config, context)
                    if isinstance(item.download_result, ErrorDownloadResult):
                        failed += 1
                        yield f"Сообщение {cid}: не удалось скачать аудио."
                        continue
                    if not sources:
                        unavailable += 1
                        yield f"Сообщение {cid}: ВК не передал ссылку на аудиофайл."
                        continue
                    if isinstance(item.download_result, SuccessDownloadResult):
                        saved += 1
                        row = audio_source_row(item)
                        title = " — ".join(filter(None, [item.artist, item.title]))
                        old_row = f"| Аудио | | {title} |"
                        new_text = new_text.replace(old_row, row) if old_row in new_text else new_text.rstrip() + "\n" + row + "\n"
                        player = _render_attachment(item)
                        new_text = new_text.rstrip() + "\n\n" + "\n".join(player) + "\n"
                        yield f"Сообщение {cid}: аудиофайл сохранён."
                if new_text != old_text:
                    if path.read_text(encoding="utf-8") != old_text:
                        raise RuntimeError("Сообщение изменилось во время скачивания аудио; MD не перезаписан.")
                    backup.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
                    (backup / (digest + ".md")).write_text(old_text, encoding="utf-8")
                    temporary = path.with_suffix(".md.audio-tmp")
                    temporary.write_text(new_text, encoding="utf-8")
                    os.replace(temporary, path)
    yield f"Готово. Сохранено аудиофайлов: {saved}; уже были сохранены: {skipped}; без ссылки от ВК: {unavailable}; ошибок: {failed}."
