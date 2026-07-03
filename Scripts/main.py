import json
from datetime import datetime
from pathlib import Path

from export_fwd import extract_items
from md_renderer import render_md_item
from md_item_builder import build_md_items
from author_resolver import load_authors, ensure_author_avatars


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "Temp" / "messages.json"


def main():
    start_create_time = datetime.now()

    print(f"Чтение {INPUT_FILE}...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    peer_id = data["peer_id"]
    print(f"Загружено сообщений: {len(data['items'])}")

    dialog_dir = BASE_DIR / "Temp" / "ExportMessages" / f"dialog_{peer_id}"

    print("Загрузка авторов...")
    authors = load_authors(str(INPUT_FILE))
    print(f"Найдено авторов: {len(authors)}")

    url_to_relpath: dict[str, str] = {}
    ensure_author_avatars(authors, str(dialog_dir / "Autors"), url_to_relpath)

    dialog_dir.mkdir(parents=True, exist_ok=True)

    extracted_dir = dialog_dir / "ExtractedOriginalMessages"
    n = extract_items(str(INPUT_FILE), str(extracted_dir))
    print(f"Сохранено сообщений: {n}")

    count = 0

    md_dir = dialog_dir / "MdConvertResults"
    message_files = sorted(Path(extracted_dir).glob("*.json"))
    for message_index, message_file in enumerate(message_files):
        with open(message_file, encoding="utf-8") as fp:
            item_data = json.load(fp)
        items = build_md_items(
            item_data, message_file.name, str(md_dir), authors,
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
