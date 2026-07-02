# VkChatBackupCommunity

## Goal
Backup forwarded messages from a VK community chat: fetch chat history via VK API, extract all forwarded (`fwd_messages`) messages into individual JSON files, then convert them to Markdown files with full attachment rendering and a sources table.

## Project Structure

```
Scripts/
├── main.py              # Entry point: fetch → extract → build → render → write
├── config.py            # Load VK_TOKEN, GROUP_ID, PEER_ID from .env
├── vk_client.py         # VK API client (raw requests, pagination, rate limiting)
├── export_fwd.py        # Extract fwd_messages[] from messages.json
├── MdItem.py            # DTO: BaseAttachmentItem + 8 subclasses + MdItem
├── md_item_builder.py   # build_md_items(): JSON → MdItem, resolves attachments, downloads files
├── md_renderer.py       # render_md_item(): MdItem → Markdown (pure, no I/O)
├── download_media.py    # download_file() + DownloadItem + download_all
├── requirements.txt     # requests, python-dotenv
├── .env.example         # Template for credentials
├── .gitignore           # Ignores .env, Temp/, __pycache__/
```

Output directory structure:
```
Temp/ExportMessages/dialog_{peer_id}/
├── messages.json                      # Full chat history
├── ExtractedOriginalMessages/         # Individual forwarded message JSON files
│   ├── {date}_{cid}.json
│   └── ...
└── MdConvertResults/                  # Converted Markdown files
    ├── {first_sentence}.Id{cid}.md
    └── ...
```

## Data Flow

1. **main.py** → `VkClient.get_all_history(peer_id)` → `messages.json`
2. **main.py** → `extract_forwarded(messages.json, ExtractedOriginalMessages/)` → per-message JSON files
3. **main.py** → `build_md_items(JSON, name, md_dir, vk_client)` → `list[MdItem]` with resolved attachments and downloaded files
4. **main.py** → `render_md_item(item)` → Markdown string → write to `.md` file

All steps run unconditionally. Step 3 resolves all attachments into typed DTOs and downloads photos/stickers/videos immediately. Step 4 is pure rendering (no I/O).

## Module Details

### config.py
- Loads `.env` from the same directory as the script
- Exports: `VK_TOKEN` (str), `GROUP_ID` (int), `PEER_ID` (int)
- Hardcoded: `API_VERSION = "5.199"`, `API_BASE_URL = "https://api.vk.com/method"`
- Video download flags: `DOWNLOAD_SHORT_VIDEO` (bool), `DOWNLOAD_LONG_VIDEO` (bool), `LONG_VIDEO_THRESHOLD` (int, секунды)

### vk_client.py
- `VkClient(token)` — raw `requests.Session`-based VK API client
- `_call(method, params, retries=3)` — generic API call with retry on error 6 (too many requests per second). Backoff: `2^attempt` seconds. Raises `RuntimeError` on other errors.
- `get_history(peer_id, count=200, offset=0)` — single page of `messages.getHistory`
- `get_all_history(peer_id)` — paginated fetch (200 per page, 0.35s sleep between calls). Returns list in chronological order (reversed at end).
- Rate limit: community token = 3 RPS → 0.35s sleep ≈ ~2.85 RPS.
- `get_video_urls(owner_id, video_id)` — fetches `vk.com/video_ext.php?oid=...&id=...`, parses mp4 URLs from embedded JSON. No authorization needed.

### export_fwd.py
- `extract_forwarded(messages_json_path, output_dir)` — reads `messages.json`, iterates `messages[].fwd_messages[]`, saves each as `{date}_{conversation_message_id}.json`
- Skips entries without `date` or `conversation_message_id`
- Returns count of extracted files

### download_media.py
- `DownloadItem` — dataclass: `url` (оригинальный URL), `relpath` (относительный путь для сохранения)
- `download_file(url, filepath, timeout=30)` — скачивает один файл в указанный путь
- `download_all(queue, md_dir)` — принимает `dict[int, list[DownloadItem]]`, скачивает файлы в `{md_dir}/RawData/{cid}/{n}.{ext}` без задержки

### MdItem.py
- `BaseAttachmentItem` — marker base class для всех типов вложений
- `PhotoAttachment`, `VideoAttachment`, `LinkAttachment`, `DocAttachment`, `AudioAttachment`, `StickerAttachment`, `WallAttachment` — dataclass-наследники с уже скачанными данными (local_path, urls, и т.д.)
- `MdItem` — dataclass: `cid`, `from_id`, `date`, `text`, `attachments: list[BaseAttachmentItem]`, `forwarded: list[MdItem]`, `json_filename`, `heading`, `filename`, `is_wall_split`

