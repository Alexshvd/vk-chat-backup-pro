from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from config import Config
from config_loader import path_rel
from author_resolver import AuthorInfo, ensure_author_avatars
from Loggers.buffer_logger import BufferLogger
from media_store import MediaStore, shared_avatars, rewrite_media_links
from video_cache import VideoCache
from test_video_cache import mp4


class MediaStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=run.root / 'Temp')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'Archive'
        self.config = Config(export_root=str(self.root))

    def attachment(self, peer, name, data, hardlink=None):
        directory = self.root / f'ExportMessages/Dialogs/dialog_{peer}'
        path = directory / 'RawData/1' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if hardlink:
            os.link(hardlink, path)
        else:
            path.write_bytes(data)
        md = directory / 'MdFiles/sub/User.Id1.md'
        md.parent.mkdir(parents=True, exist_ok=True)
        local = path_rel(str(path), str(md.parent))
        text = f'User edits\r\n<img src="{local}">\r\n[Document]({local})\r\n| Фото | [{local}]({local}) | [url](https://cdn.test/{name}) |\r\n'
        md.write_bytes(text.encode('utf-8'))
        return path, md

    def test_copies_and_hardlinks_get_one_path_preserving_edits_and_backup(self):
        for ext in ('jpg', 'm4a', 'pdf'):
            with self.subTest(ext=ext):
                first, md1 = self.attachment(1, 'file (edited).' + ext, ext.encode() * 13)
                second, md2 = self.attachment(2, 'file (edited).' + ext, first.read_bytes(), hardlink=first)
                third, md3 = self.attachment(3, 'file (edited).' + ext, first.read_bytes())
                originals = {md: md.read_bytes() for md in (md1, md2, md3)}
                with MediaStore(self.root) as store:
                    result = store.consolidate(self.config)
                    self.assertEqual(store.consolidate(self.config)['groups'], 0)
                self.assertEqual(result['groups'], 1)
                self.assertEqual(result['removed_paths'], 3)
                self.assertFalse(any(p.exists() for p in (first, second, third)))
                shared = list((self.root / 'LargeRawData/SharedMedia').rglob('*.' + ext))
                self.assertEqual(len(shared), 1)
                for md in originals:
                    text = md.read_bytes().decode('utf-8')
                    self.assertIn('User edits\r\n', text)
                    self.assertIn('[Document](' + path_rel(str(shared[0]), str(md.parent)) + ')', text)
                    self.assertIn('https://cdn.test/file (edited).' + ext, text)
                with zipfile.ZipFile(result['markdown_backup']) as backup:
                    for md, original in originals.items():
                        self.assertEqual(backup.read(md.relative_to(self.root).as_posix()), original)
                    self.assertFalse(any(name.endswith('.' + ext) for name in backup.namelist()))
                # Deleting a dialog must not delete shared media used elsewhere.
                shutil.rmtree(md1.parents[2])
                self.assertTrue(shared[0].exists())

    def test_avatars_survive_id_filename_removal_without_redownload(self):
        photo, md = self.attachment(42, '1.jpg', b'avatar')
        avatar = self.root / 'ExportMessages/Dialogs/AutorImages/17.jpg'
        avatar.parent.mkdir()
        avatar.write_bytes(photo.read_bytes())
        with MediaStore(self.root) as store:
            store.consolidate(self.config)
        mapped = shared_avatars(self.root)[17]
        self.assertFalse(avatar.exists())
        author = AuthorInfo(17, 'Name', '', 'https://cdn.test/avatar.jpg', '', 'Пользователь')
        with patch('author_resolver.download_file', side_effect=AssertionError('No redownload')):
            ensure_author_avatars({17: author}, str(avatar.parent), {}, str(md.parent), BufferLogger())
        self.assertEqual((md.parent / author.photo_local).resolve(), mapped)

    def test_video_index_reuse_does_not_create_another_shared_name(self):
        first, _ = self.attachment(1, '1.mp4', mp4())
        self.attachment(2, '1.mp4', first.read_bytes())
        with VideoCache(self.root, BufferLogger()) as cache:
            cache._register(first, 'vk-video:1:2', 720)
        with MediaStore(self.root) as store:
            store.consolidate(self.config)
        with VideoCache(self.root, BufferLogger()) as cache:
            target = cache.shared / next(cache.shared.glob('sha256_*.mp4')).name
            self.assertEqual(cache._share(target, 'vk-video:1:2', 720, target.stat().st_size), target)
            self.assertEqual(cache.db.execute('SELECT path FROM videos').fetchone()[0], target.relative_to(self.root).as_posix())
            self.assertEqual(len(list(cache.shared.iterdir())), 1)

    def test_equal_size_different_bytes_are_not_combined(self):
        first, _ = self.attachment(1, '1.jpg', b'photo one')
        second, _ = self.attachment(2, '1.jpg', b'photo two')
        with MediaStore(self.root) as store:
            self.assertEqual(store.consolidate(self.config)['groups'], 0)
        self.assertTrue(first.exists() and second.exists())


if __name__ == '__main__':
    unittest.main()
