import json
import sys
from pathlib import Path

from config import PEER_ID
from vk_client import VkClient
from export_fwd import extract_forwarded
from md_renderer import render_md_item
from md_item_builder import build_md_items


def main():
    client = VkClient()

    print(f"Загрузка истории для peer_id={PEER_ID}...")
    try:
        messages = client.get_all_history(PEER_ID)
    except RuntimeError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Загружено сообщений: {len(messages)}")

    result = {
        "peer_id": PEER_ID,
        "total": len(messages),
        "messages": messages,
    }

    dialog_dir = Path("Temp/ExportMessages") / f"dialog_{PEER_ID}"
    dialog_dir.mkdir(parents=True, exist_ok=True)

    output_path = dialog_dir / "messages.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nСохранено в {output_path}")

    extracted_dir = dialog_dir / "ExtractedOriginalMessages"
    n = extract_forwarded(str(output_path), str(extracted_dir))
    print(f"Извлечено пересланных сообщений: {n}")

    md_dir = dialog_dir / "MdConvertResults"
    count = 0
    for f in sorted(Path(extracted_dir).glob("*.json")):
        with open(f, encoding="utf-8") as fp:
            fwd = json.load(fp)
        items = build_md_items(fwd, f.name, str(md_dir), vk_client=client)
        for item in items:
            md_text = render_md_item(item)
            file_path = md_dir / item.filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write(md_text)
            count += 1
    print(f"Создано MD-файлов: {count}")


if __name__ == "__main__":
    main()
