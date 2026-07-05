import json
from datetime import datetime
from pathlib import Path

from export_fwd import extract_items
from md_renderer import render_md_item
from md_item_builder import build_md_items
from author_resolver import load_authors, ensure_author_avatars
from config import EXPORT_ROOT


def main():
    start_create_time = datetime.now()

    export_root = Path(EXPORT_ROOT)
    sources_dir = export_root / "ExportMessages" / "Sources"
    input_file = sources_dir / "messages.json"

    print(f"Чтение {input_file}...")
    with open(input_file, encoding="utf-8") as f:
        data = json.load(f)

    peer_id = data["peer_id"]
    print(f"Загружено сообщений: {len(data['items'])}")

    dialogs_dir = export_root / "ExportMessages" / "Dialogs"
    autor_images_dir = dialogs_dir / "AutorImages"
    dialog_dir = dialogs_dir / f"dialog_{peer_id}"
    little_raw_data_dir = dialog_dir / "RawData"
    original_messages_dir = dialog_dir / "OriginalMessages"
    md_dir = dialog_dir / "MdFiles"
    large_raw_data_dir = export_root / "LargeRawData" / f"dialog_{peer_id}"

    print("Загрузка авторов...")
    authors = load_authors(str(input_file))
    print(f"Найдено авторов: {len(authors)}")

    url_to_relpath: dict[str, str] = {}
    ensure_author_avatars(authors, str(autor_images_dir), url_to_relpath, str(md_dir))

    dialog_dir.mkdir(parents=True, exist_ok=True)

    n = extract_items(str(input_file), str(original_messages_dir))
    print(f"Сохранено сообщений: {n}")

    count = 0

    message_files = sorted(Path(original_messages_dir).glob("*.json"))
    for message_index, message_file in enumerate(message_files):
        with open(message_file, encoding="utf-8") as fp:
            item_data = json.load(fp)
        items = build_md_items(
            item_data, message_file.name, str(md_dir),
            str(little_raw_data_dir), str(large_raw_data_dir),
            authors,
            vk_client=None, url_to_relpath=url_to_relpath,
        )
        for md_index, item in enumerate(items):
            md_text = render_md_item(item)
            file_path = md_dir / item.filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write(md_text)
            print(f'\tСоздан {message_index + 1}/{len(message_files)} id={item.cid} (part {md_index + 1}/{len(items)}): "{item.filename}"')
            count += 1

    print(f"Создано MD-файлов: {count} (Затраченое время = {datetime.now() - start_create_time})")


if __name__ == "__main__":
    main()