### md_item_builder.py
- `build_md_items(fwd, json_filename, md_dir, vk_client=None, url_to_relpath=None)` — читает JSON dict, создаёт `list[MdItem]`. Рекурсивно обрабатывает `fwd_messages`. Скачивает фото/видео/стикеры сразу.
- **Filename rules**:
  - С текстом: `{first_sentence}.Id{cid}.md` (max 60 chars + `...`)
  - Без текста: `{AttachmentType}.{date}.Id{cid}.md` (prefix: Photo/Video/ShortVideo/Link/Article/Doc/Audio/Sticker/Media)
  - `Статья.` prefix если только wall/post без текста сообщения
  - Несколько wall/post → `_part_N` suffix
  - Filename cleaned: emojis removed, `—`→`-`, special chars `\/*?:"<>|` → `_`
- **First sentence logic** (`_first_sentence`): Split on `\n`, `.`, `!`, `?` — take first part

### md_renderer.py
- `render_md_item(item, level=1)` — превращает `MdItem` в Markdown (чистая функция, без I/O)
- Dispatch по `isinstance` (не строковые сравнения):
  - `PhotoAttachment` → `**Фото:** ![](local_path)`
  - `VideoAttachment` → `**Видео:** [title](player)`, preview, `<video>` / `<details><iframe>`
  - `LinkAttachment` → `**Ссылка:** [title](url)`
  - `DocAttachment` → `**Документ:** [title](url)`
  - `AudioAttachment` → `**Аудио:** artist — title`
  - `StickerAttachment` → `**Стикер:** ![](local_path)`
  - `WallAttachment` → expanded inline под `### Запись на стене`

- **Markdown structure** (`_render_message`):
  - `# first_sentence` (or `# Сообщение (id N)` fallback)
  - `**От:** from_id`, `**Дата:** YYYY-MM-DD HH:MM:SS`
  - Single attachment before text only when: text exists + exactly 1 attachment + no nested fwd_messages
  - Otherwise: text → `## Вложения` → attachments → nested fwd_messages (recursive, `## Пересланные сообщения`)
  - Newlines in text → `<br>`

- **Markdown for wall posts** (`_render_message_with_wall`, when `is_wall_split=True`):
  - Same header, then `## Вложения` → non-wall attachments → wall post (under `### Запись на стене`)

- **Источники table**: rendered inline via `_append_sources_table` (без отдельных функций `_collect_sources`)
  ```
  | Тип | Относительная ссылка | Ссылка |
  |-----|---------------------|--------|
  | Исходный файл | | [relative/path.json](relative/path.json) |
  | Фото | RawData/{cid}/{n}.jpg | [url](url) |
  | Видео | | [url](url) |
  | Превью | RawData/{cid}/{n}.jpg | [url](url) |
  | Ссылка | | [url](url) |
  | Ссылка на пост | | [url](url) |
  | Документ | | [url](url) |
  ```
  Обходится рекурсивно (включая вложенные fwd_messages и wall post attachments)

## Conventions

- **Python 3.9** — no `X | Y` union syntax, use `Optional[X]`, `Union[X, Y]`
- **Raw HTTP** — use `requests`, not `vk_api` library
- **No type annotations** in `export_fwd.py` (legacy code)
- **Output format**: Markdown with `<br>` for newlines (not native markdown line breaks)
- **Video rendering**: `<video src="..." controls>` for downloaded mp4, `<details>` + `<iframe>` for VK Player fallback
- **Video download**: controlled by `DOWNLOAD_SHORT_VIDEO`, `DOWNLOAD_LONG_VIDEO`, `LONG_VIDEO_THRESHOLD` in `config.py`
- **Short video / clip download**: if `video.files` is empty, `_resolve_video` calls `vk_client.get_video_urls()` on `vk.com/video_ext.php` (no auth needed), downloads mp4 immediately to `RawData/{cid}/{n}.mp4`; player URL also constructed from `oid`/`id`
- **`.gitignore`**: `Temp/` (all export outputs), `.env`, Python/PyCharm artifacts

## Constraints

- Community VK token: 3 RPS limit → 0.35s sleep between calls; error 6 retry with 1→2→4s backoff
- VK dev site is JavaScript-rendered — API knowledge is from training data / documentation
- VK API `messages.getHistory` returns newest-first; `get_all_history()` reverses at end

## Dependencies

- `requests>=2.28.0`
- `python-dotenv>=1.0.0`
