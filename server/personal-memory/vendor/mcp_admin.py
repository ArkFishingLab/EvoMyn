"""Local MCP status and fixed lifecycle operations behind same-origin CSRF checks."""
import ast
import hmac
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from local_http import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from mcp_packages import Packages
from mcp_marketplace import Marketplace

WEB = Path(__file__).resolve().parent / 'mcp_admin_web'
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')
ACTIONS = {'start': 'Start', 'stop': 'Stop', 'restart': 'Restart'}


def stamp(value):
    try: return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError): return 0


class BusyError(Exception):
    pass


class Controller:
    def __init__(self, root, runner=None):
        self.root = Path(root).resolve()
        self.runner = runner or self._run
        self.lock = threading.Lock()
        self.packages = Packages(self.root / 'mcp-packages.json')
        self.market = Marketplace(self.root)
        self.installation = None

    def _run(self, action):
        if action not in ('Status', *ACTIONS.values()): raise ValueError('Unsupported action')
        shell = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
        if not shell: raise RuntimeError('Local process controller unavailable')
        # Start-Process descendants can retain inherited pipe handles on Windows.
        # Regular files let the short controller exit independently of the bridge.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(self.root / 'manage.ps1'), action, '-Json'], shell=False,
                stdin=subprocess.DEVNULL, stdout=output, stderr=error, timeout=35,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode: raise RuntimeError('Process operation failed')
            output.seek(0)
            value = json.loads(output.read(65536).decode('utf-8-sig').strip())
        if not isinstance(value, dict): raise RuntimeError('Invalid process status')
        return value

    def _events(self):
        events = []
        for name in ('events.jsonl.1', 'events.jsonl'):
            try:
                with (self.root / 'logs' / name).open('rb') as stream:
                    size = stream.seek(0, 2)
                    stream.seek(max(0, size - 2_100_000))
                    raw = stream.read().decode('utf-8', 'replace')
                for line in raw.splitlines():
                    try: event = json.loads(line)
                    except (ValueError, RecursionError): continue
                    if isinstance(event, dict): events.append(event)
            except OSError: pass
        return events

    def _tools(self):
        tools = {}
        for name in ('mcp_server.py', 'planner_tools.py', 'market_tools.py'):
            try: module = ast.parse((self.root / 'app' / name).read_text(encoding='utf-8'))
            except (OSError, SyntaxError): continue
            for node in ast.walk(module):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(('archive_', 'planner_', 'worldtime_')):
                    decorators = [item.func for item in node.decorator_list if isinstance(item, ast.Call)]
                    if any(isinstance(item, ast.Attribute) and item.attr == 'tool' for item in decorators):
                        tools[node.name] = (ast.get_docstring(node) or '').split('\n')[0][:150]
        return tools

    def status(self):
        try: probe = self.runner('Status')
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            probe = {'running': False, 'verified': False, 'probe_error': True}
        running = probe.get('running') is True and probe.get('verified') is True
        events = self._events()
        lifecycle = None
        registered = []
        calls = {}
        latest_session = None
        lifecycle_at = tools_at = 0
        try:
            checkpoint_path = self.root / 'logs/events.state.json'
            with checkpoint_path.open('rb') as stream:
                checkpoint = json.loads(stream.read(65536))
            if isinstance(checkpoint, dict):
                if checkpoint.get('lifecycle') in ('connected', 'disconnected') and stamp(checkpoint.get('lifecycle_at')) >= stamp(probe.get('started_utc')):
                    lifecycle, lifecycle_at = checkpoint['lifecycle'], stamp(checkpoint['lifecycle_at'])
                    latest_session = checkpoint.get('session')
                if isinstance(checkpoint.get('tools'), list):
                    registered = [name for name in checkpoint['tools'] if isinstance(name, str) and NAME.fullmatch(name)][:128]
                    tools_at = stamp(checkpoint.get('tools_at'))
        except (OSError, ValueError, RecursionError):
            pass
        for event in events:
            kind = event.get('kind')
            if kind in ('connected', 'disconnected') and stamp(event.get('at')) >= max(lifecycle_at, stamp(probe.get('started_utc'))):
                lifecycle = kind
                lifecycle_at = stamp(event.get('at'))
                if kind == 'connected': latest_session = event.get('session')
            if kind == 'tools' and isinstance(event.get('tools'), list) and stamp(event.get('at')) >= tools_at:
                registered = [name for name in event['tools'] if isinstance(name, str) and NAME.fullmatch(name)][:128]
                tools_at = stamp(event.get('at'))
            if kind in ('call_started', 'call_finished'):
                ident, tool = event.get('call_id'), event.get('tool')
                if not isinstance(ident, str) or not isinstance(tool, str) or not NAME.fullmatch(tool): continue
                status = event.get('status') if kind == 'call_finished' else 'running'
                if status not in ('running', 'success', 'error', 'interrupted'): status = 'unknown'
                duration = event.get('duration_ms')
                calls[ident] = {'at': event.get('at') if stamp(event.get('at')) else None, 'tool': tool,
                    'status': status, 'duration_ms': duration if type(duration) is int and 0 <= duration <= 86_400_000 else None,
                    'session': event.get('session')}
        connection = 'unknown' if probe.get('probe_error') else 'stopped' if not running else 'connected' if probe.get('tcp_connected') is True and lifecycle == 'connected' else 'connecting'
        history = sorted(calls.values(), key=lambda call: stamp(call['at']), reverse=True)
        for call in history:
            if call['status'] == 'running' and (not running or call['session'] != latest_session): call['status'] = 'interrupted'
            call.pop('session', None)
        metadata = self._tools()
        groups = self.packages.list()
        return {'running': running, 'connection': connection, 'process_id': probe.get('process_id') if running else None,
            'started_utc': probe.get('started_utc') if running else None, 'probe_error': bool(probe.get('probe_error')),
            'tool_count': len(registered), 'tools': [{'name': name, 'description': metadata.get(name, '')} for name in registered],
            'calls': history[:50], 'recent_call_count': len(history), 'busy': self.lock.locked(),
            'packages': groups, 'packages_error': self.packages.error,
            'catalog': self.packages.catalog(), 'installation': self.installation,
            'checked_at': datetime.now(timezone.utc).isoformat()}

    def install_package(self, ident):
        if ident != 'worldtime': raise ValueError('Unsupported installation')
        if not self.lock.acquire(blocking=False): raise BusyError()
        job = {'id': secrets.token_hex(12), 'package': ident, 'state': 'running', 'message': '正在安装世界时间…'}
        self.installation = job
        def progress(message): self.installation = {**job, 'message': message}
        def work():
            try:
                self.market.install(ident, progress=progress)
                self.installation = {**job, 'state': 'success', 'message': '世界时间已安装，可在我的能力中开启。'}
            except Exception:
                self.installation = {**job, 'state': 'error', 'message': '安装未完成，请检查网络后重试。'}
            finally: self.lock.release()
        try: threading.Thread(target=work, daemon=True).start()
        except Exception:
            self.lock.release()
            raise
        return self.status()

    def remove_package(self, ident):
        if ident != 'worldtime': raise ValueError('Built-in packages cannot be removed')
        if not self.lock.acquire(blocking=False): raise BusyError()
        try:
            state = self.status()
            if state['probe_error']: raise RuntimeError('Process status unavailable')
            self.market.remove(ident)
            if state['running']:
                probe = self.runner('Restart')
                if probe.get('running') is not True or probe.get('verified') is not True:
                    raise RuntimeError('MCP did not restart')
        finally: self.lock.release()
        return self.status()

    def set_package(self, ident, enabled):
        if not self.lock.acquire(blocking=False): raise BusyError()
        try:
            state = self.status()
            if state['probe_error']: raise RuntimeError('Process status unavailable')
            current = next((item for item in state['packages'] if item['id'] == ident), None)
            if current is None or type(enabled) is not bool: raise ValueError('Invalid package switch')
            if current['enabled'] != enabled or state['packages_error']:
                self.packages.set(ident, enabled)
            # A repeated request also repairs a previously failed cloud refresh.
            if state['running']:
                probe = self.runner('Restart')
                if probe.get('running') is not True or probe.get('verified') is not True:
                    raise RuntimeError('MCP did not restart')
        finally:
            self.lock.release()
        return self.status()

    def command(self, action):
        if action not in ACTIONS: raise ValueError('Unsupported action')
        if not self.lock.acquire(blocking=False): raise BusyError()
        try: self.runner(ACTIONS[action])
        finally: self.lock.release()
        state = self.status()
        if state['probe_error'] or (action == 'stop' and state['running']) or (action != 'stop' and not state['running']):
            raise RuntimeError('Process state did not reach the requested state')
        return state


