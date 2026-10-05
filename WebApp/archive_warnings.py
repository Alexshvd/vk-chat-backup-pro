"""Recover attachment references, not historical error reasons, from saved MD."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from config_loader import load_config
from dialog_dirs import collect_dialog_dirs
from Loggers.context_logger import attachment_description, warning_text
from video_cache import source_rows


def warning_attachments(config_path, peer):
    config = load_config(str(config_path))
    root = Path(config.export_root).resolve()
    directory = collect_dialog_dirs(root / 'ExportMessages/Dialogs', config).get(peer)
    if directory is None or not directory.resolve().is_relative_to(root):
        return []
    result = []
    seen = set()
    for md in sorted((directory / 'MdFiles').rglob('*.md')):
        match = re.search(r'(?:^|\.)Id(\d+)(?:_part_\d+)?\.md$', md.name)
        if not match:
            continue
        cid = int(match[1])
        for line in md.read_text(encoding='utf-8').splitlines():
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if len(cells) != 3 or cells[1] != 'Ошибка скачивания':
                continue
            rows = list(source_rows(line))
            if not rows:
                continue
            kind, local, url = rows[0]
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc or (cid, kind, url) in seen:
                continue
            seen.add((cid, kind, url))
            title = kind
            # Keep the existing attachment's identity and human-readable title.
            originals = list((directory / 'OriginalMessages').glob('*_' + str(cid) + '.json'))
            if originals:
                try:
                    original = json.loads(originals[0].read_text(encoding='utf-8'))
                    def walk(node):
                        if isinstance(node, dict):
                            if node.get('type') and isinstance(node.get(node['type']), dict):
                                yield node
                            for child in node.values():
                                yield from walk(child)
                        elif isinstance(node, list):
                            for child in node:
                                yield from walk(child)
                    for att in walk(original):
                        if url in json.dumps(att, ensure_ascii=False):
                            title = attachment_description(att)
                            break
                except (OSError, ValueError):
                    pass
            result.append({'cid': cid, 'kind': kind, 'title': warning_text(title),
                           'url': warning_text(url), 'filename': md.name,
                           'message_url': f'/chat/{peer}?message={cid}'})
    return sorted(result, key=lambda item: (item['cid'], item['kind'], item['url']))
