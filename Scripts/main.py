import json
from datetime import datetime
from pathlib import Path

from export_fwd import extract_items_from_data
from md_renderer import render_md_item
from md_item_builder import build_md_items
from author_resolver import load_authors, ensure_author_avatars
from config_loader import config


def _is_msg_filtered(item: dict, peer_id: int) -> bool:
    min_cid = config.min_cid_by_peer_id.get(peer_id)
    min_date = config.min_date_by_peer_id.get(peer_id)
    if min_cid is not None and (item.get("conversation_message_id") or 0) <= min_cid:
        return True
    if min_date is not None and (item.get("date") or 0) <= min_date:
        return True
    return False


def main():
    start_create_time = datetime.now()

    export_root = Path(config.export_root)
    sources_dir = export_root / "ExportMessages" / "Sources"
    dialogs_dir = export_root / "ExportMessages" / "Dialogs"
    autor_images_dir = dialogs_dir / "AutorImages"
    large_root = export_root / "LargeRawData"

    sources = sorted(sources_dir.glob("*.json"))
    print(f"Найдено файлов: {len(sources)}")

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

    merged = {"profiles": list(profiles.values()), "groups": list(groups.values())}
    authors = load_authors(merged)
    print(f"Найдено авторов: {len(authors)}")

    for peer_id, items_dict in dialog_by_peer_id.items():
        items = list(items_dict.values())
        print(f"\n=== Диалог {peer_id} (сообщений: {len(items)}) ===")

        dialog_dir = dialogs_dir / f"dialog_{peer_id}"
        little_raw_data_dir = dialog_dir / "RawData"
        original_messages_dir = dialog_dir / "OriginalMessages"
        md_dir = dialog_dir / "MdFiles"
        large_raw_data_dir = large_root / f"dialog_{peer_id}"

        dialog_dir.mkdir(parents=True, exist_ok=True)

        url_to_relpath: dict[str, str] = {}
        ensure_author_avatars(authors, str(autor_images_dir), url_to_relpath, str(md_dir))

        filtered_items = [item for item in items if not _is_msg_filtered(item, peer_id)]
        n = extract_items_from_data(filtered_items, str(original_messages_dir))
        print(f"  Сохранено сообщений: {n}")

        count = 0
        message_files = sorted(Path(original_messages_dir).glob("*.json"))
        for message_index, message_file in enumerate(message_files):
            with open(message_file, encoding="utf-8") as fp:
                item_data = json.load(fp)
            if _is_msg_filtered(item_data, peer_id):
                continue
            md_items = build_md_items(
                item_data, message_file.name, str(md_dir),
                str(little_raw_data_dir), str(large_raw_data_dir),
                authors,
                url_to_relpath=url_to_relpath,
            )
            for md_index, item in enumerate(md_items):
                md_text = render_md_item(item)
                file_path = md_dir / item.filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as fp:
                    fp.write(md_text)
                print(f"  Создан {message_index + 1}/{len(message_files)} id={item.cid} (part {md_index + 1}/{len(md_items)}): \"{item.filename}\"")
                count += 1

        print(f"  Создано MD-файлов: {count}")

    print(f"\nГотово (Затраченое время = {datetime.now() - start_create_time})")


if __name__ == "__main__":
    main()
