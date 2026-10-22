import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

BASE = Path(__file__).resolve().parents[1]


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('local_onboarding', BASE / 'local/onboarding.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'app').mkdir()
        (self.root / 'app/.env').write_text('MCP_ENDPOINT=\nPLANNER_DEVICE_TOKEN=keep-this-private\n', encoding='utf-8')
        self.actions = []
        owner = self
        class Controller:
            def command(self, action): owner.actions.append(action)
        self.setup = module.Setup(self.root, Controller(), client_config=lambda kind: 'client-config-' + kind)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self): owner.setup.handle(self)
            do_POST = do_GET
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def session(self):
        status, headers, body = self.request('GET', '/setup/')
        self.assertEqual(status, 200)
        import re
        token = re.search(rb'name="csrf" value="([A-Za-z0-9_-]+)"', body).group(1).decode()
        return token, headers['Set-Cookie'].split(';', 1)[0]

    def save(self, **values):
        token, cookie = self.session()
        return self.request('POST', '/setup/save', urlencode({'csrf': token, **values}),
            {'Cookie': cookie, 'Origin': 'http://' + self.host,
             'Content-Type': 'application/x-www-form-urlencoded'})

    def test_no_secret_is_returned_or_prefilled(self):
        (self.root / 'app/.env').write_text('MCP_ENDPOINT=wss://example.test/mcp?token=secret-endpoint\n', encoding='utf-8')
        status, _, body = self.request('GET', '/setup/')
        self.assertEqual(status, 200)
        self.assertNotIn(b'secret-endpoint', body)
        self.assertIn('已配置'.encode(), body)
        self.assertIn(b'client-config-json', body)

    def test_xiaozhi_guide_explains_console_steps_and_complete_connection_address(self):
        status, _, body = self.request('GET', '/setup/')
        self.assertEqual(status, 200)
        text = body.decode('utf-8')
        for phrase in ('https://xiaozhi.me/', '智能体', '配置角色', 'MCP 接入点', '完整', 'wss://', '不是看板地址'):
            self.assertIn(phrase, text)

    def test_save_requires_origin_and_csrf(self):
        before = (self.root / 'app/.env').read_bytes()
        status, _, _ = self.request('POST', '/setup/save', 'endpoint=wss://example.test')
        self.assertEqual(status, 403)
        self.assertEqual((self.root / 'app/.env').read_bytes(), before)

    def test_form_policy_preserves_same_origin_posts_without_external_referrers(self):
        status, headers, _ = self.request('GET', '/setup/')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Referrer-Policy'], 'same-origin')

    def test_valid_session_still_rejects_null_and_foreign_origins(self):
        before = (self.root / 'app/.env').read_bytes()
        for origin in ('null', 'http://foreign.invalid', 'http://localhost:1'):
            with self.subTest(origin=origin):
                token, cookie = self.session()
                status, _, _ = self.request('POST', '/setup/save',
                    urlencode({'csrf': token, 'endpoint': 'wss://example.test/mcp'}),
                    {'Cookie': cookie, 'Origin': origin,
                     'Content-Type': 'application/x-www-form-urlencoded'})
                self.assertEqual(status, 403)
        self.assertEqual((self.root / 'app/.env').read_bytes(), before)
        self.assertEqual(self.actions, [])

    def test_save_cloud_preserves_other_configuration_and_restarts(self):
        status, _, _ = self.save(endpoint='wss://example.test/mcp?token=new-token')
        self.assertEqual(status, 303)
        from dotenv import dotenv_values
        config = dotenv_values(self.root / 'app/.env')
        self.assertEqual(config['MCP_ENDPOINT'], 'wss://example.test/mcp?token=new-token')
        self.assertEqual(config['PLANNER_DEVICE_TOKEN'], 'keep-this-private')
        self.assertEqual(self.actions, ['restart'])

    def test_blank_endpoint_does_not_erase_saved_value(self):
        self.save(endpoint='wss://example.test/mcp?token=original')
        self.actions.clear()
        self.assertEqual(self.save(endpoint='')[0], 303)
        self.assertIn('original', (self.root / 'app/.env').read_text())
        self.assertEqual(self.actions, [])

    def test_disabling_cloud_stops_only_bridge(self):
        self.save(endpoint='wss://example.test/mcp')
        self.actions.clear()
        self.assertEqual(self.save(disable='1')[0], 303)
        from dotenv import dotenv_values
        self.assertEqual(dotenv_values(self.root / 'app/.env')['MCP_ENDPOINT'], '')
        self.assertEqual(self.actions, ['stop'])

    def test_rejects_insecure_or_malformed_endpoint(self):
        for endpoint in ('http://example.test', 'ws://example.test', 'wss://u:p@example.test',
                         'wss://example.test/\nINJECT=1', 'wss://example.test/#fragment'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.save(endpoint=endpoint)[0], 400)
        self.assertEqual(self.actions, [])

    def test_rejects_foreign_host(self):
        self.assertEqual(self.request('GET', '/setup/', headers={'Host': 'evil.example'})[0], 403)

    def test_downloaded_client_config_has_no_secret(self):
        status, headers, body = self.request('GET', '/setup/clients/claude.json')
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertEqual(body, b'client-config-json')
        self.assertNotIn(b'keep-this-private', body)


if __name__ == '__main__': unittest.main()
