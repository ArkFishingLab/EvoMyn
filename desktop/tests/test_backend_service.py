"""Exercise the desktop gate against reviewed source and temporary user data."""
import asyncio
from contextlib import closing
import importlib.util
import json
import os
import queue
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'desktop/backend'


def fixture(destination):
    spec = importlib.util.spec_from_file_location('public_release_fixture', ROOT / 'tools/package_public_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for source, name in module.PUBLIC_FILES.items():
        if name.startswith(('tests/', 'viewer/tests/', 'tools/')):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target)


def alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class DesktopBackend(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop 测试 ')
        self.base = Path(self.temp.name)
        self.app = self.base / 'reviewed application'
        fixture(self.app)
        self.data = self.base / '个人 记忆'
        self.env = {**os.environ, 'MNEMOSYNE_NO_EMBEDDINGS': '1', 'PYTHONUTF8': '1'}
        self.launch()
        self.counter = 0

    def launch(self):
        self.process = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', str(BACKEND / 'service.py'),
            '--app-dir', str(self.app), '--data-root', str(self.data)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=self.env)

    def command(self, command, **parameters):
        self.counter += 1
        self.process.stdin.write(json.dumps({'id': self.counter, 'command': command, **parameters}) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.assertTrue(line, 'Service stopped before replying')
        value = json.loads(line)
        self.assertEqual(value['id'], self.counter)
        self.assertTrue(value['ok'], value)
        return value['result']

    def tearDown(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        error = self.process.stderr.read()
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()
        self.temp.cleanup()
        if self.process.returncode and not getattr(self, 'expected_killed', False):
            self.fail('Service exit failed: ' + error[-2000:])

    def test_defaults_dashboard_config_and_cloud_cannot_bypass_closed_master(self):
        status = self.command('status')
        self.assertTrue(status['ready'])
        self.assertTrue(status['mcp_enabled'])
        self.assertFalse(status['cloud_enabled'])
        self.assertEqual(status['data_root'], str(self.data.resolve()))
        with urlopen(status['dashboard_url']) as response:
            self.assertEqual(response.status, 200)
        # The visible archive needs both endpoints, including attribution metadata.
        for tail in ('api/records', 'api/dashboard'):
            with urlopen(status['dashboard_url'] + tail) as response:
                self.assertEqual(response.status, 200)
                payload = json.load(response)
                self.assertIsInstance(payload, dict)
        with urlopen(status['capabilities_url'] + 'api/status') as response:
            capabilities = json.load(response)
            self.assertTrue(capabilities.get('desktop_managed'))
        config = self.command('client-config', format='json')
        entry = json.loads(config)['mcpServers']['evomyn']
        self.assertIn(str(BACKEND / 'client.py'), entry['args'])
        self.assertEqual(entry['args'][:4], ['-E', '-s', '-X', 'utf8'])
        self.assertNotIn('token', config.lower())
        self.command('stop-mcp')
        self.command('set-cloud', enabled=True)
        status = self.command('status')
        self.assertFalse(status['mcp_enabled'])
        self.assertTrue(status['cloud_enabled'])
        self.assertFalse(status['cloud_connected'])
        with urlopen(status['setup_url']) as response:
            self.assertEqual(response.status, 200)
        self.command('save-endpoint', endpoint='wss://cloud.invalid/mcp?token=isolated-fixture-key')
        self.assertTrue(self.command('status')['cloud_configured'])
        self.assertNotIn('isolated-fixture-key', json.dumps(self.command('status')))
        self.assertFalse(self.command('status')['cloud_connected'])
        self.command('shutdown')
        self.process.wait(timeout=20)
        self.assertFalse((self.data / 'desktop-session.json').exists())
        settings = json.loads((self.data / 'desktop-settings.json').read_text('utf-8'))
        self.assertEqual(settings, {'mcp_enabled': False, 'cloud_enabled': True})

    def test_existing_official_stdio_session_is_blocked_and_can_resume(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        self.command('status')
        async def exercise():
            params = StdioServerParameters(command=sys.executable,
                args=['-X', 'utf8', str(BACKEND / 'client.py'), '--data-root', str(self.data)], env=self.env)
            with open(os.devnull, 'w') as errors:
                async with stdio_client(params, errlog=errors) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        self.assertIn('archive_status', [tool.name for tool in (await session.list_tools()).tools])
                        result = await session.call_tool('archive_record', {'category': 'journal',
                            'title': '隔离测试', 'body': 'Only temporary test data.'})
                        self.assertFalse(result.is_error, result)
                        self.command('stop-mcp')
                        blocked = await session.call_tool('archive_record', {'category': 'journal',
                            'title': 'blocked', 'body': 'Must never be stored.'})
                        self.assertTrue(blocked.is_error)
                        self.assertEqual((await session.list_tools()).tools, [])
                        self.command('start-mcp')
                        result = await session.call_tool('archive_list', {})
                        self.assertFalse(result.is_error, result)
                        self.assertIn('隔离测试', str(result))
                        self.assertNotIn('Must never be stored', str(result))
                        self.command('stop-mcp')
                        (self.data / 'mcp-packages.json').write_text(
                            json.dumps({'archive': False, 'planner': False}), 'utf-8')
                        self.command('start-mcp')
                        self.assertEqual((await session.list_tools()).tools, [])
        asyncio.run(exercise())

    def test_dashboard_categories_are_shared_with_live_mcp_and_work_with_master_off(self):
        from urllib.parse import urlsplit
        status = self.command('status')
        base = status['dashboard_url']
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(base))
        with urlopen(base + 'api/categories') as response:
            token = json.load(response)['csrf']
        def category(value):
            with urlopen(Request(base + 'api/categories', data=json.dumps(value).encode(), headers={
                    'Content-Type':'application/json', 'X-CSRF-Token':token, 'Origin':origin})) as response:
                return json.load(response)['categories']
        entry = next(x for x in category({'action':'create','label':'隔离项目分类'}) if x['label'] == '隔离项目分类')
        result = self.private_tool_call('archive_record', {'category':entry['id'], 'title':'自定义记忆', 'body':'Temporary category acceptance.'})
        self.assertFalse(result.get('isError'))
        record = result['structuredContent']
        category({'action':'rename','id':entry['id'],'label':'项目新名称'})
        current = self.private_tool_call('archive_status', {})['structuredContent']
        self.assertEqual(next(x for x in current['categories'] if x['id'] == entry['id'])['label'], '项目新名称')
        self.assertEqual(self.private_tool_call('archive_get', {'record_id':record['id']})['structuredContent']['revision'], 1)
        with self.assertRaises(HTTPError) as error: category({'action':'delete','id':entry['id']})
        self.assertEqual(error.exception.code, 400)
        self.command('stop-mcp')
        self.assertTrue(any(x['label'] == 'MCP关闭也可管理' for x in category({'action':'create','label':'MCP关闭也可管理'})))

    def test_runtime_refresh_preserves_preferences_models_configuration_and_database(self):
        self.command('status')
        self.command('stop-mcp')
        self.command('save-endpoint', endpoint='wss://cloud.invalid/mcp?token=private-fixture-only')
        models = self.data / 'app/models'
        models.mkdir()
        (models / 'preserve.bin').write_bytes(b'model fixture')
        switches = self.data / 'mcp-packages.json'
        switches.write_text('{"archive":false,"planner":false}', 'utf-8')
        database = self.data / 'state/data/mnemosyne.db'
        original_database = database.read_bytes()
        with (self.data / 'app/.env').open('a', encoding='utf-8') as config:
            config.write('\nDASHBOARD_PORT=1\nARCHIVE_PORT=1\nADMIN_PORT=1\n')
        original_env = (self.data / 'app/.env').read_bytes()
        # An update may refresh only reviewed application code.
        (self.data / 'app/mcp_server.py').write_text('# outdated runtime', 'utf-8')
        self.command('shutdown')
        self.process.wait(timeout=20)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
        self.launch()
        status = self.command('status')
        self.assertFalse(status['mcp_enabled'])
        self.assertEqual(database.read_bytes(), original_database)
        self.assertEqual((self.data / 'app/.env').read_bytes(), original_env)
        self.assertEqual((models / 'preserve.bin').read_bytes(), b'model fixture')
        self.assertEqual(switches.read_text('utf-8'), '{"archive":false,"planner":false}')
        self.assertIn('MCPServer', (self.data / 'app/mcp_server.py').read_text('utf-8'))
        self.assertFalse((self.data / 'manage.ps1').exists())
        self.assertFalse((self.data / 'launcher.py').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows file ACL check')
    def test_private_descriptor_has_a_protected_windows_acl(self):
        self.command('status')
        result = subprocess.run(['icacls.exe', str(self.data / 'desktop-session.json')],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('(I)', result.stdout)

    def test_loopback_rpc_ignores_environment_http_proxy(self):
        self.command('status')
        code = ('import sys;sys.path.insert(0,sys.argv[1]);from client import rpc;'
                'print(len(rpc(sys.argv[2],"list-tools")))')
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(BACKEND), str(self.data)],
            env={**self.env, 'HTTP_PROXY': 'http://127.0.0.1:9', 'NO_PROXY': '',
                 'ALL_PROXY': 'http://127.0.0.1:9'}, capture_output=True,
            text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, 'Local auth must never be passed to a configured proxy')
        self.assertGreater(int(result.stdout), 0)

    def test_invalid_commands_and_endpoint_are_rejected_without_disclosing_input(self):
        self.command('status')
        for command in [{'command': 'set-cloud', 'enabled': 'false'},
            {'command': 'save-endpoint', 'endpoint': 'https://secret.invalid/?token=do-not-echo'},
            {'command': 'start-mcp', 'script': 'anything.py'},
            {'command': 'client-config', 'format': 'shell'}]:
            self.process.stdin.write(json.dumps({'id': 999, **command}) + '\n')
            self.process.stdin.flush()
            response = json.loads(self.process.stdout.readline())
            self.assertFalse(response['ok'])
            self.assertNotIn('do-not-echo', str(response))
        self.assertFalse(self.command('status')['cloud_configured'])

    def large_record(self):
        # Seed only this temporary database, avoiding semantic-indexing latency
        # for an adversarial repeated-character fixture when testing transport.
        result = self.private_tool_call('archive_record', {'category': 'journal',
            'title': 'Large isolated response', 'body': 'Temporary transport fixture.'})
        ident = result['structuredContent']['id']
        import sqlite3
        with closing(sqlite3.connect(self.data / 'state/data/mnemosyne.db')) as database, database:
            value = json.loads(database.execute('SELECT payload FROM personal_archive_records WHERE id=?', (ident,)).fetchone()[0])
            value['body'] = 'x' * 70000
            database.execute('UPDATE personal_archive_records SET payload=? WHERE id=?', (json.dumps(value), ident))
        return ident

    def private_tool_call(self, name, arguments):
        self.command('status')
        descriptor = json.loads((self.data / 'desktop-session.json').read_text('utf-8'))
        payload = {'method': 'call-tool', 'name': name, 'arguments': arguments}
        with urlopen(Request(descriptor['url'], data=json.dumps(payload).encode(), headers={
            'Authorization': 'Bearer ' + descriptor['token'], 'Content-Type': 'application/json'}), timeout=30) as response:
            value = json.loads(response.read())
        self.assertTrue(value['ok'])
        return value['result']

    def test_large_tool_result_through_central_rpc(self):
        ident = self.large_record()
        self.assertIn('x' * 70000, json.dumps(self.private_tool_call('archive_get', {'record_id': ident})))

    def test_local_tls_cloud_bridge_is_independent_and_obeys_master_gate(self):
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import ssl
        import ipaddress
        from websockets.asyncio.server import serve
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
        certfile, keyfile = self.base / 'test-ca.pem', self.base / 'test-key.pem'
        certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.chmod(keyfile, 0o600)
        self.command('shutdown')
        self.process.wait(timeout=20)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
        self.env['SSL_CERT_FILE'] = str(certfile)
        self.launch()
        large_record_id = self.large_record()
        self.command('stop-mcp')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile, keyfile)
        ready = queue.Queue()
        completed, disconnected = threading.Event(), threading.Event()
        received = []
        accepted = threading.Event()

        async def websocket_handler(websocket):
            accepted.set()
            try:
                await websocket.send(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                               'clientInfo': {'name': 'isolated-cloud-fixture', 'version': '1'}}}))
                response = json.loads(await websocket.recv())
                self.assertIn('result', response)
                await websocket.send(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
                await websocket.send(json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}))
                response = json.loads(await websocket.recv())
                received.extend(tool['name'] for tool in response['result']['tools'])
                await websocket.send(json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                    'params': {'name': 'archive_get', 'arguments': {'record_id': large_record_id}}}))
                response = json.loads(await websocket.recv())
                self.assertFalse(response['result'].get('isError', False))
                self.assertIn('x' * 70000, json.dumps(response))
                completed.set()
                await websocket.wait_closed()
            finally:
                disconnected.set()

        async def run_server():
            stop = asyncio.Event()
            # One IPv4 listener has one assigned port. Binding "localhost" at
            # port zero can create separate IPv4/IPv6 sockets on different ports.
            async with serve(websocket_handler, '127.0.0.1', 0, ssl=context) as server:
                ready.put((server.sockets[0].getsockname()[1], asyncio.get_running_loop(), stop))
                await stop.wait()

        thread = threading.Thread(target=lambda: asyncio.run(run_server()), daemon=True)
        thread.start()
        port, loop, stop = ready.get(timeout=5)
        try:
            self.command('save-endpoint', endpoint=f'wss://127.0.0.1:{port}/mcp')
            self.command('set-cloud', enabled=True)
            self.assertFalse(completed.wait(0.3))
            self.assertFalse(self.command('status')['cloud_connected'])
            self.command('start-mcp')
            self.assertTrue(completed.wait(20), 'TLS cloud fixture did not initialize: ' +
                str({'accepted': accepted.is_set(), 'disconnected': disconnected.is_set(),
                     'status': self.command('status')}))
            self.assertIn('archive_status', received)
            self.assertTrue(self.command('status')['cloud_connected'])
            with urlopen(self.command('status')['capabilities_url'] + 'api/status') as response:
                capabilities = json.load(response)
            self.assertEqual(capabilities['connection'], 'connected')
            self.assertEqual(capabilities['tool_count'], len(received))
            self.assertTrue(any(call['tool'] == 'archive_get' for call in capabilities['calls']))
            self.assertNotIn('x' * 100, (self.data / 'logs/events.jsonl').read_text('utf-8'))
            self.command('set-cloud', enabled=False)
            self.assertTrue(disconnected.wait(5))
            status = self.command('status')
            self.assertTrue(status['mcp_enabled'])
            self.assertFalse(status['cloud_connected'])
            with urlopen(status['capabilities_url'] + 'api/status') as response:
                self.assertEqual(json.load(response)['connection'], 'stopped')
        finally:
            loop.call_soon_threadsafe(stop.set)
            thread.join(timeout=10)

    def test_private_rpc_rejects_wrong_host_origin_token_and_large_payload(self):
        status = self.command('status')
        with urlopen(status['dashboard_url'].replace('/memory/', '/healthz')) as response:
            dashboard_pid = json.loads(response.read())['pid']
        descriptor = json.loads((self.data / 'desktop-session.json').read_text('utf-8'))
        url = descriptor['url']
        for headers, payload, expected in [
            ({}, b'{}', 403),
            ({'Authorization': 'Bearer ' + descriptor['token'], 'Host': 'evil.invalid'}, b'{}', 403),
            ({'Authorization': 'Bearer ' + descriptor['token'], 'Origin': 'https://evil.invalid'}, b'{}', 403),
            ({'Authorization': 'Bearer ' + descriptor['token']}, b'x' * 1048577, 413),
        ]:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, data=payload, headers=headers), timeout=5)
            self.assertEqual(error.exception.code, expected)
        self.process.stdin.close()
        self.process.wait(timeout=20)
        self.assertFalse((self.data / 'desktop-session.json').exists())
        self.assertFalse(alive(dashboard_pid), 'EOF left a dashboard process alive')

    def test_stdio_adapter_exits_after_supervisor_shutdown_with_client_stdin_open(self):
        self.command('status')
        adapter = subprocess.Popen([sys.executable, '-X', 'utf8', str(BACKEND / 'client.py'),
            '--data-root', str(self.data)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', env=self.env)
        try:
            adapter.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                           'clientInfo': {'name': 'shutdown-fixture', 'version': '1'}}}) + '\n')
            adapter.stdin.flush()
            self.assertIn('result', json.loads(adapter.stdout.readline()))
            leases = list((self.data / 'desktop-clients').glob('*.json'))
            self.assertEqual(len(leases), 1)
            lease = json.loads(leases[0].read_text('utf-8'))
            self.assertEqual(set(lease), {'pid', 'creation'})
            self.assertTrue(alive(lease['pid']))
            self.command('shutdown')
            self.process.wait(timeout=20)
            adapter.wait(timeout=8)
            self.assertEqual(adapter.returncode, 0)
            self.assertEqual(list((self.data / 'desktop-clients').glob('*.json')), [])
        finally:
            if adapter.poll() is None:
                adapter.kill()
                adapter.wait()
            for stream in (adapter.stdin, adapter.stdout, adapter.stderr):
                stream.close()

    def test_adapter_exits_when_owner_is_killed_even_with_stale_descriptor_and_open_stdin(self):
        self.command('status')
        entry = json.loads(self.command('client-config', format='json'))['mcpServers']['evomyn']
        adapter = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=self.env)
        try:
            adapter.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                           'clientInfo': {'name': 'forced-exit-fixture', 'version': '1'}}}) + '\n')
            adapter.stdin.flush()
            self.assertIn('result', json.loads(adapter.stdout.readline()))
            descriptor = json.loads((self.data / 'desktop-session.json').read_text('utf-8'))
            pid = descriptor.get('owner_pid', self.process.pid)
            self.expected_killed = True
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = kernel.OpenProcess(0x1, False, pid)
                self.assertTrue(handle)
                try:
                    self.assertTrue(kernel.TerminateProcess(handle, 1))
                finally:
                    kernel.CloseHandle(handle)
            else:
                import signal
                os.kill(pid, signal.SIGKILL)
            self.process.wait(timeout=20)
            self.assertTrue((self.data / 'desktop-session.json').exists(), 'Fixture must leave stale descriptor')
            adapter.wait(timeout=8)
            self.assertEqual(adapter.returncode, 0)
            self.assertEqual(list((self.data / 'desktop-clients').glob('*.json')), [])
        finally:
            if adapter.poll() is None:
                adapter.kill()
                adapter.wait()
            for stream in (adapter.stdin, adapter.stdout, adapter.stderr):
                stream.close()

    def test_exported_adapter_ignores_pythonpath_startup_injection(self):
        self.command('status')
        poison = self.base / 'untrusted python startup'
        poison.mkdir()
        marker = self.base / 'injected.txt'
        (poison / 'sitecustomize.py').write_text(
            'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("injected")\n', 'utf-8')
        entry = json.loads(self.command('client-config', format='json'))['mcpServers']['evomyn']
        adapter = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**self.env, 'PYTHONPATH': str(poison)})
        try:
            adapter.communicate(timeout=10)
            self.assertEqual(adapter.returncode, 0)
            self.assertFalse(marker.exists(), 'Exported helper executed PYTHONPATH startup code')
        finally:
            if adapter.poll() is None:
                adapter.kill()
                adapter.communicate()


