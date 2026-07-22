import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import Config
from config_loader import load_config
from export_fwd import extract_items_from_data
from md_renderer import render_md_item
from md_item_builder import build_md_items
from author_resolver import load_authors, ensure_author_avatars
from Loggers.base_logger import BaseLogger


def _is_msg_filtered(item: dict, peer_id: int, config: Config) -> bool:
    min_cid = config.min_cid_by_peer_id.get(peer_id)
    min_date = config.min_date_by_peer_id.get(peer_id)
    if min_cid is not None and (item.get("conversation_message_id") or 0) <= min_cid:
        return True
    if min_date is not None and (item.get("date") or 0) <= min_date:
        return True
    return False


def main(config: Config, peer_ids: Optional[set[int]], logger: BaseLogger):
    start_create_time = datetime.now()

    export_root = Path(config.export_root)
    sources_dir = export_root / "ExportMessages" / "Sources"
    dialogs_dir = export_root / "ExportMessages" / "Dialogs"
    autor_images_dir = dialogs_dir / "AutorImages"
    large_root = export_root / "LargeRawData"

    sources = sorted(sources_dir.glob("*.json"))
    yield f"Найдено файлов: {len(sources)}"

    dialog_by_peer_id: dict[int, dict[int, dict]] = {}
    profiles = {}
    groups = {}

    for json_file in sources:
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)

        peer_id = data["peer_id"]
        dialog_by_peer_id.setdefault(peer_id, {})

        for item in data.get("items", []):
            cid = item.get("conversation_message_id")
            if cid is not None:
                dialog_by_peer_id[peer_id].setdefault(cid, item)

        for p in data.get("profiles", []):
            profiles.setdefault(p["id"], p)
        for g in data.get("groups", []):
            groups.setdefault(g["id"], g)

    if dialogs_dir.is_dir():
        for entry in dialogs_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("dialog_"):
                pid = int(entry.name[len("dialog_"):])
                if pid not in dialog_by_peer_id:
                    orig_dir = entry / "OriginalMessages"
                    if orig_dir.is_dir() and any(orig_dir.glob("*.json")):
                        dialog_by_peer_id[pid] = {}

    merged = {"profiles": list(profiles.values()), "groups": list(groups.values())}
    authors = load_authors(merged)
    yield f"Найдено авторов: {len(authors)}"

    if peer_ids is not None:
        dialog_by_peer_id = {k: v for k, v in dialog_by_peer_id.items() if k in peer_ids}
        yield f"Фильтрация по peer_id: отобрано {len(dialog_by_peer_id)} диалогов"

    for peer_id, items_dict in dialog_by_peer_id.items():
        items = list(items_dict.values())
        yield f"\n=== Диалог {peer_id} (сообщений: {len(items)}) ==="

        dialog_dir = dialogs_dir / f"dialog_{peer_id}"
        little_raw_data_dir = dialog_dir / "RawData"
        original_messages_dir = dialog_dir / "OriginalMessages"
        md_dir = dialog_dir / "MdFiles"
        large_raw_data_dir = large_root / f"dialog_{peer_id}"

        dialog_dir.mkdir(parents=True, exist_ok=True)

        url_to_relpath: dict[str, str] = {}
        ensure_author_avatars(authors, str(autor_images_dir), url_to_relpath, str(md_dir), logger)

        filtered_items = [item for item in items if not _is_msg_filtered(item, peer_id, config)]
        created, overwritten, skipped = extract_items_from_data(
            filtered_items, str(original_messages_dir),
            overwrite_existing_original_message_json=config.overwrite_existing_original_message_json,
        )
        yield f"  Сообщений: {created} создано, {overwritten} перезаписано, {skipped} пропущено"

        count = 0
        message_files = sorted(Path(original_messages_dir).glob("*.json"))

        existing_md_by_cid: dict[int, str] = {}
        if md_dir.is_dir():
            for md_file in md_dir.glob("*.Id*.md"):
                m = re.search(r'\.Id(\d+)\.md$', md_file.name)
                if m:
                    existing_md_by_cid[int(m.group(1))] = md_file.name

        for message_index, message_file in enumerate(message_files):
            with open(message_file, encoding="utf-8") as fp:
                item_data = json.load(fp)
            if _is_msg_filtered(item_data, peer_id, config):
                continue
            cid = item_data.get("conversation_message_id")
            if cid is None:
                continue
            is_overwrite = False
            if cid in existing_md_by_cid:
                if not config.overwrite_existing_md:
                    yield f"  Уже существует ({message_index + 1}/{len(message_files)} id={cid}): \"{existing_md_by_cid[cid]}\""
                    continue
                (md_dir / existing_md_by_cid[cid]).unlink(missing_ok=True)
                is_overwrite = True
            shutil.rmtree(little_raw_data_dir / str(cid), ignore_errors=True)
            shutil.rmtree(large_raw_data_dir / str(cid), ignore_errors=True)
            md_items = build_md_items(
                item_data, cid, cid, message_file.name, str(md_dir),
                str(little_raw_data_dir), str(large_raw_data_dir),
                authors, config, url_to_relpath, logger,
            )
            for md_index, item in enumerate(md_items):
                md_text = render_md_item(item)
                file_path = md_dir / item.filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as fp:
                    fp.write(md_text)
                action = "Перезаписан" if is_overwrite else "Создан"
                yield f"  {action} {message_index + 1}/{len(message_files)} id={item.cid} (part {md_index + 1}/{len(md_items)}): \"{item.filename}\""
                count += 1

        yield f"  Создано MD-файлов: {count}"

    yield f"\nГотово (Затраченое время = {datetime.now() - start_create_time})"


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Config"))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ExportMessageToMd"))
    from Loggers.print_logger import PrintLogger
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", required=True, help="Path to config.json")
    args = parser.parse_args()
    logger = PrintLogger()
    for msg in main(load_config(args.config), peer_ids=None, logger=logger):
        print(msg)
