from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from config import Config
from Loggers.buffer_logger import BufferLogger
from md_item_builder import _get_best_video_url
from video_backfill import backfill_videos
from vk_client import _parse_video_embed


class VideoTests(unittest.TestCase):
    def test_low_and_high_resolution_and_source(self):
        self.assertEqual(_get_best_video_url({"mp4_144": "https://cdn.test/144"}), "https://cdn.test/144")
        self.assertEqual(_get_best_video_url({"mp4_1080": "https://cdn.test/a", "mp4_2160": "https://cdn.test/b"}), "https://cdn.test/b")
        self.assertEqual(_get_best_video_url({"src": "https://cdn.test/file"}), "https://cdn.test/file")
        self.assertIsNone(_get_best_video_url({"mp4_144": None, "src": "https://cdn.test/list.m3u8"}))
        self.assertIsNone(_get_best_video_url({"mp4_144": "file:///private", "external": "https://youtube.com/watch"}))

    def test_embed_preserves_source_and_failover(self):
        files = {"src": "https://cdn.test/file", "failover_host": "vkvd296.okcdn.ru"}
        for text in ('"apiPrefetchCache": {"files":' + json.dumps(files) + '}', '"files":' + json.dumps(files, separators=(",", ":"))):
            self.assertEqual(_parse_video_embed(text, BufferLogger()), files)

    def test_backfill_preserves_message_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=run.root / "Temp") as temp:
            root = Path(temp)
            directory = root / "ExportMessages/Dialogs/dialog_7"
            (directory / "MdFiles").mkdir(parents=True)
            (directory / "OriginalMessages").mkdir()
            player = "https://vk.ru/video_ext.php?oid=1&id=2"
            original = directory / "OriginalMessages/2026_1.json"
            original.write_text(json.dumps({"conversation_message_id": 1, "attachments": [{"type": "wall", "wall": {"attachments": [{"type": "video", "video": {"player": player, "files": {"mp4_144": "https://cdn.test/file"}}}]}}]}), encoding="utf-8")
            md = directory / "MdFiles/Test.Id1.md"
            old_text = 'User text\n<img src="../RawData/1/photo.jpg">\n<details>\n<summary>Смотреть через VK Player</summary>\n<iframe src="' + player + '"></iframe>\n</details>\n| Видео |  | [url](' + player + ') |\n'
            md.write_text(old_text, encoding="utf-8")
            original_bytes = original.read_bytes()
            config = Config(export_root=str(root), download_short_video=True, download_long_video=True)
            def download(url, target, logger, fallback_urls=None):
                path = Path(target)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"a" * 32)
                return True
            with patch("video_backfill.download_file", side_effect=download) as mock:
                list(backfill_videos(config, BufferLogger()))
                new_text = md.read_text(encoding="utf-8")
                list(backfill_videos(config, BufferLogger()))
                self.assertEqual(mock.call_count, 1)
            self.assertEqual(new_text, md.read_text(encoding="utf-8"))
            self.assertIn('User text\n<img src="../RawData/1/photo.jpg">', new_text)
            self.assertIn('<video src="', new_text)
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(next((root / "ExportMessages/VideoBackups").rglob("*.md")).read_text(encoding="utf-8"), old_text)
            md.write_text(old_text, encoding="utf-8")
            for p in (root / "LargeRawData").rglob("*.mp4"):
                p.unlink()
            with patch("video_backfill.download_file", return_value=False):
                list(backfill_videos(config, BufferLogger()))
            self.assertEqual(md.read_text(encoding="utf-8"), old_text)


if __name__ == "__main__":
    unittest.main()
