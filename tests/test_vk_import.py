import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from vk_import import BrowserBridge, VkImportJobs, parse_dialog_link, read_json, write_json
from vk_import_worker import Cancelled, Status, bridge_history, collect_history, run_import


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=run.root / "Temp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"export_root": str(self.root / "Archive"), "overwrite_existing_md": True,
                                         "overwrite_existing_original_message_json": True}), encoding="utf-8")

    def test_links_and_foreign_hosts(self):
        self.assertEqual(parse_dialog_link("https://vk.ru/im/convo/12345678?entrypoint=list_all"), 12345678)
        self.assertEqual(parse_dialog_link("https://vk.com/im?sel=c42"), 2000000042)
        self.assertEqual(parse_dialog_link("https://vk.ru/im?sel=-42"), -42)
        for value in ("https://vk.ru.evil.test/im/convo/42", "https://vk.ru@evil.test/im/convo/42",
                      "https://vk.ru:9000/im/convo/42", "file:///im/convo/42", "0", "https://vk.ru/feed", "2147483648"):
            with self.assertRaises(ValueError):
                parse_dialog_link(value)

    def test_pagination_offset_author_merge_and_complete_history(self):
        status = Mock()
        call = Mock(side_effect=[{"count": 5, "items": [{"conversation_message_id": n} for n in (5, 4, 3)],
                                 "profiles": [{"id": 1}]},
                                {"count": 5, "items": [{"conversation_message_id": n} for n in (2, 1)],
                                 "groups": [{"id": 2}]}])
        result = collect_history(call, 42, status, pause=lambda delay: None)
        self.assertEqual(call.call_args_list[1].args, (42, 3))
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(result["profiles"], [{"id": 1}])
        self.assertEqual(result["groups"], [{"id": 2}])
        for responses in ([{"count": 3, "items": [{"conversation_message_id": 1}]}, {"count": 3, "items": []}],
                          [{"count": 3, "items": [{"conversation_message_id": 1}]}] * 2):
            with self.assertRaises(ValueError):
                collect_history(Mock(side_effect=responses), 42, status, pause=lambda delay: None)

    def test_jobs_survive_new_manager_prevent_duplicate_and_cancel(self):
        jobs = VkImportJobs(str(self.config))
        with patch("vk_import.subprocess.Popen", return_value=Mock(pid=123)), patch("vk_import.process_alive", return_value=True), patch("vk_import.BrowserBridge.status", return_value={"connected": True}):
            job = jobs.start("https://vk.ru/im/convo/42")
            fresh_manager = VkImportJobs(str(self.config))
            self.assertEqual(fresh_manager.latest()["id"], job)
            with self.assertRaises(RuntimeError):
                fresh_manager.start("https://vk.ru/im/convo/43")
            fresh_manager.cancel(job)
            self.assertTrue((jobs.directory(job) / "cancel").exists())
            with self.assertRaises(Cancelled):
                Status(jobs.directory(job), 42).check_cancel()
        with patch("vk_import.process_alive", return_value=False):
            self.assertEqual(jobs.status(job)["state"], "interrupted")
        with self.assertRaises(ValueError):
            jobs.directory("../../config.json")

    def worker_directory(self):
        directory = self.root / "Temp/VkImport" / ("a" * 32)
        directory.mkdir(parents=True)
        write_json(directory / "job.json", {"peer_id": 42})
        return directory

    def test_worker_saves_source_and_preserves_existing_export(self):
        directory = self.worker_directory()
        response = {"peer_id": 42, "currentDate": 1, "items": [{"conversation_message_id": 1}], "profiles": [], "groups": []}
        def pipeline(config, peers, logger):
            self.assertFalse(config.overwrite_existing_md)
            self.assertFalse(config.overwrite_existing_original_message_json)
            self.assertEqual(peers, {42})
            logger.LogWarning("Путь к MD-файлу превышает лимит https://cdn.test/private?sig=secret")
            for number in range(60):
                yield f"Сохранено сообщение {number}"
        with patch("vk_import_worker.bridge_history", return_value=response), patch("vk_import_worker.run_pipeline", side_effect=pipeline), patch.dict("os.environ", {}, clear=False):
            run_import(str(self.config), str(directory))
        source = self.root / "Archive/ExportMessages/Sources/messages_peerId_42_1.json"
        self.assertEqual(read_json(source), response)
        status = read_json(directory / "status.json")
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["warnings"], 1)
        self.assertEqual(len(status["lines"]), 40)
        self.assertEqual(status["warning_messages"], ["Путь к MD-файлу превышает лимит https://cdn.test/private?sig=secret"])
        self.assertNotIn("не удалось скачать", status["message"])
        self.assertIn("sig=secret", json.dumps(status))
        self.assertEqual(status["chat_url"], "/chat/42")

    def test_worker_errors_do_not_start_pipeline_and_cancellation_preserves_sources(self):
        directory = self.worker_directory()
        with patch("vk_import_worker.bridge_history", side_effect=ValueError("Нет доступа")), patch("vk_import_worker.run_pipeline") as pipeline:
            run_import(str(self.config), str(directory))
            pipeline.assert_not_called()
        self.assertEqual(read_json(directory / "status.json")["state"], "failed")
        self.assertFalse((self.root / "Archive").exists())
        (directory / "cancel").touch()
        with patch("vk_import_worker.bridge_history", return_value={}), patch("vk_import_worker.run_pipeline") as pipeline:
            run_import(str(self.config), str(directory))
            pipeline.assert_not_called()
        self.assertEqual(read_json(directory / "status.json")["state"], "cancelled")

    def test_complete_worker_pipeline_adds_new_message_and_keeps_previous_files(self):
        directory = self.worker_directory()
        dialog = self.root / "Archive/ExportMessages/Dialogs/dialog_42"
        (dialog / "MdFiles").mkdir(parents=True)
        previous = dialog / "MdFiles/Existing.Id1.md"
        previous.write_bytes(b"User-edited original message")
        media = dialog / "RawData/1/1.jpg"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"Existing photo")
        response = {"peer_id": 42, "currentDate": 2, "items": [
            {"conversation_message_id": 1, "text": "First", "date": 1},
            {"conversation_message_id": 2, "text": "New message", "date": 2}], "profiles": [], "groups": []}
        with patch("vk_import_worker.bridge_history", return_value=response), patch.dict("os.environ", {}, clear=False):
            run_import(str(self.config), str(directory))
        self.assertEqual(read_json(directory / "status.json")["state"], "complete")
        self.assertEqual(previous.read_bytes(), b"User-edited original message")
        self.assertEqual(media.read_bytes(), b"Existing photo")
        new_message = next((dialog / "MdFiles").glob("*.Id2.md"))
        self.assertIn("New message", new_message.read_text(encoding="utf-8"))
        self.assertEqual(len(list((dialog / "OriginalMessages").glob("*.json"))), 2)

    def test_routes_reject_cross_origin_and_bad_link(self):
        import web
        old_path = web._config_path
        web.load_configs(str(self.config))
        self.addCleanup(web.load_configs, old_path or str(run.root / "config.json"))
        with web.app.test_client() as client, patch("vk_import.subprocess.Popen") as process:
            self.assertEqual(client.post("/api/vk/import", json={"link": "https://vk.ru/im/convo/42"},
                             headers={"Origin": "https://foreign.test"}).status_code, 403)
            self.assertEqual(client.post("/api/vk/import", json={"link": "https://foreign.test"}).status_code, 400)
            self.assertEqual(client.get("/api/vk/import/not-a-job").status_code, 404)
            self.assertIsNone(client.get("/api/vk/import/latest").get_json())
            process.assert_not_called()

    def test_pairing_is_one_use_authenticated_and_expires(self):
        bridge = BrowserBridge(self.config)
        self.assertFalse(bridge.status()["connected"])
        nonce = bridge.create_pairing()
        with self.assertRaises(PermissionError):
            bridge.pair("wrong")
        token = bridge.pair(nonce)
        self.assertTrue(bridge.status()["connected"])
        self.assertNotIn(token, bridge.key_path.read_text())
        with self.assertRaises(PermissionError):
            bridge.pair(nonce)
        with self.assertRaises(PermissionError):
            bridge.authorize("wrong")
        bridge.authorize(token)
        data = read_json(bridge.key_path)
        data["last_seen"] = time.time() - 96
        write_json(bridge.key_path, data)
        self.assertFalse(bridge.status()["connected"])
        bridge.authorize(token)
        self.assertTrue(bridge.status()["connected"])
        nonce = bridge.create_pairing()
        with patch("vk_import.time.time", return_value=time.time() + 901), self.assertRaises(PermissionError):
            bridge.pair(nonce)

    def test_history_bridge_retries_login_and_collects_all_pages(self):
        directory = self.worker_directory()
        bridge = BrowserBridge(self.config)
        status = Status(directory, 42)
        status.publish()
        seen = []
        def browser_poll(_delay):
            command = bridge.pending()
            if not command:
                return
            seen.append(command["offset"])
            if len(seen) == 1:
                bridge.respond(dict(command, waiting_login=True))
            else:
                items = [{"conversation_message_id": n} for n in ((3, 2) if command["offset"] == 0 else (1,))]
                bridge.respond(dict(command, response={"count": 3, "items": items}))
        with patch("vk_import_worker.time.sleep", side_effect=browser_poll):
            result = bridge_history(directory, 42, status)
        self.assertEqual(seen, [0, 0, 2])
        self.assertEqual(len(result["items"]), 3)
        self.assertIsNone(bridge.pending())
        command = read_json(directory / "pending.json")
        with self.assertRaises(ValueError):
            bridge.respond(dict(command, command_id="b" * 32))
        (directory / "cancel").touch()
        with self.assertRaises(Cancelled):
            bridge_history(directory, 42, status)

    def test_bridge_http_requires_auth_and_cannot_answer_other_commands(self):
        import web
        old_path = web._config_path
        web.load_configs(str(self.config))
        self.addCleanup(web.load_configs, old_path or str(run.root / "config.json"))
        with web.app.test_client() as client, patch("web.open_browser", return_value=True) as browser:
            connect = client.post('/api/vk/browser/connect').get_json()
            browser.assert_not_called()
            self.assertFalse(connect['opened'])
            nonce = connect['url'].split('#')[1]
            self.assertEqual(client.get('/api/vk/bridge/pending').status_code, 403)
            self.assertEqual(client.post('/api/vk/bridge/pair', json={"nonce": "wrong"}).status_code, 403)
            token = client.post('/api/vk/bridge/pair', json={"nonce": nonce}).get_json()['token']
            headers = {"Authorization": "Bearer " + token}
            self.assertEqual(client.get('/api/vk/bridge/pending', headers=headers).get_json(), {"command": None})
            self.assertEqual(client.post('/api/vk/bridge/response', headers=headers, json={"job_id": [], "command_id": 123}).status_code, 409)
            self.assertEqual(client.post('/api/vk/bridge/response', headers=headers, json={"job_id": "a"*32, "command_id": "b"*32}).status_code, 409)
            self.assertNotIn(token, json.dumps(client.get('/api/vk/browser/status').get_json()))

    def test_start_without_connected_chrome_creates_no_job(self):
        jobs = VkImportJobs(self.config)
        with patch('vk_import.subprocess.Popen') as process, self.assertRaises(ValueError):
            jobs.start('https://vk.ru/im/convo/42')
        process.assert_not_called()
        self.assertFalse(list(jobs.root.glob('*/job.json')))

    def test_selected_browser_cannot_silently_export_from_another_browser(self):
        jobs = VkImportJobs(self.config)
        with patch('vk_import.BrowserBridge.status', return_value={'connected':True,'browser_id':'chrome','browser':'Google Chrome'}), patch('vk_import.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError, 'Google Chrome'):
                jobs.start('https://vk.ru/im/convo/42', browser_id='firefox')
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
