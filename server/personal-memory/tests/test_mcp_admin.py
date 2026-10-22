import importlib.util
import json
import tempfile
import threading
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))


class AdminTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'vendor/mcp_admin.py'
        self.assertTrue(path.is_file(), 'MCP management API is not implemented')
        spec = importlib.util.spec_from_file_location('admin_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.module = module
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'logs').mkdir()
        self.calls = []
        self.process = {'running': True, 'verified': True, 'process_id': 123, 'tcp_connected': True, 'started_utc': '2026-10-17T00:00:00Z'}
        def runner(action):
            self.calls.append(action)
            if action == 'Stop': self.process['running'] = False
            elif action in ('Start', 'Restart'): self.process['running'] = True
            return dict(self.process)
        self.controller = module.Controller(self.root, runner=runner)
        self.server = module.create_admin_server(self.controller, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def event(self, value):
        with (self.root / 'logs/events.jsonl').open('a', encoding='utf-8') as f: f.write(json.dumps(value) + '\n')

    def session(self):
        with urlopen(self.base + '/api/session') as r:
            return json.load(r)['csrf'], r.headers['Set-Cookie'].split(';')[0]

    def post(self, data, headers=None):
        request = Request(self.base + '/api/command', json.dumps(data).encode(), {'Content-Type': 'application/json', **(headers or {})}, method='POST')
        return urlopen(request)

    def valid_headers(self):
        csrf, cookie = self.session()
        return {'Origin': self.base, 'Cookie': cookie, 'X-CSRF-Token': csrf}

    def test_stopped_or_unverified_process_cannot_show_old_connection_as_live(self):
        self.event({'kind': 'connected', 'at': '2026-10-17T01:00:00Z'})
        self.event({'kind': 'tools', 'at': '2026-10-17T01:00:01Z', 'tools': ['archive_get']})
        self.process['running'] = False
        self.assertEqual(self.controller.status()['connection'], 'stopped')
        self.process.update(running=True, verified=False)
        self.assertFalse(self.controller.status()['running'])

    def test_connection_requires_live_tcp_and_history_is_redacted(self):
        self.event({'kind': 'connected', 'at': '2026-10-17T01:00:00Z'})
        self.event({'kind': 'call_finished', 'at': '2026-10-17T01:00:01Z', 'call_id': 'a', 'tool': 'archive_search', 'status': 'success', 'duration_ms': 12, 'arguments': 'SECRET', 'endpoint': 'SECRET'})
        state = self.controller.status()
        self.assertEqual(state['connection'], 'connected')
        self.assertEqual(state['calls'][0]['tool'], 'archive_search')
        self.assertNotIn('SECRET', json.dumps(state))
        self.process['tcp_connected'] = False
        self.assertNotEqual(self.controller.status()['connection'], 'connected')

    def test_post_requires_session_csrf_and_same_origin(self):
        with self.assertRaises(HTTPError) as error: self.post({'action': 'stop'})
        self.assertEqual(error.exception.code, 403)
        headers = self.valid_headers(); headers['Origin'] = 'https://evil.invalid'
        with self.assertRaises(HTTPError) as error: self.post({'action': 'stop'}, headers)
        self.assertEqual(error.exception.code, 403)
        self.assertNotIn('Stop', self.calls)

    def test_fixed_action_executes_and_status_remains_available_after_stop(self):
        with self.post({'action': 'stop'}, self.valid_headers()) as r: self.assertFalse(json.load(r)['running'])
        with urlopen(self.base + '/api/status') as r: self.assertFalse(json.load(r)['running'])
        self.assertIn('Stop', self.calls)

    def test_arbitrary_commands_extra_arguments_and_get_mutations_are_rejected(self):
        for payload in [{'action': 'whoami'}, {'action': 'stop', 'command': 'whoami'}]:
            with self.assertRaises(HTTPError) as error: self.post(payload, self.valid_headers())
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError): urlopen(self.base + '/api/command?action=stop')
        self.assertNotIn('Stop', self.calls)

    def test_wrong_host_and_oversized_body_do_not_run_commands(self):
        with self.assertRaises(HTTPError) as error: urlopen(Request(self.base + '/api/status', headers={'Host': 'evil.invalid'}))
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error: self.post({'action': 'x' * 5000}, self.valid_headers())
        self.assertEqual(error.exception.code, 413)

    def test_background_child_inheriting_stdout_does_not_hold_admin_response(self):
        original_run = subprocess.run
        parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)']); print('{\"running\":true,\"verified\":true}',flush=True)"
        def run_parent(_args, **kwargs):
            return original_run([sys.executable, '-c', parent], **kwargs)
        controller = self.module.Controller(self.root)
        started = time.monotonic()
        with patch.object(self.module.shutil, 'which', return_value=sys.executable), patch.object(self.module.subprocess, 'run', side_effect=run_parent):
            self.assertTrue(controller._run('Status')['running'])
        self.assertLess(time.monotonic() - started, 2, 'Background stdout handle kept the management response open')

    def test_checkpoint_preserves_current_session_after_history_rotates(self):
        checkpoint = {'lifecycle': 'connected', 'lifecycle_at': '2026-10-17T01:00:00Z',
                      'session': 'current', 'tools': ['archive_get'], 'tools_at': '2026-10-17T01:00:01Z'}
        (self.root / 'logs/events.state.json').write_text(json.dumps(checkpoint), encoding='utf-8')
        self.event({'kind': 'call_started', 'at': '2026-10-17T02:00:00Z', 'session': 'current',
                    'call_id': 'a', 'tool': 'archive_get'})
        state = self.controller.status()
        self.assertEqual(state['connection'], 'connected')
        self.assertEqual(state['tool_count'], 1)
        self.assertEqual(state['calls'][0]['status'], 'running')

    def test_package_switch_persists_and_refreshes_cloud_only_when_running(self):
        self.assertTrue(hasattr(self.controller, 'set_package'), 'Package management is not implemented')
        state = self.controller.set_package('planner', False)
        self.assertFalse(next(item for item in state['packages'] if item['id'] == 'planner')['enabled'])
        self.assertIn('Restart', self.calls)
        self.calls.clear()
        self.process['running'] = False
        self.controller.set_package('archive', False)
        self.assertNotIn('Restart', self.calls)

    def test_package_endpoint_requires_csrf_and_validates_fixed_schema(self):
        url = self.base + '/api/packages'
        def post(payload, headers):
            return urlopen(Request(url, json.dumps(payload).encode(),
                {'Content-Type': 'application/json', **headers}, method='POST'))
        with self.assertRaises(HTTPError) as error: post({'package': 'planner', 'enabled': False}, {})
        self.assertEqual(error.exception.code, 403)
        for payload in [{'package': 'shell', 'enabled': True}, {'package': 'planner', 'enabled': 'false'},
                        {'package': 'planner', 'enabled': False, 'command': 'whoami'}]:
            with self.assertRaises(HTTPError) as error: post(payload, self.valid_headers())
            self.assertEqual(error.exception.code, 400)
        with post({'package': 'planner', 'enabled': False}, self.valid_headers()) as response:
            self.assertIn('packages', json.load(response))

    def test_same_package_target_can_retry_failed_cloud_refresh(self):
        original = self.controller.runner
        restarts = []
        def runner(action):
            if action == 'Restart':
                restarts.append(action)
                if len(restarts) == 1: raise RuntimeError('temporary restart failure')
            return original(action)
        self.controller.runner = runner
        with self.assertRaises(RuntimeError): self.controller.set_package('planner', False)
        state = self.controller.set_package('planner', False)
        self.assertEqual(len(restarts), 2)
        self.assertFalse(next(item for item in state['packages'] if item['id'] == 'planner')['enabled'])

    def test_catalog_and_install_job_are_real_async_operations_with_fixed_input(self):
        with urlopen(self.base + '/api/catalog') as response:
            self.assertEqual(len(json.load(response)['items']), 3)
        self.assertTrue(hasattr(self.controller, 'install_package'), 'Marketplace installation API is missing')
        entered, release = threading.Event(), threading.Event()
        def install(ident, progress=None):
            entered.set()
            if not release.wait(3): raise RuntimeError('test timeout')
        self.controller.market.install = install
        try:
            state = self.controller.install_package('worldtime')
            self.assertTrue(entered.wait(1))
            self.assertTrue(state['busy'])
            self.assertEqual(state['installation']['state'], 'running')
            with self.assertRaises(self.module.BusyError): self.controller.command('restart')
        finally:
            release.set()
        for _ in range(100):
            if not self.controller.lock.locked(): break
            time.sleep(.01)
        self.assertFalse(self.controller.lock.locked())

    def test_marketplace_mutations_reject_missing_auth_and_unknown_input(self):
        for path in ('install', 'remove'):
            def post(value, headers):
                return urlopen(Request(self.base + '/api/' + path, json.dumps(value).encode(),
                    {'Content-Type': 'application/json', **headers}, method='POST'))
            with self.assertRaises(HTTPError) as error: post({'package': 'worldtime'}, {})
            self.assertEqual(error.exception.code, 403)
            for value in [{'package': '../shell'}, {'package': 'worldtime', 'command': 'whoami'}]:
                with self.assertRaises(HTTPError) as error: post(value, self.valid_headers())
                self.assertEqual(error.exception.code, 400)

    def test_remove_reports_failed_bridge_restart(self):
        original = self.controller.runner
        def runner(action):
            if action == 'Restart': return {'running': False, 'verified': False}
            return original(action)
        self.controller.runner = runner
        with self.assertRaises(RuntimeError): self.controller.remove_package('worldtime')


if __name__ == '__main__':
    unittest.main()
