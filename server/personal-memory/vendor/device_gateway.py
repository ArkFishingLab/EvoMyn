"""Private HTTPS device gateway with one completion route and fixed OTA read hooks."""
import hmac
import json
import os
import re
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler
from local_http import ThreadingHTTPServer

from device_archive import DeviceArchive, EventConflict

MAX_BODY = 16384
DEVICE_SOCKET_TIMEOUT = 10.0
BINARY_CHUNK_SIZE = 8192
BINARY_TRANSFER_TIMEOUT = 300.0
UPDATE_PATH = re.compile(r'/updates/firmware/[0-9a-f]{64}\.bin\Z')


def _decode_event(raw):
    text = raw.decode('utf-8', errors='strict')
    depth = 0; quoted = False; escaped = False
    for character in text:
        if quoted:
            if escaped: escaped = False
            elif character == '\\': escaped = True
            elif character == '"': quoted = False
        elif character == '"': quoted = True
        elif character in '[{':
            depth += 1
            if depth > 4: raise ValueError('JSON nesting exceeds limit')
        elif character in ']}': depth -= 1
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value): raise ValueError('Invalid JSON constant')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


class DeviceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    # POSIX keeps accepted connections in TIME_WAIT after an OTA restart.
    # SO_REUSEADDR permits rebinding that closed listener, not stealing a live
    # listener. Preserve Windows' exclusive binding behavior.
    allow_reuse_address = os.name != 'nt'

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(DEVICE_SOCKET_TIMEOUT)
        try:
            # Handshake happens in the request worker, keeping accept responsive.
            connection = self.tls_context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
        except Exception:
            connection.close()
            raise
        return connection, address

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()

    def handle_error(self, request, client_address):
        # Never log device payloads, credentials, or private filesystem errors.
        pass


class DeviceHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'DeviceGateway'
    sys_version = ''

    def log_message(self, *_): pass

    def reply(self, status, value=None, *, body=None, content_type='application/json'):
        if body is None:
            body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.close_connection = True
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command == 'HEAD': return
        if content_type != 'application/octet-stream':
            self.wfile.write(body)
            return
        # _SocketWriter uses sendall: its timeout covers an entire write even
        # while a slow ESP peer keeps reading/committing flash. Bound each
        # write, then independently bound the complete transfer.
        original_timeout = self.connection.gettimeout()
        write_timeout = DEVICE_SOCKET_TIMEOUT if original_timeout is None else min(DEVICE_SOCKET_TIMEOUT, original_timeout)
        deadline = time.monotonic() + BINARY_TRANSFER_TIMEOUT
        data = memoryview(body)
        try:
            for offset in range(0, len(data), BINARY_CHUNK_SIZE):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Firmware transfer deadline exceeded')
                self.connection.settimeout(min(write_timeout, remaining))
                self.wfile.write(data[offset:offset + BINARY_CHUNK_SIZE])
        finally:
            self.connection.settimeout(original_timeout)

    def error(self, status, message):
        return self.reply(status, {'ok': False, 'error': message})

    def authorized(self):
        for key in ('Host', 'Authorization', 'Device-Id'):
            if len(self.headers.get_all(key, [])) != 1:
                self.error(401 if key != 'Host' else 403, 'Unauthorized request')
                return False
        if self.headers['Host'].lower() not in self.server.allowed_hosts:
            self.error(403, 'Host forbidden'); return False
        if 'Origin' in self.headers or self.headers.get('Sec-Fetch-Site', '') not in ('', 'none'):
            self.error(403, 'Browser requests forbidden'); return False
        authorization = self.headers['Authorization']
        device = self.headers['Device-Id']
        # Compare bytes so non-ASCII input is safely rejected without TypeError.
        if (not hmac.compare_digest(authorization.encode('utf-8'), self.server.authorization)
                or not hmac.compare_digest(device.encode('utf-8'), self.server.device.encode('utf-8'))):
            self.error(401, 'Unauthorized request'); return False
        return True

    def do_POST(self):
        if not self.authorized(): return
        if not self.server.archive_enabled:
            return self.error(410, 'Device archive synchronization has been retired')
        if self.requestline.split()[1] != '/device/archive': return self.error(404, 'Route not found')
        if 'Transfer-Encoding' in self.headers or len(self.headers.get_all('Content-Length', [])) != 1:
            return self.error(400, 'Invalid request framing')
        length = self.headers['Content-Length']
        if not re.fullmatch(r'[0-9]{1,8}', length): return self.error(400, 'Invalid content length')
        size = int(length)
        if size > MAX_BODY: return self.error(413, 'Request too large')
        if len(self.headers.get_all('Content-Type', [])) != 1:
            return self.error(415, 'JSON required')
        media = self.headers['Content-Type'].lower().replace(' ', '')
        if media not in ('application/json', 'application/json;charset=utf-8'):
            return self.error(415, 'JSON required')
        try:
            raw = self.rfile.read(size)
            if len(raw) != size: raise ValueError('Incomplete body')
            event = _decode_event(raw)
            result = self.server.archive.receive(event, self.server.device)
        except EventConflict:
            return self.error(409, 'Event conflicts with saved completion')
        except (ValueError, UnicodeError, RecursionError):
            return self.error(400, 'Invalid completion event')
        except Exception:
            return self.error(503, 'Archive unavailable; retry the same event')
        if self.server.receipt_observer is not None:
            try:
                self.server.receipt_observer()
            except Exception:
                pass  # Optional status metadata must never invalidate a durable ACK.
        return self.reply(200, result)

    def do_GET(self):
        if not self.authorized(): return
        path = self.requestline.split()[1]
        if path != '/updates/manifest' and not UPDATE_PATH.fullmatch(path):
            return self.error(404, 'Route not found')
        provider = self.server.update_provider
        if provider is None: return self.error(404, 'Route not found')
        try:
            result = provider(path)
            if result is None: return self.error(404, 'Update not found')
            body, media = result
            if not isinstance(body, bytes) or media not in ('application/json', 'application/octet-stream'):
                raise ValueError('Invalid update response')
        except Exception:
            return self.error(503, 'Update unavailable')
        return self.reply(200, body=body, content_type=media)

    def unsupported(self): return self.error(405, 'Method not allowed')
    do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_PATCH = unsupported


