"""Real TLS and supervisor lifecycle against disposable desktop data."""
import http.client
import json
import socket
import ssl
import time
from types import SimpleNamespace
from urllib.request import urlopen
import unittest
from unittest.mock import Mock, patch

from test_backend_service import DesktopBackend
from test_device_sync import pairing


class DesktopDeviceSync(unittest.TestCase):
    # Reuse only the process harness, not its unrelated test cases.
    setUp = DesktopBackend.setUp
    tearDown = DesktopBackend.tearDown
    command = DesktopBackend.command
    launch = DesktopBackend.launch
    def test_sync_is_independent_durable_and_resumes_on_restart(self):
        self.command('stop-mcp')
        state = self.command('status')
        self.assertIn('device_sync', state, 'Supervisor must expose independent device sync')
        self.assertFalse(state['device_sync']['configured'])
        source, values = pairing(self.base)
        state = self.command('import-device-sync', directory=str(source))
        self.assertTrue(state['device_sync']['configured'])
        self.assertFalse(state['device_sync']['enabled'])
        (self.data / 'app/device_sync.py').write_text('raise RuntimeError("Unreviewed shadow module")', 'utf-8')
        state = self.command('set-device-sync', enabled=True)
        self.assertTrue(state['device_sync']['running'], state)
        self.assertFalse(state['mcp_enabled'])
        port = int(values['DEVICE_GATEWAY_PORT'])
        event = {'event_id': 'fixture-completion-1', 'device_id': 'fixture-device', 'task_id': 'task-1',
            'title': '隔离完成记录', 'body': 'Temporary TLS completion', 'note': '',
            'scheduled_at': None, 'completed_at': 1780000000}

        def send(token='t' * 64):
            context = ssl.create_default_context(cafile=str(source / 'cert.pem'))
            connection = http.client.HTTPSConnection('127.0.0.1', port, timeout=15, context=context)
            connection.request('POST', '/device/archive', json.dumps(event).encode(),
                {'Authorization': 'Bearer ' + token, 'Device-Id': 'fixture-device', 'Content-Type': 'application/json'})
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        self.assertEqual(send('wrong')[0], 401)
        code, receipt = send()
        self.assertEqual(code, 200, receipt)
        state = self.command('status')
        self.assertEqual(state['device_sync']['received_count'], 1)
        self.assertIsNotNone(state['device_sync']['last_received_at'])
        self.assertNotIn('t' * 64, json.dumps(state))
        self.command('set-device-sync', enabled=False)
        with socket.socket() as connection:
            self.assertNotEqual(connection.connect_ex(('127.0.0.1', port)), 0)
        self.command('set-device-sync', enabled=True)
        self.assertEqual(send()[1]['record_id'], receipt['record_id'])
        self.command('shutdown')
        self.process.wait(timeout=20)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()
        self.launch()
        state = self.command('status')
        self.assertTrue(state['device_sync']['running'], state)
        self.assertFalse(state['mcp_enabled'])
        self.assertEqual(send()[1]['record_id'], receipt['record_id'])
        with urlopen(state['dashboard_url'] + 'api/records') as response:
            records = json.load(response)
        self.assertEqual(json.dumps(records, ensure_ascii=False).count('隔离完成记录'), 1)
        self.command('start-mcp')
        from client import rpc
        result = rpc(self.data, 'call-tool', name='archive_list', arguments={})
        self.assertIn('隔离完成记录', str(result))
        self.assertEqual(self.command('status')['device_sync']['received_count'], 3)

    def test_bind_failure_does_not_break_desktop_or_retry_forever(self):
        source, values = pairing(self.base)
        state = self.command('status')
        self.assertIn('device_sync', state)
        self.command('import-device-sync', directory=str(source))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', int(values['DEVICE_GATEWAY_PORT'])))
            listener.listen()
            state = self.command('set-device-sync', enabled=True)
            self.assertTrue(state['ready'])
            self.assertFalse(state['device_sync']['running'])
            self.assertTrue(state['device_sync']['error'])
        time.sleep(0.2)
        self.assertFalse(self.command('status')['device_sync']['running'])
        self.assertTrue(self.command('set-device-sync', enabled=True)['device_sync']['running'])

    def test_bad_saved_config_is_isolated_and_environment_cannot_enable_gateway(self):
        self.command('stop-mcp')
        self.command('shutdown')
        self.process.wait(timeout=20)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()
        (self.data / 'device-sync.json').write_text('{"token":"do-not-expose"}', 'utf-8')
        self.env.update(DEVICE_GATEWAY_HOST='127.0.0.1', DEVICE_GATEWAY_PORT='18773',
            PLANNER_DEVICE_ID='environment-device', PLANNER_DEVICE_TOKEN='s' * 64)
        self.launch()
        state = self.command('status')
        self.assertTrue(state['ready'])
        self.assertFalse(state['device_sync']['running'])
        self.assertFalse(state['device_sync']['enabled'])
        self.assertTrue(state['device_sync']['error'])
        self.assertNotIn('do-not-expose', json.dumps(state))
        self.assertNotIn('environment-device', json.dumps(state))


del DesktopBackend


class RetryPolicy(unittest.TestCase):
    def test_failed_listener_recovers_on_status_only_after_cooldown(self):
        from service import Supervisor
        owner = Supervisor.__new__(Supervisor)
        owner.root = None
        owner.device_config = {'enabled': True, 'host': '127.0.0.1', 'port': 18773, 'device_id': 'fixture'}
        owner.device_gateway = None
        owner.device_error = None
        owner.device_retry_at = 0
        child = SimpleNamespace(process=SimpleNamespace(stdout=None, poll=lambda: None), stop=Mock())
        replacement = SimpleNamespace(process=SimpleNamespace(stdout=None, poll=lambda: None), stop=Mock())
        owner.spawn = Mock(side_effect=[OSError('Private diagnostic'), child, replacement])
        with patch('service.time.monotonic', return_value=100) as clock, \
                patch('service.bounded_read', return_value={'ready': True}), \
                patch('device_sync.receipt_status', return_value={'last_received_at': None, 'received_count': 0}):
            owner.refresh_device_sync()
            self.assertFalse(owner.device_status()['running'])
            clock.return_value = 129
            self.assertFalse(owner.device_status()['running'])
            self.assertEqual(owner.spawn.call_count, 1)
            clock.return_value = 131
            self.assertTrue(owner.device_status()['running'])
            self.assertEqual(owner.spawn.call_count, 2)
            self.assertIsNone(owner.device_status()['error'])
            child.process.poll = lambda: 1
            clock.return_value = 132
            self.assertFalse(owner.device_status()['running'])
            child.stop.assert_called_once()
            clock.return_value = 161
            self.assertFalse(owner.device_status()['running'])
            self.assertEqual(owner.spawn.call_count, 2)
            clock.return_value = 163
            self.assertTrue(owner.device_status()['running'])
            self.assertEqual(owner.spawn.call_count, 3)


if __name__ == '__main__':
    unittest.main()
