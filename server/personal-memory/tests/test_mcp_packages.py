import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


class PackageTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'vendor/mcp_packages.py'
        self.assertTrue(path.is_file(), 'MCP functionality packages are not implemented')
        spec = importlib.util.spec_from_file_location('packages_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'mcp-packages.json'
        self.packages = module.Packages(self.path)

    def test_default_groups_and_persistent_independent_switches(self):
        groups = self.packages.list()
        self.assertEqual([(item['id'], item['enabled'], len(item['tools'])) for item in groups],
                         [('archive', True, 10), ('planner', True, 9)])
        self.packages.set('archive', False)
        self.assertFalse(type(self.packages)(self.path).list()[0]['enabled'])
        self.assertTrue(self.packages.list()[1]['enabled'])

    def test_hidden_tools_and_cached_calls_are_blocked(self):
        self.packages.set('planner', False)
        message = {'id': 2, 'result': {'tools': [{'name': 'archive_get'}, {'name': 'planner_create'}]}}
        result = json.loads(self.packages.filter_response(json.dumps(message)))
        self.assertEqual([tool['name'] for tool in result['result']['tools']], ['archive_get'])
        blocked = self.packages.blocked_response(json.dumps({'id': 3, 'method': 'tools/call',
            'params': {'name': 'planner_create', 'arguments': {'title': 'PRIVATE'}}}))
        self.assertTrue(json.loads(blocked)['result']['isError'])
        self.assertNotIn('PRIVATE', blocked)
        self.assertIsNone(self.packages.blocked_response(json.dumps({'id': 4, 'method': 'tools/call',
            'params': {'name': 'archive_get'}})))

    def test_attachment_tool_is_registered_and_gated(self):
        import ast
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'vendor/mcp_server.py').read_text(encoding='utf-8'))
        tool = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'archive_attach')
        self.assertTrue(tool.decorator_list)
        self.packages.set('archive', False)
        result = self.packages.blocked_response(json.dumps({'id': 7, 'method': 'tools/call', 'params': {'name': 'archive_attach'}}))
        self.assertTrue(json.loads(result)['result']['isError'])

    def test_both_groups_can_be_off_and_corrupt_settings_do_not_reenable_tools(self):
        self.packages.set('archive', False)
        self.packages.set('planner', False)
        self.assertFalse(any(item['enabled'] for item in self.packages.list()))
        self.path.write_text('bad json', encoding='utf-8')
        self.assertFalse(any(item['enabled'] for item in self.packages.list()))
        self.assertTrue(self.packages.error)

    def test_only_known_group_and_boolean_switches_are_accepted(self):
        for ident, enabled in [('shell', True), ('planner', 'false'), ('planner', 0)]:
            with self.assertRaises(ValueError): self.packages.set(ident, enabled)
        self.assertFalse(self.path.exists())


if __name__ == '__main__': unittest.main()
