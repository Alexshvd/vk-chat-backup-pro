import json
from pathlib import Path

from md_builder import build_md_items
from md_renderer import render_md_item


def convert_forwarded_to_md(json_dir: str, md_dir: str, vk_client=None) -> int:
    json_path = Path(json_dir)
    md_path = Path(md_dir)
    md_path.mkdir(parents=True, exist_ok=True)

    url_to_relpath = {}
    count = 0

    for f in sorted(json_path.glob("*.json")):
        with open(f, encoding="utf-8") as fp:
            fwd = json.load(fp)

        items = build_md_items(
            fwd, f.name, md_dir, vk_client, url_to_relpath,
        )
        for item in items:
            content = render_md_item(item)
            file_path = md_path / item.filename
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write(content)
            count += 1

    return count
