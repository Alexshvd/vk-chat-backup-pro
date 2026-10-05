from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from config import Config
from Loggers.buffer_logger import BufferLogger
from photo_media import best_photo_url, image_size
from photo_backfill import backfill_photos


class PhotoTests(unittest.TestCase):
    def test_zero_and_partial_dimensions_use_named_size_and_ignore_empty_url(self):
        sizes = [{"type": kind, "width": 0, "height": 0, "url": "https://cdn.test/" + kind}
                 for kind in ('m', 'z', 's', 'y', 'x')]
        self.assertEqual(best_photo_url({"sizes": sizes}), "https://cdn.test/z")
        sizes.append({"type": "w", "width": 0, "height": 0, "url": ""})
        sizes[0].update(width=130, height=104)
        self.assertEqual(best_photo_url({"sizes": sizes}), "https://cdn.test/z")
        self.assertEqual(best_photo_url({"sizes": [{"url": "a", "width": 500, "height": 1000},
                                                   {"url": "b", "width": 800, "height": 400}]}), "a")

    def test_jpeg_and_png_dimensions_and_invalid_data(self):
        with tempfile.TemporaryDirectory(dir=run.root / 'Temp') as temp:
            path = Path(temp) / 'photo.jpg'
            path.write_bytes(b'\xff\xd8\xff\xe0\x00\x04AB\xff\xc0\x00\x08\x08' + struct.pack('>HH', 75, 60) + b'X')
            self.assertEqual(image_size(path), (60, 75))
            path.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 1280, 1024))
            self.assertEqual(image_size(path), (1280, 1024))
            path.write_bytes(b'<html>Error</html>')
            self.assertIsNone(image_size(path))

    def backfill_fixture(self, root):
        directory = root / 'ExportMessages/Dialogs/dialog_42'
        (directory / 'OriginalMessages').mkdir(parents=True)
        (directory / 'MdFiles').mkdir()
        target = directory / 'RawData/388/1.jpg'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 60, 75))
        original = directory / 'OriginalMessages/date_388.json'
        original.write_text(json.dumps({'attachments': [{'type': 'photo', 'photo': {'sizes': [
            {'type': 's', 'width': 0, 'height': 0, 'url': 'https://cdn.test/s'},
            {'type': 'z', 'width': 0, 'height': 0, 'url': 'https://cdn.test/z'}]}}]}), encoding='utf-8')
        md = directory / 'MdFiles/user.Id388.md'
        md.write_text('Edited message\n<img src="../RawData/388/1.jpg">\n| Фото | [photo](../RawData/388/1.jpg) | [url](https://cdn.test/s) |\n', encoding='utf-8')
        return target, md, original

    def test_upgrade_preserves_edits_originals_filename_and_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=run.root / 'Temp') as temp:
            root = Path(temp)
            target, md, original = self.backfill_fixture(root)
            old_photo, old_text, original_bytes = target.read_bytes(), md.read_text(), original.read_bytes()
            def download(url, destination, logger):
                self.assertEqual(url, 'https://cdn.test/z')
                Path(destination).write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 1024, 1280))
                return True
            config = Config(export_root=str(root))
            with patch('photo_backfill.download_file', side_effect=download) as mock:
                list(backfill_photos(config, BufferLogger()))
                list(backfill_photos(config, BufferLogger()))
                self.assertEqual(mock.call_count, 1)
            self.assertEqual(image_size(target), (1024, 1280))
            self.assertEqual(md.read_text(), old_text.replace('https://cdn.test/s', 'https://cdn.test/z'))
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(next((root / 'ExportMessages/PhotoBackups').rglob('1.jpg')).read_bytes(), old_photo)

    def test_failed_or_smaller_download_keeps_current_photo_and_md(self):
        for result in (False, b'Not an image', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 10, 10)):
            with tempfile.TemporaryDirectory(dir=run.root / 'Temp') as temp:
                root = Path(temp)
                target, md, _ = self.backfill_fixture(root)
                old_photo, old_md = target.read_bytes(), md.read_bytes()
                def download(url, destination, logger):
                    if result is False:
                        return False
                    Path(destination).write_bytes(result)
                    return True
                with patch('photo_backfill.download_file', side_effect=download):
                    list(backfill_photos(Config(export_root=str(root)), BufferLogger()))
                self.assertEqual(target.read_bytes(), old_photo)
                self.assertEqual(md.read_bytes(), old_md)

    def test_shared_upgrade_keeps_old_image_for_other_messages(self):
        with tempfile.TemporaryDirectory(dir=run.root / 'Temp') as temp:
            root = Path(temp)
            target, md, original = self.backfill_fixture(root)
            shared = root / 'LargeRawData/SharedMedia/images/sha256_old.jpg'
            shared.parent.mkdir(parents=True)
            target.replace(shared)
            old_bytes = shared.read_bytes()
            local = '../../../../LargeRawData/SharedMedia/images/sha256_old.jpg'
            md.write_text(md.read_text(encoding='utf-8').replace('../RawData/388/1.jpg', local), encoding='utf-8')
            untouched = md.with_name('User.Id389.md')
            untouched.write_bytes(md.read_bytes())
            old_other = untouched.read_bytes()
            def download(url, destination, logger):
                Path(destination).write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 1024, 1280))
                return True
            with patch('photo_backfill.download_file', side_effect=download):
                list(backfill_photos(Config(export_root=str(root)), BufferLogger()))
            self.assertEqual(shared.read_bytes(), old_bytes)
            self.assertEqual(untouched.read_bytes(), old_other)
            self.assertNotIn('sha256_old.jpg', md.read_text(encoding='utf-8'))
            self.assertIn('https://cdn.test/z', md.read_text(encoding='utf-8'))
            self.assertEqual(len(list(shared.parent.glob('*.jpg'))), 2)

    def test_missing_photo_is_restored_with_caption_edits_and_source_preserved(self):
        with tempfile.TemporaryDirectory(dir=run.root / 'Temp') as temp:
            root = Path(temp)
            target, md, original = self.backfill_fixture(root)
            target.unlink()
            old_text = 'User-edited message\n**Фото:** [ссылка](https://cdn.test/z)\nCaption\n| Фото | Ошибка скачивания | [url](https://cdn.test/z) |\n'
            md.write_text(old_text, encoding='utf-8')
            old_original = original.read_bytes()
            def download(url, destination, logger):
                self.assertEqual(url, 'https://cdn.test/z')
                Path(destination).write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 1024, 1280))
                return True
            with patch('photo_backfill.download_file', side_effect=download) as mock:
                messages = list(backfill_photos(Config(export_root=str(root)), BufferLogger()))
                list(backfill_photos(Config(export_root=str(root)), BufferLogger()))
                self.assertEqual(mock.call_count, 1)
            self.assertIn('восстановлено: 1', messages[-1])
            self.assertNotIn('Ошибка скачивания', md.read_text(encoding='utf-8'))
            self.assertIn('User-edited message', md.read_text(encoding='utf-8'))
            self.assertIn('Caption', md.read_text(encoding='utf-8'))
            self.assertIn('<img src="../RawData/388/recovered_', md.read_text(encoding='utf-8'))
            self.assertEqual(original.read_bytes(), old_original)
            self.assertEqual(next((root / 'ExportMessages/PhotoBackups').rglob('*.md')).read_text(encoding='utf-8'), old_text)

    def test_missing_photo_retry_failure_keeps_error_and_does_not_claim_success(self):
        with tempfile.TemporaryDirectory(dir=run.root / 'Temp') as temp:
            root = Path(temp)
            target, md, _ = self.backfill_fixture(root)
            target.unlink()
            old_text = '| Фото | Ошибка скачивания | [url](https://cdn.test/z) |\n'
            md.write_text(old_text, encoding='utf-8')
            with patch('photo_backfill.download_file', return_value=False) as mock:
                messages = list(backfill_photos(Config(export_root=str(root)), BufferLogger()))
            self.assertEqual(mock.call_count, 1)
            self.assertIn('ошибок: 1', messages[-1])
            self.assertIn('восстановлено: 0', messages[-1])
            self.assertEqual(md.read_text(encoding='utf-8'), old_text)


if __name__ == '__main__':
    unittest.main()
