import ast
import os
import ssl
import unittest
from pathlib import Path
from unittest.mock import patch

import test_device_archive_gateway as gateway_tests


class DashboardGatewayConfigurationTests(unittest.TestCase):
    def load_builder(self):
        path = Path(__file__).resolve().parents[1] / 'local/dashboard.py'
        source = ast.parse(path.read_text(encoding='utf-8-sig'))
        function = next((item for item in source.body if isinstance(item, ast.FunctionDef)
                         and item.name == 'build_device_gateway'), None)
        self.assertIsNotNone(function, 'Dashboard needs optional device gateway builder')
        namespace = {'os': os}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        return namespace['build_device_gateway']

    def test_no_gateway_configuration_is_disabled(self):
        builder = self.load_builder()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(builder(Path('/isolated-dashboard')))

    def test_partial_configuration_fails_closed(self):
        builder = self.load_builder()
        with patch.dict(os.environ, {'DEVICE_GATEWAY_HOST': '127.0.0.1'}, clear=True):
            with self.assertRaises(ValueError): builder(Path('/isolated-dashboard'))

    def test_configuration_uses_existing_archive_home_without_model_load(self):
        gateway_tests.DeviceGatewayTests.setUpClass()
        try:
            builder = self.load_builder()
            env = {'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows'), 'DEVICE_GATEWAY_HOST': '127.0.0.1', 'DEVICE_GATEWAY_PORT': '0',
                   'DEVICE_GATEWAY_CERT': str(gateway_tests.DeviceGatewayTests.cert_path),
                   'DEVICE_GATEWAY_KEY': str(gateway_tests.DeviceGatewayTests.key_path),
                   'PLANNER_DEVICE_TOKEN': 't' * 64, 'PLANNER_DEVICE_ID': 'dev1',
                   'PERSONAL_ARCHIVE_HOME': '/isolated-completions',
                   'DEVICE_UPDATE_DIR': '/isolated-updates'}
            with patch.dict(os.environ, env, clear=True):
                server = builder(Path('/isolated-dashboard'))
                try:
                    self.assertEqual(str(server.archive.archive_root), '/isolated-completions')
                    self.assertIsNone(server.archive._store)
                    from device_updates import ReleaseProvider
                    self.assertIsInstance(server.update_provider, ReleaseProvider)
                    self.assertEqual(server.update_provider.directory, Path('/isolated-updates').resolve())
                    self.assertEqual(os.environ['PERSONAL_ARCHIVE_HOME'], '/isolated-completions')
                finally: server.server_close()
        finally: gateway_tests.DeviceGatewayTests.tearDownClass()

if __name__ == '__main__': unittest.main()
