"""Curated, pinned installers. Browser input never supplies shell commands or URLs."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4
from mcp_packages import MANIFEST, Packages


class Marketplace:
    def __init__(self, root, runner=None, probe=None):
        self.root = Path(root).resolve()
        self.packages = Packages(self.root / 'mcp-packages.json')
        self.runner = runner or self._run
        self.probe = probe or self._probe

    def _run(self, args, timeout):
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                shell=False, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if result.returncode: raise RuntimeError('Installation failed')

    def _probe(self, python):
        from market_tools import call_time_server
        result = asyncio.run(call_time_server(python, 'get_current_time', {'timezone': 'Asia/Shanghai'}))
        if result.get('timezone') != 'Asia/Shanghai' or not result.get('datetime'):
            raise RuntimeError('Provider verification failed')

    def install(self, ident, progress=None):
        if ident != 'worldtime': raise ValueError('Unsupported installation')
        uv = shutil.which('uv.exe') or shutil.which('uv')
        if not uv: raise RuntimeError('Installer unavailable')
        directory = self.root / 'packages/worldtime'
        python = self.packages.python(ident)
        if progress: progress('正在安装运行环境…')
        if not python.is_file():
            self.runner([uv, 'venv', '--python', sys.executable, str(directory / '.venv')], 30)
        self.runner([uv, 'pip', 'install', '--python', str(python), '--index-url', 'https://pypi.org/simple',
                     '--only-binary', ':all:', 'mcp-server-time==2026.10.10'], 120)
        if progress: progress('正在验证时间查询…')
        self.probe(python)
        temporary = directory / ('installed.' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'version': '2026.10.10', 'verified': True}), encoding='utf-8')
            temporary.replace(directory / 'installed.json')
        finally: temporary.unlink(missing_ok=True)

    def remove(self, ident):
        if ident != 'worldtime': raise ValueError('Built-in packages cannot be removed')
        self.packages.set(ident, False)
        (self.root / 'packages/worldtime/installed.json').unlink(missing_ok=True)
