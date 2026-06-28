import json
import sys

from config import GROUP_ID
from vk_client import VkClient


def main():
    client = VkClient()

    print("Получение списка диалогов...")
    try:
        conversations = client.get_all_conversations()
    except RuntimeError as e:
        print(f"Ошибка при получении диалогов: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Найдено диалогов: {len(conversations)}")

    all_messages: dict[str, list[dict]] = {}

    for conv in conversations:
        conv_data = conv.get("conversation", {})
        peer = conv_data.get("peer", {})
        peer_id = peer.get("id")
        chat_type = peer.get("type", "unknown")

        if peer_id is None:
            continue

        print(f"  Загрузка истории для peer_id={peer_id} (тип: {chat_type})...")
        try:
            messages = client.get_all_history(peer_id)
        except RuntimeError as e:
            print(f"    Ошибка: {e}", file=sys.stderr)
            continue

        print(f"    Загружено сообщений: {len(messages)}")
        all_messages[str(peer_id)] = messages

    result = {
        "group_id": GROUP_ID,
        "total_peer_ids": len(all_messages),
        "conversations": [
            {
                "peer_id": c.get("conversation", {}).get("peer", {}).get("id"),
                "type": c.get("conversation", {}).get("peer", {}).get("type"),
                "title": (
                    c.get("conversation", {})
                    .get("chat_settings", {})
                    .get("title")
                    or c.get("conversation", {})
                    .get("peer", {})
                    .get("local_id")
                ),
                "last_message_preview": c.get("last_message", {}).get("text", "")[:100],
            }
            for c in conversations
        ],
        "messages": all_messages,
    }

    output_path = "messages.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nСохранено в {output_path}")


if __name__ == "__main__":
    main()