def create_admin_server(controller, host='127.0.0.1', port=18772):
    sessions, lock = {}, threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def respond(self, value, code=200, kind='application/json; charset=utf-8', cookie=None):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            for key, val in [('Content-Type', kind), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
                ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]:
                self.send_header(key, val)
            if cookie: self.send_header('Set-Cookie', cookie)
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(body)
        def valid_host(self):
            try: return urlsplit('http://' + self.headers.get('Host', '')).hostname in ('127.0.0.1', 'localhost')
            except ValueError: return False
        def do_GET(self):
            if not self.valid_host(): return self.respond({'error': 'Invalid host'}, 403)
            path = urlsplit(self.path).path
            if path == '/api/session':
                sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with lock:
                    for key in list(sessions):
                        if sessions[key][1] < time.time(): del sessions[key]
                    if len(sessions) >= 128: sessions.pop(next(iter(sessions)))
                    sessions[sid] = (csrf, time.time() + 28800)
                return self.respond({'csrf': csrf}, cookie='mcp_session=' + sid + '; Path=/memory/mcp/; HttpOnly; SameSite=Strict; Max-Age=28800')
            if path == '/api/status': return self.respond(controller.status())
            if path == '/api/catalog': return self.respond({'items': controller.packages.catalog(),
                'registry': 'https://registry.modelcontextprotocol.io/'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8')}
            if path not in files: return self.respond({'error': 'Not found'}, 404)
            name, kind = files[path]
            try: return self.respond((WEB / name).read_bytes(), kind=kind)
            except OSError: return self.respond({'error': 'Unavailable'}, 503)
        def do_POST(self):
            try: size = int(self.headers.get('Content-Length', '0'))
            except ValueError: return self.respond({'error': 'Invalid body'}, 400)
            if not 0 <= size <= 4096:
                self.close_connection = True
                return self.respond({'error': 'Too large'}, 413)
            cookie = SimpleCookie()
            try: cookie.load(self.headers.get('Cookie', ''))
            except Exception: return self.respond({'error': 'Invalid session'}, 403)
            sid = cookie.get('mcp_session')
            with lock: session = sessions.get(sid.value if sid else '')
            if not self.valid_host() or self.headers.get('Origin') != 'http://' + self.headers.get('Host', '') or not session or session[1] < time.time() or not hmac.compare_digest(session[0], self.headers.get('X-CSRF-Token', '')):
                self.close_connection = True
                return self.respond({'error': 'Session and same-origin CSRF token required'}, 403)
            path = urlsplit(self.path).path
            if path not in ('/api/command', '/api/packages', '/api/install', '/api/remove'): return self.respond({'error': 'Not found'}, 404)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': return self.respond({'error': 'JSON required'}, 415)
            try:
                value = json.loads(self.rfile.read(size))
                if path in ('/api/install', '/api/remove'):
                    if not isinstance(value, dict) or set(value) != {'package'}: raise ValueError()
                    operation = controller.install_package if path == '/api/install' else controller.remove_package
                    return self.respond(operation(value['package']))
                if path == '/api/packages':
                    if not isinstance(value, dict) or set(value) != {'package', 'enabled'}: raise ValueError()
                    return self.respond(controller.set_package(value['package'], value['enabled']))
                if not isinstance(value, dict) or set(value) != {'action'} or value['action'] not in ACTIONS: raise ValueError()
                return self.respond(controller.command(value['action']))
            except (ValueError, TypeError, RecursionError): return self.respond({'error': 'Invalid operation'}, 400)
            except BusyError: return self.respond({'error': 'Another operation is running'}, 409)
            except (OSError, RuntimeError, subprocess.SubprocessError): return self.respond({'error': 'Operation failed; refresh status before retrying'}, 503)
        def do_HEAD(self): self.do_GET()
    return ThreadingHTTPServer((host, port), Handler)
