# VkChatBackupCommunity

## Goal
Read local `messages.json` files, extract all messages into individual JSON files, resolve attachments (photos, videos, stickers, links, docs, audio, wall posts), download media files, render as Markdown with author info and sources table.

## Project Structure

```
├── run.py                    # Entry point: cli / web modes
├── config.json               # User-provided config (not tracked)
├── requirements.txt          # requests, flask, mistune
├── .gitignore
├── AGENTS.md
│
├── Config/
│   ├── config.py             # Config dataclass (pure, no side-effects)
│   └── config_loader.py      # load_config(path) + path_rel()
│
├── ExportMessageToMd/
│   ├── main.py               # Generator: parse sources → extract → build → render → write
│   ├── MdItem.py             # DTO: BaseDownloadResult + 3 subclasses (NoDownload/Error/Success) + BaseAttachmentItem + 7 subclasses + MdItem
│   ├── md_item_builder.py    # build_md_items(): JSON → MdItem, resolves attachments
│   ├── md_renderer.py        # render_md_item(): MdItem → Markdown (pure, no I/O)
│   ├── export_fwd.py         # extract_items_from_data(items, output_dir)
│   ├── author_resolver.py    # AuthorInfo + load_authors() + ensure_author_avatars()
│   ├── download_media.py     # download_file() → bool, download_all() — with error handling
│   ├── vk_client.py          # get_video_embed_urls()
│   └── Loggers/
│       ├── __init__.py       # Export all logger classes
│       ├── base_logger.py    # BaseLogger — ABC with LogWarning()
│       ├── print_logger.py   # PrintLogger — prints to console
│       ├── buffer_logger.py  # BufferLogger — accumulates logs, ConsumeMessages()
│       └── aggregation_logger.py  # AggregationLogger — delegates to multiple loggers
│
└── WebApp/
    ├── web.py                # Flask app: просмотр, удаление, переименование, экспорт
    └── templates/
        ├── index.html        # Список диалогов
        ├── dialog.html       # Двухколоночный UI
        └── export.html       # Страница экспорта + запуск генерации
```

Output directory structure (`EXPORT_ROOT`):
```
{EXPORT_ROOT}/
├── ExportMessages/
│   ├── Sources/                              # Input: one or more messages.json files
│   │   └── messages.json
│   └── Dialogs/
│       ├── AutorImages/                      # Shared author avatars
│       │   └── photo_12345.jpg
│       └── dialog_{peer_id}/
│           ├── RawData/                      # Small attachments, nested by root CID
│           │   └── {root_cid}/              # Root message's attachments + forwarded subdirs
│           │       ├── 1.jpg                # Root message's direct attachments
│           │       ├── 2.webp
│           │       ├── {fwd_cid}/           # Forwarded message's attachments
│           │       │   ├── Лабораторная_работа_14.docx
│           │       │   └── VIM.docx
│           │       └── {fwd_cid}/
│           │           └── ...
│           ├── OriginalMessages/             # Individual message JSON files {date}_{cid}.json
│           │   └── 2026-01-15_1234.json
│           └── MdFiles/                      # Rendered Markdown files
│               └── Привет.Id1234.md
└── LargeRawData/                             # Large files (videos), kept separate
    └── dialog_{peer_id}/                     # because the rest is intended for git repo
        └── {root_cid}/                       # Nested structure same as RawData
            └── 1.mp4
```

## Launch

```sh
# Запуск генерации MD (CLI)
python run.py --mode cli --config config.json

# Запуск веб-сервера
python run.py --mode web --config config.json
```

## Data Flow

1. **main.py** → scans all `*.json` in `Sources/`, groups messages by `peer_id` into `dialog_by_peer_id[cid]` (dedup by `conversation_message_id`), merges profiles/groups. Also scans `Dialogs/` for peer_ids not in Sources but with existing `OriginalMessages/*.json`.
2. **main.py** → `load_authors(merged_data)` → `dict[int, AuthorInfo]`
3. **main.py** → per dialog: `extract_items_from_data(filtered_items)` → `{date}_{cid}.json`
4. **main.py** → per dialog: `build_md_items(json, cid, root_cid, config, ...)` → `list[MdItem]` with resolved attachments and downloaded files. `cid` = current message's `conversation_message_id`, `root_cid` = original message's cid (passed through to forwarded messages for nested directory structure).
5. **main.py** → per dialog: `render_md_item(item)` → Markdown → write `.md` file

Step 4 resolves all attachments into typed DTOs and downloads photos/stickers/videos/docs immediately. Step 5 is pure rendering (no I/O).

`main(config, peer_ids, logger)` is a **generator function** — it `yield`s log messages instead of `print()`. Both CLI and Web iterate over it the same way. Web uses `stream_with_context` for real-time progress display.

## Module Details

### Config/config.py
- `Config` dataclass with fields: `export_root`, `download_short_video`, `download_long_video`, `long_video_threshold`, `overwrite_existing_md`, `overwrite_existing_original_message_json`, `min_cid_by_peer_id`, `min_date_by_peer_id`
- Pure data container, no logic

