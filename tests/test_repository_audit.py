"""Repository publication checks run only against disposable Git fixtures."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout


SCRIPT = Path(__file__).resolve().parents[1] / 'tools/audit_repository.py'


class RepositoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'Repository candidate auditor is missing')
        spec = importlib.util.spec_from_file_location('repository_audit_under_test', SCRIPT)
        self.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.audit)
        self.temp = tempfile.TemporaryDirectory(prefix='repository audit 中文 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '--quiet')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True).stdout

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')
        return path

    def issues(self):
        return self.audit.audit_repository(self.root)['issues']

    def test_clean_candidates_and_ignored_private_state_are_read_only(self):
        self.write('.gitignore', 'runtime/\n')
        self.write('readme 中文.md', 'source\n')
        private = self.write('runtime/.env', 'SERVICE_TOKEN=fixture-private-value-12345\n')
        before = private.read_bytes()
        self.assertEqual(self.issues(), [])
        self.assertEqual(private.read_bytes(), before)
        self.assertFalse((self.root / '.git/index').exists())

    def test_tracked_ignored_files_are_still_audited(self):
        self.write('.gitignore', '*.db\n')
        self.write('state.db', 'private state')
        self.git('add', '--force', 'state.db')
        self.assertIn({'path': 'state.db', 'rule': 'private-database'}, self.issues())

    def test_private_and_generated_candidate_paths_are_rejected(self):
        names = {
            'config/.env.local': 'private-environment',
            'data/memory.sqlite3': 'private-database',
            'cert/client.pfx': 'private-certificate',
            'main/round_services_private.h': 'private-header',
            'main/warm_assets/warm_font_24.inc': 'generated-font',
            'build/generated.json': 'generated-cache',
            'src/__pycache__/module.pyc': 'generated-cache',
            '.venv-fonts/pyvenv.cfg': 'generated-cache',
            'server/personal-memory/viewer/static/fonts/legacy.woff2': 'private-webfont',
            'artifacts/local-memory-mcp/state/settings.json': 'local-artifact',
            'backups/previous-install.json': 'local-artifact',
        }
        for name in names:
            self.write(name, 'fixture')
        self.assertTrue(all({'path': name, 'rule': rule} in self.issues()
                            for name, rule in names.items()))

    def test_env_example_and_upstream_private_implementation_header_are_allowed(self):
        self.write('.env.example', 'SERVICE_TOKEN=<your-token>\n')
        self.write('xiaozhi-firmware/components/demo/private/implementation.h', '// source\n')
        self.assertEqual(self.issues(), [])

    def test_known_private_value_is_rejected_even_in_reserved_test_fixture(self):
        value = 'unit-test-only-' + 'private-value-472994'
        self.write('.gitignore', 'runtime/\n')
        self.write('runtime/.env', 'SERVICE_TOKEN=' + value)
        self.write('tests/test_example.py', '# ' + value)
        issues = self.issues()
        self.assertIn({'path': 'tests/test_example.py', 'rule': 'private-credential-reuse'}, issues)
        self.assertNotIn(value, json.dumps(issues))

    def test_real_looking_credentials_are_rejected_without_content_in_report(self):
        value = 'github_pat_' + 'A' * 65
        self.write('src/settings.py', value)
        issues = self.issues()
        self.assertIn({'path': 'src/settings.py', 'rule': 'credential-pattern'}, issues)
        self.assertNotIn(value, json.dumps(issues))

    def test_literal_test_credentials_and_upstream_pem_marker_are_allowed(self):
        self.write('tests/test_source.py',
                   'url = "wss://fixture.test/mcp?token=obviously-invalid-token"\n')
        self.write('xiaozhi-firmware/crypto.py',
                   'HEADER = "-----BEGIN ' + 'PRIVATE KEY-----"\n')
        self.assertEqual(self.issues(), [])

    def test_reserved_fixture_url_exception_does_not_apply_to_application_source(self):
        self.write('src/settings.py', 'wss://fixture.test/?token=invalid-test-value')
        self.assertIn({'path': 'src/settings.py', 'rule': 'credential-pattern'}, self.issues())

    def test_test_source_does_not_whitelist_real_service_token(self):
        self.write('tests/test_source.py', 'wss://service.example.org/?token=' + 'real-looking-token')
        self.assertIn({'path': 'tests/test_source.py', 'rule': 'credential-pattern'}, self.issues())

    def test_actual_profile_paths_are_rejected_but_placeholders_are_allowed(self):
        self.write('README.md', 'C:' + chr(92) + 'Users' + chr(92) + 'SpecificPerson\\Desktop\\app\n')
        self.write('template.md', 'C:\\Users\\<username>\\project\n/home/user/project\n')
        self.assertIn({'path': 'README.md', 'rule': 'personal-profile-path'}, self.issues())
        self.assertFalse(any(issue['path'] == 'template.md' for issue in self.issues()))

    def test_profile_detection_regex_source_is_not_an_actual_profile_path(self):
        self.write('policy.py', 'pattern = r"/Users/[^/]+/"\n')
        self.assertEqual(self.issues(), [])

    def test_bare_and_unicode_profile_paths_are_detected(self):
        self.write('bare.md', '/Users/' + 'SpecificPerson')
        self.write('unicode.md', 'C:' + chr(92) + 'Users' + chr(92) + '某个用户' + chr(92) + 'source')
        self.assertEqual({issue['path'] for issue in self.issues()}, {'bare.md', 'unicode.md'})

    def test_deleted_tracked_file_is_not_a_publication_candidate(self):
        path = self.write('deleted.md', 'old')
        self.git('add', 'deleted.md')
        path.unlink()
        self.assertEqual(self.issues(), [])

    def test_symlink_candidate_is_rejected_without_reading_target(self):
        target = self.write('target.md', 'safe')
        try:
            (self.root / 'linked.md').symlink_to(target)
        except OSError:
            self.skipTest('Symlinks require Windows developer mode or permission')
        self.assertIn({'path': 'linked.md', 'rule': 'linked-path'}, self.issues())

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction')
    def test_junction_ancestor_is_rejected_without_reading_target(self):
        import _winapi
        self.write('target/source.py', '# source')
        _winapi.CreateJunction(str(self.root / 'target'), str(self.root / 'linked'))
        self.assertEqual(self.audit.inspect_candidate(self.root, 'linked/source.py', set()),
                         [{'path': 'linked/source.py', 'rule': 'linked-path'}])

    def test_cli_emits_structured_path_and_rule_only(self):
        value = 'github_pat_' + 'B' * 65
        self.write('leak.py', value)
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.audit.main(['--workspace', str(self.root)])
        self.assertEqual(result, 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report['status'], 'failed')
        self.assertNotIn(value, output.getvalue())


if __name__ == '__main__':
    unittest.main()
