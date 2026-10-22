import importlib.util
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


if __name__ == '__main__':
    unittest.main()
