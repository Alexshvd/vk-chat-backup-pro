import json
import sys
from pathlib import Path

from config import GROUP_ID, PEER_ID
from vk_client import VkClient
from export_fwd import extract_forwarded
from export_md import convert_forwarded_to_md
from download_media import DownloadItem, download_all


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
        "group_id": GROUP_ID,
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
    download_queue: dict[int, list[DownloadItem]] = {}
    m = convert_forwarded_to_md(str(extracted_dir), str(md_dir), download_queue)
    print(f"Создано MD-файлов: {m}")

    total_images = sum(len(v) for v in download_queue.values())
    if total_images:
        print(f"\nСкачивание изображений ({total_images} шт.)...")
        download_all(download_queue, str(md_dir))


if __name__ == "__main__":
    main()
