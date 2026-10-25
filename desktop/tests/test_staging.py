import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RuntimeStagingTests(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('desktop_staging', ROOT / 'desktop/scripts/stage-runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_application_map_excludes_private_data_and_fonts(self):
        staging = self.load()
        paths = staging.application_files(ROOT)
        self.assertIn('app/mcp_server.py', paths)
        self.assertIn('dashboard.py', paths)
        self.assertIn('app/attachment_files.py', paths)
        self.assertIn('viewer/static/attachments.mjs', paths)
        spec = importlib.util.spec_from_file_location('desktop_runtime_paths', ROOT / 'desktop/backend/paths.py')
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        self.assertIn('app/attachment_files.py', runtime.FILES)
        self.assertIn('viewer/static/attachments.mjs', runtime.FILES)
        self.assertNotIn('app/.env', paths)
        self.assertNotIn('app/.env.example', paths)
        self.assertFalse(any('/fonts/' in name or name.startswith(('tests/', 'state/', 'logs/')) for name in paths))
        self.assertNotIn(b'@font-face', paths['viewer/static/style.css'])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for name, data in paths.items():
                target = output / 'application' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            staging.audit_stage(output)

    def test_python_copy_is_portable_and_keeps_package_licences_and_ca_store(self):
        staging = self.load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            python = root / 'python'
            packages = root / 'site-packages'
            for base, name, content in [(python, 'python.exe', b'exe'), (python, 'LICENSE.txt', b'python licence'),
                (python, 'Lib/os.py', b'stdlib'), (python, 'Lib/test/private.txt', b'development'),
                (packages, 'package/__init__.py', b'module'), (packages, 'package/tests/private.pem', b'test fixture'),
                (packages, 'package-1.0.dist-info/licenses/LICENSE', b'package licence'),
                (packages, 'certifi/cacert.pem', b'CA bundle'), (packages, '_virtualenv.pth', b'import _virtualenv'),
                (packages, 'pywin32.pth', b'win32')]:
                file = base / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(content)
            output = root / 'output'
            approved = {str(file.relative_to(packages)).replace('\\', '/'): file for file in packages.rglob('*') if file.is_file()}
            staging.copy_python(python, packages, output, approved)
            self.assertEqual((output / 'Lib/site-packages/certifi/cacert.pem').read_bytes(), b'CA bundle')
            self.assertTrue((output / 'Lib/site-packages/package-1.0.dist-info/licenses/LICENSE').is_file())
            self.assertTrue((output / 'Lib/site-packages/pywin32.pth').is_file())
            self.assertFalse((output / 'Lib/site-packages/_virtualenv.pth').exists())
            self.assertFalse((output / 'Lib/site-packages/package/tests').exists())
            self.assertFalse((output / 'Lib/test').exists())

    def test_unrelated_files_are_not_copied_and_private_record_entries_are_rejected(self):
        staging = self.load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); base = root / 'python'; packages = root / 'packages'
            base.mkdir(); (base / 'python.exe').write_bytes(b'exe'); packages.mkdir()
            approved = packages / 'approved.py'; approved.write_bytes(b'module')
            for name in ('private-tool/.env', 'private-tool/private.sqlite', 'models/private-model.bin'):
                file = packages / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'private fixture')
            output = root / 'out'
            staging.copy_python(base, packages, output, {'approved.py': approved})
            self.assertFalse((output / 'Lib/site-packages/private-tool').exists())
            self.assertFalse((output / 'Lib/site-packages/models').exists())
            with self.assertRaises(ValueError):
                staging.copy_python(base, packages, root / 'bad', {'private-tool/.env': packages / 'private-tool/.env'})

    def test_final_stage_audits_private_artifacts_and_known_credentials(self):
        staging = self.load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / '.env').write_bytes(b'harmless fixture')
            with self.assertRaises(ValueError): staging.audit_stage(root)

    def test_mac_runtime_retains_executable_modes_and_uses_posix_site_packages(self):
        staging = self.load()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); base = root / 'python'; packages = root / 'packages'
            for name in ('bin/python3.11', 'lib/libpython3.11.dylib', 'lib/python3.11/os.py', 'lib/python3.11/LICENSE.txt'):
                file = base / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'fixture')
            (base / 'bin/python3.11').chmod(0o755)
            packages.mkdir(); source = packages / 'module.py'; source.write_text('value = 1')
            output = root / 'staged'
            staging.copy_python(base, packages, output, {'module.py': source}, 'darwin')
            # NTFS does not expose POSIX executable bits; native Mac CI checks them.
            if os.name != 'nt':
                self.assertTrue((output / 'bin/python3.11').stat().st_mode & 0o100)
            self.assertTrue((output / 'lib/python3.11/site-packages/module.py').is_file())
            self.assertTrue((output / 'lib/python3.11/LICENSE.txt').is_file())
            self.assertNotIn('Lib', [item.name for item in output.iterdir()])

    def test_platform_requirements_select_one_compatible_onnx_pin(self):
        staging = self.load()
        for system, machine, version in [('Darwin', 'x86_64', '1.23.2'),
                                         ('Darwin', 'arm64', '1.31.0'),
                                         ('Windows', 'AMD64', '1.31.0'),
                                         ('Linux', 'x86_64', '1.31.0')]:
            requirements = staging.runtime_requirements({'platform_system': system, 'platform_machine': machine})
            onnx = [requirement for requirement in requirements if requirement.name == 'onnxruntime']
            self.assertEqual(len(onnx), 1)
            self.assertEqual(str(onnx[0].specifier), '==' + version)


if __name__ == '__main__':
    unittest.main()
