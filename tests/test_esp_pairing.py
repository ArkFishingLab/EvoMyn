"""Public USB pairing uses temporary credentials and a simulated wire only."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('esp_pairing', ROOT / 'tools/pair_esp_device.py')
pairing = None
if SPEC.origin and Path(SPEC.origin).exists():
    pairing = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(pairing)


class Wire:
    def __init__(self, change=None, partial=37):
        self.change, self.partial = change, partial
        self.input, self.output = bytearray(), bytearray()
        self.requests, self.chunks = [], []

    def write(self, raw):
        self.chunks.append(len(raw))
        n = min(self.partial, len(raw))
        self.input.extend(raw[:n])
        if self.input.endswith(b'\n'):
            command = json.loads(bytes(self.input).removeprefix(b'ROUND_CTL '))
            self.requests.append(command)
            self.input.clear()
            reply = {'id': command['id'], 'ok': True}
            if command['op'] == 'pairing_status':
                reply.update(schema=1, configured=False)
            else:
                reply.update(saved=True, restart_required=True)
            if self.change:
                reply = self.change(command, reply)
            if reply is not None:
                self.output.extend(b'boot message\nROUND_REPLY ' + json.dumps(reply).encode() + b'\n')
        return n

    def read(self, size=1):
        result = bytes(self.output[:size])
        del self.output[:size]
        return result


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(pairing, 'public USB pairing helper is not implemented')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_pair(self, wire=None, **kwargs):
        return pairing.pair_device(wire or Wire(), self.root, '192.168.1.20', timeout=.05, **kwargs)

    def test_fresh_pair_stages_real_tls_credentials_then_commits_after_ack(self):
        def check(command, reply):
            if command['op'] == 'pairing_set':
                self.assertFalse((self.root / 'device-sync.json').exists())
                self.assertTrue((self.root / 'device-pairing-pending.json').exists())
                self.assertEqual(set(command['config']), {'base_url', 'ca', 'token', 'device_id'})
            return reply
        wire = Wire(check)
        self.run_pair(wire)
        config = pairing.load_config(self.root)
        self.assertEqual(config['host'], '192.168.1.20')
        self.assertEqual([r['op'] for r in wire.requests], ['pairing_status', 'pairing_set'])
        self.assertLessEqual(max(wire.chunks), 512)
        self.assertFalse((self.root / 'device-pairing-pending.json').exists())
        self.assertFalse((self.root / 'state').exists())

    def test_status_is_read_only_and_rejects_old_schema(self):
        wire = Wire()
        self.assertFalse(pairing.pairing_status(wire, timeout=.05)['configured'])
        self.assertEqual(len(wire.requests), 1)
        for mutate in (lambda c, r: None, lambda c, r: {**r, 'schema': 0}):
            wire = Wire(mutate)
            with self.assertRaises(pairing.PairingError):
                self.run_pair(wire)
            self.assertEqual(len(wire.requests), 1)
            self.assertFalse((self.root / 'device-sync').exists())

    def test_existing_pairing_is_reused_without_rotating_or_rewriting(self):
        self.run_pair()
        before = (self.root / 'device-sync.json').read_bytes()
        wire = Wire()
        self.run_pair(wire)
        self.assertEqual((self.root / 'device-sync.json').read_bytes(), before)
        config = pairing.load_config(self.root)
        self.assertEqual(wire.requests[1]['config']['token'], config['token'])
        with self.assertRaises(pairing.PairingError):
            pairing.pair_device(Wire(), self.root, '192.168.1.21', timeout=.05)
        self.assertEqual((self.root / 'device-sync.json').read_bytes(), before)

    def test_existing_missing_or_invalid_ca_refuses_device_write(self):
        self.run_pair()
        config = pairing.load_config(self.root)
        ca = self.root / 'device-sync' / config['pairing_id'] / 'ca.pem'
        valid_ca = ca.read_bytes()
        for value in (None, b'not a PEM CA', (self.root / config['cert']).read_bytes()):
            if value is None:
                ca.unlink()
            else:
                ca.write_bytes(value)
            wire = Wire()
            with self.assertRaises(pairing.PairingError):
                self.run_pair(wire)
            self.assertNotIn('pairing_set', [r['op'] for r in wire.requests])
        imported = self.root / 'imported-ca.pem'
        imported.write_bytes(valid_ca)
        self.run_pair(ca_path=imported)

    def test_unrelated_ca_and_server_host_are_rejected(self):
        self.run_pair()
        with tempfile.TemporaryDirectory() as other:
            other_root = Path(other)
            pairing.pair_device(Wire(), other_root, '192.168.1.20', timeout=.05)
            config = pairing.load_config(other_root)
            ca = other_root / 'device-sync' / config['pairing_id'] / 'ca.pem'
            with self.assertRaises(pairing.PairingError):
                self.run_pair(ca_path=ca)

    def test_pc_commit_failure_retains_candidate_and_retry_reuses_identity(self):
        original = pairing.atomic_json
        def fail_commit(path, value):
            if path.name == 'device-sync.json':
                raise OSError('secret must not be printed')
            return original(path, value)
        wire = Wire()
        with patch.object(pairing, 'atomic_json', fail_commit):
            with self.assertRaisesRegex(pairing.PairingError, 'pending'):
                self.run_pair(wire)
        pending = self.root / 'device-pairing-pending.json'
        self.assertTrue(pending.exists())
        second = Wire()
        self.run_pair(second)
        self.assertEqual(wire.requests[1]['config'], second.requests[1]['config'])
        self.assertFalse(pending.exists())

    def test_device_failure_keeps_pc_uncommitted_and_pending_for_retry(self):
        def fail(command, reply):
            if command['op'] == 'pairing_set':
                return {'id': command['id'], 'ok': False, 'saved': False,
                        'restart_required': True, 'error': 'storage_failed'}
            return reply
        with self.assertRaisesRegex(pairing.PairingError, 'storage_failed'):
            self.run_pair(Wire(fail))
        self.assertFalse((self.root / 'device-sync.json').exists())
        self.assertTrue((self.root / 'device-pairing-pending.json').exists())

    def test_missing_save_ack_explains_manual_restart_and_preserves_retry_identity(self):
        wire = Wire(lambda command, reply: None if command['op'] == 'pairing_set' else reply)
        with self.assertRaisesRegex(pairing.PairingError, 'Manually restart'):
            self.run_pair(wire)
        self.assertFalse((self.root / 'device-sync.json').exists())
        retry = Wire()
        self.run_pair(retry)
        self.assertEqual(wire.requests[1]['config'], retry.requests[1]['config'])

    def test_active_desktop_lock_refuses_pairing(self):
        from filelock import FileLock
        with FileLock(str(self.root / 'desktop.lock'), timeout=0):
            wire = Wire()
            with self.assertRaisesRegex(pairing.PairingError, 'desktop'):
                self.run_pair(wire)
            self.assertFalse(wire.requests)

    def test_malformed_replies_ids_timeout_and_zero_write_fail_closed(self):
        mutations = [lambda c, r: {**r, 'id': 'different'},
                     lambda c, r: {**r, 'secret': 'do-not-print'},
                     lambda c, r: {**r, 'configured': 1},
                     lambda c, r: {**r, 'schema': True}, lambda c, r: None]
        for change in mutations:
            with self.assertRaises(pairing.PairingError) as error:
                pairing.pairing_status(Wire(change), timeout=.005)
            self.assertNotIn('do-not-print', str(error.exception))
        with self.assertRaises(pairing.PairingError):
            pairing.pairing_status(Wire(partial=0), timeout=.005)
        wire = Wire(lambda c, r: None)
        wire.output.extend(b'x' * 4097)
        with self.assertRaises(pairing.PairingError):
            pairing.pairing_status(wire, timeout=.005)

    def test_cli_does_not_print_serial_or_exception_secrets(self):
        with patch.object(pairing, 'open_serial', side_effect=OSError('private-token-value')):
            output = io.StringIO()
            with patch('sys.stderr', output):
                self.assertEqual(pairing.main(['--port', 'COM7', '--status']), 1)
            self.assertNotIn('private-token-value', output.getvalue())

    def test_ca_rejects_non_certificate_trailing_data_without_writing_device(self):
        self.run_pair()
        config = pairing.load_config(self.root)
        ca = self.root / 'device-sync' / config['pairing_id'] / 'ca.pem'
        ca.write_bytes(ca.read_bytes() + b'not-certificate-data\n')
        wire = Wire()
        with self.assertRaises(pairing.PairingError):
            self.run_pair(wire)
        self.assertEqual([r['op'] for r in wire.requests], ['pairing_status'])

    def test_existing_token_firmware_limit_and_corrupt_certificate_preserve_pc(self):
        self.run_pair()
        target = self.root / 'device-sync.json'
        config = pairing.load_config(self.root)
        config['token'] = 'x' * 257
        target.write_text(json.dumps(config), encoding='utf-8')
        before = target.read_bytes()
        with self.assertRaises(pairing.PairingError):
            self.run_pair()
        self.assertEqual(target.read_bytes(), before)
        config['token'] = 'x' * 64
        target.write_text(json.dumps(config), encoding='utf-8')
        (self.root / config['cert']).write_text('invalid-cert')
        wire = Wire()
        with self.assertRaises(pairing.PairingError):
            self.run_pair(wire)
        self.assertEqual(len(wire.requests), 1)

    def test_non_ascii_or_oversized_device_identity_is_rejected_before_staging(self):
        self.run_pair()
        target = self.root / 'device-sync.json'
        config = pairing.load_config(self.root)
        for device_id in ('设备', 'x' * 129):
            with self.subTest(device_id_kind='non-ASCII' if len(device_id) < 129 else 'oversized'):
                config['device_id'] = device_id
                pairing.atomic_json(target, config)
                before = target.read_bytes()
                wire = Wire()
                with self.assertRaises(pairing.PairingError):
                    self.run_pair(wire)
                self.assertEqual([r['op'] for r in wire.requests], ['pairing_status'])
                self.assertFalse((self.root / pairing.PENDING).exists())
                self.assertEqual(target.read_bytes(), before)

    def test_wrong_host_certificate_and_public_or_loopback_host_are_rejected(self):
        self.run_pair()
        config = pairing.load_config(self.root)
        config.update(host='192.168.1.21', allowed_hosts=['192.168.1.21'])
        pairing.atomic_json(self.root / 'device-sync.json', config)
        with self.assertRaises(pairing.PairingError):
            pairing.pair_device(Wire(), self.root, '192.168.1.21', timeout=.05)
        for host in ('127.0.0.1', '8.8.8.8', '192.168.1.20/path'):
            wire = Wire()
            with self.assertRaises(pairing.PairingError):
                pairing.pair_device(wire, self.root, host, timeout=.05)
            self.assertFalse(wire.requests)

    def test_unknown_device_error_and_duplicate_json_keys_are_not_echoed(self):
        wire = Wire(lambda c, r: {'id': c['id'], 'ok': False, 'saved': False,
                                 'restart_required': False, 'error': 'private-token-value'})
        with self.assertRaises(pairing.PairingError) as caught:
            pairing.pairing_status(wire, timeout=.05)
        self.assertNotIn('private-token-value', str(caught.exception))
        with self.assertRaises(ValueError):
            pairing.strict_json('{"ok":true,"ok":false}')

    def test_serial_opens_at_115200_without_reset_control_lines(self):
        class Port:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.opened = None
            def open(self):
                self.opened = self.dtr, self.rts, self.port
        import types
        with patch.dict('sys.modules', {'serial': types.SimpleNamespace(Serial=Port)}):
            port = pairing.open_serial('COM7')
        self.assertEqual(port.kwargs, {'port': None, 'baudrate': 115200, 'timeout': .1, 'write_timeout': 1})
        self.assertEqual(port.opened, (False, False, 'COM7'))


if __name__ == '__main__':
    unittest.main()
