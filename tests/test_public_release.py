"""Privacy and reproducibility checks for the public source exporter."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'package_public_release.py'
spec = importlib.util.spec_from_file_location('package_public_release', SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='公开 包 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for source in release.PUBLIC_FILES:
            target = self.root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('# clean public source\n', encoding='utf-8')

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def members(self, output):
        with zipfile.ZipFile(output) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    @unittest.skipUnless(os.name == 'nt', 'Windows short path aliases')
    def test_windows_short_workspace_alias_preserves_export_contents(self):
        import ctypes
        from ctypes import wintypes
        get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        buffer = ctypes.create_unicode_buffer(32768)
        self.assertTrue(get_short(str(self.root.resolve()), buffer, len(buffer)))
        alias = Path(buffer.value)
        if str(alias).casefold() == str(self.root.resolve()).casefold():
            self.skipTest('8.3 alias creation is disabled on this volume')
        expected = self.members(release.build_public_release(self.root)['zip'])
        actual = self.members(release.build_public_release(alias)['zip'])
        self.assertEqual(actual, expected)

    def test_explicit_allowlist_blocks_private_state_and_arbitrary_additions(self):
        for name in (
            'runtime/.env', 'runtime/data/archive.db', 'runtime/logs/error.log',
            'server/personal-memory/vendor/new_module.py',
            'server/personal-memory/vendor/__pycache__/runtime.pyc',
            'server/personal-memory/viewer/static/fonts/private.woff2',
            'server/personal-memory/distribution/random-notice.txt',
            'xiaozhi-firmware/main/round_services_private.h',
            'artifacts/firmware.bin', 'backups/private.json',
        ):
            self.write(name, 'NEVER_DISTRIBUTE_SENTINEL')
        result = release.build_public_release(self.root)
        members = self.members(result['zip'])
        self.assertTrue(all(name.startswith('evomyn-mcp/') for name in members))
        self.assertIn('evomyn-mcp/app/runtime.py', members)
        self.assertIn('evomyn-mcp/viewer/LICENSE', members)
        self.assertNotIn(b'NEVER_DISTRIBUTE_SENTINEL', b''.join(members.values()))
        self.assertFalse(any('fonts/' in name or 'new_module.py' in name for name in members))

    def test_zip_and_manifest_are_deterministic_and_complete(self):
        first = release.build_public_release(self.root)
        before = first['zip'].read_bytes()
        second = release.build_public_release(self.root)
        self.assertEqual(before, second['zip'].read_bytes())
        self.assertEqual(second['checksum'].read_text(encoding='utf-8'),
                         hashlib.sha256(before).hexdigest() + '  ' + second['zip'].name + '\n')
        members = self.members(second['zip'])
        manifest = json.loads(second['manifest'].read_text(encoding='utf-8'))
        self.assertEqual(manifest, json.loads(members['evomyn-mcp/MANIFEST.json']))
        expected = {name.removeprefix('evomyn-mcp/') for name in members}
        self.assertEqual({entry['path'] for entry in manifest['files']}, expected - {'MANIFEST.json'})
        for entry in manifest['files']:
            data = members['evomyn-mcp/' + entry['path']]
            self.assertEqual(entry['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(entry['size'], len(data))
        self.assertEqual(json.loads(second['audit'].read_text(encoding='utf-8'))['status'], 'passed')

    def test_extracted_public_source_rebuilds_without_private_workspace_layout(self):
        result = release.build_public_release(self.root)
        extracted = self.root / '解压 后的源码'
        with zipfile.ZipFile(result['zip']) as archive:
            archive.extractall(extracted)
        public_root = extracted / 'evomyn-mcp'
        self.assertFalse((public_root / 'server').exists())
        rebuilt = release.build_public_release(public_root)
        self.assertEqual(result['zip'].read_bytes(), rebuilt['zip'].read_bytes())

    def test_public_css_does_not_request_unshipped_font_files(self):
        self.write('server/personal-memory/viewer/static/style.css',
                   '@font-face{font-family:workspace;src:url("./fonts/private.woff2")}\n'
                   ':root{--paper:white}\n')
        result = release.build_public_release(self.root)
        css = self.members(result['zip'])['evomyn-mcp/viewer/static/style.css']
        self.assertNotIn(b'@font-face', css)
        self.assertIn(b'--paper:white', css)

    def test_optional_firmware_is_explicit_audited_and_ships_export_helper(self):
        for relative in release.FIRMWARE_SUPPORT_FILES:
            self.write(relative, '# safe support source\n')
        self.write('tools/export_round_sources.py',
                   'def export_round_sources(workspace, dest):\n'
                   '    (dest / "README.md").write_text("Optional source only\\n", encoding="utf-8")\n'
                   '    return ["No binaries included"]\n')
        plain = self.members(release.build_public_release(self.root)['zip'])
        self.assertFalse(any('/firmware/' in name for name in plain))
        result = release.build_public_release(self.root, include_firmware=True)
        members = self.members(result['zip'])
        self.assertIn('evomyn-mcp/firmware/README.md', members)
        self.assertIn('evomyn-mcp/tools/export_round_sources.py', members)
        self.assertEqual(members['evomyn-mcp/VERSION'], b'0.2.10\n')

    def test_reserved_test_domain_fixtures_do_not_disable_real_credential_audit(self):
        fixture = 'wss://fixture.test/mcp?token=' + 'obviously-dummy-fixture'
        self.write('server/personal-memory/tests/test_local_onboarding.py', fixture)
        release.build_public_release(self.root)
        self.write('artifacts/runtime/.env', 'MCP_ENDPOINT=' + fixture)
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root)

    def test_missing_required_source_fails_without_replacing_existing_zip(self):
        output = self.root / 'artifacts/public-release/keep.zip'
        output.parent.mkdir(parents=True)
        output.write_bytes(b'previous release')
        (self.root / next(iter(release.PUBLIC_FILES))).unlink()
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root, output)
        self.assertEqual(output.read_bytes(), b'previous release')

    def test_known_env_secret_reused_in_allowed_source_is_rejected_without_disclosure(self):
        secret = 'unit-test-runtime-' + 'secret-9083736373'
        self.write('artifacts/local-personal-memory/.env', 'MCP_ENDPOINT=wss://host.example/mcp?token=' + secret)
        self.write('server/personal-memory/vendor/runtime.py', '# accidentally copied ' + secret)
        with self.assertRaises(release.ReleaseError) as caught:
            release.build_public_release(self.root)
        self.assertNotIn(secret, str(caught.exception))
        self.assertFalse(list((self.root / 'artifacts/public-release').glob('*.zip')))

    def test_known_private_header_secret_is_also_rejected(self):
        secret = 'private-header-' + 'credential-029372635'
        self.write('firmware/main/round_services_private.h',
                   '#define DEVICE_GATEWAY_TOKEN "' + secret + '"\n')
        self.write('server/personal-memory/viewer/index.html', '<!--' + secret + '-->')
        with self.assertRaises(release.ReleaseError) as caught:
            release.build_public_release(self.root)
        self.assertNotIn(secret, str(caught.exception))

    def test_env_quotes_comments_and_bom_do_not_hide_a_known_secret(self):
        secret = 'quoted-private-' + 'credential-927365482'
        self.write('runtime/.env', '\ufeffSERVICE_PASSWORD="' + secret + '" # local only\n')
        self.write('server/personal-memory/vendor/runtime.py', '# ' + secret)
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows junction check')
    def test_windows_directory_junction_is_rejected_without_symlink_privilege(self):
        import _winapi
        vendor = self.root / 'server/personal-memory/vendor'
        moved = vendor.with_name('linked-private-vendor')
        vendor.rename(moved)
        _winapi.CreateJunction(str(moved), str(vendor))
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows junction check')
    def test_export_staging_never_writes_through_directory_junction(self):
        import _winapi
        target = self.root / 'elsewhere'
        target.mkdir()
        _winapi.CreateJunction(str(target), str(self.root / 'artifacts'))
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root)
        self.assertFalse((target / 'public-release').exists())

    def test_generic_credential_patterns_are_rejected(self):
        values = [
            'wss://host.example/mcp?token=' + 'abc123credential456',
            '-----BEGIN ' + 'RSA PRIVATE KEY-----\n' + 'A' * 48 + '\n',
            '-----BEGIN ' + 'RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\n',
            '{"private_key":"-----BEGIN ' + 'PRIVATE KEY-----\\n' + 'A' * 48 + '"}',
            'github_pat_' + ('A' * 70),
        ]
        for value in values:
            with self.subTest(kind=value[:8]):
                self.write('server/personal-memory/vendor/runtime.py', value)
                with self.assertRaises(release.ReleaseError) as caught:
                    release.build_public_release(self.root)
                self.assertNotIn(value, str(caught.exception))

    def test_private_key_marker_in_crypto_implementation_is_not_key_material(self):
        self.write('server/personal-memory/vendor/backup_bundle.py',
                   'PRIVATE_PEM_HEADER = "-----BEGIN ' + 'PRIVATE KEY-----"\n')
        release.build_public_release(self.root)

    def test_symlink_file_and_parent_directory_are_rejected(self):
        source = self.root / 'server/personal-memory/vendor/runtime.py'
        other = self.write('private/runtime.py', 'secret')
        source.unlink()
        try:
            source.symlink_to(other)
        except OSError:
            self.skipTest('Creating symlinks requires Windows developer mode or permission')
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root)
        source.unlink()
        source.write_text('# clean\n', encoding='utf-8')
        vendor = source.parent
        moved = vendor.with_name('private-vendor')
        vendor.rename(moved)
        vendor.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(release.ReleaseError):
            release.build_public_release(self.root)


if __name__ == '__main__':
    unittest.main()
