"""Upgrade regressions for retired completion sync; all state is disposable."""
import json
import socket
import subprocess
import sys
from urllib.request import urlopen
import unittest

import test_backend_service as backend
from test_device_sync import pairing


class RetiredDesktopDeviceSync(unittest.TestCase):
    # Reuse only the isolated process harness, not its unrelated test cases.
    setUp = backend.DesktopBackend.setUp
    tearDown = backend.DesktopBackend.tearDown
    command = backend.DesktopBackend.command
    launch = backend.DesktopBackend.launch
    private_tool_call = backend.DesktopBackend.private_tool_call

    def stop(self):
        self.command('shutdown')
        self.process.wait(timeout=20)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

    def assert_retired_command(self, command, **parameters):
        self.counter += 1
        self.process.stdin.write(json.dumps({'id': self.counter, 'command': command, **parameters}) + '\n')
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        self.assertEqual(response['id'], self.counter)
        self.assertFalse(response['ok'], 'Retired sync commands must not enable a listener')

    def test_enabled_legacy_pairing_is_preserved_without_listener_and_archive_still_works(self):
        record = self.private_tool_call('archive_record', {'category': 'journal',
            'title': '升级前的完成日志', 'body': 'Previously archived completion fixture.'})['structuredContent']
        record = self.private_tool_call('archive_get', {'record_id': record['id']})['structuredContent']
        self.stop()
        # Reproduce the files left by a prior desktop release, with valid TLS
        # material: the old supervisor would start a real listener on upgrade.
        from device_sync import import_pairing
        source, values = pairing(self.base)
        config = import_pairing(self.data, str(source))
        config['enabled'] = True
        saved_config = self.data / 'device-sync.json'
        saved_config.write_text(json.dumps(config), 'utf-8')
        receipt = self.data / 'state/device-sync-status.json'
        receipt.write_text(json.dumps({'pairing_id': config['pairing_id'],
            'last_received_at': '2026-10-20T10:00:00Z', 'received_count': 1}), 'utf-8')
        preserved = {path: path.read_bytes() for path in
            [saved_config, receipt, *list((self.data / 'device-sync').rglob('*.pem'))]}
        self.launch()
        state = self.command('status')
        self.assertTrue(state['ready'])
        self.assertTrue(state['mcp_enabled'])
        with socket.socket() as connection:
            self.assertNotEqual(connection.connect_ex(('127.0.0.1', int(values['DEVICE_GATEWAY_PORT']))), 0,
                'A saved enabled pairing must never launch the retired listener')
        self.assertNotIn('device_sync', state)
        self.assert_retired_command('set-device-sync', enabled=True)
        self.assert_retired_command('set-device-sync', enabled=False)
        self.assert_retired_command('import-device-sync', directory=str(source))
        self.assertEqual(self.private_tool_call('archive_get', {'record_id': record['id']})['structuredContent'], record)
        explicit = self.private_tool_call('archive_record', {'category': 'journal',
            'title': '主动保存的记忆', 'body': 'Explicit MCP archiving remains available.'})['structuredContent']
        self.command('stop-mcp')
        with urlopen(state['dashboard_url'] + 'api/records') as response:
            records = json.load(response)['records']
        self.assertEqual({item['id'] for item in records}, {record['id'], explicit['id']})
        self.command('start-mcp')
        self.assertIn(explicit['id'], str(self.private_tool_call('archive_list', {})))
        for path, original in preserved.items():
            self.assertEqual(path.read_bytes(), original, 'Upgrade must preserve legacy pairing and receipt files')

    def test_invalid_legacy_config_and_gateway_environment_do_not_affect_startup(self):
        self.stop()
        saved = self.data / 'device-sync.json'
        original = b'{"token":"do-not-expose"'
        saved.write_bytes(original)
        self.env.update(DEVICE_GATEWAY_HOST='127.0.0.1', DEVICE_GATEWAY_PORT='1',
                        PLANNER_DEVICE_TOKEN='do-not-expose')
        self.launch()
        state = self.command('status')
        self.assertTrue(state['ready'])
        self.assertTrue(state['mcp_enabled'])
        self.assertNotIn('device_sync', state)
        self.assertNotIn('do-not-expose', json.dumps(state))
        self.assertEqual(saved.read_bytes(), original)
        with urlopen(state['dashboard_url']) as response:
            self.assertEqual(response.status, 200)
        self.assertFalse(self.private_tool_call('archive_status', {}).get('isError'))

    def test_retired_host_role_is_rejected(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(backend.BACKEND / 'host.py'),
            '--role', 'device-gateway', '--data-root', str(self.base / 'unused')],
            env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid choice', result.stderr)


if __name__ == '__main__':
    unittest.main()
