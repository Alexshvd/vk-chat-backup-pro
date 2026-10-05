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
from Loggers.context_logger import warning_text
from md_item_builder import build_md_items
from vk_import import VkImportJobs, write_json
from vk_import_worker import Status


class WarningDetailsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=run.root / 'Temp')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_warning_keeps_signed_media_url_and_exception_reason(self):
        status = Status(self.root, 42)
        status.LogWarning('URL: https://cdn.test/file?sig=visible&access_token=private', ValueError('HTTP 424'))
        message = status.data['warning_messages'][0]
        self.assertIn('sig=visible', message)
        self.assertIn('ValueError: HTTP 424', message)
        self.assertNotIn('private', message)
        self.assertNotIn('[ссылка]', message)

    def test_failed_attachment_has_dialog_root_nested_message_and_identity(self):
        logger = BufferLogger()
        fwd = {'attachments': [{'type': 'doc', 'doc': {'owner_id': 8, 'id': 99,
                'title': 'Report.pdf', 'ext': 'pdf', 'url': 'https://cdn.test/report.pdf'}}]}
        def failed(url, destination, logger, **kwargs):
            logger.LogWarning('HTTP 424: ' + url)
            return False
        with patch('md_item_builder.download_file', side_effect=failed):
            build_md_items(fwd, 17, 947, 'Original.json', str(self.root/'MdFiles'),
                           str(self.root/'RawData'), str(self.root/'LargeRawData/dialog_42'),
                           {}, Config(export_root=str(self.root)), {}, logger)
        text = '\n'.join(logger.ConsumeMessages())
        for value in ('Диалог 42', '№947', '№17', 'Report.pdf', 'ID 8_99', 'HTTP 424', 'https://cdn.test/report.pdf'):
            self.assertIn(value, text)

    def test_old_job_returns_archive_references_without_inventing_error_reasons(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps({'export_root': str(self.root/'Archive')}), encoding='utf-8')
        directory = self.root / 'Archive/ExportMessages/Dialogs/dialog_42'
        (directory/'MdFiles').mkdir(parents=True)
        (directory/'OriginalMessages').mkdir()
        url = 'https://cdn.test/music.m3u8?sig=visible'
        (directory/'MdFiles/User.Id947.md').write_text(f'| Аудио | Ошибка скачивания | [url]({url}) |\n'*2, encoding='utf-8')
        (directory/'MdFiles/Good.Id948.md').write_text('| Фото | [photo](../RawData/1.jpg) | [url](https://cdn.test/photo) |', encoding='utf-8')
        (directory/'OriginalMessages/date_947.json').write_text(json.dumps({'attachments': [
            {'type': 'audio', 'audio': {'artist':'Artist','title':'Song','url':url}}]}), encoding='utf-8')
        job = self.root/'Temp/VkImport'/('a'*32)
        job.mkdir(parents=True)
        write_json(job/'job.json', {'peer_id':42})
        write_json(job/'status.json', {'peer_id':42,'state':'complete','warnings':7,'warning_messages':['Ошибка [ссылка]']})
        result = VkImportJobs(config).status(job.name)
        self.assertEqual(result['warnings'],7)
        self.assertTrue(result['warning_details_legacy'])
        self.assertEqual(len(result['warning_attachments']),1)
        issue = result['warning_attachments'][0]
        self.assertEqual(issue['url'],url)
        self.assertEqual(issue['message_url'],'/chat/42?message=947')
        self.assertIn('Artist — Song',issue['title'])
        self.assertNotIn('reason',issue)
