import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
from device_updates import ReleaseProvider, publish_release, validate_firmware


def firmware(version='1.2.3', project='xiaozhi', chip=9, marker=b'ROUND-VOICE-175C:v2/32m:OTA1'):
    description = bytearray(256)
    struct.pack_into('<I', description, 0, 0xABCD5432)
    description[16:16 + len(version)] = version.encode('ascii')
    description[48:48 + len(project)] = project.encode('ascii')
    header = bytearray(24); header[0] = 0xE9; header[1] = 1
    struct.pack_into('<H', header, 12, chip); header[23] = 1
    payload = bytes(description) + marker
    data = bytes(header) + struct.pack('<II', 0x3C000020, len(payload)) + payload
    checksum = 0xEF
    for byte in payload: checksum ^= byte
    data += bytes((15 - len(data) % 16) % 16) + bytes([checksum])
    return data + hashlib.sha256(data).digest()


class DeviceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.build = self.root / 'build.bin'; self.build.write_bytes(firmware())
        self.release = self.root / 'release'
    def tearDown(self): self.tmp.cleanup()
    def publish(self, **kwargs):
        return publish_release(self.build, self.release, version='1.2.3', notes='真实发布说明', **kwargs)

    def test_publish_and_provider_exact_manifest_and_hash_bytes(self):
        manifest = self.publish()
        self.assertEqual(set(manifest), {'board', 'version', 'sha256', 'size', 'url', 'notes', 'partition', 'project'})
        self.assertEqual(manifest['board'], 'round-voice-175c')
        self.assertEqual(manifest['partition'], 'v2/32m'); self.assertEqual(manifest['project'], 'xiaozhi')
        self.assertEqual(manifest['size'], self.build.stat().st_size)
        self.assertEqual(manifest['sha256'], hashlib.sha256(self.build.read_bytes()).hexdigest())
        provider = ReleaseProvider(self.release)
        raw, media = provider('/updates/manifest')
        self.assertEqual(json.loads(raw), manifest); self.assertEqual(media, 'application/json')
        self.assertEqual(provider(manifest['url']), (self.build.read_bytes(), 'application/octet-stream'))
        self.assertEqual(self.publish(), manifest)

    def test_bad_images_and_requested_version_never_publish(self):
        values = [b'bad', firmware(project='other'), firmware(chip=0), firmware(version='9.9.9'),
                  firmware()[:-10], firmware() + b'extra', b'X' * (4 * 1024 * 1024 + 1)]
        for value in values:
            with self.subTest(length=len(value)):
                self.build.write_bytes(value)
                with self.assertRaises(ValueError): self.publish()
                self.assertFalse((self.release / 'manifest.json').exists())

    def test_publisher_rejects_missing_or_wrong_board_marker(self):
        for marker in (b'', b'ROUND-VOICE-OTHER:v2/32m:OTA1', b'ROUND-VOICE-175C:v1/16m:OTA1'):
            with self.subTest(marker=marker):
                self.build.write_bytes(firmware(marker=marker))
                with self.assertRaisesRegex(ValueError, 'board|marker'):
                    self.publish()
                self.assertFalse((self.release / 'manifest.json').exists())

    def test_provider_rejects_markerless_image_with_consistent_manifest_hash(self):
        manifest = self.publish()
        data = firmware(marker=b'')
        digest = hashlib.sha256(data).hexdigest()
        manifest.update(sha256=digest, size=len(data), url='/updates/firmware/' + digest + '.bin')
        (self.release / (digest + '.bin')).write_bytes(data)
        (self.release / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'board|marker'):
            ReleaseProvider(self.release)('/updates/manifest')
        # Legacy inspection is explicit and never makes an image publishable.
        self.assertEqual(validate_firmware(firmware(version='2.5.2', marker=b''), version='2.5.2')['version'], '2.5.2')

    def test_version_and_notes_limits(self):
        for version, notes in [('v1.2.3', ''), ('1.2', ''), ('1.2.3.4', ''), ('1.2.' + '1' * 28, ''),
                               ('1.2.3', '字' * 683), ('1.2.3', '\ud800')]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                publish_release(self.build, self.release, version=version, notes=notes)

    def test_provider_rejects_tampered_binary_and_manifest(self):
        manifest = self.publish(); path = self.release / 'manifest.json'
        for key, value in [('sha256', 'a' * 64), ('size', True), ('version', '9.0.0'),
                           ('url', '/updates/firmware/../../private'), ('board', 'other'),
                           ('project', 'other'), ('partition', 'wrong'), ('extra', 'field')]:
            path.write_text(json.dumps({**manifest, key: value}), encoding='utf-8')
            with self.subTest(key=key), self.assertRaises(ValueError):
                ReleaseProvider(self.release)('/updates/manifest')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        (self.release / (manifest['sha256'] + '.bin')).write_bytes(b'tamper')
        with self.assertRaises(ValueError): ReleaseProvider(self.release)(manifest['url'])

    def test_only_current_fixed_hash_and_no_paths_are_served(self):
        manifest = self.publish(); provider = ReleaseProvider(self.release)
        for path in ('/updates/../manifest.json', '/updates/manifest?x=1', '/private',
                     '/updates/firmware/' + 'a' * 64 + '.bin', '/updates/firmware/../../build.bin'):
            self.assertIsNone(provider(path))
        self.assertIsNone(ReleaseProvider(self.root / 'missing')('/updates/manifest'))

    def test_failed_manifest_publish_keeps_previous_release(self):
        original = self.publish()
        self.build.write_bytes(firmware(version='1.2.4'))
        import device_updates
        replace = device_updates.os.replace
        def fail_manifest(source, target):
            if Path(target).name == 'manifest.json': raise OSError('disk failure')
            return replace(source, target)
        with patch.object(device_updates.os, 'replace', fail_manifest):
            with self.assertRaises(OSError):
                publish_release(self.build, self.release, version='1.2.4', notes='new')
        self.assertEqual(json.loads(ReleaseProvider(self.release)('/updates/manifest')[0]), original)

    def test_cli_publishes_and_invalid_version_exits_nonzero(self):
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'vendor/device_updates.py'),
                   '--build-bin', str(self.build), '--output-dir', str(self.release),
                   '--version', '1.2.3', '--notes', 'release']
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['version'], '1.2.3')
        command[command.index('--version') + 1] = '2.0.0'
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

if __name__ == '__main__': unittest.main()
