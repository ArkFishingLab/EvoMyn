"""Official MCP stdio transport; all execution belongs to the desktop service."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import threading
import uuid
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request
from paths import atomic_json, private_permissions, reject_links

LIMIT = 1024 * 1024
loopback_open = build_opener(ProxyHandler({})).open


class DesktopOwner:
    """Retain a stable process handle, not a PID-only liveness assumption."""
    def __init__(self, pid, created=None):
        self.pid, self.created = pid, None
        self.handle = self.fd = self.kernel = None
        self.valid = False
        if type(pid) is not int or not 0 < pid <= 0xffffffff:
            return
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
            if not handle:
                return
            self.kernel, self.handle = kernel, handle
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                self.close()
                return
            self.created = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        else:
            try:
                self.created = self._posix_created()
                if hasattr(os, 'pidfd_open'):
                    self.fd = os.pidfd_open(pid)
                    if self._posix_created() != self.created:
                        self.close()
                        return
            except (OSError, ValueError):
                self.close()
                return
        self.valid = created is None or self.created == created
        if not self.valid:
            self.close()

    def _posix_created(self):
        stat = Path('/proc') / str(self.pid) / 'stat'
        if stat.exists():
            text = stat.read_text()
            fields = text[text.rfind(')') + 2:].split()
            if fields[0] == 'Z':
                raise ProcessLookupError()
            return fields[19]
        import subprocess
        ps = '/bin/ps' if Path('/bin/ps').is_file() else '/usr/bin/ps'
        result = subprocess.run([ps, '-o', 'lstart=', '-p', str(self.pid)],
            capture_output=True, text=True, timeout=2)
        value = result.stdout.strip()
        if result.returncode or not value:
            raise ProcessLookupError()
        return value

    def alive(self):
        if not self.valid:
            return False
        if self.handle is not None:
            return self.kernel.WaitForSingleObject(self.handle, 0) == 258  # WAIT_TIMEOUT
        if self.fd is not None:
            import select
            return not select.select([self.fd], [], [], 0)[0]
        try:
            return self._posix_created() == self.created
        except (OSError, ValueError):
            return False

    def close(self):
        self.valid = False
        if self.handle is not None:
            handle, self.handle = self.handle, None
            self.kernel.CloseHandle(handle)
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)


def remove_client_lease(lease):
    try:
        lease.unlink(missing_ok=True)
    except OSError:
        pass


def register_client(root, descriptor, owner):
    directory = reject_links(Path(root) / 'desktop-clients')
    directory.mkdir(exist_ok=True)
    private_permissions(directory, directory=True)
    lease = directory / (uuid.uuid4().hex + '.json')
    identity = DesktopOwner(os.getpid())
    try:
        if not identity.alive():
            return None
        atomic_json(lease, {'pid': os.getpid(), 'creation': identity.created})
    finally:
        identity.close()
    try:
        current = json.loads((Path(root) / 'desktop-session.json').read_text('utf-8'))
        if (all(current.get(key) == descriptor.get(key) for key in
                ('instance', 'owner_pid', 'owner_created')) and owner.alive()):
            return lease
    except (OSError, ValueError):
        pass
    # Registration may race shutdown. A missing/replaced owner descriptor must
    # never leave a new helper or lease behind after the shutdown snapshot.
    remove_client_lease(lease)
    return None


def rpc(root, method, **parameters):
    descriptor = json.loads((Path(root) / 'desktop-session.json').read_text('utf-8'))
    url = urlsplit(descriptor['url'])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.path != '/rpc' or url.query:
        raise RuntimeError('Desktop service unavailable')
    payload = json.dumps({'method': method, **parameters}, ensure_ascii=False).encode('utf-8')
    if len(payload) > LIMIT:
        raise ValueError('Request too large')
    request = Request(descriptor['url'], data=payload, headers={
        'Authorization': 'Bearer ' + descriptor['token'], 'Content-Type': 'application/json'})
    with loopback_open(request, timeout=120) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise RuntimeError('Desktop response too large')
    value = json.loads(raw)
    if not value.get('ok'):
        raise RuntimeError(value.get('error', 'Desktop operation failed'))
    return value['result']


async def serve(root):
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    async def list_tools(_context, _parameters):
        try:
            result = await asyncio.to_thread(rpc, root, 'list-tools')
            return types.ListToolsResult(tools=[types.Tool.model_validate(tool) for tool in result])
        except Exception:
            return types.ListToolsResult(tools=[])

    async def call_tool(_context, parameters):
        try:
            result = await asyncio.to_thread(rpc, root, 'call-tool',
                name=parameters.name, arguments=parameters.arguments or {})
            return types.CallToolResult.model_validate(result)
        except Exception:
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text',
                text='EvoMyn MCP 已关闭或桌面应用不可用。请在桌面应用开启后重试。')])

    server = Server('EvoMyn', version='0.2.8',
                    on_list_tools=list_tools, on_call_tool=call_tool)
    descriptor_path = Path(root) / 'desktop-session.json'
    try:
        descriptor = json.loads(descriptor_path.read_text('utf-8'))
        instance = descriptor['instance']
        owner = DesktopOwner(descriptor['owner_pid'], descriptor['owner_created'])
    except (OSError, ValueError, KeyError):
        return
    if not owner.alive():
        owner.close()
        return
    try:
        lease = register_client(root, descriptor, owner)
    except (OSError, ValueError):
        owner.close()
        return
    if lease is None:
        owner.close()
        return

    async def desktop_stopped():
        while True:
            await asyncio.sleep(0.25)
            if not owner.alive():
                return
            try:
                if json.loads(descriptor_path.read_text('utf-8')).get('instance') == instance:
                    continue
            except (OSError, ValueError):
                pass
            return

    try:
        async with stdio_server() as streams:
            runner = asyncio.create_task(server.run(*streams, server.create_initialization_options()))
            watcher = asyncio.create_task(desktop_stopped())
            try:
                done, _ = await asyncio.wait((runner, watcher), return_when=asyncio.FIRST_COMPLETED)
                if watcher in done:
                    # Windows SDK stdin can be blocked in a non-cancellable OS
                    # read while Codex holds its pipe. This forwarding-only
                    # helper has no DB/child; self-exit releases updater DLLs.
                    def finish_helper():
                        remove_client_lease(lease)
                        owner.close()
                        os._exit(0)
                    safeguard = threading.Timer(1, finish_helper)
                    safeguard.daemon = True
                    safeguard.start()
            finally:
                runner.cancel()
                watcher.cancel()
                await asyncio.gather(runner, watcher, return_exceptions=True)
    finally:
        remove_client_lease(lease)
        owner.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path,
        default=os.environ.get('MNEMOSYNE_DESKTOP_DATA_ROOT'))
    args = parser.parse_args()
    if args.data_root is None:
        parser.error('A desktop data directory is required')
    asyncio.run(serve(args.data_root))
