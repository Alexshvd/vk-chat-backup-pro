import json
import sys
from pathlib import Path

from config import GROUP_ID, PEER_ID
from vk_client import VkClient


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

    output_path = "Temp/ExportMessages/messages.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nСохранено в {output_path}")


if __name__ == "__main__":
    main()
