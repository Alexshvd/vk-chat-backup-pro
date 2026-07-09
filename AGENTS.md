# VkChatBackupCommunity

## Goal
Read local `messages.json` files, extract all messages into individual JSON files, resolve attachments (photos, videos, stickers, links, docs, audio, wall posts), download media files, render as Markdown with author info and sources table.

## Project Structure

```
Scripts/
├── main.py              # Entry point: parse sources → extract → build → render → write
├── config.py            # Config dataclass (pure, no side-effects)
├── config_loader.py     # load_config(path) — reads config.json, validates existence + path_rel()
├── author_resolver.py   # AuthorInfo dataclass + load_authors() + ensure_author_avatars()
├── vk_client.py         # get_video_embed_urls() — standalone, no class
├── export_fwd.py        # extract_items_from_data(items, output_dir)
├── MdItem.py            # DTO: BaseAttachmentItem + 8 subclasses + MdItem
├── md_item_builder.py   # build_md_items(): JSON → MdItem, resolves attachments, downloads files
├── md_renderer.py       # render_md_item(): MdItem → Markdown (pure, no I/O)
├── logger.py            # Logger class with LogWarning()
├── download_media.py    # download_file() + DownloadItem + download_all
├── requirements.txt     # requests, python-dotenv
├── .gitignore           # Ignores Temp/, __pycache__/
WebApp/
├── webapp.py            # Flask-сервер: просмотр, удаление, переименование
├── config.json          # Пример конфига (git-трекаемый шаблон)
├── requirements.txt     # flask, mistune
├── .gitignore
└── templates/
    ├── index.html       # Список диалогов
    └── dialog.html      # Двухколоночный UI: список + просмотр/удаление/rename
```

Output directory structure (`EXPORT_ROOT`):
```
{EXPORT_ROOT}/
├── ExportMessages/
│   ├── Sources/                      # Input: one or more messages.json files
│   │   └── messages.json
│   └── Dialogs/
│       ├── AutorImages/              # Shared author avatars
│       └── dialog_{peer_id}/
│           ├── RawData/              # Small attachments (images, previews, stickers)
│           ├── OriginalMessages/     # Individual message JSON files {date}_{cid}.json
│           └── MdFiles/              # Rendered Markdown files
└── LargeRawData/                     # Large files (videos)
    └── dialog_{peer_id}/{cid}/
```

## Data Flow

1. **main.py** → scans all `*.json` in `Sources/`, groups messages by `peer_id` into `dialog_by_peer_id[cid]` (dedup by `conversation_message_id`), merges profiles/groups
2. **main.py** → `load_authors(merged_data)` → `dict[int, AuthorInfo]`
3. **main.py** → per dialog: `extract_items_from_data(filtered_items)` → `{date}_{cid}.json`
4. **main.py** → per dialog: `build_md_items(json, config, ...)` → `list[MdItem]` with resolved attachments and downloaded files
5. **main.py** → per dialog: `render_md_item(item)` → Markdown → write `.md` file

Step 4 resolves all attachments into typed DTOs and downloads photos/stickers/videos immediately. Step 5 is pure rendering (no I/O).

## Module Details

### config.py
- `Config` dataclass with fields: `export_root`, `download_short_video`, `download_long_video`, `long_video_threshold`, `min_cid_by_peer_id`, `min_date_by_peer_id`
- Pure data container, no logic

### config.json (user-provided, not tracked in git)
- `export_root` — path to export root (default: `Scripts/Temp/ExportMessages/`)
- `download_short_video` / `download_long_video` / `long_video_threshold` — video download flags
- `min_cid_by_peer_id` — per-dialog filter: `{peer_id: min_cid}` (messages with cid <= min_cid are skipped)
- `min_date_by_peer_id` — per-dialog filter: `{peer_id: "yyyy-mm-dd-hh-mm-ss"}` (messages with date <= filter are skipped)
- If peer_id not in dict — filter disabled for that dialog

