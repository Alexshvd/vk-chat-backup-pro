"""Music and voice attachments, including legacy document voice messages."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

from MdItem import AudioAttachment, NoDownloadResult, ErrorDownloadResult, SuccessDownloadResult
from config_loader import path_rel
from download_media import DOWNLOAD_HEADERS, download_file
from Loggers.context_logger import ContextLogger
import requests


def audio_payload(attachment):
    kind = attachment.get("type")
    if kind in ("audio", "audio_message"):
        return attachment.get(kind) or {}, kind == "audio_message"
    if kind == "doc":
        doc = attachment.get("doc") or {}
        voice = (doc.get("preview") or {}).get("audio_msg")
        if isinstance(voice, dict):
            return dict(voice, id=doc.get("id"), owner_id=doc.get("owner_id")), True
    return None


def audio_sources(data, is_voice):
    entries = [(data.get("link_mp3"), "mp3"), (data.get("link_ogg"), "ogg")] if is_voice else [(data.get("url"), "mp3")]
    result = []
    for url, default_ext in entries:
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            continue
        ext = Path(parsed.path).suffix.lower().lstrip(".")
        if ext not in ("mp3", "ogg", "opus", "wav", "m4a", "aac", "webm", "m3u8"):
            ext = default_ext
        result.append((url, ext))
    return result


def _get_hls_bytes(url, limit):
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValueError("Некорректный адрес ресурса музыкального потока")
    try:
        with requests.get(url, headers=DOWNLOAD_HEADERS, timeout=(15, 30), stream=True) as response:
            if not response.ok:
                raise RuntimeError(f"Сервер аудио вернул HTTP {response.status_code}")
            result = bytearray()
            for block in response.iter_content(64 * 1024):
                result.extend(block)
                if len(result) > limit:
                    raise ValueError("Ресурс музыкального потока превышает допустимый размер")
            return bytes(result), response.url
    except requests.RequestException:
        raise RuntimeError("Не удалось получить ресурс музыкального потока") from None


def _hls_source(url, directory):
    import m3u8
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    for depth in range(4):
        content, final_url = _get_hls_bytes(url, 2 * 1024 * 1024)
        if not content.lstrip().startswith(b"#EXTM3U"):
            raise ValueError("Сервер вернул не музыкальный плейлист")
        playlist = m3u8.loads(content.decode("utf-8-sig"), uri=final_url)
        if not playlist.is_variant:
            break
        if not playlist.playlists:
            raise ValueError("Музыкальный плейлист не содержит вариантов")
        url = max(playlist.playlists, key=lambda item: item.stream_info.bandwidth or 0).absolute_uri
    else:
        raise ValueError("Слишком много вложенных музыкальных плейлистов")
    if not playlist.is_endlist or not playlist.segments:
        raise ValueError("Музыкальный плейлист не содержит законченной записи")
    keys = {}
    for segment in playlist.segments:
        if segment.byterange or segment.init_section:
            raise ValueError("Этот формат музыкального потока пока не поддерживается")
        key = segment.key
        if key and key.method != "NONE":
            if key.method != "AES-128" or key.keyformat not in (None, "identity"):
                raise ValueError("Этот способ защиты музыкального потока не поддерживается")
            if key.absolute_uri not in keys:
                keys[key.absolute_uri] = _get_hls_bytes(key.absolute_uri, 256)[0]
                if len(keys[key.absolute_uri]) != 16:
                    raise ValueError("Некорректный ключ музыкального потока")

    def fetch(entry):
        index, segment = entry
        content = _get_hls_bytes(segment.absolute_uri, 32 * 1024 * 1024)[0]
        key = segment.key
        if key and key.method == "AES-128":
            iv = int(key.iv, 16).to_bytes(16, "big") if key.iv else (playlist.media_sequence + index).to_bytes(16, "big")
            content = unpad(AES.new(keys[key.absolute_uri], AES.MODE_CBC, iv).decrypt(content), 16)
        if not content:
            raise ValueError("Пустой сегмент музыкального потока")
        path = directory / f"{index}.segment"
        path.write_bytes(content)
        return path

    with ThreadPoolExecutor(max_workers=min(8, len(playlist.segments))) as pool:
        parts = list(pool.map(fetch, enumerate(playlist.segments)))
    joined = directory / "source.media"
    with joined.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
    return joined, sum(segment.duration for segment in playlist.segments)


def _download_hls(url, target, duration):
    import imageio_ffmpeg
    temporary = target.with_name(target.name + ".part")
    try:
        with tempfile.TemporaryDirectory(prefix=".audio-", dir=target.parent) as workspace:
            directory = Path(workspace)
            directory.resolve().relative_to(target.parent.resolve())
            source, playlist_duration = _hls_source(url, directory)
            command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-protocol_whitelist", "file", "-i", str(source),
                       "-map", "0:a:0", "-vn", "-c:a", "copy", "-movflags", "+faststart",
                       "-progress", "pipe:1", "-f", "mp4", str(temporary)]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=max(180, min(1800, duration * 2)),
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Do not expose signed CDN addresses from FFmpeg's stderr in logs.
        if result.returncode:
            raise RuntimeError("Не удалось скачать поток музыки (FFmpeg)")
        times = [int(line.split(b"=", 1)[1]) / 1000000 for line in result.stdout.splitlines()
                 if line.startswith(b"out_time_us=") and line.split(b"=", 1)[1].isdigit()]
        expected_duration = max(duration, playlist_duration)
        actual_duration = max(times, default=0)
        if expected_duration and actual_duration < expected_duration - 2:
            raise ValueError(f"Музыкальный поток скачан не полностью: получено {actual_duration:.1f} с из {expected_duration:.1f} с")
        with temporary.open("rb") as stream:
            header = stream.read(12)
        if b"ftyp" not in header or temporary.stat().st_size < 100:
            raise ValueError("Музыкальный поток не содержит аудиофайла")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_audio(data, is_voice, raw_dir, md_dir, assets, config, logger):
    sources = audio_sources(data, is_voice)
    item = AudioAttachment(artist="" if is_voice else data.get("artist", ""),
                           title="Голосовое сообщение" if is_voice else data.get("title", ""),
                           original_url=sources[0][0] if sources else "", is_voice=is_voice,
                           duration=data.get("duration") or 0)
    enabled = config.download_voice_messages if is_voice else config.download_audio
    if not enabled or not sources:
        return item
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    title = ' — '.join(filter(None, [item.artist, item.title]))
    logger = ContextLogger(logger, 'Аудио: ' + (title or 'без названия'))
    for url, ext in sources:
        if url in assets:
            item.original_url = url
            item.download_result = SuccessDownloadResult(assets[url])
            return item
        name = ("voice_" if is_voice else "music_") + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        target = raw_dir / (name + "." + ("m4a" if ext == "m3u8" else ext))
        try:
            if not target.is_file() or target.stat().st_size == 0:
                if ext == "m3u8":
                    _download_hls(url, target, item.duration)
                elif not download_file(url, str(target), logger):
                    continue
                if ext != "m3u8":
                    with target.open("rb") as stream:
                        header = stream.read(12)
                    valid = (header.startswith((b"ID3", b"OggS", b"\x1aE\xdf\xa3")) or b"ftyp" in header
                             or (header.startswith(b"RIFF") and header[8:12] == b"WAVE")
                             or (len(header) > 1 and header[0] == 255 and header[1] & 224 == 224))
                    if not valid:
                        target.unlink(missing_ok=True)
                        raise ValueError("Сервер вернул не аудиофайл")
            relative = path_rel(str(target), str(md_dir))
            assets[url] = relative
            item.original_url = url
            item.download_result = SuccessDownloadResult(relative)
            return item
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            reason = "Превышено время ожидания" if isinstance(error, subprocess.TimeoutExpired) else str(error)
            logger.LogWarning(f"Ошибка скачивания аудио\nФайл: {target}\nURL: {url}\nПричина: {reason}")
    item.download_result = ErrorDownloadResult()
    return item
