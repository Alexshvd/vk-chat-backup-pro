import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "WebApp"))
sys.path.insert(0, str(ROOT / "Config"))
sys.path.insert(0, str(ROOT / "ExportMessageToMd"))
from config import Config
from chat_view import ChatArchive, local_url, media_index, safe_url


class ChatViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "Temp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.export = self.root / "ExportMessages"
        self.large = self.root / "LargeRawData"
        self.dialog = self.export / "Dialogs" / "dialog_42"
        for path in (self.export / "Sources", self.dialog / "OriginalMessages", self.dialog / "MdFiles", self.large):
            path.mkdir(parents=True, exist_ok=True)
        self.config = Config(export_root=str(self.root))

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_chronological_dedup_source_only_messages_and_nested_content(self):
        items = [
            {"conversation_message_id": 2, "date": 200, "from_id": 7, "out": 1, "text": "Новое <script>",
             "reply_message": {"text": "Ответ", "from_id": 42},
             "fwd_messages": [{"from_id": 42, "text": "Пересылка"}], "attachments": []},
            {"conversation_message_id": 1, "date": 100, "from_id": 42, "out": 0, "text": "Первое"},
        ]
        self.write_json(self.export / "Sources" / "a.json", {"peer_id": 42, "items": items,
                        "profiles": [{"id": 42, "first_name": "Иван", "last_name": "Петров"}]})
        self.write_json(self.dialog / "OriginalMessages" / "old.json", dict(items[1], text="Старый текст"))
        (self.dialog / "MdFiles" / "Id1.md").write_text("", encoding="utf-8")
        (self.dialog / "MdFiles" / "Текст.Id1_part_2.md").write_text("", encoding="utf-8")
        with patch("requests.get", side_effect=AssertionError("Viewer must not download")):
            data = ChatArchive(self.config).conversation(42)
        self.assertEqual([m["cid"] for m in data["messages"]], [1, 2])
        first, second = data["messages"]
        self.assertEqual(first["text"], "Первое")
        self.assertFalse(first["out"])
        self.assertTrue(second["out"])
        self.assertEqual(second["reply"]["text"], "Ответ")
        self.assertEqual(second["forwarded"][0]["text"], "Пересылка")
        self.assertEqual(data["pending"], 1)
        self.assertEqual(data["dialog"]["count"], 2)
        self.assertEqual(data["dialog"]["name"], "Иван Петров")
        self.assertIsNone(ChatArchive(self.config).conversation(404))

    def test_media_with_unicode_spaces_parentheses_and_outside_path_rejected(self):
        photo = self.dialog / "RawData" / "1" / "Фото (1)#.jpg"
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b"image")
        video = self.large / "dialog_42" / "1" / "video.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"video")
        outside = self.root / "private.txt"
        outside.write_text("private", encoding="utf-8")
        md = self.dialog / "MdFiles" / "A.Id1.md"
        md.write_text("\n".join([
            "| Фото | [file](../RawData/1/Фото (1)#.jpg) | [url](https://vk.example/photo) |",
            "| Видео | [file](../../../../LargeRawData/dialog_42/1/video.mp4) | [url](https://vk.example/player) |",
            "| Doc | [file](../../../../private.txt) | [url](https://vk.example/private) |",
        ]), encoding="utf-8")
        assets = media_index([md], self.export, self.large)
        self.assertIn("%20%281%29%23.jpg", assets["https://vk.example/photo"])
        self.assertEqual(assets["https://vk.example/player"], "/large/dialog_42/1/video.mp4")
        self.assertNotIn("https://vk.example/private", assets)
        self.assertEqual(local_url(outside, self.export, self.large), "")
        archive = ChatArchive(self.config)
        self.assertEqual(archive.attachment({"type": "video", "video": {"player": "https://vk.example/player"}}, assets, 0)["src"], "/large/dialog_42/1/video.mp4")
        sticker = archive.attachment({"type": "sticker", "sticker": {"images_with_background": [{"url": "no"}], "images": [{"url": "https://vk.example/photo"}]}}, assets, 0)
        self.assertEqual(sticker["src"], assets["https://vk.example/photo"])

    def test_filters_invalid_partial_source_and_safe_links(self):
        source = self.export / "Sources" / "a.json"
        source.write_text('{"peer_id":', encoding="utf-8")
        self.assertEqual(ChatArchive(self.config).dialogs()[0]["count"], 0)
        self.write_json(source, {"peer_id": 42, "items": [{"conversation_message_id": 1, "date": 50}, {"conversation_message_id": 2, "date": 100}]})
        self.config.min_cid_by_peer_id = {42: 1}
        self.assertEqual(ChatArchive(self.config).dialogs()[0]["count"], 1)
        for url in ("javascript:alert(1)", "file:///C:/private", "https://[", "//example.com"):
            self.assertEqual(safe_url(url), "")


if __name__ == "__main__":
    unittest.main()
