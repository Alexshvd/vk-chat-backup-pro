# VkChatBackupCommunity

## Goal
Backup forwarded messages from a VK community chat: fetch chat history via VK API, extract all forwarded (`fwd_messages`) messages into individual JSON files, then convert them to Markdown files with full attachment rendering and a sources table.

## Project Structure

```
Scripts/
├── main.py            # Entry point: fetch → extract → convert
├── config.py          # Load VK_TOKEN, GROUP_ID, PEER_ID from .env
├── vk_client.py       # VK API client (raw requests, pagination, rate limiting)
├── export_fwd.py      # Extract fwd_messages[] from messages.json
├── export_md.py       # Convert forwarded JSON files to Markdown
├── requirements.txt   # requests, python-dotenv
├── .env.example       # Template for credentials
├── .gitignore         # Ignores .env, Temp/, __pycache__/
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
3. **main.py** → `convert_forwarded_to_md(ExtractedOriginalMessages/, MdConvertResults/)` → .md files with relative paths to `RawData/{cid}/{n}.{ext}`, fills download queue, downloads mp4 immediately
4. **main.py** → `download_all(queue, MdConvertResults/)` → downloads images to `RawData/{cid}/{n}.{ext}`

All steps run unconditionally. Step 3 accepts a `dict[int, list[DownloadItem]]` queue; images are registered during MD generation. Step 4 downloads without delay. Videos are downloaded immediately during step 3 via `get_video_urls()` on `vk.com/video_ext.php`.

## Module Details

### config.py
- Loads `.env` from the same directory as the script
- Exports: `VK_TOKEN` (str), `GROUP_ID` (int), `PEER_ID` (int)
- Hardcoded: `API_VERSION = "5.199"`, `API_BASE_URL = "https://api.vk.com/method"`
- Video download flags: `DOWNLOAD_VIDEO_SHORT` (bool), `DOWNLOAD_VIDEO_LONG` (bool), `VIDEO_LONG_THRESHOLD` (int, секунды)

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
- `download_all(queue, md_dir)` — принимает `dict[int, list[DownloadItem]]`, скачивает файлы в `{md_dir}/RawData/{cid}/{n}.{ext}` без задержки

### export_md.py
- `convert_forwarded_to_md(json_dir, md_dir, vk_client=None, download_queue=None)` — main conversion function, returns file count. Accepts optional `vk_client` for fetching mp4 URLs from `video_ext.php` when `video.files` is empty (e.g., short_video clips).

- **Filename rules** (`_make_filename`):
  - With text: `{first_sentence}.Id{cid}.md` (max 60 chars + `...`)
  - Without text: `{AttachmentType}.{date}.Id{cid}.md` (prefix: Photo/Video/ShortVideo/Link/Article/Doc/Audio/Sticker/Media)
  - `Статья.` prefix if only wall/post attachment with no message text
  - Multiple wall posts → `_part_N` suffix per wall post
  - Filename cleaned: emojis removed, `—`→`-`, special chars `\/*?:"<>|` → `_`

- **First sentence logic** (`_first_sentence`): Split on `\n`, `.`, `!`, `?` — take first part

- **Markdown structure** (`_render_message`):
  - `# first_sentence` (or `# Сообщение (id N)` fallback)
  - `**От:** from_id`, `**Дата:** YYYY-MM-DD HH:MM:SS`
  - Single attachment before text only when: text exists + exactly 1 attachment + no nested fwd_messages
  - Otherwise: text → `## Вложения` → attachments → nested fwd_messages (recursive, `## Пересланные сообщения`)
  - Newlines in text → `<br>`

- **Markdown for wall posts** (`_render_message_with_wall`):
  - Same header, then `## Вложения` → non-wall attachments → wall post (under `### Запись на стене`)
  - Wall post: `**Ссылка на запись:** [vk.com/wall...]`, text, nested attachments

- **Источники table** (both render functions):
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
  Collected recursively (including nested fwd_messages and wall post attachments)

- **Attachment rendering** (`_render_attachment`):
  - Photo: `**Фото:** ![](url)` (largest size)
  - Video: `**Видео:** [title](player)` + preview image
  - Link: `**Ссылка:** [title](url)`
  - Doc: `**Документ:** [title](url)`
  - Audio: `**Аудио:** artist — title`
  - Sticker: `**Стикер:** ![](url)` (last image)
  - Wall/post: expanded inline

## Conventions

- **Python 3.9** — no `X | Y` union syntax, use `Optional[X]`, `Union[X, Y]`
- **Raw HTTP** — use `requests`, not `vk_api` library
- **No type annotations** in `export_md.py` (legacy code)
- **Output format**: Markdown with `<br>` for newlines (not native markdown line breaks)
- **Video rendering**: `<video src="..." controls>` for downloaded mp4, `<details>` + `<iframe>` for VK Player fallback
- **Video download**: controlled by `DOWNLOAD_VIDEO_SHORT`, `DOWNLOAD_VIDEO_LONG`, `VIDEO_LONG_THRESHOLD` in `config.py`
- **Short video / clip download**: if `video.files` is empty, `_render_video` calls `vk_client.get_video_urls()` on `vk.com/video_ext.php` (no auth needed), downloads mp4 immediately to `RawData/{cid}/{n}.mp4`; player URL also constructed from `oid`/`id`
- **`.gitignore`**: `Temp/` (all export outputs), `.env`, Python/PyCharm artifacts

## Constraints

- Community VK token: 3 RPS limit → 0.35s sleep between calls; error 6 retry with 1→2→4s backoff
- VK dev site is JavaScript-rendered — API knowledge is from training data / documentation
- VK API `messages.getHistory` returns newest-first; `get_all_history()` reverses at end

## Dependencies

- `requests>=2.28.0`
- `python-dotenv>=1.0.0`