### Config/config_loader.py
- `load_config(path: str) -> Config` — reads `config.json`, raises `FileNotFoundError` if file doesn't exist with path in message; parses and transforms (str keys → int, date strings → unix timestamps)
- `path_rel(target, start)` — `os.path.relpath()` with `\` → `/`

### config.json (user-provided, not tracked in git)
- `export_root` — path to export root (default: `{parent_dir}/Temp/ExportMessages`)
- `download_short_video` / `download_long_video` / `long_video_threshold` — video download flags
- `overwrite_existing_md` — if `true`, re-converts messages with existing MD files (deletes old MD + RawData + LargeRawData first); if `false` (default), skips already converted messages
- `overwrite_existing_original_message_json` — if `true`, overwrites existing OriginalMessages JSON files; if `false` (default), skips already extracted messages
- `min_cid_by_peer_id` — per-dialog filter: `{peer_id: min_cid}` (messages with cid <= min_cid are skipped)
- `min_date_by_peer_id` — per-dialog filter: `{peer_id: "yyyy-mm-dd-hh-mm-ss"}` (messages with date <= filter are skipped)
- If peer_id not in dict — filter disabled for that dialog

### ExportMessageToMd/main.py
- Generator function `main(config: Config, peer_ids: Optional[set[int]], logger: BaseLogger)` — yields log messages as it processes. `peer_ids` filters which dialogs to export (None = all). `logger` receives warnings during execution.
- Used both by CLI (`run.py --mode cli`) and web (`POST /export/generate`)
- Can be run standalone: `python ExportMessageToMd/main.py --config ../config.json`

### ExportMessageToMd/md_item_builder.py
- `build_md_items(fwd, cid, root_cid, json_filename, md_dir, little_raw_data_dir, large_raw_data_dir, authors, config, url_to_relpath, logger)` — reads JSON dict, creates `list[MdItem]`. Recursively processes `fwd_messages`. Downloads photos/videos/stickers/docs immediately. `cid` and `root_cid` are passed from caller (main.py). Forwarded messages use `root_cid` for nested directory structure: `RawData/{root_cid}/{fwd_cid}/`.
- **Filename rules**:
  - With text: `{first_sentence}.Id{cid}.md`
  - Without text: `{AttachmentType}.{date}.Id{cid}.md` (prefix: Photo/Video/ShortVideo/Link/Article/Doc/Audio/Sticker/Media)
  - `Статья.` prefix if only wall/post without text
  - Multiple wall/post → `_part_N` suffix
  - Filename cleaned: emojis removed, `—`→`-`, `@mention` prefixes stripped (same as `#hashtag`), special chars `\/*?:"<>|` → `_`
- **Max path length (254 chars)**: `_compute_filename(md_dir_abs_len, extra_suffix_len)` truncates text dynamically: `max_text = 254 - len(os.path.abspath(md_dir)) - 1 - len(".Id{cid}.md") - extra_suffix_len` (min 10). `extra_suffix_len` accounts for `"Статья."` (8) and `_part_N` suffix. `Logger.LogWarning` if final path exceeds 254. `_compute_heading()` remains hardcoded at 60 (display-only, not filename).

### ExportMessageToMd/md_renderer.py
- `render_md_item(item)` — public entry point, `level = 1` inside, appends Sources table, returns full MD string
- `_build_md_lines(item, level)` — private recursive dispatcher, returns `list[str]` without Sources
- `_build_md_message_lines(item, tag, level)` — renders regular message to `list[str]`, calls `_build_md_lines(child, level + 2)` for forwarded messages
- `_build_md_wall_message_lines(item, tag, level)` — renders wall-split message to `list[str]`, no Sources
- `_rel_cell(result)` — maps `BaseDownloadResult` to Sources table cell: `SuccessDownloadResult` → link, `ErrorDownloadResult` → "Ошибка скачивания", `NoDownloadResult` → empty. Raises `TypeError` for unknown types.
- `_append_sources_table(lines, item)` — builds one consolidated Sources table with `seen` set for deduplication. JSON file row added once before `_walk()`. `_walk()` recursively processes forwarded messages via `_add_row()`.

### ExportMessageToMd/MdItem.py
- **Download result pattern**: `BaseDownloadResult` → `NoDownloadResult` (no URL) | `ErrorDownloadResult` (download failed) | `SuccessDownloadResult(local_path: str)`
- `PhotoAttachment`, `DocAttachment`, `StickerAttachment` — field `download_result: BaseDownloadResult` (default `NoDownloadResult`)
- `VideoAttachment` — two fields: `mp4_download_result` + `preview_download_result`

## WebApp

### web.py
- Flask app factory pattern: `init_app(config_path)` → `_init_paths()` → sets all path globals
- `_build_message_date_str_by_cid(orig_dir, logger)` — builds `dict[int, str]` cache mapping cid → date string from OriginalMessages JSON filenames (called once per dialog view instead of per-message)
- `/export` → `render_template("export.html", ...)` passes `dialogs_path=str(dialogs_dir_abs)`, `orig_counts=dict` (count of OriginalMessages per peer_id) for displaying the MD output directory
- `_list_attachments` uses `rglob("*")` to recursively find files in nested `RawData/{root_cid}/{fwd_cid}/` dirs
- `_delete_cid` uses `shutil.rmtree(cid_raw)` to remove entire subtree including forwarded message subdirs