class BackendOwnedProcess(unittest.TestCase):
    def test_fixed_host_commands_disable_python_environment_and_user_site(self):
        sys.path.insert(0, str(BACKEND))
        try:
            import service
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            owner = service.Supervisor.__new__(service.Supervisor)
            owner.root = Path(directory)
            (owner.root / 'app').mkdir()
            (owner.root / 'app/.env').write_text('PLANNER_OWNER=device\n', 'utf-8')
            owner.env = {'DASHBOARD_PORT': '1', 'ARCHIVE_PORT': '2', 'ADMIN_PORT': '3', 'MCP_LAUNCH_INSTANCE': 'fixture'}
            owner.instance = 'fixture'
            with patch.object(service, 'OwnedProcess') as spawn:
                owner.spawn('worker', pipes=True)
                args = spawn.call_args.args[0]
                self.assertEqual(args[1:6], ['-E', '-s', '-X', 'utf8', '-u'])

    @unittest.skipUnless(os.name == 'nt', 'Windows job assignment race regression')
    def test_child_cannot_run_before_assignment_even_when_assignment_is_delayed(self):
        sys.path.insert(0, str(BACKEND))
        try:
            from service import OwnedProcess
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory(prefix='suspended owner ') as directory:
            directory = Path(directory)
            marker = directory / 'escaped-child.txt'
            child = 'from pathlib import Path;import sys,time;Path(sys.argv[1]).write_text("started");time.sleep(2)'
            script = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);time.sleep(20)'
            original_assign = OwnedProcess._assign_job
            ran_before_assignment = []
            def delayed_assign(owner):
                time.sleep(1.5)
                ran_before_assignment.append(marker.exists())
                original_assign(owner)
            process = None
            try:
                with patch.object(OwnedProcess, '_assign_job', delayed_assign):
                    process = OwnedProcess([sys.executable, '-c', script, child, str(marker)],
                        env=os.environ.copy(), cwd=directory)
                self.assertEqual(ran_before_assignment, [False], 'Child ran before its job was assigned')
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists(), 'Assigned process never resumed')
            finally:
                if process:
                    process.stop()
                # The intentionally uncontained pre-fix child self-exits.
                if ran_before_assignment == [True]:
                    time.sleep(2)

    def test_failed_worker_exchange_discards_pipe_before_another_request(self):
        sys.path.insert(0, str(BACKEND))
        try:
            import service
        finally:
            sys.path.pop(0)
        for mode in ('timeout', 'invalid-json', 'invalid-shape'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='worker failure ') as directory:
                directory = Path(directory)
                reply = {'timeout': 'import time;time.sleep(0.3);print("{\\\"ok\\\":true,\\\"result\\\":[]}",flush=True)',
                         'invalid-json': 'print("broken-json",flush=True)',
                         'invalid-shape': 'print("[]",flush=True)'}[mode]
                worker = service.OwnedProcess([sys.executable, '-u', '-c',
                    'import sys\nprint("{\\\"ready\\\":true}",flush=True)\nfor line in sys.stdin:\n ' + reply],
                    env=os.environ.copy(), cwd=directory, pipes=True)
                self.assertEqual(service.bounded_read(worker.process.stdout, timeout=5), {'ready': True})
                owner = service.Supervisor.__new__(service.Supervisor)
                owner.worker, owner.bridge = worker, None
                owner.lock, owner.io_lock = threading.RLock(), threading.Lock()
                owner.settings = {'mcp_enabled': True, 'cloud_enabled': False}
                owner.settings_path = directory / 'settings.json'
                read = service.bounded_read
                try:
                    with patch.object(service, 'bounded_read', lambda stream: read(stream, timeout=0.05)):
                        with self.assertRaises(Exception):
                            owner.execute({'method': 'list-tools'})
                    self.assertIsNone(owner.worker, 'A failed exchange retained its worker pipe')
                    self.assertIsNotNone(worker.process.poll(), 'Failed worker still running')
                    self.assertFalse(owner.settings['mcp_enabled'])
                    with patch.object(service, 'bounded_read') as stale_read:
                        with self.assertRaises(RuntimeError):
                            owner.execute({'method': 'list-tools'})
                        stale_read.assert_not_called()
                    fresh = service.OwnedProcess([sys.executable, '-u', '-c',
                        'import sys,json\nfor line in sys.stdin:\n print(json.dumps({"ok":True,"result":[{"name":"fresh-response","inputSchema":{}}]}),flush=True)'],
                        env=os.environ.copy(), cwd=directory, pipes=True)
                    try:
                        owner.worker = fresh
                        owner.settings['mcp_enabled'] = True
                        self.assertEqual(owner.execute({'method': 'list-tools'}),
                            [{'name': 'fresh-response', 'inputSchema': {}}])
                    finally:
                        fresh.stop()
                finally:
                    worker.stop()

    @unittest.skipUnless(os.name == 'nt', 'Windows suspended-process failure cleanup')
    def test_assignment_and_resume_failures_close_all_owned_process_handles(self):
        sys.path.insert(0, str(BACKEND))
        try:
            from service import OwnedProcess
        finally:
            sys.path.pop(0)
        for mode in ('assign-before', 'assign-after', 'resume'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='suspended failure ') as directory:
                directory = Path(directory)
                marker = directory / 'must-not-run'
                captured = []
                original_assign = OwnedProcess._assign_job
                def failure(owner):
                    captured.append(owner)
                    if mode == 'assign-after':
                        original_assign(owner)
                    raise OSError('Injected lifecycle failure')
                method = '_resume_primary_thread' if mode == 'resume' else '_assign_job'
                with patch.object(OwnedProcess, method, failure):
                    with self.assertRaises(RuntimeError):
                        OwnedProcess([sys.executable, '-c',
                            'from pathlib import Path;import sys;Path(sys.argv[1]).write_text("ran")', str(marker)],
                            env=os.environ.copy(), cwd=directory, pipes=True)
                owner = captured[0]
                self.assertIsNone(owner.job)
                self.assertIsNotNone(owner.process.poll())
                self.assertTrue(owner.process._handle.closed)
                self.assertTrue(owner.process.stdin.closed)
                self.assertTrue(owner.process.stdout.closed)
                self.assertFalse(marker.exists())

    def test_stop_kills_owned_python_descendants_including_venv_redirectors(self):
        sys.path.insert(0, str(BACKEND))
        try:
            from service import OwnedProcess
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory(prefix='owned child 测试 ') as directory:
            directory = Path(directory)
            child_pid = directory / 'child.json'
            parent_pids = directory / 'parent.json'
            child_script = 'import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(120)'
            script = ('import os,subprocess,sys,time,json;from pathlib import Path;'
                'child=subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);'
                'Path(sys.argv[3]).write_text(json.dumps([os.getpid(),child.pid]));time.sleep(120)')
            process = OwnedProcess([sys.executable, '-c', script, child_script, str(child_pid), str(parent_pids)],
                env=os.environ.copy(), cwd=directory)
            try:
                deadline = time.monotonic() + 10
                while not (child_pid.exists() and parent_pids.exists()) and time.monotonic() < deadline:
                    time.sleep(0.05)
                pids = json.loads(parent_pids.read_text()) + [int(child_pid.read_text())]
                self.assertTrue(all(alive(pid) for pid in pids))
                process.stop()
                deadline = time.monotonic() + 5
                while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(any(alive(pid) for pid in pids), 'Owned child descendants survived stop')
            finally:
                process.stop()


