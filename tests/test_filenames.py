from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from config import Config
from Loggers.buffer_logger import BufferLogger
from md_item_builder import _compute_filename, _windows_length, build_md_items, fit_md_filename


class FilenameTests(unittest.TestCase):
    def test_long_title_and_date_reserve_ellipsis_and_cid(self):
        logger = BufferLogger()
        for text, date in (("А" * 1000, "2026-10-01"), ("", "2026-10-01-" * 100)):
            name = _compute_filename(text, [], date, 123, 83, logger)
            self.assertLessEqual(83 + 1 + _windows_length(name), 254)
            self.assertTrue(name.endswith(".Id123.md"))
        self.assertEqual(logger.ConsumeMessages(), [])

    def test_article_and_multipart_final_names_fit(self):
        directory = str(run.root / "Temp/Archive/ExportMessages/Dialogs/dialog_1234567/MdFiles")
        message = {"conversation_message_id": 1, "text": "", "attachments": [
            {"type": "wall", "wall": {"id": n, "owner_id": -42, "text": "Б" * 1000}}
            for n in range(1, 13)]}
        items = build_md_items(message, 1, 1, "2026_1.json", directory,
                               directory + "/raw", directory + "/large", {}, Config(), {}, BufferLogger())
        self.assertEqual(len(items), 12)
        for index, item in enumerate(items, 1):
            self.assertLessEqual(_windows_length(directory + "/" + item.filename), 254)
            self.assertTrue(item.filename.startswith("Статья."))
            self.assertTrue(item.filename.endswith(f".Id1_part_{index}.md"))
            self.assertEqual(item.attachments[-1].text, "Б" * 1000)

    def test_unicode_and_deep_path_keep_identifiers_or_fail_clearly(self):
        name = fit_md_filename("𓂀" * 200 + ".Id123_part_12.md", 100)
        self.assertLessEqual(100 + 1 + _windows_length(name), 254)
        self.assertRegex(name, r"\.Id123_part_12\.md$")
        self.assertEqual(fit_md_filename("Very long title.Id123.md", 245), "Id123.md")
        with self.assertRaisesRegex(ValueError, "слишком глубока"):
            fit_md_filename("Title.Id123.md", 250)

    def test_repair_preserves_cid_multipart_and_short_names(self):
        for name in ("Title.Id28756.md", "Статья." + "В" * 200 + ".Id12_part_2.md"):
            fitted = fit_md_filename(name, 83)
            self.assertLessEqual(83 + 1 + _windows_length(fitted), 254)
            self.assertEqual(re.search(r"Id\d+(?:_part_\d+)?\.md$", name).group(),
                             re.search(r"Id\d+(?:_part_\d+)?\.md$", fitted).group())
        self.assertEqual(fit_md_filename("Title.Id28756.md", 83), "Title.Id28756.md")
