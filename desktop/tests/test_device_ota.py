"""OTA uses disposable pairing and images, never the installed database."""
import json
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'desktop/backend'), str(ROOT / 'server/personal-memory/vendor'),
                str(ROOT / 'server/personal-memory/tests')]
from test_device_sync import pairing
from test_device_updates import firmware
from device_updates import publish_release
from device_sync import import_pairing


class DeviceOTA(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'profile'
        self.root.mkdir()
        self.source, self.values = pairing(self.base)
        self.config = import_pairing(self.root, str(self.source))
        self.build = self.base / 'firmware.bin'
        self.build.write_bytes(firmware(version='2.5.7'))
        self.release = self.base / 'release'
        self.manifest = publish_release(self.build, self.release, version='2.5.7', notes='fixture')

    def test_import_is_private_validated_and_atomic_on_bad_image(self):
        from device_ota import import_release, inspect
        self.assertEqual(inspect(self.root)['state'], 'no-firmware')
        import_release(self.root, str(self.release / 'manifest.json'))
        state = inspect(self.root)
        self.assertEqual(state['version'], '2.5.7')
        cached = self.root / 'device-updates/manifest.json'
        saved = cached.read_bytes()
        (self.release / (self.manifest['sha256'] + '.bin')).write_bytes(b'bad')
        with self.assertRaises(ValueError):
            import_release(self.root, str(self.release / 'manifest.json'))
        self.assertEqual(cached.read_bytes(), saved)
        self.assertFalse((self.root / 'state').exists())

    def test_old_firmware_and_wrong_board_rejected(self):
        from device_ota import import_release
        self.build.write_bytes(firmware(version='2.5.6'))
        publish_release(self.build, self.release, version='2.5.6', notes='old')
        with self.assertRaises(ValueError):
            import_release(self.root, str(self.release / 'manifest.json'))
        self.assertFalse((self.root / 'device-updates/manifest.json').exists())

    def test_unpaired_prepared_version_survives_fresh_inspection(self):
        from device_ota import import_release, inspect
        (self.root / 'device-sync.json').unlink()
        import_release(self.root, str(self.release / 'manifest.json'))
        for _ in range(2):
            status = inspect(self.root)
            self.assertEqual(status['state'], 'unconfigured')
            self.assertFalse(status['configured'])
            self.assertFalse(status['running'])
            self.assertEqual(status['version'], '2.5.7')
        # Invalid pairing must not hide a valid, independently prepared cache.
        (self.root / 'device-sync.json').write_text('{', encoding='utf-8')
        self.assertEqual(inspect(self.root)['state'], 'invalid-config')
        self.assertEqual(inspect(self.root)['version'], '2.5.7')

    def test_configuration_states_hide_credentials(self):
        from device_ota import inspect
        (self.root / 'device-sync.json').unlink()
        self.assertEqual(inspect(self.root)['state'], 'unconfigured')
        (self.root / 'device-sync.json').write_text('{"token":"do-not-expose"', encoding='utf-8')
        state = inspect(self.root)
        self.assertEqual(state['state'], 'invalid-config')
        self.assertNotIn('do-not-expose', json.dumps(state))

    def test_authenticated_download_archive_retired_and_no_database(self):
        from device_ota import import_release, create_server
        import_release(self.root, str(self.release / 'manifest.json'))
        # Legacy enabled remains false. OTA does not use the archive switch.
        with patch('device_gateway.DeviceArchive', side_effect=AssertionError('No archive instance')):
            server = create_server(self.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(self.source / 'cert.pem'))))
        base = 'https://127.0.0.1:' + str(server.server_port)
        headers = {'Authorization': 'Bearer ' + self.config['token'], 'Device-Id': self.config['device_id']}
        with opener.open(Request(base + '/updates/manifest', headers=headers)) as response:
            manifest = json.load(response)
        with opener.open(Request(base + manifest['url'], headers=headers)) as response:
            self.assertEqual(response.read(), self.build.read_bytes())
        for route, data, auth, code in [('/updates/manifest', None, {}, 401),
                ('/device/archive', b'{}', headers, 410), ('/private', None, headers, 404)]:
            with self.assertRaises(HTTPError) as error:
                opener.open(Request(base + route, data=data, headers=auth))
            self.assertEqual(error.exception.code, code)
        self.assertFalse((self.root / 'state').exists())


if __name__ == '__main__':
    unittest.main()
