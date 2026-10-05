import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from config import Config
from Loggers.buffer_logger import BufferLogger
from main import main
from chat_view import ChatArchive
from md_item_builder import _resolve_video
from MdItem import SuccessDownloadResult
from video_backfill import backfill_videos
from video_cache import VideoCache, VideoPaths, mp4_quality, video_key


def mp4(tier=720):
    def box(kind, payload):
        return struct.pack('>I4s', len(payload) + 8, kind) + payload
    track = box(b'tkhd', b'\0' * 76 + struct.pack('>II', tier * 2 << 16, tier << 16))
    return box(b'ftyp', b'isom\0\0\0\0isom') + box(b'mdat', b'video-data') + box(b'moov', box(b'trak', track))


class VideoCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=run.root / 'Temp')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'Archive'
        self.root.mkdir()
        self.config = Config(export_root=str(self.root), download_long_video=True)
        self.logger = BufferLogger()

    def video(self, signature='old', owner=1, ident=2, tier=720):
        return {'owner_id':owner, 'id':ident, 'duration':10, 'title':'Same video',
                'player':f'https://vk.ru/video_ext.php?oid={owner}&id={ident}&hash={signature}',
                'files':{f'mp4_{tier}':f'https://cdn.test/{signature}.mp4'}}

    def message(self, video, cid=1):
        return {'conversation_message_id':cid, 'date':100, 'from_id':10,
                'text':'Preserve user text', 'attachments':[{'type':'video','video':video}]}

    def existing(self, peer, video, tier=720, nested=False, missing=False):
        directory = self.root / f'ExportMessages/Dialogs/dialog_{peer}'
        for name in ('MdFiles', 'OriginalMessages'):
            (directory / name).mkdir(parents=True, exist_ok=True)
        media = self.root / f'LargeRawData/dialog_{peer}/1/1.mp4'
        media.parent.mkdir(parents=True, exist_ok=True)
        if not missing:
            media.write_bytes(mp4(tier))
        data = self.message(video)
        if nested:
            data = {'conversation_message_id':1, 'date':100, 'reply_message':{'fwd_messages':[data]}}
        original = directory / 'OriginalMessages/2026_1.json'
        original.write_text(json.dumps(data), encoding='utf-8')
        local = os.path.relpath(media, directory / 'MdFiles').replace('\\','/') if not missing else ''
        md = directory / 'MdFiles/User.Id1.md'
        md.write_text(f'Edited text\n| Видео | [{local}]({local}) | [player]({video["player"]}) |\n', encoding='utf-8')
        return media, md, original

    def resolve(self, peer, video, cache):
        directory = self.root / f'ExportMessages/Dialogs/dialog_{peer}'
        return _resolve_video(video, str(directory / 'RawData/1'),
                              str(self.root / f'LargeRawData/dialog_{peer}/1'),
                              str(directory / 'MdFiles'), VideoPaths(cache),
                              self.config, self.logger, False)

    def download(self, url, destination, logger, **kwargs):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(mp4(1080 if '1080' in url else 720))
        return True

    def test_existing_video_matches_changed_urls_and_survives_source_dialog_deletion(self):
        source, md, original = self.existing(7, self.video(), nested=True)
        original_bytes, md_bytes = original.read_bytes(), md.read_bytes()
        with VideoCache(self.root, self.logger) as cache:
            self.assertEqual(cache.scan(self.config), (1,1))
            with patch('video_cache.json.loads', side_effect=AssertionError('Unchanged JSON must not be reread')):
                self.assertEqual(cache.scan(self.config), (0,1))
            with patch('requests.get', side_effect=AssertionError('No CDN or embed requests')):
                result = self.resolve(8, self.video('new-signature'), cache)
            self.assertIsInstance(result.mp4_download_result, SuccessDownloadResult)
            target = (self.root / 'ExportMessages/Dialogs/dialog_8/MdFiles' / result.mp4_download_result.local_path).resolve()
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertTrue(target.is_relative_to(cache.shared))
            self.assertTrue(os.path.samefile(source, target))
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(md.read_bytes(), md_bytes)
            # Fixture only: remove the first dialog and its per-dialog video.
            shutil.rmtree(source.parent)
            shutil.rmtree(md.parents[1])
            self.assertEqual(cache.find(self.video('third-signature'),720),target)

    def test_two_new_dialogs_download_video_once_and_view_the_shared_file(self):
        sources = self.root / 'ExportMessages/Sources'
        sources.mkdir(parents=True)
        for peer in (7,8):
            (sources / f'{peer}.json').write_text(json.dumps({'peer_id':peer, 'items':[self.message(self.video(str(peer)))]}), encoding='utf-8')
        with patch('md_item_builder.download_file', side_effect=self.download) as download:
            logs = list(main(self.config,None,self.logger))
        self.assertEqual(download.call_count,1)
        self.assertTrue(any('Видео использованы повторно: 1' in line for line in logs))
        archive = ChatArchive(self.config)
        left = archive.conversation(7)['messages'][0]['attachments'][0]['src']
        right = archive.conversation(8)['messages'][0]['attachments'][0]['src']
        self.assertEqual(left,right)
        self.assertTrue(left.startswith('/large/SharedMedia/videos/'))
        self.assertEqual(len(list((self.root / 'LargeRawData').rglob('*.mp4'))),1)
        # Re-export: existing messages and videos are retained with no traffic.
        with patch('requests.get', side_effect=AssertionError('No repeated download')):
            list(main(self.config,None,self.logger))

    def test_lower_quality_is_not_reused_instead_of_a_higher_requested_tier(self):
        self.existing(7,self.video(tier=1080),tier=360)
        with VideoCache(self.root,self.logger) as cache:
            cache.scan(self.config)
            video = self.video('1080',tier=1080)
            with patch('md_item_builder.download_file', side_effect=self.download) as download:
                result = self.resolve(8,video,cache)
            self.assertEqual(download.call_count,1)
            target = (self.root / 'ExportMessages/Dialogs/dialog_8/MdFiles' / result.mp4_download_result.local_path).resolve()
            self.assertEqual(mp4_quality(target),1080)
            self.assertEqual(cache.find(self.video('different',tier=720),720),target)

    def test_web_view_range_requests_moves_and_deletion_keep_other_dialog_playable(self):
        import web
        sources = self.root / 'ExportMessages/Sources'
        sources.mkdir(parents=True)
        for peer in (7,8):
            (sources / f'{peer}.json').write_text(json.dumps({'peer_id':peer,'items':[self.message(self.video(str(peer)))]}),encoding='utf-8')
        with patch('md_item_builder.download_file',side_effect=self.download):
            list(main(self.config,None,self.logger))
        config_path = self.root / 'config.json'
        config_path.write_text(json.dumps({'export_root':str(self.root)}),encoding='utf-8')
        old_config = web._config_path
        web.load_configs(str(config_path))
        self.addCleanup(web.load_configs,old_config or str(run.root / 'config.json'))
        shared = next((self.root / 'LargeRawData/SharedMedia/videos').glob('*.mp4'))
        md = next((self.root / 'ExportMessages/Dialogs/dialog_8/MdFiles').glob('*.md'))
        old = md.read_text(encoding='utf-8')
        moved = md.parent / 'subfolder' / md.name
        moved.parent.mkdir()
        moved.write_text(web._rewrite_links_for_move(old,1),encoding='utf-8')
        md.unlink()
        self.assertEqual(web._list_attachments(8,1)['shared'][0]['size'],shared.stat().st_size)
        self.assertIn('/large/SharedMedia/videos/',web._md_to_html(moved))
        with web.app.test_client() as client:
            path = '/large/SharedMedia/videos/' + shared.name
            response = client.get(path,headers={'Range':'bytes=0-7'})
            self.assertEqual(response.status_code,206)
            self.assertEqual(response.data,shared.read_bytes()[:8])
            response.close()
            self.assertEqual(client.delete('/dialog/7/1').status_code,200)
            self.assertTrue(shared.is_file())
            self.assertTrue(ChatArchive(self.config).conversation(8)['messages'][0]['attachments'][0]['src'].startswith('/large/SharedMedia/videos/'))
        self.assertEqual(web._get_attachment_size(moved.parent,self.root / 'ExportMessages/Dialogs/dialog_8/RawData',8,1,[moved]),shared.stat().st_size)

    def test_overwriting_a_legacy_message_preserves_video_without_downloading_again(self):
        source, md, _ = self.existing(7,self.video())
        self.config.overwrite_existing_md = True
        with patch('requests.get',side_effect=AssertionError('Saved video must be preserved before deleting its message folder')):
            list(main(self.config,None,self.logger))
        self.assertFalse(source.exists())
        shared = next((self.root / 'LargeRawData/SharedMedia/videos').glob('*.mp4'))
        self.assertEqual(mp4_quality(shared),720)
        self.assertEqual(ChatArchive(self.config).conversation(7)['messages'][0]['attachments'][0]['src'],
                         '/large/SharedMedia/videos/' + shared.name)

    def test_same_numeric_id_with_different_owners_is_a_different_video(self):
        self.existing(7,self.video(owner=1))
        with VideoCache(self.root,self.logger) as cache:
            cache.scan(self.config)
            with patch('md_item_builder.download_file', side_effect=self.download) as download:
                self.resolve(8,self.video(owner=3),cache)
            self.assertEqual(download.call_count,1)

    def test_missing_truncated_and_changed_files_are_not_reused(self):
        source, _, _ = self.existing(7,self.video())
        with VideoCache(self.root,self.logger) as cache:
            cache.scan(self.config)
            shared = cache.find(self.video(),720)
            source.unlink()
            shared.write_bytes(mp4()[:20])
            self.assertIsNone(cache.find(self.video(),720))
            with patch('md_item_builder.download_file', side_effect=self.download) as download:
                result = self.resolve(8,self.video('retry'),cache)
            self.assertEqual(download.call_count,1)
            self.assertIsInstance(result.mp4_download_result,SuccessDownloadResult)

    def test_failed_download_never_enters_the_index_and_is_retried(self):
        with VideoCache(self.root,self.logger) as cache:
            with patch('md_item_builder.download_file',return_value=False) as download:
                self.resolve(7,self.video(),cache)
                self.resolve(8,self.video('different-signature'),cache)
            self.assertEqual(download.call_count,2)
            self.assertIsNone(cache.find(self.video(),720))

    def test_backfill_reuses_video_across_two_existing_messages(self):
        for peer in (7,8):
            self.existing(peer,self.video(str(peer)),missing=True)
        with patch('video_backfill.download_file',side_effect=self.download) as download:
            list(backfill_videos(self.config,self.logger))
            list(backfill_videos(self.config,self.logger))
        self.assertEqual(download.call_count,1)
        for md in (self.root / 'ExportMessages/Dialogs').rglob('*.md'):
            self.assertTrue(md.read_text(encoding='utf-8').startswith('Edited text\n'))
            self.assertIn('SharedMedia/videos',md.read_text(encoding='utf-8'))

    def test_index_rejects_paths_outside_media_archive_and_partial_files(self):
        outside = self.root / 'private.mp4'
        outside.write_bytes(mp4())
        partial = self.root / 'LargeRawData/unfinished.mp4'
        partial.parent.mkdir()
        partial.write_bytes(mp4()[:-12])
        with VideoCache(self.root,self.logger) as cache:
            self.assertFalse(cache.register(outside,self.video()))
            self.assertFalse(cache.register(partial,self.video()))
            self.assertIsNone(cache.find(self.video(),720))
        self.assertEqual(video_key(self.video('new')),video_key({'player':self.video('old')['player']}))

    def test_filesystem_without_hard_links_copies_once_and_preserves_source(self):
        source, _, _ = self.existing(7,self.video())
        with VideoCache(self.root,self.logger) as cache:
            cache.scan(self.config)
            with patch('video_cache.os.link',side_effect=OSError('No hard-link support')), patch('video_cache.shutil.copy2',wraps=shutil.copy2) as copy:
                target = cache.find(self.video('new'),720)
                self.assertEqual(cache.find(self.video('third'),720),target)
                self.assertEqual(copy.call_count,1)
            self.assertEqual(target.read_bytes(),source.read_bytes())
            self.assertFalse(os.path.samefile(source,target))

    def test_archive_can_be_moved_without_invalidating_the_relative_index(self):
        self.existing(7,self.video())
        with VideoCache(self.root,self.logger) as cache:
            cache.scan(self.config)
            target = cache.find(self.video(),720)
            name = target.name
        moved = self.root.parent / 'Archive-moved'
        self.root.rename(moved)
        moved_config = Config(export_root=str(moved))
        with VideoCache(moved,self.logger) as cache:
            self.assertEqual(cache.scan(moved_config),(0,1))
            self.assertEqual(cache.find(self.video('new'),720),cache.shared / name)


if __name__ == '__main__':
    unittest.main()
