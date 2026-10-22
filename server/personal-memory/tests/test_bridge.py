import asyncio
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))

spec = importlib.util.spec_from_file_location("memory_pipe", Path(__file__).resolve().parents[1] / "vendor/mcp_pipe.py")
pipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipe)


class Process:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class Connection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def recv(self):
        await asyncio.Event().wait()

    async def send(self, value):
        pass


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_import_does_not_load_private_configuration(self):
        isolated = importlib.util.module_from_spec(spec)
        with patch('dotenv.load_dotenv') as load:
            spec.loader.exec_module(isolated)
        load.assert_not_called()

    async def test_disabled_cached_call_never_reaches_child_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            packages = pipe.Packages(Path(temporary) / 'packages.json')
            packages.set('planner', False)
            process = Process()
            class Input(io.StringIO):
                writes = []
                def write(self, value):
                    self.writes.append(value)
                    return super().write(value)
            process.stdin = Input()
            class Socket:
                sent = []
                received = False
                async def recv(self):
                    if self.received: raise ConnectionError('test done')
                    self.received = True
                    return json.dumps({'id': 7, 'method': 'tools/call', 'params': {'name': 'planner_create'}})
                async def send(self, value): self.sent.append(json.loads(value))
            socket = Socket()
            with patch.object(pipe, 'packages', packages), patch.object(pipe, 'log_protocol_event'):
                with self.assertRaises(ConnectionError):
                    await pipe.pipe_websocket_to_process(socket, process, 'test')
            self.assertEqual(len(socket.sent), 1)
            self.assertTrue(socket.sent[0]['result']['isError'])
            self.assertEqual(socket.sent[0]['id'], 7)
            self.assertEqual(process.stdin.writes, [])
            self.assertTrue(process.stdin.closed)

    async def test_cloud_discovery_receives_only_enabled_package_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            packages = pipe.Packages(Path(temporary) / 'packages.json')
            packages.set('archive', False)
            process = Process()
            process.stdout = io.StringIO(json.dumps({'id': 1, 'result': {'tools': [
                {'name': 'archive_get'}, {'name': 'planner_list'}]}}) + '\n')
            class Socket:
                sent = []
                async def send(self, value): self.sent.append(json.loads(value))
            socket = Socket()
            with patch.object(pipe, 'packages', packages), patch.object(pipe, 'log_protocol_event'):
                with self.assertRaises(ConnectionError):
                    await pipe.pipe_process_to_websocket(process, socket, 'test')
            self.assertEqual([tool['name'] for tool in socket.sent[0]['result']['tools']], ['planner_list'])

    def test_protocol_log_confirms_discovery_without_recording_private_arguments(self):
        with self.assertLogs(pipe.logger, level="INFO") as logs:
            pipe.log_protocol_event('{"method":"tools/call","params":{"arguments":{"body":"PRIVATE_CONTENT"}}}', incoming=True)
            pipe.log_protocol_event('{"result":{"tools":[{"name":"archive_search"}]}}', incoming=False)
        self.assertIn("tools/call", " ".join(logs.output))
        self.assertIn("tools published: 1", " ".join(logs.output))
        self.assertNotIn("PRIVATE_CONTENT", " ".join(logs.output))

    async def test_dead_child_reconnects_even_when_cloud_socket_remains_open(self):
        process = Process()
        before = set(asyncio.all_tasks())
        with patch.object(pipe.websockets, "connect", return_value=Connection()), \
             patch.object(pipe, "build_server_command", return_value=(["test-child"], {})), \
             patch.object(pipe.subprocess, "Popen", return_value=process):
            with self.assertRaises(ConnectionError):
                await asyncio.wait_for(pipe.connect_to_server("wss://example.invalid/", "test"), .5)
        await asyncio.sleep(0)
        self.assertTrue(process.terminated)
        self.assertFalse(set(asyncio.all_tasks()) - before)


if __name__ == "__main__":
    unittest.main()
