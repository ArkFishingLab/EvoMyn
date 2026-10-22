"""Portable helper contracts; no SDK, hardware or private runtime required."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('round_provision_fixture', ROOT / 'tools/provision_round_gateway.py')
PROVISION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVISION)


class DevelopmentToolsTests(unittest.TestCase):
    def test_ipv6_rejected_before_creating_any_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'IPv4'):
                PROVISION.provision('::1', runtime=root / 'runtime', private_dir=root / 'private', header=root / 'header.h')
            self.assertEqual(list(root.iterdir()), [])

    @unittest.skipUnless(importlib.util.find_spec('cryptography') and importlib.util.find_spec('dotenv'), 'Optional gateway dependencies')
    def test_isolated_tls_reuse_and_host_mismatch_preserve_existing_files(self):
        import secrets
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            (runtime / 'app').mkdir(parents=True)
            env = runtime / 'app/.env'
            env.write_text('PLANNER_DEVICE_TOKEN=' + secrets.token_hex(32) + '\nPLANNER_DEVICE_ID=fixture-device\n', encoding='utf-8')
            options = dict(runtime=runtime, private_dir=root / 'private', header=root / 'header.h')
            PROVISION.provision('192.0.2.10', **options)
            snapshot = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            PROVISION.provision('192.0.2.10', **options)
            self.assertTrue(all(p.read_bytes() == contents for p, contents in snapshot.items()))
            with self.assertRaisesRegex(ValueError, 'does not match'):
                PROVISION.provision('192.0.2.11', **options)
            self.assertTrue(all(p.read_bytes() == contents for p, contents in snapshot.items()))

    def test_render_help_does_not_compile_or_create_outputs(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/render_round_update.py'), '--help'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--build-dir', result.stdout)

    def test_provisioning_requires_explicit_host(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/provision_round_gateway.py')], capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--host', result.stderr)

    def test_icon_source_is_standalone_and_complete(self):
        icons = json.loads((ROOT / 'assets/warm-icons.json').read_text('utf-8'))
        for key in ('wifi', 'settings', 'back', 'right', 'link', 'volume', 'sun', 'refresh', 'eye', 'stop', 'lock', 'check'):
            self.assertIn('<', icons[key])

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell wrapper')
    def test_build_help_uses_configurable_sdk_and_build_directory(self):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(ROOT / 'tools/build_round.ps1'), '-IdfPath', str(ROOT / 'missing-sdk-fixture'), '-Check'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('IDF_PATH', result.stderr)


if __name__ == '__main__':
    unittest.main()