class BackendOwnerRegistration(unittest.TestCase):
    def test_owner_creation_identity_rejects_reused_pid_and_registration_race_cleans_lease(self):
        sys.path.insert(0, str(BACKEND))
        try:
            import client
        finally:
            sys.path.pop(0)
        owner = client.DesktopOwner(os.getpid())
        self.assertTrue(owner.alive())
        wrong = client.DesktopOwner(os.getpid(), owner.created + '-different')
        self.assertFalse(wrong.alive())
        wrong.close()
        try:
            with tempfile.TemporaryDirectory(prefix='registration race ') as directory:
                root = Path(directory)
                descriptor = {'instance': 'test-instance', 'owner_pid': os.getpid(), 'owner_created': owner.created}
                path = root / 'desktop-session.json'
                path.write_text(json.dumps(descriptor), 'utf-8')
                atomic = client.atomic_json
                def shutdown_during_register(lease, value):
                    atomic(lease, value)
                    path.unlink()
                with patch.object(client, 'atomic_json', shutdown_during_register):
                    self.assertIsNone(client.register_client(root, descriptor, owner))
                self.assertEqual(list((root / 'desktop-clients').glob('*.json')), [])
        finally:
            owner.close()
        self.assertFalse(owner.alive())


if __name__ == '__main__':
    unittest.main()
