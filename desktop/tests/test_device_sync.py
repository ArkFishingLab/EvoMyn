"""Private pairing import tests; all keys and paths are disposable fixtures."""
import datetime
import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))


def pairing(base, *, expired=False, san='127.0.0.1'):
    source = base / 'paired runtime'
    (source / 'app').mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=2))
        .not_valid_after(now + datetime.timedelta(days=-1 if expired else 2))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(san))]), False)
        .sign(key, hashes.SHA256()))
    (source / 'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (source / 'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    values = {'DEVICE_GATEWAY_HOST': '127.0.0.1', 'DEVICE_GATEWAY_PORT': str(port),
        'DEVICE_GATEWAY_ALLOWED_HOSTS': '127.0.0.1', 'DEVICE_GATEWAY_CERT': 'cert.pem',
        'DEVICE_GATEWAY_KEY': 'key.pem', 'PLANNER_DEVICE_ID': 'fixture-device',
        'PLANNER_DEVICE_TOKEN': 't' * 64, 'PERSONAL_ARCHIVE_HOME': '<UNUSED-FIXTURE-VALUE>',
        'DEVICE_UPDATE_DIR': '<UNUSED-FIXTURE-VALUE>', 'MCP_ENDPOINT': '<UNUSED-FIXTURE-VALUE>'}
    write_env(source, values)
    return source, values


def write_env(source, values):
    (source / 'app/.env').write_text('\n'.join(key + '=' + value for key, value in values.items()), 'utf-8')


class PairingImport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'desktop'
        self.root.mkdir()
        self.source, self.values = pairing(self.base)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('device_sync'), 'Desktop pairing module must exist')
        import device_sync
        return device_sync

    def test_import_copies_only_pairing_and_preserves_identity_without_enabling(self):
        sync = self.module()
        sync.import_pairing(self.root, str(self.source))
        config = sync.load_config(self.root)
        self.assertFalse(config['enabled'])
        self.assertEqual(config['token'], 't' * 64)
        self.assertEqual(config['device_id'], 'fixture-device')
        self.assertNotIn('<UNUSED-FIXTURE-VALUE>', json.dumps(config))
        for key in ('cert', 'key'):
            copied = self.root / config[key]
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_bytes(), (self.source / (key + '.pem')).read_bytes())

    def test_invalid_import_never_replaces_saved_pairing(self):
        sync = self.module()
        sync.import_pairing(self.root, str(self.source))
        before = (self.root / 'device-sync.json').read_bytes()
        for field, invalid in [('DEVICE_GATEWAY_HOST', '0.0.0.0'), ('DEVICE_GATEWAY_HOST', '8.8.8.8'),
                ('DEVICE_GATEWAY_PORT', '0'), ('DEVICE_GATEWAY_PORT', '65536'),
                ('PLANNER_DEVICE_TOKEN', 'short'), ('DEVICE_GATEWAY_ALLOWED_HOSTS', '*'),
                ('DEVICE_GATEWAY_CERT', '../outside.pem')]:
            with self.subTest(field=field, invalid=invalid):
                write_env(self.source, {**self.values, field: invalid})
                with self.assertRaisesRegex(ValueError, '配对'):
                    sync.import_pairing(self.root, str(self.source))
                self.assertEqual((self.root / 'device-sync.json').read_bytes(), before)

    def test_expired_and_wrong_san_certificates_are_rejected(self):
        sync = self.module()
        for options in ({'expired': True}, {'san': '127.0.0.2'}):
            source, _ = pairing(self.base, **options)
            with self.assertRaisesRegex(ValueError, '配对'):
                sync.import_pairing(self.root, str(source))

    def test_mismatched_key_is_rejected(self):
        sync = self.module()
        other, _ = pairing(self.base / 'other')
        (self.source / 'key.pem').write_bytes((other / 'key.pem').read_bytes())
        with self.assertRaisesRegex(ValueError, '配对'):
            sync.import_pairing(self.root, str(self.source))

    def test_oversized_env_is_rejected(self):
        sync = self.module()
        (self.source / 'app/.env').write_bytes(b'x' * 65537)
        with self.assertRaisesRegex(ValueError, '配对'):
            sync.import_pairing(self.root, str(self.source))

    def test_symlinked_credentials_are_rejected(self):
        sync = self.module()
        original = self.source / 'key.pem'
        relocated = self.source / 'original-key.pem'
        original.rename(relocated)
        try:
            original.symlink_to(relocated)
        except OSError:
            self.skipTest('Creating symlinks requires Windows developer mode')
        with self.assertRaisesRegex(ValueError, '配对'):
            sync.import_pairing(self.root, str(self.source))

    def test_saved_schema_cannot_select_external_credentials(self):
        sync = self.module()
        sync.import_pairing(self.root, str(self.source))
        config = json.loads((self.root / 'device-sync.json').read_text('utf-8'))
        config['cert'] = str(self.source / 'cert.pem')
        (self.root / 'device-sync.json').write_text(json.dumps(config), 'utf-8')
        with self.assertRaisesRegex(ValueError, '配对'):
            sync.load_config(self.root)

    def test_managed_credential_path_rejects_traversal_before_file_access(self):
        sync = self.module()
        config = {'pairing_id': '../../outside', 'cert': 'device-sync/../../outside/cert.pem'}
        with self.assertRaisesRegex(ValueError, '配对'):
            sync.credential_path(self.root, config, 'cert')


if __name__ == '__main__':
    unittest.main()
