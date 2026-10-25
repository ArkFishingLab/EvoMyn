"""Fixed desktop-owned child roles; never accepts executable/script targets."""
import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys

from client import LIMIT, loopback_open, rpc
from paths import atomic_json


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def worker(root):
    with contextlib.redirect_stdout(sys.stderr):
        from mcp_server import mcp
    print(json.dumps({'ready': True}), flush=True)
    for line in sys.stdin:
        try:
            if len(line.encode('utf-8')) > LIMIT:
                raise ValueError()
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if request['method'] == 'list-tools':
                    result = [tool.model_dump(mode='json', by_alias=True, exclude_none=True)
                              for tool in await mcp.list_tools()]
                elif request['method'] == 'call-tool':
                    result = (await mcp.call_tool(request['name'], request['arguments'])).model_dump(
                        mode='json', by_alias=True, exclude_none=True)
                else:
                    raise ValueError()
            response = {'ok': True, 'result': result}
        except Exception:
            response = {'ok': False, 'error': 'Tool execution failed'}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def dashboard(root):
    from mcp_admin import Controller
    from onboarding import Setup

    def runner(action):
        result = rpc(root, 'control', action=action)
        return {'running': result['mcp_enabled'], 'verified': result['mcp_enabled'],
                'tcp_connected': result['cloud_connected'], 'process_id': None}

    class DesktopController(Controller):
        def __init__(self, _root):
            super().__init__(root, runner=runner)

        def status(self):
            status = {**super().status(), 'desktop_managed': True}
            try:
                live = rpc(root, 'control', action='Status')
            except Exception:
                return status
            status.update(cloud_enabled=live['cloud_enabled'], cloud_configured=live['cloud_configured'],
                connection='stopped' if not live['mcp_enabled'] or not live['cloud_enabled'] else
                    'connected' if live['cloud_connected'] else 'connecting')
            if status['connection'] == 'stopped':
                for call in status['calls']:
                    if call['status'] == 'running':
                        call['status'] = 'interrupted'
            return status

    class CloudController:
        def command(self, action):
            return rpc(root, 'set-cloud', enabled=action != 'stop')

    class DesktopSetup(Setup):
        def __init__(self, _root, _controller):
            super().__init__(root, CloudController(),
                client_config=lambda format: rpc(root, 'client-config', format=format))

        def save_endpoint(self, endpoint):
            if endpoint:
                rpc(root, 'save-endpoint', endpoint=self.endpoint(endpoint))
            else:
                rpc(root, 'set-cloud', enabled=False)

        def page(self, *args, **kwargs):
            return super().page(*args, **kwargs).replace(
                '每个客户端按需启动服务，共享本地记忆库。', '客户端连接桌面应用中的同一个 MCP 服务，共享本地记忆库。').replace(
                '保存后自动连接。', '保存后开启小智连接；桌面 MCP 总开关需保持开启。')

    # The historical dashboard loads .env on import. Its saved port values must
    # not override listeners assigned by the desktop supervisor.
    supervised_environment = os.environ.copy()
    module = load_module('desktop_dashboard', root / 'dashboard.py')
    os.environ.clear()
    os.environ.update(supervised_environment)
    module.urlopen = loopback_open
    module.Controller, module.Setup = DesktopController, DesktopSetup
    # dashboard.main imports Setup locally, so patch its authoritative module.
    import onboarding
    onboarding.Setup = DesktopSetup
    original = module.Dashboard.forward

    def forward(self):
        host = self.headers.get('Host', '')
        allowed = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
        if len(self.headers.get_all('Host', [])) != 1 or host not in allowed:
            return self.send_error(403)
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'http://' + host:
            return self.send_error(403)
        if self.command == 'POST' and ('Transfer-Encoding' in self.headers or
                len(self.headers.get_all('Content-Length', [])) != 1):
            return self.send_error(400)
        return original(self)

    module.Dashboard.forward = forward
    module.Dashboard.do_GET = module.Dashboard.do_HEAD = module.Dashboard.do_POST = forward
    module.main()


async def bridge(root, instance):
    """One WSS transport, one forwarding adapter; no private execution worker."""
    import websockets
    from dotenv import dotenv_values
    from mcp_observability import Observer
    observer = Observer(root / 'logs/events.jsonl')
    endpoint = dotenv_values(root / 'app/.env', interpolate=False).get('MCP_ENDPOINT', '')
    client = Path(__file__).with_name('client.py')
    state = root / 'state/desktop-cloud.json'
    delay = 1
    while True:
        process = None
        try:
            async with websockets.connect(endpoint, max_size=LIMIT, open_timeout=10) as websocket:
                atomic_json(state, {'instance': instance, 'connected': True})
                observer.connected()
                process = await asyncio.create_subprocess_exec(sys.executable, '-E', '-s', '-B', '-X', 'utf8', str(client),
                    '--data-root', str(root), stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=LIMIT + 1,
                    creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))

                async def incoming():
                    async for message in websocket:
                        if isinstance(message, bytes):
                            message = message.decode('utf-8')
                        # One JSON-RPC object per bounded WebSocket frame.
                        value = json.loads(message)
                        if not isinstance(value, dict):
                            raise ValueError()
                        observer.observe(message, incoming=True)
                        process.stdin.write(json.dumps(value, ensure_ascii=False).encode('utf-8') + b'\n')
                        await process.stdin.drain()

                async def outgoing():
                    while True:
                        message = await process.stdout.readline()
                        if not message or len(message) > LIMIT:
                            raise ConnectionError()
                        observer.observe(message, incoming=False)
                        await websocket.send(message.decode('utf-8'))

                tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass  # Endpoint and exception details are credentials: never log them.
        finally:
            observer.disconnected()
            atomic_json(state, {'instance': instance, 'connected': False})
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True, choices=('worker', 'dashboard', 'bridge', 'device-ota'))
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--instance', default='')
    args = parser.parse_args()
    root = args.data_root.resolve()
    os.environ['PERSONAL_ARCHIVE_HOME'] = str(root / 'state')
    sys.path[:0] = [str(root / 'app'), str(root)]
    os.chdir(root)
    if args.role == 'worker':
        asyncio.run(worker(root))
    elif args.role == 'dashboard':
        dashboard(root)
    elif args.role == 'device-ota':
        from device_ota import serve
        serve(root)
    else:
        asyncio.run(bridge(root, args.instance))


if __name__ == '__main__':
    main()
