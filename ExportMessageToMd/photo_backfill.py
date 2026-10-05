"""Upgrade existing photo copies while preserving message edits and originals."""
from datetime import datetime
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse

from dialog_dirs import collect_dialog_dirs
from config_loader import path_rel
from download_media import download_file
from photo_media import best_photo_url, image_size, photo_sizes
from Loggers.context_logger import ContextLogger


def walk_photos(node):
    if isinstance(node, list):
        for child in node:
            yield from walk_photos(child)
    elif isinstance(node, dict):
        if node.get("type") == "photo" and isinstance(node.get("photo"), dict):
            yield node["photo"]
            return
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from walk_photos(child)


def backfill_photos(config, logger, peer_ids=None):
    root = Path(config.export_root)
    backup = root / "ExportMessages/PhotoBackups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    checked = saved = restored = failed = 0
    handled = set()
    upgraded_targets = set()
    for peer, directory in collect_dialog_dirs(root / "ExportMessages/Dialogs", config).items():
        if peer_ids is not None and peer not in peer_ids:
            continue
        originals = {}
        for original in (directory / "OriginalMessages").glob("*.json"):
            match = re.search(r"_(\d+)\.json$", original.name)
            if match:
                originals[int(match.group(1))] = original
        for md in (directory / "MdFiles").rglob("*.md"):
            match = re.search(r"(?:^|\.)Id(\d+)(?:_part_\d+)?\.md$", md.name)
            if not match or int(match.group(1)) not in originals:
                continue
            cid = int(match.group(1))
            message = json.loads(originals[cid].read_text(encoding="utf-8"))
            if (cid <= config.min_cid_by_peer_id.get(peer, -1)
                    or message.get("date", 0) <= config.min_date_by_peer_id.get(peer, -1)):
                continue
            photos = {s["url"]: photo for photo in walk_photos(message) for s in photo_sizes(photo)}
            if not photos:
                continue
            old_text = md.read_text(encoding="utf-8")
            new_text = old_text
            for row in old_text.splitlines():
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if len(cells) != 3 or cells[0] != "Фото":
                    continue
                remote = re.fullmatch(r"\[.*?\]\((https?://.*)\)", cells[2])
                local = re.fullmatch(r"\[.*?\]\((.*)\)", cells[1])
                repair = cells[1] == "Ошибка скачивания"
                if not remote or (not local and not repair) or remote.group(1) not in photos:
                    continue
                photo = photos[remote.group(1)]
                best = best_photo_url(photo)
                if repair:
                    suffix = Path(urlparse(best).path).suffix.lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        suffix = ".jpg"
                    identity = f"{photo.get('owner_id')}:{photo.get('id')}:{best}"
                    name = "recovered_" + hashlib.sha256(identity.encode()).hexdigest()[:24] + suffix
                    target = (directory / "RawData" / str(cid) / name).resolve()
                else:
                    target = (md.parent / local.group(1)).resolve()
                shared = (root / "LargeRawData/SharedMedia/images").resolve()
                is_shared = target.is_relative_to(shared)
                if not is_shared and not target.is_relative_to((directory / "RawData").resolve()):
                    continue
                dimensions = image_size(target)
                largest = photo_sizes(photo)[0]
                expected_area = (largest.get("width") or 0) * (largest.get("height") or 0)
                actual_area = dimensions[0] * dimensions[1] if dimensions else 0
                if target not in handled:
                    checked += 1
                if best == remote.group(1) and dimensions and actual_area >= expected_area:
                    handled.add(target)
                    if not repair:
                        continue
                    upgraded_targets.add(target)
                if target in handled and target not in upgraded_targets:
                    continue
                if target not in handled:
                    yield f"Фото: диалог {peer}, сообщение {cid} — скачиваю максимальный размер…"
                    temporary = target.with_name(target.stem + ".photo-upgrade" + target.suffix)
                    context = ContextLogger(logger, f"Диалог {peer}; сообщение №{cid}; фото — максимальный размер")
                    if not download_file(best, str(temporary), context):
                        failed += 1
                        handled.add(target)
                        continue
                    upgraded = image_size(temporary)
                    if not upgraded or upgraded[0] * upgraded[1] < max(actual_area, expected_area):
                        logger.LogWarning(f"Сообщение {cid}: сервер вернул фото меньше ожидаемого; прежний файл сохранён.")
                        failed += 1
                        handled.add(target)
                        temporary.unlink(missing_ok=True)
                        continue
                    if not is_shared:
                        relative = target.relative_to(directory.resolve())
                        photo_backup = backup / f"dialog_{peer}" / relative
                        photo_backup.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            shutil.copy2(target, photo_backup)
                    if is_shared:
                        # Content-addressed shared images are immutable. Upgrade
                        # only this message, preserving all other references.
                        from media_store import file_hash
                        upgraded_path = shared / ('sha256_' + file_hash(temporary) + target.suffix)
                        if upgraded_path.exists():
                            temporary.unlink()
                        else:
                            os.replace(temporary, upgraded_path)
                        old_relative = local.group(1)
                        new_relative = path_rel(str(upgraded_path), str(md.parent))
                        new_text = new_text.replace(old_relative, new_relative)
                        row = row.replace(old_relative, new_relative)
                        target = upgraded_path
                    else:
                        os.replace(temporary, target)
                    handled.add(target)
                    upgraded_targets.add(target)
                    if dimensions:
                        saved += 1
                    else:
                        restored += 1
                    yield f"Фото {peer}/{cid}: {dimensions or 'нет файла'} → {upgraded}, {target.stat().st_size} байт."
                # Only update the source URL; the filename, local link and message stay intact.
                new_row = row.replace(remote.group(1), best)
                if repair and target in upgraded_targets:
                    relative = path_rel(str(target), str(md.parent))
                    new_row = new_row.replace("Ошибка скачивания", f"[{relative}]({relative})")
                    fallback = f"**Фото:** [ссылка]({remote.group(1)})"
                    image = f'**Фото:** <a href="{escape(relative, quote=True)}"><img src="{escape(relative, quote=True)}" width="300" alt="Фото"></a>'
                    new_text = new_text.replace(fallback, image)
                new_text = new_text.replace(row, new_row)
            if new_text != old_text:
                if md.read_text(encoding="utf-8") != old_text:
                    raise RuntimeError("Сообщение изменилось во время догрузки фото; MD не перезаписан.")
                md_backup = backup / f"dialog_{peer}" / md.relative_to(directory)
                md_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(md, md_backup)
                temporary_md = md.with_suffix(".md.photo-tmp")
                temporary_md.write_text(new_text, encoding="utf-8")
                os.replace(temporary_md, md)
    yield f"Проверка фото завершена. Проверено: {checked}; заменено: {saved}; восстановлено: {restored}; ошибок: {failed}."
