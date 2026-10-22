"""Real owned-process OTA lifecycle using isolated user directories."""
import json
import socket
import ssl
import unittest
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
from urllib.error import HTTPError

import test_backend_service as backend
from test_device_sync import pairing
from test_device_ota import firmware, publish_release


class DesktopDeviceOTA(unittest.TestCase):
    setUp = backend.DesktopBackend.setUp
    tearDown = backend.DesktopBackend.tearDown
    command = backend.DesktopBackend.command
    launch = backend.DesktopBackend.launch

    def stop(self):
        self.command('shutdown')
        self.process.wait(timeout=20)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

    def test_app_owns_ota_independent_of_mcp_and_restarts_with_cache(self):
        self.assertEqual(self.command('status')['device_ota']['state'], 'unconfigured')
        source, values = pairing(self.base)
        self.command('ota-import-pairing', directory=str(source))
        self.assertEqual(self.command('status')['device_ota']['state'], 'no-firmware')
        build = self.base / 'firmware.bin'
        build.write_bytes(firmware(version='2.5.7'))
        release = self.base / 'release'
        publish_release(build, release, version='2.5.7', notes='fixture')
        status = self.command('ota-import-release', manifest=str(release / 'manifest.json'))
        self.assertTrue(status['device_ota']['running'])
        self.assertEqual(status['device_ota']['version'], '2.5.7')
        endpoint = 'https://127.0.0.1:' + values['DEVICE_GATEWAY_PORT']
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(source / 'cert.pem'))))
        headers = {'Authorization': 'Bearer ' + values['PLANNER_DEVICE_TOKEN'], 'Device-Id': values['PLANNER_DEVICE_ID']}
        for action in ('stop-mcp', 'start-mcp', 'ota-retry'):
            state = self.command(action)
            self.assertTrue(state['device_ota']['running'])
            with opener.open(Request(endpoint + '/updates/manifest', headers=headers), timeout=5) as response:
                self.assertEqual(json.load(response)['version'], '2.5.7')
        with self.assertRaises(HTTPError) as error:
            opener.open(Request(endpoint + '/device/archive', data=b'{}', headers=headers), timeout=5)
        self.assertEqual(error.exception.code, 410)
        before = (self.data / 'device-updates/manifest.json').read_bytes()
        self.stop()
        with socket.socket() as connection:
            self.assertNotEqual(connection.connect_ex(('127.0.0.1', int(values['DEVICE_GATEWAY_PORT']))), 0)
        self.launch()
        self.assertTrue(self.command('status')['device_ota']['running'])
        self.assertEqual((self.data / 'device-updates/manifest.json').read_bytes(), before)
        manifest = json.loads(before)
        (self.data / 'device-updates' / (manifest['sha256'] + '.bin')).write_bytes(b'corrupt')
        broken = self.command('status')['device_ota']
        self.assertEqual(broken['state'], 'invalid-firmware')
        self.assertFalse(broken['running'])

    def test_port_conflict_is_visible_without_breaking_mcp_and_retry_recovers(self):
        source, values = pairing(self.base)
        self.command('ota-import-pairing', directory=str(source))
        build = self.base / 'firmware.bin'
        build.write_bytes(firmware(version='2.5.7'))
        release = self.base / 'release'
        publish_release(build, release, version='2.5.7', notes='fixture')
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', int(values['DEVICE_GATEWAY_PORT'])))
            occupied.listen()
            status = self.command('ota-import-release', manifest=str(release / 'manifest.json'))
            self.assertEqual(status['device_ota']['state'], 'error')
            self.assertTrue(status['ready'])
            self.assertTrue(status['mcp_enabled'])
        self.assertTrue(self.command('ota-retry')['device_ota']['running'])

    def test_bad_native_import_returns_safe_actionable_message(self):
        self.counter += 1
        self.process.stdin.write(json.dumps({'id': self.counter, 'command': 'ota-import-release',
            'manifest': str(self.base / 'private-do-not-print/manifest.json')}) + '\n')
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        self.assertFalse(response['ok'])
        self.assertIn('固件包', response['error'])
        self.assertNotIn('private-do-not-print', response['error'])
        self.assertTrue(self.command('status')['ready'])


if __name__ == '__main__':
    unittest.main()
