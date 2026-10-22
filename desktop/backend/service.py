"""JSON-lines supervisor for the installed Windows desktop application."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

from client import DesktopOwner, LIMIT, loopback_open
from paths import atomic_json, environment, prepare, private_permissions, reject_links


class OwnedProcess:
    """Retain the Popen handle and own descendants, including venv redirectors."""
    def __init__(self, command, *, env, cwd, pipes=False):
        self.job = None
        self.process = subprocess.Popen(command, cwd=cwd, env=env,
            stdin=subprocess.PIPE if pipes else subprocess.DEVNULL,
            stdout=subprocess.PIPE if pipes else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1,
            # CPython closes CreateProcess's primary-thread handle internally.
            # Keep the process suspended until its whole descendant tree is
            # contained, then reopen/resume that primary thread below.
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | (0x4 if os.name == 'nt' else 0),
            start_new_session=os.name != 'nt')
        if os.name == 'nt':
            try:
                self._assign_job()
                self._resume_primary_thread()
            except Exception:
                self.stop()
                raise RuntimeError('Could not isolate an owned child process') from None

    def _assign_job(self):
        import ctypes
        from ctypes import wintypes
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Basic(ctypes.Structure):
            _fields_ = [('per_process', ctypes.c_longlong), ('per_job', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise OSError()
        try:
            info = Extended()
            info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle, int(self.process._handle)):
                raise OSError()
            self.job = (kernel, handle)
        except BaseException:
            kernel.CloseHandle(handle)
            raise

    def _resume_primary_thread(self):
        import ctypes
        from ctypes import wintypes
        class ThreadEntry(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                ('thread', wintypes.DWORD), ('process', wintypes.DWORD),
                ('base_priority', wintypes.LONG), ('delta_priority', wintypes.LONG),
                ('flags', wintypes.DWORD)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenThread.restype = wintypes.HANDLE
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError('Could not inspect the suspended process')
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.process == self.process.pid:
                    thread = kernel.OpenThread(0x2, False, entry.thread)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise OSError('Could not open the suspended primary thread')
                    try:
                        if kernel.ResumeThread(thread) != 1:
                            raise OSError('Could not resume the suspended primary thread')
                        return
                    finally:
                        kernel.CloseHandle(thread)
                found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError('Suspended primary thread was not found')
        finally:
            kernel.CloseHandle(snapshot)

    def stop(self):
        process = self.process
        if self.job:
            kernel, handle = self.job
            kernel.CloseHandle(handle)
            self.job = None
        elif process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        if os.name == 'nt':
            process._handle.Close()


def bounded_read(stream, timeout=120):
    result = queue.Queue(maxsize=1)
    def read():
        try:
            result.put(stream.readline(LIMIT + 1))
        except (OSError, ValueError):
            result.put('')
    threading.Thread(target=read, daemon=True).start()
    line = result.get(timeout=timeout)
    if not line or len(line.encode('utf-8')) > LIMIT:
        raise RuntimeError('Owned execution worker unavailable')
    return json.loads(line)


class Supervisor:
    def __init__(self, app_dir, root):
        from filelock import FileLock
        self.root = reject_links(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lockfile = FileLock(str(reject_links(self.root / 'desktop.lock')), timeout=0)
        self.lockfile.acquire()
        self.worker = self.bridge = self.dashboard = self.http = self.ota = None
        self.ota_status = None
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        self.ready = False
        self.instance = uuid.uuid4().hex
        self.descriptor = self.root / 'desktop-session.json'
        try:
            prepare(app_dir, self.root)
            self.settings_path = self.root / 'desktop-settings.json'
            reject_links(self.settings_path)
            try:
                settings = json.loads(self.settings_path.read_text('utf-8'))
            except FileNotFoundError:
                settings = {'mcp_enabled': True, 'cloud_enabled': False}
            if not isinstance(settings, dict) or set(settings) != {'mcp_enabled', 'cloud_enabled'} or any(type(value) is not bool for value in settings.values()):
                raise ValueError('Desktop preferences are invalid')
            self.settings = settings
            self.token = secrets.token_urlsafe(48)
            self.http = self._rpc_server()
            self.rpc_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
            self.rpc_thread.start()
            owner = DesktopOwner(os.getpid())
            try:
                if not owner.alive():
                    raise RuntimeError('Could not establish desktop owner identity')
                atomic_json(self.descriptor, {'url': f'http://127.0.0.1:{self.http.server_port}/rpc',
                    'token': self.token, 'instance': self.instance,
                    'owner_pid': os.getpid(), 'owner_created': owner.created})
            finally:
                owner.close()
            self.env = environment(self.root)
            # Import only reviewed runtime modules, never inherited PYTHONPATH.
            sys.path.insert(0, str(self.root / 'app'))
            # Reserve all three ephemeral loopback listeners together so they
            # are distinct, then hand them to the fixed dashboard child.
            sockets = [socket.socket() for _ in range(3)]
            try:
                for listener in sockets:
                    listener.bind(('127.0.0.1', 0))
                ports = [listener.getsockname()[1] for listener in sockets]
            finally:
                for listener in sockets:
                    listener.close()
            self.env.update(dict(zip(('DASHBOARD_PORT', 'ARCHIVE_PORT', 'ADMIN_PORT'), map(str, ports))))
            self.env['MCP_LAUNCH_INSTANCE'] = self.instance
            self.base_url = f'http://127.0.0.1:{ports[0]}'
            self.dashboard = self.spawn('dashboard')
            deadline = time.monotonic() + 35
            while True:
                try:
                    with loopback_open(self.base_url + '/healthz', timeout=1) as response:
                        health = json.loads(response.read(4096))
                        if health.get('instance') == self.instance:
                            break
                except (OSError, ValueError):
                    pass
                if self.dashboard.process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Dashboard failed to start')
                time.sleep(0.1)
            if self.settings['mcp_enabled']:
                self.start_worker()
            self.refresh_bridge()
            self.refresh_ota()
            self.ready = True
        except Exception:
            self.close()
            raise

    def spawn(self, role, pipes=False):
        return OwnedProcess([sys.executable, '-E', '-s', '-X', 'utf8', '-u', str(Path(__file__).with_name('host.py')),
            '--role', role, '--data-root', str(self.root), '--instance', self.instance],
            env=environment(self.root) | {key: self.env[key] for key in
                ('DASHBOARD_PORT', 'ARCHIVE_PORT', 'ADMIN_PORT', 'MCP_LAUNCH_INSTANCE')},
            cwd=self.root, pipes=pipes)

    def start_worker(self):
        if self.worker and self.worker.process.poll() is None:
            return
        if self.worker:
            self.worker.stop()
        worker = self.spawn('worker', pipes=True)
        try:
            if bounded_read(worker.process.stdout, timeout=45) != {'ready': True}:
                raise RuntimeError()
        except Exception:
            worker.stop()
            raise RuntimeError('MCP execution worker failed to start') from None
        self.worker = worker

    def refresh_ota(self):
        from device_ota import inspect
        if self.ota:
            self.ota.stop()
            self.ota = None
        self.ota_status = inspect(self.root)
        if self.ota_status['state'] != 'starting':
            return
        child = None
        try:
            child = self.spawn('device-ota', pipes=True)
            if bounded_read(child.process.stdout, timeout=10) != {'ready': True}:
                raise RuntimeError('OTA host did not start')
            self.ota = child
            self.ota_status.update(state='ready', running=True,
                message='已允许设备更新。在同一局域网内，从设备设置中检查更新。')
        except Exception:
            if child:
                child.stop()
            self.ota_status.update(state='error', running=False,
                message='更新服务未启动。请检查电脑地址是否变化、端口是否被占用，然后重试。')

    def device_ota_status(self):
        status = dict(getattr(self, 'ota_status', None) or {})
        if status.get('running') and (not self.ota or self.ota.process.poll() is not None):
            status.update(state='error', running=False, message='设备更新服务已停止，请点击重试。')
        elif status.get('running'):
            from device_ota import inspect
            current = inspect(self.root)
            if current['state'] != 'starting':
                return current
            status['version'] = current['version']
        return status

    def configured(self):
        from dotenv import dotenv_values
        return bool(dotenv_values(self.root / 'app/.env', interpolate=False).get('MCP_ENDPOINT', '').strip())

    def connected(self):
        if not self.settings['mcp_enabled'] or not self.settings['cloud_enabled'] or not self.bridge or self.bridge.process.poll() is not None:
            return False
        try:
            state = json.loads((self.root / 'state/desktop-cloud.json').read_text('utf-8'))
            return state == {'instance': self.instance, 'connected': True}
        except (OSError, ValueError):
            return False

    def refresh_bridge(self):
        should_run = self.settings['mcp_enabled'] and self.settings['cloud_enabled'] and self.configured()
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        atomic_json(self.root / 'state/desktop-cloud.json', {'instance': self.instance, 'connected': False})
        if should_run:
            self.bridge = self.spawn('bridge')

    def status(self):
        with self.lock:
            return {'ready': self.ready and self.dashboard is not None and self.dashboard.process.poll() is None,
                'mcp_enabled': self.settings['mcp_enabled'] and self.worker is not None and self.worker.process.poll() is None,
                'cloud_enabled': self.settings['cloud_enabled'], 'cloud_configured': self.configured(),
                'cloud_connected': self.connected(), 'dashboard_url': self.base_url + '/memory/',
                'setup_url': self.base_url + '/setup/', 'capabilities_url': self.base_url + '/memory/mcp/',
                'data_root': str(self.root), 'device_ota': self.device_ota_status()}

    def client_config(self, format):
        if format not in ('json', 'toml'):
            raise ValueError('Unsupported configuration format')
        command = str(Path(sys.executable).absolute())
        args = ['-E', '-s', '-X', 'utf8', str(Path(__file__).with_name('client.py').resolve()), '--data-root', str(self.root)]
        if format == 'json':
            return json.dumps({'mcpServers': {'evomyn': {'command': command, 'args': args}}}, ensure_ascii=False, indent=2)
        return '[mcp_servers.evomyn]\ncommand = ' + json.dumps(command, ensure_ascii=False) + '\nargs = ' + json.dumps(args, ensure_ascii=False) + '\n'

    def command(self, command, **params):
        with self.lock:
            if command == 'status' and not params:
                return self.status()
            if command == 'client-config' and set(params) == {'format'}:
                return self.client_config(params['format'])
            if command == 'ota-retry' and not params:
                self.refresh_ota()
                return self.status()
            if command == 'ota-import-pairing' and set(params) == {'directory'} and isinstance(params['directory'], str):
                from device_sync import import_pairing
                import_pairing(self.root, params['directory'])
                self.refresh_ota()
                return self.status()
            if command == 'ota-import-release' and set(params) == {'manifest'} and isinstance(params['manifest'], str):
                from device_ota import import_release
                import_release(self.root, params['manifest'])
                self.refresh_ota()
                return self.status()
            if command in ('start-mcp', 'stop-mcp') and not params:
                enabled = command == 'start-mcp'
                # Close the gate before killing children; existing adapters have
                # no authority or code path to execute a private worker.
                self.settings['mcp_enabled'] = enabled
                if enabled:
                    try:
                        self.start_worker()
                    except Exception:
                        self.settings['mcp_enabled'] = False
                        atomic_json(self.settings_path, self.settings)
                        raise
                elif self.worker:
                    worker, self.worker = self.worker, None
                    worker.stop()
                self.refresh_bridge()
            elif command == 'set-cloud' and set(params) == {'enabled'} and type(params['enabled']) is bool:
                self.settings['cloud_enabled'] = params['enabled']
                self.refresh_bridge()
            elif command == 'save-endpoint' and set(params) == {'endpoint'} and isinstance(params['endpoint'], str):
                sys.path.insert(0, str(self.root))
                from onboarding import Setup
                endpoint = Setup.endpoint(params['endpoint'])
                Setup(self.root, None, client_config=self.client_config).save_endpoint(endpoint)
                private_permissions(self.root / 'app/.env')
                self.refresh_bridge()
            else:
                raise ValueError('Unsupported desktop operation')
            atomic_json(self.settings_path, self.settings)
            return self.status()

    def execute(self, request):
        method = request.get('method')
        if method == 'control' and set(request) == {'method', 'action'}:
            action = request['action']
            if action == 'Status':
                return self.status()
            if action == 'Restart':
                self.command('stop-mcp')
                return self.command('start-mcp')
            if action in ('Start', 'Stop'):
                return self.command('start-mcp' if action == 'Start' else 'stop-mcp')
        if method in ('set-cloud', 'save-endpoint', 'client-config'):
            return self.command(method, **{key: value for key, value in request.items() if key != 'method'})
        if method not in ('list-tools', 'call-tool'):
            raise ValueError('Unsupported RPC operation')
        if method == 'list-tools' and set(request) != {'method'}:
            raise ValueError('Invalid tool request')
        if method == 'call-tool' and (set(request) != {'method', 'name', 'arguments'} or
            not isinstance(request['name'], str) or not isinstance(request['arguments'], dict)):
            raise ValueError('Invalid tool request')
        with self.io_lock:
            worker = None
            try:
                with self.lock:
                    if not self.settings['mcp_enabled'] or self.worker is None or self.worker.process.poll() is not None:
                        raise RuntimeError('MCP master switch is closed')
                    worker = self.worker
                    worker.process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
                    worker.process.stdin.flush()
                # Never hold the lifecycle lock while a tool executes. Stop can
                # kill an in-flight operation without waiting behind it.
                response = bounded_read(worker.process.stdout)
                if not isinstance(response, dict) or type(response.get('ok')) is not bool:
                    raise ValueError('Invalid execution response')
                if response['ok']:
                    expected = list if method == 'list-tools' else dict
                    if set(response) != {'ok', 'result'} or not isinstance(response['result'], expected):
                        raise ValueError('Invalid execution response')
                elif set(response) != {'ok', 'error'} or not isinstance(response['error'], str):
                    raise ValueError('Invalid execution response')
            except Exception:
                if worker is None:
                    raise
                with self.lock:
                    if self.worker is worker:
                        # A timeout leaves a blocking reader on this pipe. Kill
                        # that execution generation before releasing io_lock;
                        # later requests can only use a fresh worker/pipe.
                        self.worker = None
                        self.settings['mcp_enabled'] = False
                        if self.bridge:
                            self.bridge.stop()
                            self.bridge = None
                        worker.stop()
                        atomic_json(self.settings_path, self.settings)
                raise RuntimeError('Owned execution worker reset after a failed exchange') from None
            if not response['ok']:
                raise RuntimeError('Tool execution failed')
            return response['result']

    def _rpc_server(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.connection.settimeout(10)
                host = self.headers.get('Host', '')
                if (self.path != '/rpc' or len(self.headers.get_all('Host', [])) != 1 or
                    host != '127.0.0.1:' + str(self.server.server_port) or
                    self.headers.get('Origin') is not None or
                    len(self.headers.get_all('Authorization', [])) != 1 or
                    not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + owner.token)):
                    self.close_connection = True
                    return self.send_error(403)
                try:
                    if 'Transfer-Encoding' in self.headers or len(self.headers.get_all('Content-Length', [])) != 1:
                        raise ValueError()
                    length = int(self.headers['Content-Length'])
                    if not 0 <= length <= LIMIT:
                        self.close_connection = True
                        return self.send_error(413)
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        return self.send_error(415)
                    request = json.loads(self.rfile.read(length))
                    if not isinstance(request, dict):
                        raise ValueError()
                    result = {'ok': True, 'result': owner.execute(request)}
                except Exception:
                    result = {'ok': False, 'error': 'MCP disabled or desktop operation unavailable'}
                raw = json.dumps(result, ensure_ascii=False).encode('utf-8')
                if len(raw) > LIMIT:
                    raw = b'{"ok":false,"error":"Response too large"}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (OSError, ConnectionError):
                    pass
        return ThreadingHTTPServer(('127.0.0.1', 0), Handler)

    def close(self):
        self.ready = False
        for name in ('ota', 'bridge', 'worker', 'dashboard'):
            child = getattr(self, name, None)
            if child:
                child.stop()
                setattr(self, name, None)
        if self.http:
            self.http.shutdown()
            self.http.server_close()
        try:
            if json.loads(self.descriptor.read_text('utf-8')).get('instance') == self.instance:
                self.descriptor.unlink()
        except (OSError, ValueError):
            pass
        self.lockfile.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    args = parser.parse_args()
    supervisor = None
    try:
        supervisor = Supervisor(args.app_dir, args.data_root)
        while True:
            line = sys.stdin.buffer.readline(LIMIT + 1)
            if not line:
                break
            ident = None
            command = None
            shutdown = False
            try:
                if len(line) > LIMIT or not line.endswith(b'\n'):
                    raise ValueError()
                request = json.loads(line)
                if not isinstance(request, dict) or 'id' not in request or 'command' not in request:
                    raise ValueError()
                ident = request.pop('id')
                command = request.pop('command')
                if type(ident) not in (str, int):
                    raise ValueError()
                if command == 'shutdown' and not request:
                    shutdown = True
                    result = {'shutdown': True}
                else:
                    result = supervisor.command(command, **request)
                response = {'id': ident, 'ok': True, 'result': result}
            except Exception:
                errors = {
                    'ota-import-pairing': '设备配对配置无效，请选择包含有效设备地址、凭证及证书的原运行目录。',
                    'ota-import-release': '固件包无效或不兼容，请选择官方 manifest.json，并保留相邻固件文件；最低版本为 2.5.7。',
                }
                response = {'id': ident, 'ok': False, 'error': errors.get(command if isinstance(command, str) else None,
                    'Desktop operation failed; check the selected operation and local installation.')}
            print(json.dumps(response, ensure_ascii=False), flush=True)
            if shutdown:
                break
        return 0
    except Exception:
        print('Desktop service could not start. Check application layout and data-directory access.', file=sys.stderr)
        return 1
    finally:
        if supervisor:
            supervisor.close()


if __name__ == '__main__':
    raise SystemExit(main())
