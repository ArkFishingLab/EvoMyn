"""Loopback front door for the archive, setup and capability management."""
import importlib.util
import os
import sys
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / 'app/.env', override=True)
os.environ['PERSONAL_ARCHIVE_HOME'] = str(ROOT / 'state')
os.environ.setdefault('PLANNER_OWNER', 'device')
sys.path.insert(0, str(ROOT / 'app'))
from local_http import ThreadingHTTPServer
from mcp_packages import planner_owner
PLANNER_OWNER = planner_owner()
from mcp_admin import Controller, create_admin_server

spec = importlib.util.spec_from_file_location('local_archive_viewer', ROOT / 'viewer/server.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def build_device_gateway(root):
    """Optional device-only HTTPS listener; no model load or environment mutation."""
    keys = ('DEVICE_GATEWAY_HOST', 'DEVICE_GATEWAY_PORT', 'DEVICE_GATEWAY_CERT',
            'DEVICE_GATEWAY_KEY', 'DEVICE_GATEWAY_ALLOWED_HOSTS', 'DEVICE_UPDATE_DIR')
    if not any(os.environ.get(key) for key in keys):
        return None
    host = os.environ.get('DEVICE_GATEWAY_HOST', '').strip()
    certificate = os.environ.get('DEVICE_GATEWAY_CERT', '')
    private_key = os.environ.get('DEVICE_GATEWAY_KEY', '')
    if not host or not certificate or not private_key:
        raise ValueError('Device gateway requires HOST, CERT and KEY')
    import ssl
    from device_gateway import create_device_server
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    configured_hosts = os.environ.get('DEVICE_GATEWAY_ALLOWED_HOSTS', '')
    allowed_hosts = {item.strip() for item in configured_hosts.split(',') if item.strip()} if configured_hosts else {host}
    update_provider = None
    if os.environ.get('DEVICE_UPDATE_DIR'):
        from device_updates import ReleaseProvider
        update_provider = ReleaseProvider(os.environ['DEVICE_UPDATE_DIR'])
    return create_device_server(host=host, port=int(os.environ.get('DEVICE_GATEWAY_PORT', '18773')),
        tls_context=context, token=os.environ.get('PLANNER_DEVICE_TOKEN', ''),
        device=os.environ.get('PLANNER_DEVICE_ID', ''), allowed_hosts=allowed_hosts, update_provider=update_provider,
        archive_root=os.environ.get('PERSONAL_ARCHIVE_HOME', str(root / 'state')))


def build_planner_services(owner):
    """Device ownership never opens or migrates the PC planner database."""
    if owner == 'device':
        return None, None, None
    if owner != 'pc':
        raise ValueError('PLANNER_OWNER must be pc or device')
    token = os.environ.get('PLANNER_DEVICE_TOKEN', '')
    if len(token) < 64:
        raise RuntimeError('A private device token is required for reminder synchronization')
    from planner_store import PlannerStore
    import planner_server as planner_backend
    from planner_server import create_http_server, create_websocket_server
    store = PlannerStore()
    planner = create_http_server(store, host='127.0.0.1', port=int(os.environ.get('PLANNER_PORT', '18769')), secure_cookie=False)
    original_message = planner_backend.process_device_message
    def observed_message(store, device, raw):
        result = original_message(store, device, raw)
        import json
        message = json.loads(raw)
        if message.get('type') == 'ack':
            print('DEVICE_ACK revision=' + str(message.get('revision')) + ' reminders=' + str(len(message.get('ids', []))), flush=True)
        return result
    planner_backend.process_device_message = observed_message
    try:
        device_server = create_websocket_server(store, '127.0.0.1', int(os.environ.get('PLANNER_WS_PORT', '18771')), token,
            os.environ['PLANNER_DEVICE_ID'], {'localhost', '127.0.0.1'})
    except Exception:
        planner.server_close()
        raise
    return store, planner, device_server


class Dashboard(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def forward(self):
        host = self.headers.get('Host', '')
        front_port = int(os.environ.get('DASHBOARD_PORT', '18768'))
        if host not in ('127.0.0.1:' + str(front_port), 'localhost:' + str(front_port)):
            return self.send_error(403)
        path = urlsplit(self.path).path
        if path == '/healthz' and self.command in ('GET', 'HEAD'):
            import json
            body = json.dumps({'ok': True, 'service': 'personal-memory-mcp', 'pid': os.getpid(),
                               'instance': os.environ.get('MCP_LAUNCH_INSTANCE', '')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(body)
            return
        if path == '/setup':
            self.send_response(302)
            self.send_header('Location', '/setup/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if path.startswith('/setup/'):
            setup = getattr(self.server, 'setup', None)
            return setup.handle(self) if setup is not None else self.send_error(503)
        if PLANNER_OWNER == 'device' and (path == '/memory/planner' or path.startswith('/memory/planner/')):
            body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                    '<title>计划已迁移到圆盘</title><p>计划提醒已迁移到圆盘，PC 仅接收完成日志。</p>'
                    '<p>请在圆盘上查看或管理计划。</p><a href="/memory/">返回记忆档案</a></html>').encode('utf-8')
            self.close_connection = True
            self.send_response(410)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(body)
            return
        if path in ('/', '/memory', '/memory/planner', '/memory/mcp'):
            self.send_response(302)
            self.send_header('Location', path + '/' if path in ('/memory/planner', '/memory/mcp') else '/memory/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if path.startswith('/memory/mcp/'):
            port, tail = int(os.environ.get('ADMIN_PORT', '18772')), self.path[len('/memory/mcp'):]
        elif path.startswith('/memory/planner/'):
            port, tail = int(os.environ.get('PLANNER_PORT', '18769')), self.path[len('/memory/planner'):]
        elif path.startswith('/memory/'):
            port, tail = int(os.environ.get('ARCHIVE_PORT', '18770')), self.path[len('/memory'):]
        else:
            return self.send_error(404)
        body = None
        uploading = path == '/memory/api/attachments'
        if self.command == 'POST':
            if len(self.headers.get_all('Content-Length', [])) != 1 or self.headers.get_all('Transfer-Encoding') or any(len(self.headers.get_all(name, [])) > 1 for name in ('Host', 'Origin', 'X-CSRF-Token', 'X-File-Name')):
                self.close_connection = True
                return self.send_error(400)
            if uploading:
                try:
                    origin = urlsplit(self.headers.get('Origin', ''))
                    valid = (origin.scheme in ('http', 'https') and origin.netloc == host
                        and self.headers.get('Sec-Fetch-Site') != 'cross-site'
                        and bool(self.headers.get('X-CSRF-Token'))
                        and 0 < len(self.headers.get('X-File-Name', '')) <= 1024)
                except ValueError: valid = False
                if not valid:
                    self.close_connection = True
                    return self.send_error(403)
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/octet-stream':
                    self.close_connection = True
                    return self.send_error(415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.send_error(400)
            limit = 50 * 1024 * 1024 if uploading else 4096 if path.startswith('/memory/mcp/') else 65536
            if not 0 <= size <= limit:
                self.close_connection = True
                return self.send_error(413)
            if uploading:
                body = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
                try:
                    remaining, deadline = size, time.monotonic() + 60
                    while remaining:
                        budget = deadline - time.monotonic()
                        if budget <= 0: raise TimeoutError()
                        self.connection.settimeout(min(15, budget))
                        block = self.rfile.read1(min(65536, remaining))
                        if not block: raise ConnectionError()
                        body.write(block); remaining -= len(block)
                    body.seek(0)
                except (OSError, TimeoutError, ConnectionError):
                    body.close(); self.close_connection = True
                    return self.send_error(408)
            else:
                body = self.rfile.read(size)
        headers = {key: self.headers[key] for key in ('Host', 'Origin', 'Cookie', 'Content-Type', 'X-CSRF-Token', 'X-File-Name', 'Sec-Fetch-Site') if key in self.headers}
        if self.command == 'POST': headers['Content-Length'] = str(size)
        request = Request('http://127.0.0.1:' + str(port) + tail, data=body, headers=headers, method=self.command)
        try:
            try:
                response = urlopen(request, timeout=115 if path.startswith('/memory/mcp/') else 65 if uploading else 15)
            except HTTPError as error:
                response = error
            with response:
                data = response.read()
                self.send_response(response.status)
                for key in ('Content-Type', 'Cache-Control', 'Content-Security-Policy', 'X-Content-Type-Options', 'Content-Disposition', 'Set-Cookie', 'Referrer-Policy'):
                    for value in response.headers.get_all(key, []):
                        self.send_header(key, value)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(data)
        except (URLError, TimeoutError, ConnectionError):
            self.send_error(503)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if uploading and body is not None: body.close()

    do_GET = do_HEAD = do_POST = forward


def main():
    from archive_store import ArchiveStore
    from onboarding import Setup
    store = ArchiveStore()
    controller = Controller(ROOT)
    ports = [int(os.environ.get(name, default)) for name, default in
             [('DASHBOARD_PORT', '18768'), ('ARCHIVE_PORT', '18770'), ('ADMIN_PORT', '18772')]]
    if any(not 1 <= port <= 65535 for port in ports) or len(set(ports)) != len(ports):
        raise ValueError('Dashboard ports must be distinct values in 1..65535')
    frontend = ThreadingHTTPServer(('127.0.0.1', ports[0]), Dashboard)
    frontend.setup = Setup(ROOT, controller)
    servers = []
    started = []
    try:
        servers.append(viewer.create_server(store.db_path, host='127.0.0.1', port=ports[1], record_store=store))
        _, planner, device_server = build_planner_services(PLANNER_OWNER)
        servers.extend(server for server in (planner, device_server) if server is not None)
        servers.append(create_admin_server(controller, port=ports[2]))
        gateway = build_device_gateway(ROOT)
        if gateway is not None: servers.append(gateway)
        for server in servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            started.append(server)
        print('Local dashboard ready: http://127.0.0.1:' + str(ports[0]) + '/memory/', flush=True)
        frontend.serve_forever()
    finally:
        for server in started: server.shutdown()
        for server in servers: server.server_close()
        frontend.server_close()


if __name__ == '__main__': main()
