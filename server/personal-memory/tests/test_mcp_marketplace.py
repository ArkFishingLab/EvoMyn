import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

VENDOR = Path(__file__).resolve().parents[1] / 'vendor'
sys.path.insert(0, str(VENDOR))


class MarketplaceTests(unittest.TestCase):
    def setUp(self):
        path = VENDOR / 'mcp_marketplace.py'
        self.assertTrue(path.is_file(), 'Unified MCP marketplace is not implemented')
        spec = importlib.util.spec_from_file_location('market_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.module = module
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Installation is simulated by runner below; discovery must also stay
        # independent of whether the developer or CI machine has uv installed.
        discovery = patch.object(module.shutil, 'which', return_value=str(self.root / 'fixture-uv.exe'))
        discovery.start()
        self.addCleanup(discovery.stop)
        from mcp_packages import Packages
        self.packages = Packages(self.root / 'mcp-packages.json')
        self.commands = []
        self.probes = []
        def runner(args, timeout):
            self.commands.append(args)
            if 'venv' in args:
                python = self.packages.python('worldtime')
                python.parent.mkdir(parents=True, exist_ok=True)
                python.touch()
        self.market = module.Marketplace(self.root, runner=runner, probe=lambda path: self.probes.append(path))

    def test_unified_catalog_has_provenance_and_only_installed_items_appear_in_my_abilities(self):
        catalog = self.packages.catalog()
        self.assertEqual([item['id'] for item in catalog], ['archive', 'planner', 'worldtime'])
        self.assertTrue(all(item['source'] and item['author'] and item['version'] for item in catalog))
        self.assertFalse(catalog[-1]['installed'])
        self.assertEqual(len(self.packages.list()), 2)

    def test_legacy_settings_survive_new_catalog(self):
        (self.root / 'mcp-packages.json').write_text('{"archive":false,"planner":true}', encoding='utf-8')
        self.assertEqual([item['enabled'] for item in self.packages.list()], [False, True])
        self.assertFalse(self.packages.error)

    def test_install_is_pinned_isolated_and_verified_before_publication(self):
        self.market.install('worldtime')
        item = self.packages.catalog()[-1]
        self.assertTrue(item['installed'])
        self.assertFalse(item['enabled'])
        self.assertEqual(len(self.probes), 1)
        self.assertTrue(any('mcp-server-time==2026.10.10' in command for command in self.commands))
        self.assertTrue(all(isinstance(command, list) for command in self.commands))
        self.packages.set('worldtime', True)
        self.assertTrue(self.packages.list()[-1]['enabled'])

    def test_failed_probe_does_not_publish_install_or_change_existing_switches(self):
        self.packages.set('archive', False)
        def fail(_): raise RuntimeError('provider not usable')
        self.market.probe = fail
        with self.assertRaises(RuntimeError): self.market.install('worldtime')
        self.assertFalse(self.packages.catalog()[-1]['installed'])
        self.assertFalse(self.packages.list()[0]['enabled'])

    def test_only_fixed_packages_can_install_and_uninstalled_tools_are_blocked(self):
        for ident in ['shell', '../worldtime', {'command': 'whoami'}]:
            with self.assertRaises(ValueError): self.market.install(ident)
        self.assertEqual(self.commands, [])
        with self.assertRaises(ValueError): self.packages.set('worldtime', True)
        blocked = self.packages.blocked_response(json.dumps({'id': 1, 'method': 'tools/call',
            'params': {'name': 'worldtime_now'}}))
        self.assertTrue(json.loads(blocked)['result']['isError'])

    def test_remove_hides_provider_and_does_not_remove_core_or_user_data(self):
        self.market.install('worldtime')
        self.packages.set('worldtime', True)
        self.market.remove('worldtime')
        self.assertFalse(self.packages.catalog()[-1]['installed'])
        self.assertFalse(self.packages.catalog()[-1]['enabled'])
        self.assertTrue(self.packages.python('worldtime').exists())
        for ident in ['archive', 'planner']:
            with self.assertRaises(ValueError): self.market.remove(ident)

    def test_stdio_registers_only_enabled_installed_provider(self):
        from market_tools import register_market_tools
        registered = []
        class Registry:
            def tool(self, **kwargs):
                def add(function): registered.append(function.__name__); return function
                return add
        self.market.install('worldtime')
        register_market_tools(Registry(), self.packages)
        self.assertEqual(registered, [])
        self.packages.set('worldtime', True)
        register_market_tools(Registry(), self.packages)
        self.assertEqual(registered, ['worldtime_now', 'worldtime_convert'])


if __name__ == '__main__': unittest.main()
