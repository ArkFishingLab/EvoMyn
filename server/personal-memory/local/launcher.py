"""Portable local MCP lifecycle. Importable without third-party dependencies.

The public distribution places this file next to app/, viewer/ and dashboard.py.
Every command supports --root for isolated installations and acceptance tests.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import uuid
import webbrowser


class LauncherError(Exception):
    """An actionable message which never includes configuration values."""


DEFAULTS = {'MCP_ENDPOINT': '', 'PLANNER_OWNER': 'device', 'DASHBOARD_PORT': '18768',
            'ARCHIVE_PORT': '18770', 'ADMIN_PORT': '18772', 'PLANNER_PORT': '18769',
            'PLANNER_WS_PORT': '18771'}
CONFIG_KEYS = set(DEFAULTS) | {'MCP_CONFIG', 'MCP_EVENT_LOG', 'PERSONAL_ARCHIVE_HOME',
    'DEVICE_GATEWAY_HOST', 'DEVICE_GATEWAY_PORT', 'DEVICE_GATEWAY_CERT', 'DEVICE_GATEWAY_KEY',
    'DEVICE_GATEWAY_ALLOWED_HOSTS', 'DEVICE_UPDATE_DIR', 'PLANNER_DEVICE_TOKEN', 'PLANNER_DEVICE_ID'}


def process_identity(pid):
    """Read PID generation, executable and command; permission failures fail closed."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        if os.name == 'nt':
            shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
            if not shell:
                return None
            script = ("$env:PSModulePath=$PSHOME+'\\Modules;'+$env:PSModulePath;"
                "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
                f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
                "if($p){@{pid=[int]$p.ProcessId;created=[string]$p.CreationDate.ToFileTimeUtc();"
                "executable=$p.ExecutablePath;command=$p.CommandLine}|ConvertTo-Json -Compress}")
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
                capture_output=True, encoding='utf-8', timeout=12,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or not result.stdout.strip():
                return None
            value = json.loads(result.stdout.lstrip('\ufeff'))
            if not value.get('executable') or not value.get('command'):
                return None
            return value
        proc = Path('/proc') / str(pid)
        stat = (proc / 'stat').read_text()
        fields = stat[stat.rfind(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'created': fields[19],
                'executable': str((proc / 'exe').resolve(strict=True)),
                'command': (proc / 'cmdline').read_bytes().decode('utf-8', 'replace').replace('\0', ' ')}
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return None


def tcp_connected(pid):
    """Compatibility signal for the Windows bridge management dashboard."""
    if os.name != 'nt' or type(pid) is not int:
        return False
    shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not shell:
        return False
    script = ("$env:PSModulePath=$PSHOME+'\\Modules;'+$env:PSModulePath;"
              f"$ids=@{{{pid}=$true}};$all=@(Get-CimInstance Win32_Process);"
              "for($depth=0;$depth -lt 32;$depth++){foreach($p in $all){"
              "if($ids.ContainsKey([int]$p.ParentProcessId)){$ids[[int]$p.ProcessId]=$true}}};"
              "$c=@(Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
              "Where-Object {$ids.ContainsKey([int]$_.OwningProcess)});"
              "if($c.Count -gt 0){[Console]::Write('connected')}")
    try:
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True, encoding='utf-8', timeout=12,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode == 0 and result.stdout.strip() == 'connected'
    except (OSError, subprocess.SubprocessError):
        return False


@contextmanager
def lifecycle_lock(path):
    """OS-released file lock serializes Start/Stop, including concurrent clicks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise LauncherError('Another lifecycle operation is busy. Please retry.') from None
                time.sleep(0.1)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


class Runtime:
    def __init__(self, root, python=None):
        self.root = Path(root).resolve()
        self.script = Path(__file__).resolve()
        candidate = self.root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        self.python = str(Path(python).absolute()) if python else str(candidate if candidate.is_file() else Path(sys.executable).absolute())
        self.records_path = self.root / 'state/launcher-processes.json'

    def ensure_config(self):
        if not (self.root / 'app').is_dir():
            raise LauncherError('Missing app directory. Extract the complete portable package first.')
        for directory in ('state/data', 'logs'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        try:
            with (self.root / 'app/.env').open('x', encoding='utf-8', newline='\n') as stream:
                stream.write('# Optional cloud endpoint; leave blank for local MCP clients.\n')
                stream.writelines(f'{key}={value}\n' for key, value in DEFAULTS.items())
        except FileExistsError:
            pass

    def environment(self):
        self.ensure_config()
        try:
            from dotenv import dotenv_values
        except ImportError:
            # Bootstrap and stdlib-only tests may run before requirements install.
            values = {}
            for line in (self.root / 'app/.env').read_text(encoding='utf-8-sig').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        else:
            values = dotenv_values(self.root / 'app/.env', interpolate=False)
        env = {key: value for key, value in os.environ.items() if key not in CONFIG_KEYS}
        env.update(DEFAULTS)
        env.update({key: value for key, value in values.items() if value is not None})
        env.update(PERSONAL_ARCHIVE_HOME=str(self.root / 'state'),
                   MCP_EVENT_LOG=str(self.root / 'logs/events.jsonl'),
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        # .env must not redirect child imports to an unrelated installation.
        env['PYTHONPATH'] = os.pathsep.join((str(self.root / 'app'), str(self.root)))
        return env

    def _records(self):
        try:
            value = json.loads(self.records_path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, records):
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.records_path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.records_path)

    def _owned(self, role, record):
        if not isinstance(record, dict) or record.get('role') != role or record.get('root') != str(self.root):
            return None
        current = process_identity(record.get('pid'))
        if not current or any(current.get(key) != record.get(key) for key in ('pid', 'created', 'executable', 'command')):
            return None
        command = current['command']
        token = record.get('instance')
        if not token or token not in command or '--instance' not in command or '--role' not in command:
            return None
        if str(self.script).lower() not in command.lower() or str(self.root).lower() not in command.lower():
            return None
        return current

    def _role_status(self, role, records):
        record = records.get(role)
        current = self._owned(role, record)
        return {'running': bool(current), 'verified': bool(current),
                'tcp_connected': tcp_connected(current['pid']) if role == 'bridge' and current else False,
                'process_id': current['pid'] if current else None,
                'started_utc': record.get('started_utc') if current else None}

    def status(self, bridge_only=False):
        records = self._records()
        if bridge_only:
            return self._role_status('bridge', records)
        return {role: self._role_status(role, records) for role in ('dashboard', 'bridge')}

    def _ports(self, env):
        names = ['DASHBOARD_PORT', 'ARCHIVE_PORT', 'ADMIN_PORT']
        if env.get('PLANNER_OWNER') == 'pc':
            names += ['PLANNER_PORT', 'PLANNER_WS_PORT']
        if env.get('DEVICE_GATEWAY_HOST'):
            names += ['DEVICE_GATEWAY_PORT']
        ports = []
        for name in names:
            try:
                port = int(env.get(name, '18773'))
                if not 1 <= port <= 65535:
                    raise ValueError()
            except ValueError:
                raise LauncherError(f'{name} must be a port between 1 and 65535.') from None
            if port in ports:
                raise LauncherError('Configured service ports must be distinct.')
            ports.append(port)
        return ports

    def _check_ports(self, env):
        for port in self._ports(env):
            with socket.socket() as listener:
                if os.name == 'nt':
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                try:
                    listener.bind(('127.0.0.1', port))
                except OSError:
                    raise LauncherError(f'Local port {port} is already in use. Stop its application or change ports in app/.env.') from None

    def _spawn(self, role, env, records):
        if self._owned(role, records.get(role)):
            return
        target = self.root / ('dashboard.py' if role == 'dashboard' else 'app/mcp_pipe.py')
        if not target.is_file():
            raise LauncherError(f'Missing {role} program. Extract the complete portable package.')
        instance = uuid.uuid4().hex
        env = {**env, 'MCP_LAUNCH_INSTANCE': instance}
        command = [self.python, '-X', 'utf8', '-u', str(self.script), '--root', str(self.root),
                   '_serve', '--role', role, '--instance', instance]
        flags = (getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)) if os.name == 'nt' else 0
        prefix = 'cloud' if role == 'bridge' else 'dashboard'
        started_utc = datetime.now(timezone.utc).isoformat()
        with (self.root / f'logs/{prefix}.stdout.log').open('ab') as output, (self.root / f'logs/{prefix}.stderr.log').open('ab') as error:
            child = subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=error, creationflags=flags, start_new_session=os.name != 'nt')
        current = process_identity(child.pid)
        if current is None:
            # This is our fresh Popen handle, never a PID recovered from disk.
            child.terminate()
            child.wait(timeout=10)
            raise LauncherError(f'Could not verify the new {role} process. See logs/{prefix}.stderr.log.')
        records[role] = {**current, 'role': role, 'root': str(self.root), 'instance': instance,
                         'started_utc': started_utc}
        self._save(records)
        # Popen objects need not retain Windows handles for detached services.
        if os.name == 'nt':
            child._handle.Close()
            child._child_created = False

    def _stop_role(self, role, records):
        current = self._owned(role, records.get(role))
        if current:
            if os.name == 'nt':
                result = subprocess.run(['taskkill.exe', '/PID', str(current['pid']), '/T', '/F'],
                    capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode and self._owned(role, records.get(role)):
                    raise LauncherError(f'Could not stop the owned {role} process. Please retry.')
            else:
                try:
                    os.killpg(current['pid'], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 8
            while self._owned(role, records.get(role)):
                if time.monotonic() >= deadline:
                    raise LauncherError(f'The {role} process has not stopped. Please retry.')
                time.sleep(0.1)
        records.pop(role, None)
        self._save(records)

    def _wait_dashboard(self, env, records):
        base = f"http://127.0.0.1:{env['DASHBOARD_PORT']}"
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                with urlopen(base + '/healthz', timeout=1) as response:
                    if response.status == 200:
                        try:
                            health = json.loads(response.read(4096))
                        except (ValueError, UnicodeError):
                            raise LauncherError('Unexpected dashboard health response. Check configured ports.') from None
                        # Windows venv python.exe is a redirector: the HTTP server
                        # runs in its child. Bind readiness to the spawned instance
                        # while retaining the verified redirector PID for tree stop.
                        record = records.get('dashboard', {})
                        if (not isinstance(health, dict) or health.get('ok') is not True
                                or health.get('service') != 'personal-memory-mcp'
                                or type(health.get('pid')) is not int or health['pid'] <= 0
                                or health.get('instance') != record.get('instance')
                                or not self._owned('dashboard', record)):
                            raise LauncherError('Unexpected dashboard health identity. Check configured ports.')
                        return base + '/memory/'
            except (OSError, HTTPError, URLError):
                pass
            if not self._owned('dashboard', records.get('dashboard')):
                raise LauncherError('Dashboard exited before readiness. See logs/dashboard.stderr.log.')
            time.sleep(0.2)
        raise LauncherError('Dashboard readiness timed out. See logs/dashboard.stderr.log.')

    def start(self, open_browser=True):
        env = self.environment()
        self._ports(env)
        with lifecycle_lock(self.root / 'state/.launcher.lock'):
            records = self._records()
            created = not self._owned('dashboard', records.get('dashboard'))
            if created:
                self._check_ports(env)
                self._spawn('dashboard', env, records)
            try:
                url = self._wait_dashboard(env, records)
                if env.get('MCP_ENDPOINT', '').strip():
                    self._spawn('bridge', env, records)
            except Exception:
                if created:
                    self._stop_role('dashboard', records)
                raise
            result = self.status()
        if open_browser:
            webbrowser.open(url)
        return result

    def stop(self, bridge_only=False):
        if not self.records_path.exists():
            return self.status(bridge_only=bridge_only)
        with lifecycle_lock(self.root / 'state/.launcher.lock'):
            records = self._records()
            for role in (('bridge',) if bridge_only else ('bridge', 'dashboard')):
                self._stop_role(role, records)
        return self.status(bridge_only=bridge_only)

    def bridge_start(self):
        env = self.environment()
        with lifecycle_lock(self.root / 'state/.launcher.lock'):
            records = self._records()
            if env.get('MCP_ENDPOINT', '').strip():
                self._spawn('bridge', env, records)
        return self.status(bridge_only=True)

    def configure(self, open_browser=True):
        result = self.start(open_browser=False)
        env = self.environment()
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{env['DASHBOARD_PORT']}/setup/")
        return result

    def client_config(self, format='json'):
        args = ['-X', 'utf8', str(self.script), '--root', str(self.root), 'stdio']
        entry = {'command': self.python, 'args': args}
        if format == 'json':
            return json.dumps({'mcpServers': {'evomyn': entry}}, ensure_ascii=False, indent=2)
        # JSON double-quoted strings/arrays are also valid TOML basic syntax.
        return '[mcp_servers.evomyn]\ncommand = ' + json.dumps(self.python, ensure_ascii=False) + '\nargs = ' + json.dumps(args, ensure_ascii=False) + '\n'

    def stdio(self):
        env = self.environment()
        target = self.root / 'app/mcp_server.py'
        if not target.is_file():
            raise LauncherError('Missing MCP server. Extract the complete portable package.')
        os.environ.clear()
        os.environ.update(env)
        sys.path[:0] = [str(self.root / 'app'), str(self.root)]
        os.chdir(self.root / 'app')
        sys.argv = [str(target)]
        # In-process stdio retains the client's handles on Windows as well as POSIX.
        runpy.run_path(str(target), run_name='__main__')

    def serve(self, role, instance):
        env = self.environment()
        # Command-line identity is authoritative, never an app/.env value.
        env['MCP_LAUNCH_INSTANCE'] = instance
        os.environ.clear()
        os.environ.update(env)
        sys.path[:0] = [str(self.root / 'app'), str(self.root)]
        os.chdir(self.root / 'app')
        target = self.root / ('dashboard.py' if role == 'dashboard' else 'app/mcp_pipe.py')
        sys.argv = [str(target)] + ([str(self.root / 'app/mcp_server.py')] if role == 'bridge' else [])
        runpy.run_path(str(target), run_name='__main__')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'stop', 'status', 'stdio', 'configure', 'client-config',
                                            'bridge-start', 'bridge-stop', 'bridge-status', '_serve'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--format', choices=('json', 'toml'), default='json')
    parser.add_argument('--role', choices=('dashboard', 'bridge'))
    parser.add_argument('--instance', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    runtime = Runtime(args.root)
    try:
        if args.command == 'stdio':
            runtime.stdio()
            return 0
        if args.command == '_serve':
            if not args.role or not args.instance:
                raise LauncherError('Managed role requires an instance identifier.')
            runtime.serve(args.role, args.instance)
            return 0
        if args.command == 'client-config':
            print(runtime.client_config(args.format))
            return 0
        if args.command == 'start':
            result = runtime.start(open_browser=not args.no_browser)
        elif args.command == 'configure':
            result = runtime.configure(open_browser=not args.no_browser)
        elif args.command == 'bridge-start':
            result = runtime.bridge_start()
        elif args.command in ('stop', 'bridge-stop'):
            result = runtime.stop(bridge_only=args.command.startswith('bridge-'))
        else:
            result = runtime.status(bridge_only=args.command.startswith('bridge-'))
        print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2))
        return 0
    except LauncherError as error:
        print(f'Personal MCP: {error}', file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Personal MCP: operation failed. Check the local logs and installation permissions.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
