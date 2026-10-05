import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ExportMessageToMd"))
from download_media import download_file
from Loggers.buffer_logger import BufferLogger

DATA = bytes(range(256)) * (140 * 1024)


class CDN(BaseHTTPRequestHandler):
    requests_seen = []
    fail_piece = False
    lock = threading.Lock()

    def do_GET(self):
        if "Chrome/" not in self.headers.get("User-Agent", ""):
            self.send_error(400)
            return
        byte_range = self.headers.get("Range")
        with self.lock:
            self.requests_seen.append(byte_range)
        if self.path == "/broken-stream":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"partial")
            return
        if not byte_range or self.path == "/no-ranges":
            self.send_response(200)
            self.send_header("Content-Length", str(len(DATA)))
            self.end_headers()
            try:
                self.wfile.write(DATA)
            except (ConnectionError, OSError):
                pass  # Probe intentionally closes a server that ignores Range.
            return
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", byte_range)
        first, last = map(int, match.groups())
        if self.fail_piece and first == 16 * 1024 * 1024:
            self.send_error(503)
            return
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {first}-{last}/{len(DATA)}" if self.path != "/bad-range" or last == 0 else f"bytes 0-{last-first}/{len(DATA)}")
        self.send_header("Content-Length", str(last-first+1))
        self.send_header("ETag", '"test-object"')
        self.end_headers()
        try:
            self.wfile.write(DATA[first:last+1])
        except (ConnectionError, OSError):
            pass

    def log_message(self, *args):
        pass


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CDN)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "Temp")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.target = self.directory / "video.mp4"
        self.progress = self.directory / "progress.json"
        self.env = patch.dict(os.environ, {"VK_BACKUP_DOWNLOAD_CACHE": str(self.directory / "cache"), "VK_BACKUP_DOWNLOAD_PROGRESS": str(self.progress), "VK_BACKUP_DOWNLOAD_CONNECTIONS": "8"})
        self.env.start()
        self.addCleanup(self.env.stop)
        CDN.requests_seen = []
        CDN.fail_piece = False
        self.logger = BufferLogger()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def assert_video(self):
        self.assertEqual(self.target.stat().st_size, len(DATA))
        self.assertEqual(hashlib.sha256(self.target.read_bytes()).digest(), hashlib.sha256(DATA).digest())
        self.assertEqual(json.loads(self.progress.read_text(encoding="utf-8"))["state"], "complete")

    def test_parallel_video_matches_original_bytes(self):
        self.assertTrue(download_file(self.base + "/video", str(self.target), self.logger))
        self.assert_video()
        self.assertIn("bytes=16777216-33554431", CDN.requests_seen)
        self.assertFalse(self.logger.ConsumeMessages())
        self.assertEqual(json.loads(self.progress.read_text(encoding="utf-8"))["connections"], 3)

    def test_high_concurrency_preserves_exact_video_with_smaller_pieces(self):
        with patch.dict(os.environ, {"VK_BACKUP_DOWNLOAD_CONNECTIONS": "112"}):
            self.assertTrue(download_file(self.base + "/video", str(self.target), self.logger))
        self.assert_video()
        self.assertIn("bytes=0-1048575", CDN.requests_seen)
        self.assertEqual(json.loads(self.progress.read_text(encoding="utf-8"))["connections"], 35)

    def test_high_concurrency_resumes_legacy_cache_without_redownloading_piece(self):
        url = self.base + "/video"
        identity = json.dumps([str(self.target.resolve()), url, len(DATA), '"test-object"']).encode("utf-8")
        cache = self.directory / "cache" / hashlib.sha256(identity).hexdigest()
        cache.mkdir(parents=True)
        (cache / "0.part").write_bytes(DATA[:16 * 1024 * 1024])
        with patch.dict(os.environ, {"VK_BACKUP_DOWNLOAD_CONNECTIONS": "112"}):
            self.assertTrue(download_file(url, str(self.target), self.logger))
        self.assert_video()
        self.assertNotIn("bytes=0-16777215", CDN.requests_seen)

    def test_failed_piece_resumes_cached_parts_without_replacing_original(self):
        self.target.write_bytes(b"original")
        CDN.fail_piece = True
        self.assertFalse(download_file(self.base + "/video", str(self.target), self.logger))
        self.assertEqual(self.target.read_bytes(), b"original")
        self.assertEqual(CDN.requests_seen.count("bytes=0-16777215"), 1)
        CDN.fail_piece = False
        self.assertTrue(download_file(self.base + "/video", str(self.target), self.logger))
        self.assert_video()
        self.assertEqual(CDN.requests_seen.count("bytes=0-16777215"), 1)

    def test_server_without_ranges_uses_stream_download(self):
        self.assertTrue(download_file(self.base + "/no-ranges", str(self.target), self.logger))
        self.assert_video()
        self.assertEqual(json.loads(self.progress.read_text(encoding="utf-8"))["connections"], 1)

    def test_wrong_range_and_incomplete_stream_do_not_replace_saved_file(self):
        self.target.write_bytes(b"original")
        self.assertFalse(download_file(self.base + "/bad-range", str(self.target), self.logger))
        self.assertEqual(self.target.read_bytes(), b"original")
        image = self.directory / "photo.jpg"
        image.write_bytes(b"saved photo")
        self.assertFalse(download_file(self.base + "/broken-stream", str(image), self.logger))
        self.assertEqual(image.read_bytes(), b"saved photo")


if __name__ == "__main__":
    unittest.main()