### config_loader.py
- `load_config(path: str) -> Config` — reads `config.json`, raises `FileNotFoundError` if file doesn't exist with path in message; parses and transforms (str keys → int, date strings → unix timestamps)
- `path_rel(target, start)` — `os.path.relpath()` with `\` → `/`

### vk_client.py
- `get_video_embed_urls(owner_id, video_id)` — standalone, fetches `vk.com/video_ext.php`, parses mp4 URLs from embedded JSON (`apiPrefetchCache`). No authorization needed.
- `_parse_video_embed(text)` — handles both new `apiPrefetchCache` format and old regex fallback
- No class, no VK API calls

### author_resolver.py
- `AuthorInfo` dataclass: `author_id`, `name`, `screen_name`, `photo_url`, `photo_local`, `author_type`
- `load_authors(data: dict)` — parses `profiles[]` (users) and `groups[]` (communities) from merged messages data
- `ensure_author_avatars(authors, authors_dir, url_to_relpath, md_dir)` — downloads avatars to `AutorImages/`, computes relpath from `md_dir`

### export_fwd.py
- `extract_items_from_data(items: list, output_dir: str)` — writes each item as `{date}_{cid}.json`. No guard for missing cid/date (guaranteed upstream). No dedup (data already deduplicated by caller).

### logger.py
- `Logger.LogWarning(error_type, exception)` — prints `[Warning] {error_type}.{exception}`

### download_media.py
- `download_file(url, filepath, timeout=30)` — downloads a single file
- `DownloadItem`, `download_all()` — legacy, not used

### MdItem.py
- `BaseAttachmentItem` — marker base class
- `PhotoAttachment`, `VideoAttachment`, `LinkAttachment`, `DocAttachment`, `AudioAttachment`, `StickerAttachment`, `WallAttachment` — dataclass subclasses with already-downloaded data
- `MdItem` — dataclass: `cid`, `from_id`, `date`, `text`, `attachments: list[BaseAttachmentItem]`, `forwarded: list[MdItem]`, `json_filename`, `heading`, `filename`, `is_wall_split`, `author: Optional[AuthorInfo]`

### md_item_builder.py
- `build_md_items(fwd, json_filename, md_dir, little_raw_data_dir, large_raw_data_dir, authors, config, url_to_relpath)` — reads JSON dict, creates `list[MdItem]`. Recursively processes `fwd_messages`. Downloads photos/videos/stickers immediately.
- `config: Config` passed through chain: `_resolve_attachment()` → `_resolve_video()` → `_should_download_video(config)`, `_resolve_wall()` → `_resolve_attachment()`
- **Filename rules**:
  - With text: `{first_sentence}.Id{cid}.md` (max 60 chars + `...`)
  - Without text: `{AttachmentType}.{date}.Id{cid}.md` (prefix: Photo/Video/ShortVideo/Link/Article/Doc/Audio/Sticker/Media)
  - `Статья.` prefix if only wall/post without text
  - Multiple wall/post → `_part_N` suffix
  - Filename cleaned: emojis removed, `—`→`-`, special chars `\/*?:"<>|` → `_`
- **First sentence** (`_first_sentence`): Split on `\n`, `.`, `!`, `?` — take first part
- Video download: `_resolve_video()` calls `get_video_embed_urls(oid, vid)` → `_get_best_video_url()` → `_download_to_raw()` to `LargeRawData/`
- Controlled by `config.long_video_threshold`, `config.download_short_video`, `config.download_long_video`

### md_renderer.py
- `render_md_item(item, level=1)` — pure function, no I/O
- Dispatch by `isinstance` (not string comparison)
- **Author rendering**: HTML `<table>` with `<img width="55" height="55" style="vertical-align:middle">`, inline CSS
- **Sources table**: per-attachment rows for all 8 types (Photo, Video, Link, Doc, Audio, Sticker, Wall) with relative links (computed via `path_rel()`)

## Conventions

- **Python 3.9** — no `X | Y` union syntax, use `Optional[X]`, `Union[X, Y]`
- **Output format**: Markdown with `<br>` for newlines
- **Video rendering**: `<video src="..." controls>` for downloaded mp4, `<details>` + `<iframe>` for VK Player fallback
- **Relative paths**: computed via `path_rel()` — forward slashes, relative from `MdFiles/` dir
- **`.gitignore`**: `Temp/`, `__pycache__/`

## Launch

```sh
python main.py --config config.json
```

## Filtering

Two per-dialog filters in `config.json`:
- `min_cid_by_peer_id`: skip messages where `conversation_message_id <= value`
- `min_date_by_peer_id`: skip messages where `date <= parsed unix timestamp`

Applied in two places:
1. Before `extract_items_from_data()` — filtered items don't get JSON files
2. When iterating `OriginalMessages/` — existing filtered files are skipped (defense against pre-filter leftovers)

## WebApp

### webapp.py
- Импортирует `config_loader.load_config()` для получения `export_root`
- Пути на диске: `{export_root}/ExportMessages/Dialogs/`, `{export_root}/LargeRawData/`
- `CID_PATTERN`: `\.Id(\d+)(?:_part_\d+)?\.md$`
- Markdown → HTML: `mistune.HTMLRenderer(escape=False)` + плагины `table`, `strikethrough`
- Переписывание путей: все относительные пути из `.md` → `/export/...` или `/large/...`
- `_delete_cid()`: удаляет `*Id{cid}*.md`, `RawData/{cid}/`, `LargeRawData/.../{cid}/`, `*_{cid}.json`
- `rename_md_file()`: меняет имя `.md`, сохраняя суффикс `.Id{cid}.md`
- `rename_attachment()`: переименовывает файл вложения + обновляет ссылки внутри `.md`

| Маршрут | Метод | Описание |
|---|---|---|
| `/` | GET | Список диалогов |
| `/dialog/<peer_id>` | GET | Список `.md` файлов |
| `/dialog/<peer_id>/<cid>/content` | GET | HTML-рендер `.md` |
| `/dialog/<peer_id>/<cid>` | DELETE | Удаление сообщения |
| `/dialog/<peer_id>/delete-batch` | POST | Массовое удаление |
| `/dialog/<peer_id>/<cid>/rename` | PUT | Переименование `.md` |
| `/dialog/<peer_id>/<cid>/attachments` | GET | Список файлов вложений |
| `/dialog/<peer_id>/<cid>/rename-attachment` | PUT | Переименование вложения |
| `/export/<path>` | GET | Статика (Dialogs, Sources) |
| `/large/<path>` | GET | Статика (LargeRawData) |

### Запуск

```sh
cd WebApp
pip install -r requirements.txt
python webapp.py --config config.json
```

### Зависимости

- `flask>=3.0.0`
- `mistune>=3.0.0`

## Dependencies

- `requests>=2.28.0`