| Маршрут | Метод | Описание |
|---|---|---|
| `/` | GET | Список диалогов |
| `/export` | GET | Страница экспорта (список Sources по peer_id + диалоги с OriginalMessages без Sources, фильтры, кнопка генерации) |
| `/export/create-sources` | POST | Создание директории Sources |
| `/export/upload` | POST | Загрузка файла в Sources |
| `/export/save-filters` | POST | Сохранение фильтров min_cid/min_date в config.json |
| `/export/generate` | POST | Потоковая генерация MD (chunked HTML), читает `peer_ids` из формы |
| `/dialog/<peer_id>` | GET | Список `.md` файлов |
| `/dialog/<peer_id>/limits/<cid>` | GET | Макс. длины имён файлов |
| `/dialog/<peer_id>/<cid>/content` | GET | HTML-рендер `.md` |
| `/dialog/<peer_id>/<cid>` | DELETE | Удаление сообщения |
| `/dialog/<peer_id>/delete-batch` | POST | Массовое удаление |
| `/dialog/<peer_id>/<cid>/rename` | PUT | Переименование `.md` |
| `/dialog/<peer_id>/<cid>/attachments` | GET | Список файлов вложений |
| `/dialog/<peer_id>/<cid>/open-folder` | POST | Открытие папки в проводнике |
| `/dialog/<peer_id>/<cid>/rename-attachment` | PUT | Переименование вложения |
| `/export/<path>` | GET | Статика (Dialogs, Sources) |
| `/large/<path>` | GET | Статика (LargeRawData) |

### export.html
- **Блок 1 «Как получить messages.json»**: Пошаговая инструкция (открыть VK, открыть консоль, настроить параметры, запустить скрипт). Поля ввода `peerId` (обязательный), `fromDate` (yyyy-mm-dd, опционально), `fromMessageId` (опционально). Динамически генерируемый скрипт для консоли браузера с кнопкой копирования. Валидация даты.
- **Блок 2 «Подключение messages.json»**: Путь к Sources, описание назначения, кнопка создания директории (`POST /export/create-sources`), кнопка загрузки файла (`POST /export/upload`)
- **Блок 3 «Экспорт в MD»**: Описание конвертации, путь к директории MD-файлов, сворачиваемая структура директорий, список `.json` файлов из `Sources/` сгруппированных по `peer_id`, а также диалоги с уже извлечёнными OriginalMessages (без исходных файлов в Sources), с чекбоксами выбора диалогов, количеством извлечённых сообщений для каждого peer_id, поля фильтров `min_cid`/`min_date` для каждого peer_id (сохраняются через `POST /export/save-filters`), кнопка "Сформировать MD" → `POST /export/generate`. После нажатия кнопка блокируется, сервер отдаёт потоковый HTML-лог.

### dialog.html & index.html
- Добавлена ссылка «Экспорт» в шапке (рядом с «Диалоги»)
- **Файлы вложений**: группируются по родительской папке. У каждой группы — заголовок с абсолютным путём, кнопка «Скопировать» (копирует путь в буфер обмена), кнопка «Открыть» (открывает папку в проводнике через `/open-folder`). Файлы внутри группы сдвинуты `padding-left: 16px`, маркеры `disc` через `::before`.

## Зависимости

- `requests>=2.28.0`
- `flask>=3.0.0`
- `mistune>=3.0.0`

## Conventions

- **Python 3.9** — no `X | Y` union syntax, use `Optional[X]`, `Union[X, Y]`
- **Output format**: Markdown with `<br>` for newlines
- **Video rendering**: `<video src="..." controls>` for downloaded mp4, `<details>` + `<iframe>` for VK Player fallback
- **Relative paths**: computed via `path_rel()` — forward slashes, relative from `MdFiles/` dir
- **`.gitignore`**: `Temp/`, `__pycache__/`

## Filtering

Two per-dialog filters in `config.json`:
- `min_cid_by_peer_id`: skip messages where `conversation_message_id <= value`
- `min_date_by_peer_id`: skip messages where `date <= parsed unix timestamp`

Applied in two places:
1. Before `extract_items_from_data()` — filtered items don't get JSON files
2. When iterating `OriginalMessages/` — existing filtered files are skipped (defense against pre-filter leftovers)

## Logging

All logging goes through `BaseLogger` interface with 3 implementations:
- `PrintLogger` — prints to console (CLI mode)
- `BufferLogger` — accumulates warnings, `ConsumeMessages()` drains them (web streaming)
- `AggregationLogger` — delegates to multiple loggers

Logger instance is passed as required parameter to all functions that may emit warnings: `main()`, `build_md_items()`, `download_file()`, `get_video_embed_urls()`, `ensure_author_avatars()`, etc.

In web export (`/export/generate`), `BufferLogger` is used and drained after each pipeline yield, displaying warnings in yellow (`#cca700`) among the white log text.
