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
│   ├── MdItem.py             # DTO: BaseAttachmentItem + 8 subclasses (DocAttachment has local_path) + MdItem
│   ├── md_item_builder.py    # build_md_items(): JSON → MdItem, resolves attachments
│   ├── md_renderer.py        # render_md_item(): MdItem → Markdown (pure, no I/O)
│   ├── export_fwd.py         # extract_items_from_data(items, output_dir)
│   ├── author_resolver.py    # AuthorInfo + load_authors() + ensure_author_avatars()
│   ├── download_media.py     # download_file() → bool, download_all() — with error handling
│   ├── vk_client.py          # get_video_embed_urls()
│   └── logger.py             # Logger.LogWarning()
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
│           ├── RawData/                      # Small attachments, grouped by CID
│           │   └── {cid}/
│           │       ├── 1.jpg
│           │       └── 2.webp
│           ├── OriginalMessages/             # Individual message JSON files {date}_{cid}.json
│           │   └── 2026-01-15_1234.json
│           └── MdFiles/                      # Rendered Markdown files
│               └── Привет.Id1234.md
└── LargeRawData/                             # Large files (videos), kept separate
    └── dialog_{peer_id}/                     # because the rest is intended for git repo
        └── {cid}/
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

1. **main.py** → scans all `*.json` in `Sources/`, groups messages by `peer_id` into `dialog_by_peer_id[cid]` (dedup by `conversation_message_id`), merges profiles/groups
2. **main.py** → `load_authors(merged_data)` → `dict[int, AuthorInfo]`
3. **main.py** → per dialog: `extract_items_from_data(filtered_items)` → `{date}_{cid}.json`
4. **main.py** → per dialog: `build_md_items(json, config, ...)` → `list[MdItem]` with resolved attachments and downloaded files
5. **main.py** → per dialog: `render_md_item(item)` → Markdown → write `.md` file

Step 4 resolves all attachments into typed DTOs and downloads photos/stickers/videos/docs immediately. Step 5 is pure rendering (no I/O).

`main(config, peer_ids=None)` is a **generator function** — it `yield`s log messages instead of `print()`. Both CLI and Web iterate over it the same way. Web uses `stream_with_context` for real-time progress display.

## Module Details

### Config/config.py
- `Config` dataclass with fields: `export_root`, `download_short_video`, `download_long_video`, `long_video_threshold`, `min_cid_by_peer_id`, `min_date_by_peer_id`
- Pure data container, no logic

### Config/config_loader.py
- `load_config(path: str) -> Config` — reads `config.json`, raises `FileNotFoundError` if file doesn't exist with path in message; parses and transforms (str keys → int, date strings → unix timestamps)
- `path_rel(target, start)` — `os.path.relpath()` with `\` → `/`

### config.json (user-provided, not tracked in git)
- `export_root` — path to export root (default: `{parent_dir}/Temp/ExportMessages`)
- `download_short_video` / `download_long_video` / `long_video_threshold` — video download flags
- `min_cid_by_peer_id` — per-dialog filter: `{peer_id: min_cid}` (messages with cid <= min_cid are skipped)
- `min_date_by_peer_id` — per-dialog filter: `{peer_id: "yyyy-mm-dd-hh-mm-ss"}` (messages with date <= filter are skipped)
- If peer_id not in dict — filter disabled for that dialog

### ExportMessageToMd/main.py
- Generator function `main(config: Config, peer_ids: Optional[set[int]] = None)` — yields log messages as it processes. `peer_ids` filters which dialogs to export (None = all)
- Used both by CLI (`run.py --mode cli`) and web (`POST /export/generate`)
- Can be run standalone: `python ExportMessageToMd/main.py --config ../config.json`

### ExportMessageToMd/md_item_builder.py
- `build_md_items(fwd, json_filename, md_dir, little_raw_data_dir, large_raw_data_dir, authors, config, url_to_relpath)` — reads JSON dict, creates `list[MdItem]`. Recursively processes `fwd_messages`. Downloads photos/videos/stickers/docs immediately.
- **Filename rules**:
  - With text: `{first_sentence}.Id{cid}.md`
  - Without text: `{AttachmentType}.{date}.Id{cid}.md` (prefix: Photo/Video/ShortVideo/Link/Article/Doc/Audio/Sticker/Media)
  - `Статья.` prefix if only wall/post without text
  - Multiple wall/post → `_part_N` suffix
  - Filename cleaned: emojis removed, `—`→`-`, `@mention` prefixes stripped (same as `#hashtag`), special chars `\/*?:"<>|` → `_`
- **Max path length (254 chars)**: `_compute_filename(md_dir_abs_len, extra_suffix_len)` truncates text dynamically: `max_text = 254 - len(os.path.abspath(md_dir)) - 1 - len(".Id{cid}.md") - extra_suffix_len` (min 10). `extra_suffix_len` accounts for `"Статья."` (8) and `_part_N` suffix. `Logger.LogWarning` if final path exceeds 254. `_compute_heading()` remains hardcoded at 60 (display-only, not filename).

### ExportMessageToMd/md_renderer.py
- `_render_video()` — blank line before preview image to separate it from title
- `_render_attachment(DocAttachment)` — uses `local_path` if available, falls back to URL

## WebApp

### web.py
- Flask app factory pattern: `init_app(config_path)` → `_init_paths()` → sets all path globals
- `_build_message_date_str_by_cid(orig_dir)` — builds `dict[int, str]` cache mapping cid → date string from OriginalMessages JSON filenames (called once per dialog view instead of per-message)
- `/export` → `render_template("export.html", ...)` passes `dialogs_path=str(dialogs_dir_abs)` for displaying the MD output directory

| Маршрут | Метод | Описание |
|---|---|---|
| `/` | GET | Список диалогов |
| `/export` | GET | Страница экспорта (список Sources по peer_id, фильтры, кнопка генерации) |
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
| `/dialog/<peer_id>/<cid>/rename-attachment` | PUT | Переименование вложения |
| `/export/<path>` | GET | Статика (Dialogs, Sources) |
| `/large/<path>` | GET | Статика (LargeRawData) |

### export.html
- **Блок 1 «Как получить messages.json»**: Пошаговая инструкция (открыть VK, открыть консоль, настроить параметры, запустить скрипт). Поля ввода `peerId` (обязательный), `fromDate` (yyyy-mm-dd, опционально), `fromMessageId` (опционально). Динамически генерируемый скрипт для консоли браузера с кнопкой копирования. Валидация даты.
- **Блок 2 «Подключение messages.json»**: Путь к Sources, описание назначения, кнопка создания директории (`POST /export/create-sources`), кнопка загрузки файла (`POST /export/upload`)
- **Блок 3 «Экспорт в MD»**: Описание конвертации, путь к директории MD-файлов, сворачиваемая структура директорий, список `.json` файлов из `Sources/` сгруппированных по `peer_id` с чекбоксами выбора диалогов (включая «Выбрать все»), поля фильтров `min_cid`/`min_date` для каждого peer_id (сохраняются через `POST /export/save-filters`), кнопка "Сформировать MD" → `POST /export/generate`. После нажатия кнопка блокируется, сервер отдаёт потоковый HTML-лог.

### dialog.html & index.html
- Добавлена ссылка «Экспорт» в шапке (рядом с «Диалоги»)
- Остальное без изменений

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
