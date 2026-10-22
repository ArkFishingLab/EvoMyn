"""Source-checkout entry points, always exercised in isolated installations."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('powershell.exe') or shutil.which('pwsh')
BASE = 'server/personal-memory'


def cleanup_fixture(temporary):
    """Retry short Windows deletion races only within our owned temp root."""
    root = Path(temporary.name)
    if not root.is_absolute() or root.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        raise ValueError('Fixture cleanup must stay within its temporary directory')
    if root.exists() and (root.is_symlink() or getattr(root.lstat(), 'st_file_attributes', 0) & 0x400):
        raise ValueError('Fixture cleanup root must not be a link')
    for attempt in range(6):
        try:
            temporary.cleanup()
            return
        except OSError as error:
            # Access/sharing/locking violations and nonempty directories may be
            # transient after Windows process-tree shutdown or virus scanning.
            # Other errors and exhausted retries remain real test failures.
            if getattr(error, 'winerror', None) not in (5, 32, 33, 145) or attempt == 5:
                raise
            time.sleep(0.1 * (attempt + 1))


def public_files():
    spec = importlib.util.spec_from_file_location('release_files', ROOT / 'tools/package_public_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {source: target for source, target in module.PUBLIC_FILES.items()
            if source.startswith((BASE + '/vendor/', BASE + '/local/'))
            or source.startswith(BASE + '/viewer/') and '/tests/' not in source
            or source in (BASE + '/requirements.txt', BASE + '/distribution/public-fonts.css',
                          BASE + '/distribution/.env.example')}


def free_ports():
    sockets = []
    try:
        for _ in range(3):
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


@unittest.skipUnless(os.name == 'nt' and SHELL, 'Windows PowerShell entry points')
class WorkspaceLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='source checkout 中文 ')
        self.root = Path(self.temp.name) / 'clone with spaces'
        self.root.mkdir()
        self.runtime = self.root / 'artifacts/local-memory-mcp'
        self.environment = dict(os.environ)
        # Exercise the real bootstrap against this test runner's installed Python.
        # A caller's PATH need not contain sys.executable (for example uv run).
        self.environment.update(
            PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''),
            UV_OFFLINE='1', UV_PYTHON_DOWNLOADS='never', PIP_NO_INDEX='1')
        for source in public_files():
            destination = self.root / source
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, destination)
        (self.root / BASE / 'requirements.txt').write_text('# Dependency-free acceptance fixture\n')

    def tearDown(self):
        try:
            if (self.runtime / 'state/launcher-processes.json').exists():
                stopped = subprocess.run([sys.executable, str(self.runtime / 'launcher.py'), '--root',
                                str(self.runtime), 'stop'], capture_output=True, timeout=60,
                                encoding='utf-8', env=self.environment)
                self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        finally:
            cleanup_fixture(self.temp)

    def command(self, action='Prepare'):
        return [SHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(ROOT / 'tools/workspace.ps1'), '-Workspace', str(self.root),
                '-Action', action, '-NoBrowser']

    def run_action(self, action='Prepare', success=True, timeout=60):
        result = subprocess.run(self.command(action), capture_output=True, encoding='utf-8',
                                timeout=timeout, env=self.environment)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_first_assembly_uses_only_reviewed_files_and_system_fonts(self):
        (self.root / BASE / 'vendor/DO_NOT_COPY.secret').write_text('excluded')
        self.run_action()
        self.assertTrue((self.runtime / 'app/mcp_server.py').is_file())
        self.assertTrue((self.runtime / 'dashboard.py').is_file())
        self.assertTrue((self.runtime / 'bootstrap.ps1').is_file())
        self.assertEqual(json.loads((self.runtime / 'runtime-install.json').read_text(encoding='utf-8'))['manager'], 'portable')
        self.assertFalse((self.runtime / 'app/DO_NOT_COPY.secret').exists())
        self.assertFalse((self.runtime / 'viewer/static/fonts').exists())
        self.assertFalse((self.runtime / 'tests').exists())
        css = (self.runtime / 'viewer/static/style.css').read_text(encoding='utf-8')
        self.assertNotIn('@font-face', css)
        self.assertNotIn('Workspace Sans', css)
        self.assertNotIn('./fonts/', css)
        self.assertIn('Segoe UI', css)
        self.assertFalse((self.runtime / 'app/.env').exists())

    def test_second_assembly_preserves_private_state_and_installed_code(self):
        self.runtime.joinpath('app').mkdir(parents=True)
        config = self.runtime / 'app/.env'
        config.write_bytes(b'MCP_ENDPOINT=\n# private sentinel\n')
        database = self.runtime / 'state/data/archive.sqlite3'
        database.parent.mkdir(parents=True)
        database.write_bytes(b'private database sentinel')
        self.run_action()
        installed = self.runtime / 'app/mcp_server.py'
        original = installed.read_bytes()
        marker = (self.runtime / 'runtime-install.json').stat().st_mtime_ns
        (self.root / BASE / 'vendor/mcp_server.py').write_text('raise RuntimeError("source changed")')
        self.run_action()
        self.assertEqual(installed.read_bytes(), original)
        self.assertEqual(config.read_bytes(), b'MCP_ENDPOINT=\n# private sentinel\n')
        self.assertEqual(database.read_bytes(), b'private database sentinel')
        self.assertEqual((self.runtime / 'runtime-install.json').stat().st_mtime_ns, marker)

    def test_missing_source_fails_before_publishing_runtime_marker(self):
        (self.root / BASE / 'vendor/mcp_server.py').unlink()
        self.run_action(success=False)
        self.assertFalse((self.runtime / 'runtime-install.json').exists())

    def test_empty_stop_does_not_install_or_assemble(self):
        self.run_action('Stop')
        self.assertFalse(self.runtime.exists())

    def test_direct_assembly_needs_no_python_on_path(self):
        environment = dict(os.environ)
        environment['PATH'] = str(Path(SHELL).parent)
        command = [SHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(ROOT / 'tools/prepare_runtime.ps1'), '-Workspace', str(self.root)]
        result = subprocess.run(command, capture_output=True, encoding='utf-8', env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.runtime / 'runtime-install.json').is_file())
        self.assertFalse((self.runtime / '.venv').exists())

    def test_legacy_process_metadata_reuses_private_manager(self):
        self.runtime.mkdir(parents=True)
        legacy = self.runtime / 'process.json'
        legacy.write_text('{}')
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'current_memory.ps1').write_text(
            "param([string]$Action,[switch]$NoBrowser)\n"
            "[IO.File]::AppendAllText((Join-Path $PSScriptRoot 'legacy-calls.txt'),$Action+';')\n")
        for action in ('Start', 'Stop', 'Configure', 'Status'):
            self.run_action(action)
        self.assertEqual((tools / 'legacy-calls.txt').read_text(), 'Start;Stop;Configure;Status;')
        self.assertEqual(legacy.read_text(), '{}')
        self.assertFalse((self.runtime / 'runtime-install.json').exists())

    def test_portable_marker_never_routes_to_legacy_manager(self):
        self.run_action()
        (self.runtime / 'state').mkdir()
        (self.runtime / 'state/launcher-processes.json').write_text('{}')
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'current_memory.ps1').write_text("throw 'Legacy manager must not run'\n")
        self.run_action('Status')

    def junction(self, path, target):
        # Use a script file so Unicode paths stay data and need no interpolation.
        script = Path(self.temp.name) / 'junction.ps1'
        script.write_text('param($Link,$Target)\nNew-Item -ItemType Junction -Path $Link -Target $Target | Out-Null\n')
        result = subprocess.run([SHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(script), str(path), str(target)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(lambda: os.rmdir(path) if path.exists() else None)

    def test_linked_runtime_destination_is_rejected_without_writes(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        self.root.joinpath('artifacts').mkdir()
        self.junction(self.runtime, outside)
        result = self.run_action(success=False)
        self.assertIn(str(self.runtime), result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_linked_source_ancestor_is_rejected(self):
        source = self.root / BASE / 'vendor'
        moved = Path(self.temp.name) / 'moved vendor'
        source.rename(moved)
        self.junction(source, moved)
        self.run_action(success=False)
        self.assertFalse((self.runtime / 'runtime-install.json').exists())

    def test_linked_private_state_is_rejected_without_touching_target(self):
        self.runtime.mkdir(parents=True)
        outside = Path(self.temp.name) / 'outside state'
        outside.mkdir()
        self.junction(self.runtime / 'state', outside)
        self.run_action(success=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_cloud_placeholder_is_allowed_but_other_reparse_tags_are_rejected(self):
        script = Path(self.temp.name) / 'cloud-tags.ps1'
        script.write_text(
            "param($Helper,$Workspace,$Tag)\n"
            ". $Helper -Workspace $Workspace\n"
            "$cloudPath=Join-Path $Workspace 'cloud-placeholder'\n"
            "New-Item -ItemType Directory -Path $cloudPath -Force | Out-Null\n"
            "function Get-Item { param($LiteralPath,[switch]$Force,$ErrorAction)\n"
            " if($LiteralPath -eq $cloudPath){return [pscustomobject]@{Attributes=[IO.FileAttributes]::Directory -bor [IO.FileAttributes]::ReparsePoint}}\n"
            " Microsoft.PowerShell.Management\\Get-Item @PSBoundParameters\n}\n"
            "function Get-ReparseTag {param($Path) return [Convert]::ToUInt32($Tag,16)}\n"
            "try {Assert-PlainPath $cloudPath} catch {[Console]::Error.WriteLine($_.Exception.Message);exit 1}\n",
            encoding='utf-8')
        for tag in ('9000001a', '9000601a', '9000f01a'):
            with self.subTest(tag=tag):
                result = subprocess.run([SHELL, '-NoProfile', '-File', str(script),
                    str(ROOT / 'tools/prepare_runtime.ps1'), str(self.root), tag],
                    capture_output=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
        for tag in ('a0000003', 'a000000c', '8000001b'):
            with self.subTest(tag=tag):
                result = subprocess.run([SHELL, '-NoProfile', '-File', str(script),
                    str(ROOT / 'tools/prepare_runtime.ps1'), str(self.root), tag],
                    capture_output=True, encoding='utf-8', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('cloud-placeholder', result.stderr)

    def test_fresh_source_bootstrap_and_concurrent_start_reuse_dashboard_and_cloud(self):
        ports = free_ports()
        (self.root / BASE / 'local/dashboard.py').write_text(
            'from http.server import BaseHTTPRequestHandler,HTTPServer\nimport os,json\n'
            'class Handler(BaseHTTPRequestHandler):\n'
            ' def do_GET(self):\n  self.send_response(200); self.end_headers(); '
            "self.wfile.write(json.dumps({'ok':True,'pid':os.getpid(),"
            "'instance':os.environ['MCP_LAUNCH_INSTANCE'],'service':'personal-memory-mcp'}).encode())\n"
            ' def log_message(self,*args): pass\n'
            "HTTPServer(('127.0.0.1',int(os.environ['DASHBOARD_PORT'])),Handler).serve_forever()\n")
        (self.root / BASE / 'vendor/mcp_pipe.py').write_text('import time\ntime.sleep(300)\n')
        # Pre-existing private config is preserved while source runtime is assembled.
        self.runtime.joinpath('app').mkdir(parents=True)
        config = self.runtime / 'app/.env'
        config.write_text(f'DASHBOARD_PORT={ports[0]}\nARCHIVE_PORT={ports[1]}\nADMIN_PORT={ports[2]}\n'
                          'MCP_ENDPOINT=wss://cloud.invalid/test\n', encoding='utf-8')
        self.run_action('Start', timeout=150)
        self.assertFalse((self.runtime / '.tools/python').exists(), 'Bootstrap must reuse an installed Python offline')
        records_path = self.runtime / 'state/launcher-processes.json'
        first = json.loads(records_path.read_text(encoding='utf-8'))
        self.assertEqual(set(first), {'dashboard', 'bridge'})
        marker = self.runtime / '.venv/requirements.sha256'
        modified = marker.stat().st_mtime_ns
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.run_action('Start', timeout=90), range(2)))
        self.assertEqual(len(results), 2)
        self.assertEqual(json.loads(records_path.read_text(encoding='utf-8')), first)
        self.assertEqual(marker.stat().st_mtime_ns, modified)
        self.run_action('Stop')
        self.assertEqual(json.loads(records_path.read_text(encoding='utf-8')), {})
        self.assertTrue(config.is_file())


class RootShortcutTests(unittest.TestCase):
    def test_english_and_localized_wrappers_share_ascii_workspace_entry_point(self):
        for filename, action in [('Start.cmd', 'Start'), ('Stop.cmd', 'Stop'),
                                 ('Configure.cmd', 'Configure'), ('启动EvoMyn.cmd', 'Start'),
                                 ('停止EvoMyn.cmd', 'Stop'), ('接入配置.cmd', 'Configure')]:
            path = ROOT / filename
            self.assertTrue(path.is_file(), filename)
            content = path.read_bytes().decode('ascii')
            self.assertIn('tools\\workspace.ps1', content)
            self.assertIn('-Action ' + action, content)
            self.assertIn('%*', content)
            self.assertIn('exit /b', content)


class FixtureCleanupTests(unittest.TestCase):
    def test_transient_cleanup_retries_only_owned_temp_directory(self):
        self.assertTrue(callable(globals().get('cleanup_fixture')), 'Bounded fixture cleanup is missing')
        temporary = tempfile.TemporaryDirectory(prefix='fixture cleanup ')
        self.addCleanup(temporary.cleanup)
        marker = Path(temporary.name) / 'sentinel'
        marker.write_text('temporary only')
        original = temporary.cleanup
        error = OSError('transient directory race')
        error.winerror = 145
        def cleanup_attempt():
            if cleanup.call_count == 1:
                raise error
            original()
        with patch.object(temporary, 'cleanup', side_effect=cleanup_attempt) as cleanup, \
             patch('time.sleep') as sleep:
            cleanup_fixture(temporary)
        self.assertFalse(marker.exists())
        sleep.assert_called_once()

    def test_persistent_cleanup_error_is_not_suppressed(self):
        self.assertTrue(callable(globals().get('cleanup_fixture')), 'Bounded fixture cleanup is missing')
        temporary = tempfile.TemporaryDirectory(prefix='fixture cleanup ')
        self.addCleanup(temporary.cleanup)
        error = OSError('persistent directory race')
        error.winerror = 145
        with patch.object(temporary, 'cleanup', side_effect=error) as cleanup, patch('time.sleep'):
            with self.assertRaises(OSError) as caught:
                cleanup_fixture(temporary)
        self.assertIs(caught.exception, error)
        self.assertEqual(cleanup.call_count, 6)

    def test_unrelated_cleanup_error_is_not_retried(self):
        self.assertTrue(callable(globals().get('cleanup_fixture')), 'Bounded fixture cleanup is missing')
        temporary = tempfile.TemporaryDirectory(prefix='fixture cleanup ')
        self.addCleanup(temporary.cleanup)
        error = OSError('invalid operation')
        error.winerror = 87
        with patch.object(temporary, 'cleanup', side_effect=error) as cleanup, patch('time.sleep') as sleep:
            with self.assertRaises(OSError) as caught:
                cleanup_fixture(temporary)
        self.assertIs(caught.exception, error)
        self.assertEqual(cleanup.call_count, 1)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
