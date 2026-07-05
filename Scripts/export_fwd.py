import json
from datetime import datetime
from pathlib import Path


def extract_forwarded(messages_json_path: str, output_dir: str) -> int:
    with open(messages_json_path, encoding="utf-8") as f:
        data = json.load(f)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    count = 0
    for msg in data.get("messages", []):
        for fwd in msg.get("fwd_messages", []):
            ts = fwd.get("date")
            cid = fwd.get("conversation_message_id")
            if ts is None or cid is None:
                continue

            name = f"{_fmt_date(ts)}_{cid}.json"
            file_path = out / name
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(fwd, f, ensure_ascii=False, indent=2)
            count += 1

    return count


def extract_items_from_data(items: list, output_dir: str) -> int:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    count = 0
    for msg in items:
        ts = msg.get("date")
        cid = msg.get("conversation_message_id")
        if ts is None or cid is None:
            continue

        name = f"{_fmt_date(ts)}_{cid}.json"
        file_path = out / name
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(msg, f, ensure_ascii=False, indent=2)
        count += 1

    return count


def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d-%H-%M-%S")
