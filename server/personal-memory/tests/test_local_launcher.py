"""Portable lifecycle acceptance against isolated, dependency-free fake applications."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'local/launcher.py'
if not SOURCE.is_file():
    SOURCE = Path(__file__).resolve().parents[1] / 'launcher.py'


def load_launcher():
    spec = importlib.util.spec_from_file_location('portable_launcher', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class PortableLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='portable launcher 中文 ')
        self.root = Path(self.temp.name).resolve()
        (self.root / 'app').mkdir()
        self.assertTrue(SOURCE.is_file(), 'Portable launcher implementation is missing')
        self.launcher = load_launcher()
        self.runtime = self.launcher.Runtime(self.root, python=sys.executable)

    def tearDown(self):
        self.runtime.stop()
        self.temp.cleanup()

    def test_first_run_preserves_existing_configuration_and_state(self):
        self.runtime.ensure_config()
        envfile = self.root / 'app/.env'
        self.assertIn('MCP_ENDPOINT=', envfile.read_text(encoding='utf-8'))
        self.assertIn('PLANNER_OWNER=device', envfile.read_text(encoding='utf-8'))
        envfile.write_text('MCP_ENDPOINT=wss://private.invalid/?token=secret\n', encoding='utf-8')
        database = self.root / 'state/data/sentinel'
        database.parent.mkdir(parents=True, exist_ok=True)
        database.write_text('keep me')
        self.runtime.ensure_config()
        self.assertIn('secret', envfile.read_text(encoding='utf-8'))
        self.assertEqual(database.read_text(), 'keep me')

    def test_environment_is_local_even_with_inherited_private_configuration(self):
        with patch.dict(os.environ, {'PERSONAL_ARCHIVE_HOME': '/private',
                        'MCP_ENDPOINT': 'wss://private.invalid/token',
                        'PLANNER_OWNER': 'pc', 'DEVICE_GATEWAY_HOST': '0.0.0.0'}):
            env = self.runtime.environment()
        self.assertEqual(env['PERSONAL_ARCHIVE_HOME'], str(self.root / 'state'))
        self.assertEqual(env['PLANNER_OWNER'], 'device')
        self.assertFalse(env.get('MCP_ENDPOINT'))
        self.assertFalse(env.get('DEVICE_GATEWAY_HOST'))
        self.assertEqual(env['MCP_EVENT_LOG'], str(self.root / 'logs/events.jsonl'))

    def test_stdio_emits_only_child_protocol_and_shares_local_state(self):
        (self.root / 'app/mcp_server.py').write_text(
            "import json, os\nprint(json.dumps({'archive': os.environ['PERSONAL_ARCHIVE_HOME'], "
            "'planner': os.environ['PLANNER_OWNER'], 'cloud': os.environ.get('MCP_ENDPOINT', '')}))\n",
            encoding='utf-8')
        result = subprocess.run([sys.executable, '-X', 'utf8', str(SOURCE), '--root',
                                 str(self.root), 'stdio'], capture_output=True, text=True,
                                encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value, {'archive': str(self.root / 'state'), 'planner': 'device', 'cloud': ''})

    def test_client_configuration_contains_absolute_paths_and_no_credentials(self):
        self.runtime.ensure_config()
        (self.root / 'app/.env').write_text('MCP_ENDPOINT=wss://private.invalid/?token=secret\n')
        value = self.runtime.client_config('json')
        entry = json.loads(value)['mcpServers']['evomyn']
        self.assertTrue(Path(entry['command']).is_absolute())
        self.assertIn('stdio', entry['args'])
        self.assertIn(str(self.root), entry['args'])
        self.assertNotIn('secret', value)
        self.assertNotIn('MCP_ENDPOINT', value)
        import tomllib
        parsed = tomllib.loads(self.runtime.client_config('toml'))
        self.assertIn('evomyn', parsed['mcp_servers'])

    def fake_dashboard(self):
        ports = [free_port() for _ in range(3)]
        (self.root / 'app/.env').write_text(
            f'DASHBOARD_PORT={ports[0]}\nARCHIVE_PORT={ports[1]}\nADMIN_PORT={ports[2]}\n', encoding='utf-8')
        (self.root / 'dashboard.py').write_text(
            "from http.server import BaseHTTPRequestHandler, HTTPServer\nimport os,json\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n  self.send_response(200); self.end_headers(); "
            "self.wfile.write(json.dumps({'ok': True, 'pid': os.getpid(), "
            "'instance': 'wrong' if os.environ.get('BAD_INSTANCE') else "
            "os.environ.get('MCP_LAUNCH_INSTANCE', ''), 'service': "
            "'wrong' if os.environ.get('BAD_HEALTH') else 'personal-memory-mcp'}).encode())\n"
            " def log_message(self, *args): pass\n"
            "HTTPServer(('127.0.0.1', int(os.environ['DASHBOARD_PORT'])), Handler).serve_forever()\n", encoding='utf-8')
        return ports

    def test_start_reuses_owned_process_and_stop_preserves_config(self):
        self.fake_dashboard()
        first = self.runtime.start(open_browser=False)
        second = self.runtime.start(open_browser=False)
        self.assertTrue(first['dashboard']['running'])
        self.assertEqual(first['dashboard']['process_id'], second['dashboard']['process_id'])
        self.assertFalse(first['bridge']['running'])
        self.runtime.stop()
        self.assertFalse(self.runtime.status()['dashboard']['running'])
        self.assertTrue((self.root / 'app/.env').is_file())

    def test_configure_no_browser_starts_dashboard_without_opening_page(self):
        self.fake_dashboard()
        with patch.object(self.launcher.webbrowser, 'open') as browser, patch('sys.stdout'):
            result = self.launcher.main(['--root', str(self.root), 'configure', '--no-browser'])
        self.assertEqual(result, 0)
        browser.assert_not_called()
        self.assertTrue(self.runtime.status()['dashboard']['running'])

    def test_configure_opens_setup_page_by_default(self):
        ports = self.fake_dashboard()
        with patch.object(self.launcher.webbrowser, 'open') as browser, patch('sys.stdout'):
            result = self.launcher.main(['--root', str(self.root), 'configure'])
        self.assertEqual(result, 0)
        browser.assert_called_once_with(f'http://127.0.0.1:{ports[0]}/setup/')
        self.assertTrue(self.runtime.status()['dashboard']['running'])

    @unittest.skipUnless(os.name == 'nt', 'Windows stdlib venv redirector regression')
    def test_actual_venv_start_accepts_serving_child_and_stops_whole_tree(self):
        self.fake_dashboard()
        with (self.root / 'app/.env').open('a') as stream:
            stream.write('MCP_LAUNCH_INSTANCE=untrusted-config-value\n')
        created = subprocess.run([sys.executable, '-m', 'venv', '--without-pip',
                                  str(self.root / '.venv')], capture_output=True, timeout=45)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.runtime = self.launcher.Runtime(self.root)
        first = self.runtime.start(open_browser=False)
        owned_pid = first['dashboard']['process_id']
        from urllib.request import urlopen
        env = self.runtime.environment()
        with urlopen(f"http://127.0.0.1:{env['DASHBOARD_PORT']}/healthz") as response:
            health = json.load(response)
        self.assertNotEqual(health['pid'], owned_pid, 'Fixture must exercise Windows venv redirector')
        self.assertTrue(health['instance'])
        self.assertNotEqual(health['instance'], 'untrusted-config-value')
        self.assertEqual(self.runtime.start(open_browser=False)['dashboard']['process_id'], owned_pid)
        self.runtime.stop()
        self.assertIsNone(self.launcher.process_identity(owned_pid))
        self.assertIsNone(self.launcher.process_identity(health['pid']))

    def test_occupied_port_fails_without_claiming_or_killing_listener(self):
        ports = self.fake_dashboard()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', ports[0]))
            listener.listen()
            with self.assertRaisesRegex(self.launcher.LauncherError, 'port'):
                self.runtime.start(open_browser=False)
            self.assertFalse(self.runtime.status()['dashboard']['running'])
            self.runtime.stop()
            self.assertEqual(listener.getsockname()[1], ports[0])

    def test_forged_and_reused_pid_records_never_own_an_unrelated_process(self):
        self.runtime.ensure_config()
        record = self.launcher.process_identity(os.getpid())
        record['command'] = 'forged command'
        record.update(role='dashboard', root=str(self.root), instance='forged-instance')
        self.runtime.records_path.write_text(json.dumps({'dashboard': record}))
        self.assertFalse(self.runtime.status()['dashboard']['verified'])
        self.runtime.stop()
        self.assertIsNotNone(self.launcher.process_identity(os.getpid()))

    def test_stale_creation_time_does_not_match_even_when_pid_and_command_match(self):
        self.fake_dashboard()
        self.runtime.start(open_browser=False)
        original = self.runtime.records_path.read_text(encoding='utf-8')
        try:
            for field in ('created', 'executable', 'command'):
                records = json.loads(original)
                records['dashboard'][field] = 'stale'
                self.runtime.records_path.write_text(json.dumps(records), encoding='utf-8')
                self.assertFalse(self.runtime.status()['dashboard']['running'], field)
                self.runtime.stop()
                self.assertIsNotNone(self.launcher.process_identity(json.loads(original)['dashboard']['pid']))
        finally:
            self.runtime.records_path.write_text(original, encoding='utf-8')

    def test_invalid_config_errors_do_not_disclose_secret(self):
        self.runtime.ensure_config()
        (self.root / 'app/.env').write_text('DASHBOARD_PORT=private-secret\n')
        with self.assertRaisesRegex(self.launcher.LauncherError, 'DASHBOARD_PORT') as caught:
            self.runtime.start(open_browser=False)
        self.assertNotIn('private-secret', str(caught.exception))

    def test_bridge_compatibility_commands_do_not_start_dashboard(self):
        self.runtime.ensure_config()
        (self.root / 'app/.env').write_text('MCP_ENDPOINT=wss://example.invalid/test\n')
        (self.root / 'app/mcp_pipe.py').write_text('import time\ntime.sleep(90)\n')
        result = self.runtime.bridge_start()
        self.assertTrue(result['running'])
        self.assertTrue(result['verified'])
        self.assertIn('tcp_connected', result)
        self.assertFalse(self.runtime.status()['dashboard']['running'])
        self.assertEqual(self.runtime.bridge_start()['process_id'], result['process_id'])
        self.runtime.stop(bridge_only=True)
        self.assertFalse(self.runtime.status(bridge_only=True)['running'])

    def test_concurrent_start_clicks_create_only_one_dashboard(self):
        from concurrent.futures import ThreadPoolExecutor
        self.fake_dashboard()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.runtime.start(open_browser=False), range(2)))
        self.assertEqual(results[0]['dashboard']['process_id'], results[1]['dashboard']['process_id'])

    def test_stdio_accepts_input_and_preserves_child_exit_code(self):
        (self.root / 'app/mcp_server.py').write_text(
            "import sys\nfor line in sys.stdin:\n print(line.strip(), flush=True)\nsys.exit(7)\n", encoding='utf-8')
        result = subprocess.run([sys.executable, '-X', 'utf8', str(SOURCE), '--root',
                                 str(self.root), 'stdio'], input='{"jsonrpc":"2.0"}\n',
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), '{"jsonrpc":"2.0"}')

    def test_bootstrap_supports_hash_cache_and_local_execution_policy(self):
        bootstrap = SOURCE.with_name('bootstrap.ps1')
        self.assertTrue(bootstrap.is_file(), 'Portable PowerShell bootstrap is missing')
        value = bootstrap.read_text(encoding='utf-8-sig')
        self.assertIn('Get-FileHash', value)
        self.assertIn('requirements', value)
        self.assertNotIn('Set-ExecutionPolicy', value)
        self.assertIn('UV_NO_MODIFY_PATH', value)
        for name in ('Start.cmd', 'Stop.cmd', 'Configure.cmd'):
            self.assertTrue(SOURCE.with_name(name).is_file(), name)

    def test_readiness_rejects_wrong_service_without_opening_browser(self):
        self.fake_dashboard()
        with (self.root / 'app/.env').open('a') as stream:
            stream.write('BAD_HEALTH=1\n')
        with patch.object(self.launcher.webbrowser, 'open') as browser:
            with self.assertRaises(self.launcher.LauncherError):
                self.runtime.start()
        browser.assert_not_called()

    def test_readiness_rejects_wrong_instance_without_opening_browser(self):
        self.fake_dashboard()
        with (self.root / 'app/.env').open('a') as stream:
            stream.write('BAD_INSTANCE=1\n')
        with patch.object(self.launcher.webbrowser, 'open') as browser:
            with self.assertRaises(self.launcher.LauncherError):
                self.runtime.start()
        browser.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell bootstrap')
    def test_real_bootstrap_installs_local_venv_once_and_manager_returns_json(self):
        for name in ('launcher.py', 'bootstrap.ps1', 'manage.ps1'):
            shutil.copy2(SOURCE.with_name(name), self.root / name)
        (self.root / 'requirements.txt').write_text('# Empty dependency fixture\n')
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(self.root / 'bootstrap.ps1'), '-Action', 'client-config']
        first = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=90)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        marker = self.root / '.venv/requirements.sha256'
        self.assertTrue(marker.is_file())
        modified = marker.stat().st_mtime_ns
        second_command = [*command[:-1], 'Client-Config']
        second = subprocess.run(second_command, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(marker.stat().st_mtime_ns, modified)
        self.assertTrue(Path(json.loads(second.stdout)['mcpServers']['evomyn']['command']).is_file())
        managed = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                  '-File', str(self.root / 'manage.ps1'), 'Status', '-Json'],
                                 capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(managed.returncode, 0, managed.stderr)
        self.assertFalse(json.loads(managed.stdout)['running'])

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree ownership')
    def test_stop_terminates_owned_bridge_children_and_preserves_unrelated_process(self):
        import time
        self.runtime.ensure_config()
        (self.root / 'app/.env').write_text('MCP_ENDPOINT=wss://example.invalid/test\n')
        (self.root / 'app/mcp_pipe.py').write_text(
            "import subprocess,sys,os,time\nfrom pathlib import Path\n"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'], "
            "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
            "(Path(os.environ['PERSONAL_ARCHIVE_HOME'])/'bridge-child.pid').write_text(str(child.pid))\n"
            "time.sleep(90)\n", encoding='utf-8')
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(90)'],
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            self.runtime.bridge_start()
            pidfile = self.root / 'state/bridge-child.pid'
            deadline = time.monotonic() + 10
            while not pidfile.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            child_pid = int(pidfile.read_text())
            self.assertIsNotNone(self.launcher.process_identity(child_pid))
            self.runtime.stop()
            self.assertIsNone(self.launcher.process_identity(child_pid))
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=10)

    @unittest.skipUnless(os.name == 'nt', 'Windows TCP status compatibility')
    def test_bridge_status_reports_actual_tcp_connection(self):
        self.runtime.ensure_config()
        created = subprocess.run([sys.executable, '-m', 'venv', '--without-pip',
                                  str(self.root / '.venv')], capture_output=True, timeout=45)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.runtime = self.launcher.Runtime(self.root)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            (self.root / 'app/.env').write_text('MCP_ENDPOINT=wss://example.invalid/test\n')
            (self.root / 'app/mcp_pipe.py').write_text(
                f"import socket,time\ns=socket.create_connection(('127.0.0.1',{port}))\ntime.sleep(90)\n")
            self.runtime.bridge_start()
            listener.settimeout(10)
            accepted, _ = listener.accept()
            try:
                self.assertTrue(self.runtime.status(bridge_only=True)['tcp_connected'])
            finally:
                accepted.close()


if __name__ == '__main__':
    unittest.main()