def create_device_server(*, host, port, tls_context, token, device, store=None,
                         archive_root=None, allowed_hosts=None, update_provider=None, receipt_observer=None,
                         archive_enabled=True):
    """Return a stopped server; provider(path) may return (bytes, media_type).

    Only fixed authenticated OTA paths reach the provider. It must map hashes to
    trusted artifacts itself. No route interprets supplied paths or commands.
    """
    if not isinstance(tls_context, ssl.SSLContext): raise ValueError('TLS context is required')
    if not isinstance(token, str) or len(token) < 64 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('A private device token of at least 64 ASCII characters is required')
    if not isinstance(device, str) or not device or len(device.encode('utf-8')) > 128 or any(c.isspace() for c in device):
        raise ValueError('A fixed device identity is required')
    hosts = {host} if allowed_hosts is None else set(allowed_hosts)
    if not hosts or any(not isinstance(item, str) or not item or item in ('0.0.0.0', '::', '*') for item in hosts):
        raise ValueError('Explicit device gateway Host whitelist is required')
    tls_context.minimum_version = max(tls_context.minimum_version, ssl.TLSVersion.TLSv1_2)
    server = DeviceHTTPServer((host, port), DeviceHandler, bind_and_activate=False)
    server.tls_context = tls_context
    server.device = device
    server.authorization = ('Bearer ' + token).encode('ascii')
    server.archive_enabled = archive_enabled
    server.archive = DeviceArchive(store=store, archive_root=archive_root) if archive_enabled else None
    server.update_provider = update_provider
    server.receipt_observer = receipt_observer
    server.workers = threading.BoundedSemaphore(16)
    try:
        server.server_bind()
        server.server_activate()
        server.allowed_hosts = {item.lower() for item in hosts}
        server.allowed_hosts.update(item.lower() + ':' + str(server.server_port) for item in hosts if ':' not in item)
    except Exception:
        server.server_close()
        raise
    return server
