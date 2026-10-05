import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run
from config import Config
from config_loader import path_rel
from chat_view import ChatArchive
from dialog_media import media_library


class DialogMediaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=ROOT / 'Temp')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dialog = self.root / 'ExportMessages/Dialogs/dialog_42'
        self.md = self.dialog / 'MdFiles'
        self.md.mkdir(parents=True)
        self.config = Config(export_root=str(self.root))

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def row(self, label, path, remote):
        return f'| {label} | [file]({path_rel(str(path), str(self.md))}) | [url]({remote}) |\n'

    def test_shared_file_once_with_all_messages_and_no_foreign_or_avatar_files(self):
        shared = self.write('LargeRawData/SharedMedia/images/sha256_photo.jpg', b'photo')
        unused = self.write('LargeRawData/SharedMedia/images/unrelated.jpg', b'other shared')
        avatar = self.write('ExportMessages/Dialogs/AutorImages/42.jpg', b'avatar')
        foreign = self.write('ExportMessages/Dialogs/dialog_99/RawData/1/secret.jpg', b'foreign')
        outside = self.write('private.jpg', b'outside')
        for cid in (1, 2):
            text = self.row('Фото', shared, 'https://cdn.test/photo')
            text += self.row('Аватар автора', avatar, 'https://cdn.test/avatar')
            text += self.row('Фото', foreign, 'https://cdn.test/foreign')
            text += self.row('Фото', outside, 'https://cdn.test/private')
            (self.md/f'User.Id{cid}.md').write_text(text, encoding='utf-8')
        conversation = {'dialog': {'peer_id':42,'name':'Chat'}, 'messages':[
            {'cid':cid,'date':cid*100,'reply':{'attachments':[{'type':'photo','src':'/large/SharedMedia/images/sha256_photo.jpg','title':'Forwarded photo'}]}}
            for cid in (1,2)]}
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('requests.get', side_effect=AssertionError('Library must not download')):
            data = media_library(self.config, 42, conversation)
        self.assertEqual(data['total'],1)
        self.assertEqual(data['total_bytes'],5)
        item = data['items'][0]
        self.assertTrue(item['shared'])
        self.assertEqual(item['title'],'Forwarded photo')
        self.assertEqual([m['cid'] for m in item['messages']],[2,1])
        self.assertEqual(item['messages'][0]['url'],'/chat/42?message=2')
        self.assertEqual(data['counts']['photo'],1)
        self.assertEqual({p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()},before)

    def test_nested_raw_large_unicode_files_missing_and_partial_downloads(self):
        self.write('ExportMessages/Dialogs/dialog_42/RawData/10/11/Фото (1)#.png',b'image')
        self.write('ExportMessages/Dialogs/dialog_42/RawData/10/music.m4a',b'audio')
        self.write('ExportMessages/Dialogs/dialog_42/RawData/10/Report & notes.pdf',b'doc')
        self.write('LargeRawData/dialog_42/10/1.mp4',b'video')
        self.write('LargeRawData/dialog_42/10/1.mp4.part',b'partial')
        self.write('ExportMessages/Dialogs/dialog_42/RawData/10/.audio-work/chunk.ts',b'temp')
        self.write('ExportMessages/Dialogs/dialog_42/RawData/10/1.photo-upgrade.jpg',b'temp')
        self.write('ExportMessages/Dialogs/dialog_42/RawData/10/empty.jpg',b'')
        missing = self.root/'LargeRawData/SharedMedia/images/missing.jpg'
        (self.md/'Id10.md').write_text(self.row('Фото',missing,'https://cdn.test/missing'),encoding='utf-8')
        data = media_library(self.config,42,{'dialog':{'name':'Chat'},'messages':[{'cid':10,'date':100}]})
        self.assertEqual(data['total'],4)
        self.assertEqual(data['counts'],{'photo':1,'audio':1,'video':1,'file':1})
        photo=next(i for i in data['items'] if i['type']=='photo')
        self.assertIn('%20%281%29%23.png',photo['src'])
        self.assertEqual(photo['messages'][0]['cid'],10)

    def test_custom_dialog_large_folder_and_empty_source_only_chat(self):
        self.dialog.rename(self.dialog.with_name('Custom'))
        self.config.dialog_name_by_peer_id={42:'Custom'}
        self.config.peer_id_by_dialog_custom_name={'Custom':42}
        self.write('LargeRawData/dialog_42/1/1.mp4',b'video')
        data=media_library(self.config,42,{'dialog':{'name':'Custom'},'messages':[]})
        self.assertEqual(data['total'],1)
        self.assertEqual(data['items'][0]['src'],'/large/dialog_42/1/1.mp4')
        data=media_library(self.config,404,{'dialog':{'name':'Empty'},'messages':[]})
        self.assertEqual(data['total'],0)


if __name__ == '__main__':
    unittest.main()
