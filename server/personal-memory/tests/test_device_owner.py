import ast
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'vendor'))
from mcp_packages import Packages


class Registry:
    def __init__(self, name): self.tools = {}; self.descriptions = {}
    def tool(self, **kwargs):
        def register(function):
            self.tools[function.__name__] = function
            self.descriptions[function.__name__] = kwargs.get('description') or function.__doc__
            return function
        return register
    def remove_tool(self, name): self.tools.pop(name)


class DeviceOwnerTests(unittest.TestCase):
    def test_device_builtins_are_absent_from_capabilities_and_ignore_saved_planner_enable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'PLANNER_OWNER': 'device'}):
            location = Path(tmp) / 'packages.json'
            location.write_text(json.dumps({'archive': True, 'planner': True}))
            packages = Packages(location)
            catalog = {item['id']: item for item in packages.catalog()}
            self.assertNotIn('planner', catalog)
            self.assertNotIn('planner', {item['id'] for item in packages.list()})
            self.assertTrue(catalog['archive']['enabled'])
            before = location.read_bytes()
            with self.assertRaisesRegex(ValueError, 'device|圆盘'):
                packages.set('planner', True)
            self.assertEqual(location.read_bytes(), before)
            response = json.dumps({'id': 1, 'result': {'tools': [{'name': 'planner_create'}, {'name': 'archive_get'}]}})
            self.assertEqual([x['name'] for x in json.loads(packages.filter_response(response))['result']['tools']], ['archive_get'])
            blocked = packages.blocked_response(json.dumps({'id': 2, 'method': 'tools/call', 'params': {'name': 'planner_create'}}))
            self.assertIn('self.planner.', blocked)

    def load_mcp(self, owner, groups=None):
        registered = []
        modules = {}
        archive = types.ModuleType('archive_store'); archive.ArchiveStore = lambda: object()
        mcp = types.ModuleType('mcp.server.mcpserver'); mcp.MCPServer = Registry
        planner = types.ModuleType('planner_tools')
        planner.register_planner_tools = lambda registry: registered.append('planner')
        market = types.ModuleType('market_tools')
        market.register_market_tools = lambda registry: registered.append('market')
        modules.update(archive_store=archive, planner_tools=planner, market_tools=market)
        modules['mcp.server.mcpserver'] = mcp
        spec = importlib.util.spec_from_file_location('isolated_owner_mcp', BASE / 'vendor/mcp_server.py')
        module = importlib.util.module_from_spec(spec)
        with patch('mcp_packages.Packages') as packages, patch.dict(os.environ, {'PLANNER_OWNER': owner}), patch.dict(sys.modules, modules):
            packages.return_value.list.return_value = groups or []
            spec.loader.exec_module(module)
        return module, registered

    def test_device_mcp_registers_only_archive_and_unchanged_market(self):
        module, registered = self.load_mcp('device')
        self.assertEqual(registered, ['market'])
        self.assertEqual(len(module.mcp.tools), 9)
        self.assertIn('self.planner.', module.mcp.descriptions['archive_record'])
        self.assertIn('self.planner.', module.mcp.descriptions['archive_list'])
        self.assertNotIn('planner_create', module.mcp.descriptions['archive_record'])
        self.assertNotIn('planner_list', module.mcp.descriptions['archive_list'])

    def test_default_pc_mcp_registration_and_description_remain(self):
        module, registered = self.load_mcp('pc')
        self.assertEqual(registered, ['planner', 'market'])
        self.assertIn('planner_create', module.mcp.descriptions['archive_record'])

    def test_direct_stdio_registry_respects_disabled_archive_package(self):
        tools = ['archive_status', 'archive_record', 'archive_update', 'archive_list',
                 'archive_get', 'archive_search', 'archive_history', 'archive_backup', 'archive_retry_index']
        module, _ = self.load_mcp('device', groups=[
            {'builtin': True, 'enabled': False, 'external': False, 'tools': tools}])
        self.assertEqual(module.mcp.tools, {})

    def dashboard_part(self, name):
        source = ast.parse((BASE / 'local/dashboard.py').read_text(encoding='utf-8'))
        item = next((node for node in source.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name), None)
        self.assertIsNotNone(item, 'Missing isolated dashboard component: ' + name)
        namespace = {'os': os, 'BaseHTTPRequestHandler': BaseHTTPRequestHandler,
                     'PLANNER_OWNER': 'device', 'urlsplit': urlsplit}
        exec(compile(ast.Module(body=[item], type_ignores=[]), '<dashboard-isolated>', 'exec'), namespace)
        return namespace[name]

    def test_device_owner_creates_no_pc_store_or_listeners(self):
        factory = self.dashboard_part('build_planner_services')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(factory('device'), (None, None, None))
        with self.assertRaises(ValueError): factory('unknown')

    def test_default_pc_planner_services_keep_existing_ports(self):
        factory = self.dashboard_part('build_planner_services')
        created = []
        store_module = types.ModuleType('planner_store')
        store_module.PlannerStore = lambda: created.append('store') or object()
        backend = types.ModuleType('planner_server')
        backend.process_device_message = lambda *args: None
        backend.create_http_server = lambda *args, **kwargs: created.append(kwargs['port']) or 'http'
        backend.create_websocket_server = lambda *args: created.append(args[2]) or 'websocket'
        with patch.dict(os.environ, {'PLANNER_DEVICE_TOKEN': 't' * 64, 'PLANNER_DEVICE_ID': 'dev1'}), patch.dict(sys.modules, {'planner_store': store_module, 'planner_server': backend}):
            store, http, websocket = factory('pc')
        self.assertIsNotNone(store); self.assertEqual((http, websocket), ('http', 'websocket'))
        self.assertEqual(created, ['store', 18769, 18771])

    def test_viewer_navigation_omits_pc_planner_only_for_device_owner(self):
        spec = importlib.util.spec_from_file_location('isolated_owner_viewer', BASE / 'viewer/server.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            for owner in ('pc', 'device'):
                with patch.dict(os.environ, {'PLANNER_OWNER': owner}):
                    server = module.create_server(Path(tmp) / 'unused.db', host='127.0.0.1', port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                    connection.request('GET', '/'); response = connection.getresponse(); html = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(b'href="/memory/planner/"' in html, owner == 'pc')
                    connection.close()
                finally: server.shutdown(); server.server_close(); thread.join()

    def test_retired_planner_dashboard_is_410_without_forward(self):
        handler = self.dashboard_part('Dashboard')
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for path in ('/memory/planner', '/memory/planner/', '/memory/planner/api/tasks'):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                connection.request('GET', path, headers={'Host': '127.0.0.1:18768'})
                response = connection.getresponse(); body = response.read()
                self.assertEqual(response.status, 410)
                self.assertIn('/memory/', body.decode()); connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()

if __name__ == '__main__': unittest.main()
