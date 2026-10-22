import datetime
import http.client
import json
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from test_device_archive import EVENT, VENDOR, isolated_store
from device_gateway import DeviceHandler, create_device_server

TOKEN = 't' * 64


class DeviceGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certs = tempfile.TemporaryDirectory()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
        cls.cert_path = Path(cls.certs.name) / 'cert.pem'; cls.key_path = Path(cls.certs.name) / 'key.pem'
        cls.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        cls.key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    @classmethod
    def tearDownClass(cls): cls.certs.cleanup()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = isolated_store(self.tmp.name)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert_path, self.key_path)
        self.server = create_device_server(host='127.0.0.1', port=0, tls_context=context,
                          token=TOKEN, device='dev1', store=self.store, allowed_hosts={'localhost'})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()
    def request(self, method='POST', path='/device/archive', body=None, **headers):
        if body is None: body = json.dumps(EVENT, ensure_ascii=False).encode()
        h = {'Host': 'localhost', 'Authorization': 'Bearer ' + TOKEN, 'Device-Id': 'dev1',
             'Content-Type': 'application/json', **headers}
        c = http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                                       context=ssl._create_unverified_context(), timeout=4)
        c.request(method, path, body, h); response = c.getresponse()
        result = response.status, dict(response.getheaders()), response.read(); c.close(); return result

    def test_https_success_retry_conflict_and_no_cors(self):
        code, headers, raw = self.request()
        self.assertEqual(code, 200); first = json.loads(raw)
        self.assertTrue(first['ok']); self.assertEqual(first['index_status'], 'pending')
        self.assertEqual(json.loads(self.request()[2]), first)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request(body=json.dumps({**EVENT, 'title': 'changed'}))[0], 409)
        self.assertEqual(len(self.store.history(first['record_id'])), 1)

    def test_https_whitespace_original_body_has_durable_replay_and_conflict(self):
        event = {**EVENT, 'body': ' \t'}
        code, _, raw = self.request(body=json.dumps(event))
        self.assertEqual(code, 200)
        result = json.loads(raw)
        self.assertEqual(json.loads(self.request(body=json.dumps(event))[2]), result)
        record = self.store.get(result['record_id'])
        self.assertEqual(record['fields']['body'], event['body'])
        self.assertEqual(record['body'], event['title'])
        self.assertEqual(self.request(body=json.dumps({**event, 'body': ' '}))[0], 409)
        self.assertEqual(len(self.store.history(result['record_id'])), 1)

    def test_strict_authorization_host_origin_path_and_method(self):
        for headers in ({'Authorization': ''}, {'Authorization': 'Bearer ' + 'x' * 64},
                        {'Device-Id': 'other'}, {'Host': 'evil.example'},
                        {'Origin': 'https://localhost'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=list(headers)):
                self.assertIn(self.request(**headers)[0], (401, 403))
        for path in ('/other', '/device/archive?x=1', '//device/archive'):
            self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.request(method='GET')[0], 404)
        self.assertEqual(self.request(method='OPTIONS')[0], 405)
        self.assertFalse(self.store.list())

    def test_rejects_bad_media_framing_depth_duplicates_and_utf8(self):
        cases = [(b'{}', {'Content-Type': 'text/plain'}, 415),
                 (b'x' * 16385, {}, 413), (b'{}', {'Transfer-Encoding': 'chunked'}, 400),
                 (b'{}', {'Content-Length': '-1'}, 400),
                 (b'[' * 3000 + b'0' + b']' * 3000, {}, 400),
                 (b'{"event_id":"one","event_id":"two"}', {}, 400),
                 (b'\xff', {}, 400), (b'NaN', {}, 400)]
        for body, headers, expected in cases:
            with self.subTest(expected=expected, body=body[:20]):
                self.assertEqual(self.request(body=body, **headers)[0], expected)
        self.assertEqual(self.request()[0], 200)

    def test_disk_error_never_returns_ok_or_exception_details(self):
        with patch.object(self.store, 'save', side_effect=OSError('PRIVATE_PATH SECRET')):
            code, _, body = self.request()
        self.assertEqual(code, 503); self.assertNotIn(b'PRIVATE', body); self.assertFalse(json.loads(body)['ok'])

    def test_authenticated_fixed_update_extension(self):
        calls = []
        def provider(path):
            calls.append(path)
            if path == '/updates/manifest': return b'{"version":"test"}', 'application/json'
            if path == '/updates/firmware/' + 'a' * 64 + '.bin': return b'firmware', 'application/octet-stream'
            return None
        self.server.update_provider = provider
        self.assertEqual(self.request('GET', '/updates/manifest', b'')[0], 200)
        self.assertEqual(self.request('GET', '/updates/firmware/' + 'a' * 64 + '.bin', b'')[2], b'firmware')
        self.assertEqual(self.request('GET', '/updates/manifest', b'', Authorization='bad')[0], 401)
        self.assertEqual(self.request('GET', '/updates/../private', b'')[0], 404)
        self.assertEqual(len(calls), 2)

    def test_real_release_provider_uses_authenticated_https_routes(self):
        from device_updates import ReleaseProvider, publish_release
        from test_device_updates import firmware
        build = Path(self.tmp.name) / 'firmware.bin'; build.write_bytes(firmware())
        output = Path(self.tmp.name) / 'releases'
        manifest = publish_release(build, output, version='1.2.3', notes='isolated release')
        self.server.update_provider = ReleaseProvider(output)
        status, _, raw = self.request('GET', '/updates/manifest', b'')
        self.assertEqual(status, 200); self.assertEqual(json.loads(raw), manifest)
        self.assertEqual(self.request('GET', manifest['url'], b'')[2], build.read_bytes())
        (output / (manifest['sha256'] + '.bin')).write_bytes(b'tampered')
        self.assertEqual(self.request('GET', '/updates/manifest', b'')[0], 503)

    def test_requires_tls_and_strong_nonempty_configuration(self):
        for changes in ({'tls_context': None}, {'token': 'short'}, {'device': ''}, {'allowed_hosts': set()}):
            kwargs = dict(host='127.0.0.1', port=0, tls_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER),
                          token=TOKEN, device='dev1', store=self.store, allowed_hosts={'localhost'})
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                create_device_server(**{**kwargs, **changes})

    def test_import_does_not_load_models(self):
        code = "import sys; sys.path.insert(0, sys.argv[1]); import device_gateway; assert 'mnemosyne' not in sys.modules; assert 'archive_store' not in sys.modules"
        result = subprocess.run([sys.executable, '-c', code, str(VENDOR)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

class BinaryReplyBackpressureTests(unittest.TestCase):
    def handler(self, *, rate):
        # Socket sendall's timeout covers the whole call, even while the peer
        # makes progress. Model that deadline without network sleeps/flakiness.
        clock = [0.0]
        class Connection:
            timeout = 10.0
            timeouts = []
            def gettimeout(self): return self.timeout
            def settimeout(self, value): self.timeout = value; self.timeouts.append(value)
        connection = Connection()
        class SlowSocketWriter:
            def __init__(self): self.calls = []; self.delivered = bytearray()
            def write(self, data):
                duration = len(data) / rate
                if connection.timeout is not None and duration > connection.timeout:
                    clock[0] += connection.timeout
                    raise TimeoutError('sendall cumulative deadline exceeded')
                clock[0] += duration
                self.calls.append(len(data)); self.delivered.extend(data)
                return len(data)
        writer = SlowSocketWriter()
        handler = DeviceHandler.__new__(DeviceHandler)
        handler.command = 'GET'; handler.connection = connection; handler.wfile = writer
        handler.headers_sent = {}
        handler.send_response = lambda status: None
        handler.send_header = lambda key, value: handler.headers_sent.__setitem__(key, value)
        handler.end_headers = lambda: None
        return handler, writer, connection, clock

    def test_binary_slow_peer_exceeds_one_write_timeout_but_completes_chunks(self):
        body = b'firmware-data' * 300000  # 3.9 MB, within the OTA slot.
        handler, writer, connection, clock = self.handler(rate=128 * 1024)
        with self.assertRaises(TimeoutError): writer.write(body)
        self.assertEqual(clock[0], 10.0)
        clock[0] = 0.0
        with patch('time.monotonic', side_effect=lambda: clock[0]):
            handler.reply(200, body=body, content_type='application/octet-stream')
        self.assertEqual(bytes(writer.delivered), body)
        self.assertGreater(clock[0], 10.0)
        self.assertGreater(len(writer.calls), 1)
        self.assertLessEqual(max(writer.calls), 8192)
        self.assertEqual(handler.headers_sent['Content-Length'], str(len(body)))
        self.assertEqual(connection.gettimeout(), 10.0)

    def test_binary_total_transfer_deadline_is_bounded_at_300_seconds(self):
        body = b'x' * (4 * 1024 * 1024)
        handler, writer, connection, clock = self.handler(rate=5000)
        with patch('time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                handler.reply(200, body=body, content_type='application/octet-stream')
        self.assertAlmostEqual(clock[0], 300.0)
        self.assertLess(min(connection.timeouts), 1.0)
        self.assertGreater(len(writer.calls), 1)
        self.assertLess(len(writer.delivered), len(body))
        self.assertTrue(all(0 < timeout <= 10 for timeout in connection.timeouts))
        self.assertEqual(connection.gettimeout(), 10.0)

    def test_json_reply_keeps_one_write_and_original_timeout(self):
        handler, writer, connection, clock = self.handler(rate=128 * 1024)
        handler.reply(200, {'ok': True, 'event_id': 'stable'})
        self.assertEqual(json.loads(writer.delivered), {'ok': True, 'event_id': 'stable'})
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(connection.timeouts, [])


if __name__ == '__main__': unittest.main()
