import functools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run
import imageio_ffmpeg
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from audio_media import resolve_audio, _download_hls
from audio_backfill import backfill_audio
from config import Config
from config_loader import load_config
from Loggers.buffer_logger import BufferLogger
from MdItem import AudioAttachment, NoDownloadResult, SuccessDownloadResult
from md_item_builder import _resolve_attachment
from chat_view import ChatArchive


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "Temp")
        cls.files = Path(cls.temp.name)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietFiles, directory=str(cls.files)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        def generate(args):
            result = subprocess.run([cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2"] + args, capture_output=True)
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
        generate(["-c:a", "libmp3lame", str(cls.files / "voice.mp3")])
        generate(["-c:a", "libvorbis", str(cls.files / "voice.ogg")])
        (cls.files / "invalid.mp3").write_bytes(b"<html>not audio</html>")
        (cls.files / "key.bin").write_bytes(b"1234567890abcdef")
        key_info = cls.files / "key-info.txt"
        key_info.write_text(cls.base + "/key.bin\n" + (cls.files / "key.bin").as_posix() + "\n", encoding="utf-8")
        generate(["-c:a", "aac", "-f", "hls", "-hls_time", "1", "-hls_playlist_type", "vod", "-hls_key_info_file", str(key_info), str(cls.files / "music.m3u8")])
        mp3 = (cls.files / "voice.mp3").read_bytes()
        split = len(mp3) // 3
        parts = [mp3[:split], mp3[split:2 * split], mp3[2 * split:]]
        manifest = ["#EXTM3U", "#EXT-X-TARGETDURATION:1", "#EXT-X-MEDIA-SEQUENCE:12"]
        for index, part in enumerate(parts):
            if index != 1:
                part = AES.new(b"1234567890abcdef", AES.MODE_CBC, (12 + index).to_bytes(16, "big")).encrypt(pad(part, 16))
                manifest.append('#EXT-X-KEY:METHOD=AES-128,URI="key.bin"')
            else:
                manifest.append("#EXT-X-KEY:METHOD=NONE")
            (cls.files / f"mixed{index}.segment").write_bytes(part)
            manifest.extend(["#EXTINF:0.666667,", f"mixed{index}.segment"])
        manifest.append("#EXT-X-ENDLIST")
        (cls.files / "mixed.m3u8").write_text("\n".join(manifest), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def setUp(self):
        self.temp_archive = tempfile.TemporaryDirectory(dir=ROOT / "Temp")
        self.addCleanup(self.temp_archive.cleanup)
        self.root = Path(self.temp_archive.name)
        self.dialog = self.root / "ExportMessages/Dialogs/dialog_42"
        self.md_dir = self.dialog / "MdFiles"
        self.raw = self.dialog / "RawData/1"
        self.md_dir.mkdir(parents=True)
        (self.dialog / "OriginalMessages").mkdir()
        self.config = Config(export_root=str(self.root), download_audio=True, download_voice_messages=True)
        self.logger = BufferLogger()

    def test_switches_and_missing_urls_never_download(self):
        self.config.download_audio = False
        self.config.download_voice_messages = False
        with patch("requests.get", side_effect=AssertionError("Disabled audio must not download")):
            for voice, data in ((False, {"url": self.base + "/voice.mp3"}), (True, {"link_mp3": self.base + "/voice.mp3"}), (False, {})):
                item = resolve_audio(data, voice, self.raw, self.md_dir, {}, self.config, self.logger)
                self.assertIsInstance(item.download_result, NoDownloadResult)
        self.assertFalse(self.raw.exists())

    def test_voice_fallback_uses_ogg_and_legacy_document_is_audio(self):
        attachment = {"type": "doc", "doc": {"id": 7, "preview": {"audio_msg": {
            "link_mp3": self.base + "/missing.mp3", "link_ogg": self.base + "/voice.ogg"}}}}
        item = _resolve_attachment(attachment, str(self.raw), str(self.raw), str(self.md_dir), {}, {}, self.config, self.logger)
        self.assertIsInstance(item, AudioAttachment)
        self.assertTrue(item.is_voice)
        self.assertIsInstance(item.download_result, SuccessDownloadResult)
        target = self.md_dir / item.download_result.local_path
        self.assertEqual(target.suffix, ".ogg")
        self.assertEqual(target.read_bytes(), (self.files / "voice.ogg").read_bytes())

    def test_html_response_is_rejected_and_voice_uses_valid_alternative(self):
        item = resolve_audio({"link_mp3": self.base + "/invalid.mp3", "link_ogg": self.base + "/voice.ogg"}, True,
                             self.raw, self.md_dir, {}, self.config, self.logger)
        self.assertIsInstance(item.download_result, SuccessDownloadResult)
        self.assertEqual((self.md_dir / item.download_result.local_path).suffix, ".ogg")
        self.assertFalse(list(self.raw.glob("*.mp3")))

    def test_encrypted_hls_becomes_playable_local_audio(self):
        item = resolve_audio({"url": self.base + "/music.m3u8", "duration": 2}, False, self.raw, self.md_dir, {}, self.config, self.logger)
        self.assertIsInstance(item.download_result, SuccessDownloadResult, self.logger.ConsumeMessages())
        target = self.md_dir / item.download_result.local_path
        self.assertEqual(target.suffix, ".m4a")
        self.assertIn(b"ftyp", target.read_bytes()[:12])
        decoded = subprocess.run([self.ffmpeg, "-v", "error", "-i", str(target), "-f", "null", "-"], capture_output=True)
        self.assertEqual(decoded.returncode, 0, decoded.stderr)

    def test_incomplete_hls_preserves_existing_file(self):
        self.raw.mkdir(parents=True)
        target = self.raw / "original.m4a"
        target.write_bytes(b"original audio")
        with self.assertRaisesRegex(ValueError, "не полностью"):
            _download_hls(self.base + "/music.m3u8", target, 20)
        self.assertEqual(target.read_bytes(), b"original audio")
        self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_mixed_encrypted_and_clear_mp3_segments_with_implicit_iv(self):
        item = resolve_audio({"url": self.base + "/mixed.m3u8", "duration": 2}, False, self.raw, self.md_dir, {}, self.config, self.logger)
        self.assertIsInstance(item.download_result, SuccessDownloadResult, self.logger.ConsumeMessages())
        target = self.md_dir / item.download_result.local_path
        decoded = subprocess.run([self.ffmpeg, "-v", "error", "-i", str(target), "-progress", "pipe:1", "-f", "null", "-"], capture_output=True)
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        times = [int(line.split(b"=", 1)[1]) for line in decoded.stdout.splitlines() if line.startswith(b"out_time_us=")]
        self.assertGreater(max(times), 1800000)

    def test_backfill_preserves_other_media_and_is_idempotent_with_nested_voices(self):
        music = {"type": "audio", "audio": {"url": self.base + "/voice.mp3", "artist": "Artist", "title": "Track"}}
        voice = {"type": "audio_message", "audio_message": {"link_mp3": self.base + "/voice.mp3"}}
        legacy = {"type": "doc", "doc": {"preview": {"audio_msg": {"link_ogg": self.base + "/voice.ogg"}}}}
        message = {"conversation_message_id": 1, "date": 100, "text": "Keep me", "attachments": [music],
                   "fwd_messages": [{"attachments": [legacy]}], "reply_message": {"attachments": [voice]}}
        original = self.dialog / "OriginalMessages/100_1.json"
        original.write_text(json.dumps(message), encoding="utf-8")
        original_bytes = original.read_bytes()
        self.raw.mkdir(parents=True)
        photo = self.raw / "photo.jpg"
        photo.write_bytes(b"preserved image")
        md_file = self.md_dir / "Id1.md"
        prefix = "# Original heading\n\nKeep me\n\n![photo](../RawData/1/photo.jpg)\n\n"
        md_file.write_text(prefix + "## Источники\n\n| Тип | Относительная ссылка | Ссылка |\n|-----|-----|-----|\n| Аудио | | Artist — Track |\n", encoding="utf-8")
        report = list(backfill_audio(self.config, self.logger))
        first = md_file.read_bytes()
        self.assertIn("ошибок: 0", report[-1])
        self.assertIn("<audio ", first.decode("utf-8"))
        self.assertTrue(md_file.read_text(encoding="utf-8").startswith(prefix))
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(photo.read_bytes(), b"preserved image")
        with patch("requests.get", side_effect=AssertionError("Saved audio must not download again")):
            list(backfill_audio(self.config, self.logger))
        self.assertEqual(md_file.read_bytes(), first)
        conversation = ChatArchive(self.config).conversation(42)
        root = conversation["messages"][0]
        for item in (root, root["reply"], root["forwarded"][0]):
            self.assertTrue(item["attachments"][0]["src"].startswith("/export/"))

    def test_settings_round_trip_keeps_independent_switches(self):
        import web
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps({"export_root": str(self.root), "custom": "preserved"}))
        with patch.multiple(web, _config_path=str(config_path), export_root_abs=self.root,
                            export_serve_abs=self.root / "ExportMessages", large_root_abs=self.root / "LargeRawData",
                            dialogs_dir_abs=self.root / "ExportMessages/Dialogs"):
            client = web.app.test_client()
            response = client.post("/settings/save", json={"download_audio": True, "download_voice_messages": False})
            self.assertEqual(response.status_code, 200)
            loaded = load_config(str(config_path))
            self.assertTrue(loaded.download_audio)
            self.assertFalse(loaded.download_voice_messages)
            self.assertEqual(json.loads(config_path.read_text())["custom"], "preserved")
            page = client.get("/settings").data.decode("utf-8")
            self.assertIn("Скачивать музыку", page)
            self.assertIn("Скачивать голосовые сообщения", page)
            self.assertIn("/export/audio", page)
