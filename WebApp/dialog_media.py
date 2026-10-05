"""Read-only, dialog-scoped file inventory, including referenced shared media."""
from pathlib import Path

from chat_view import CID_PATTERN, IMAGE_EXTENSIONS, local_url
from dialog_dirs import collect_dialog_dirs
from video_cache import source_rows


def media_kind(path):
    extension = path.suffix.lower().lstrip('.')
    if extension in IMAGE_EXTENSIONS or extension in ('bmp', 'ico', 'svg'):
        return 'photo'
    if extension in ('mp4', 'webm', 'mkv', 'mov', 'avi', 'm4v', 'ogv'):
        return 'video'
    if extension in ('mp3', 'm4a', 'ogg', 'opus', 'wav', 'flac', 'aac'):
        return 'audio'
    return 'file'


def media_library(config, peer, conversation):
    root = Path(config.export_root).resolve()
    directories = collect_dialog_dirs(root / 'ExportMessages/Dialogs', config)
    directory = directories.get(peer)
    if directory is None:
        directory = root / 'ExportMessages/Dialogs' / (config.dialog_name_by_peer_id.get(peer) or f'dialog_{peer}')
    raw = directory / 'RawData'
    large = root / 'LargeRawData' / f'dialog_{peer}'
    shared = root / 'LargeRawData/SharedMedia'
    export_root, large_root = root / 'ExportMessages', root / 'LargeRawData'
    own_roots = (raw.resolve(), large.resolve())
    shared_root = shared.resolve()
    entries = {}
    messages = {m['cid']: m for m in conversation['messages']}
    metadata = {}

    def walk(node, cid):
        if isinstance(node, list):
            for child in node:
                walk(child, cid)
        elif isinstance(node, dict):
            if node.get('src') and node.get('type'):
                metadata[(cid, node['src'])] = node
            if node.get('poster'):
                metadata[(cid, node['poster'])] = {'title': 'Превью: ' + node.get('title', 'Видео')}
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child, cid)

    for cid, message in messages.items():
        walk(message, cid)

    def add(path, cid, label=''):
        # Never include another dialog's private files or enumerate SharedMedia.
        path = path.resolve()
        is_shared = path.is_relative_to(shared_root)
        if not (is_shared or any(path.is_relative_to(base) for base in own_roots)):
            return
        if any(part.startswith(('.audio-', '.downloads')) for part in path.parts):
            return
        if path.name.endswith(('.part', '.tmp', '.copying', '.photo-tmp')) or any(
                marker in path.name for marker in ('.downloading.', '.photo-upgrade.')):
            return
        if not path.is_file():
            return
        try:
            size = path.stat().st_size
        except OSError:
            return  # An active export may replace a file before refresh.
        if not size:
            return
        src = local_url(path, export_root, large_root)
        if not src:
            return
        details = metadata.get((cid, src), {})
        title = details.get('title') or label or path.name
        kind = media_kind(path)
        if details.get('type') in ('audio', 'video', 'photo', 'sticker'):
            kind = 'photo' if details['type'] == 'sticker' else details['type']
        entry = entries.setdefault(src, {'src': src, 'filename': path.name, 'title': title,
                                        'type': kind, 'size': size, 'shared': is_shared,
                                        'poster': details.get('poster', ''), 'messages': {}})
        if cid is not None and cid in messages:
            message = messages.get(cid, {})
            entry['messages'][cid] = {'cid': cid, 'date': message.get('date', 0),
                                      'url': f'/chat/{peer}?message={cid}'}

    # Source tables retain forwarded/reply media and stable shared paths.
    for md in (directory / 'MdFiles').rglob('*.md'):
        match = CID_PATTERN.search(md.name)
        if not match:
            continue
        cid = int(match[1])
        try:
            text = md.read_text(encoding='utf-8')
        except OSError:
            continue
        for label, relative, remote in source_rows(text):
            if relative and not label.startswith('Аватар'):
                add(md.parent / relative, cid, label)
    # Also show files in this dialog which have no source-table entry.
    for base in (raw, large):
        for path in base.rglob('*'):
            if not path.is_file():
                continue
            first = path.relative_to(base).parts[0]
            add(path, int(first) if first.isdigit() else None)
    items = []
    counts = dict.fromkeys(('photo', 'video', 'audio', 'file'), 0)
    for entry in entries.values():
        entry['messages'] = sorted(entry['messages'].values(), key=lambda m: (m['date'], m['cid']), reverse=True)
        entry['date'] = max((m['date'] for m in entry['messages']), default=0)
        counts[entry['type']] += 1
        items.append(entry)
    items.sort(key=lambda item: (-item['date'], item['title'].casefold(), item['src']))
    return {'dialog': conversation['dialog'], 'items': items, 'counts': counts,
            'total': len(items), 'total_bytes': sum(item['size'] for item in items)}
