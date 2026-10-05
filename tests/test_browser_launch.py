import io
import json
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from browser_launch import open_browser
from vk_import import BrowserBridge, read_json


class BrowserTests(unittest.TestCase):
    def test_default_and_manual_never_force_chrome(self):
        url = 'http://127.0.0.1:8080/browser-connect#local-test'
        with patch('browser_launch.webbrowser.open', return_value=True) as default, patch('browser_launch.subprocess.Popen') as process:
            self.assertTrue(open_browser('default', url))
            default.assert_called_once_with(url, new=2)
            self.assertFalse(open_browser('manual', url))
            process.assert_not_called()

    def test_selected_browser_uses_normal_executable_and_missing_browser_returns_link(self):
        url = 'http://127.0.0.1:5000/browser-connect'
        for browser, flag in [('firefox', '-new-tab'), ('edge', '--new-tab'), ('brave', '--new-tab')]:
            with patch('browser_launch.browser_executable', return_value='browser.exe'), patch('browser_launch.subprocess.Popen') as process:
                self.assertTrue(open_browser(browser, url))
                self.assertEqual(process.call_args.args[0], ['browser.exe', flag, url])
        with patch('browser_launch.browser_executable', return_value=None), patch('browser_launch.subprocess.Popen') as process:
            self.assertFalse(open_browser('firefox', url))
            process.assert_not_called()
        with self.assertRaises(ValueError):
            open_browser('C:/arbitrary.exe', url)

    def test_connection_keeps_current_browser_and_port_and_rejects_invalid_identity(self):
        import web
        from tests.test_vk_import import ImportTests
        fixture = ImportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        old_path = web._config_path
        web.load_configs(str(fixture.config))
        self.addCleanup(web.load_configs, old_path or str(run.root / 'config.json'))
        with web.app.test_client() as client, patch('web.open_browser', return_value=False) as browser:
            response = client.post('/api/vk/browser/connect', base_url='http://127.0.0.1:8080', json={'browser': 'firefox'})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertFalse(data['opened'])
            self.assertTrue(data['url'].startswith('http://127.0.0.1:8080/browser-connect?browser=firefox#'))
            browser.assert_not_called()
            bridge = BrowserBridge(fixture.config)
            token = bridge.pair(data['url'].split('#')[1])
            self.assertEqual(bridge.status()['browser'], 'Mozilla Firefox')
            bridge.authorize(token)
            self.assertEqual(client.post('/api/vk/browser/connect', json={'browser': []}).status_code, 400)
            self.assertEqual(client.post('/api/vk/browser/connect', json={'browser': 'C:/arbitrary.exe'}).status_code, 400)

    def test_automatic_detection_script_is_served_and_no_selector_is_rendered(self):
        import web
        from tests.test_vk_import import ImportTests
        fixture = ImportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        old_path = web._config_path
        web.load_configs(str(fixture.config))
        self.addCleanup(web.load_configs, old_path or str(run.root / 'config.json'))
        with web.app.test_client() as client:
            page = client.get('/export')
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(b'vkBrowserChoice', page.data)
            self.assertIn(b'VkBrowser.detect(navigator)', page.data)
            script = client.get('/static/browser-detect.js')
            self.assertEqual(script.status_code, 200)
            self.assertIn(b'userAgentData', script.data)
            script.close()

    def test_browser_packages_have_correct_manifests_and_shared_logic(self):
        import web
        with web.app.test_client() as client:
            for family in ('chromium', 'firefox'):
                response = client.get('/browser-helper/' + family + '.zip')
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.data)) as package:
                    self.assertEqual(set(package.namelist()), {'manifest.json', 'background.js', 'connect.js'})
                    manifest = json.loads(package.read('manifest.json'))
                    self.assertEqual(manifest['manifest_version'], 3)
                    if family == 'firefox':
                        self.assertNotIn('service_worker', manifest['background'])
                        self.assertEqual(manifest['background']['scripts'], ['background.js'])
                        self.assertEqual(manifest['browser_specific_settings']['gecko']['strict_min_version'], '128.0')
                    else:
                        self.assertEqual(manifest['background']['service_worker'], 'background.js')
                    self.assertEqual(package.read('background.js'), (run.root / 'BrowserExtension/background.js').read_bytes())
            self.assertEqual(client.get('/browser-helper/unknown.zip').status_code, 404)
            self.assertEqual(client.get('/browser-connect?browser=unknown').status_code, 400)


if __name__ == '__main__':
    unittest.main()
