import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
from backup_github import BackupGitHubError, GitHubClient, MARKER
import backup_github


class FakeTransport:
    def __init__(self, digest=None, private=True):
        self.calls, self.digest, self.private = [], digest, private
        self.releases, self.deleted = [], []
        self.fail_page = False
        self.empty = False

    def __call__(self, method, host, path, headers, body):
        if hasattr(body, 'read'):
            self.uploaded = body.read()
        payload = json.loads(body) if isinstance(body, bytes) and body else None
        self.calls.append((method, host, path, payload))
        base = '/repos/alice/memory'
        if path == base and method == 'GET':
            return 200, {}, {'private': self.private, 'full_name': 'alice/memory', 'default_branch': 'main', 'permissions': {'push': True}, 'secret': 'omit'}
        if path == base + '/commits?per_page=1':
            return (409, {}, {}) if self.empty else (200, {}, [{'sha': 'abc'}])
        if path == base + '/releases' and method == 'POST':
            self.new = {'id': 99, 'body': payload['body'], 'tag_name': payload['tag_name'], 'draft': True, 'published_at': '2026-10-16T00:00:00Z'}
            return 201, {}, dict(self.new)
        if host == 'uploads.github.com':
            return 201, {}, {'id': 100, 'state': 'uploaded', 'size': len(self.uploaded), 'digest': self.digest}
        if path == base + '/releases/assets/100':
            return 200, {}, {'id': 100, 'state': 'uploaded', 'size': len(self.uploaded), 'digest': self.digest}
        if path == base + '/releases/99' and method == 'PATCH':
            self.new['draft'] = False
            return 200, {}, dict(self.new)
        if '/releases?per_page=100&page=' in path:
            page = int(path.rsplit('=', 1)[1])
            if self.fail_page and page == 2:
                return 500, {}, {'message': 'secret-token'}
            releases = [dict(self.new), *self.releases]
            return 200, {}, releases[(page - 1)*100:page*100]
        if method == 'DELETE':
            self.deleted.append(int(path.rsplit('/', 1)[1]))
            return 204, {}, None
        raise AssertionError((method, host, path))


class GitHubTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(backup_github, 'datetime', wraps=datetime)
        fixed_clock = clock.start()
        self.addCleanup(clock.stop)
        fixed_clock.now.return_value = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'backup.pmbak'
        self.path.write_bytes(b'encrypted backup ciphertext')
        self.metadata = {'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(), 'size': self.path.stat().st_size}
        self.fake = FakeTransport('sha256:' + self.metadata['sha256'])
        self.client = GitHubClient('secret-token', 'alice/memory', transport=self.fake)

    def test_check_sanitizes_and_requires_private_initialized_repository(self):
        self.assertEqual(self.client.check(), {'repository': 'alice/memory', 'private': True, 'default_branch': 'main'})
        self.fake.private = False
        with self.assertRaisesRegex(BackupGitHubError, 'private'):
            self.client.check()
        self.fake.private, self.fake.empty = True, True
        with self.assertRaisesRegex(BackupGitHubError, 'initial commit'):
            self.client.check()

    def test_upload_is_draft_then_verified_before_publication(self):
        result = self.client.upload(self.path, self.metadata)
        self.assertTrue(result['verified'])
        self.assertEqual(result['release_id'], 99)
        self.assertTrue(result['url'].startswith('https://github.com/alice/memory/releases/tag/'))
        methods = [call[0] for call in self.fake.calls]
        self.assertEqual(methods, ['GET', 'GET', 'POST', 'POST', 'GET', 'PATCH'])
        self.assertTrue(self.fake.calls[2][3]['draft'])
        self.assertEqual(self.fake.uploaded, self.path.read_bytes())
        self.assertEqual({c[1] for c in self.fake.calls}, {'api.github.com', 'uploads.github.com'})

    def test_unverified_or_public_upload_never_publishes_or_prunes(self):
        for digest in (None, 'sha256:' + '0'*64):
            self.fake.digest = digest
            with self.assertRaisesRegex(BackupGitHubError, 'verification'):
                self.client.upload(self.path, self.metadata)
            self.assertFalse(any(c[0] == 'PATCH' for c in self.fake.calls))
            with self.assertRaises(BackupGitHubError):
                self.client.prune(30, 12)
        self.fake.private = False
        self.fake.calls.clear()
        with self.assertRaises(BackupGitHubError):
            self.client.upload(self.path, self.metadata)
        self.assertEqual(len(self.fake.calls), 1)

    def test_retention_preserves_daily_monthly_and_unrelated(self):
        self.client.upload(self.path, self.metadata)
        for number, date in enumerate(('2026-10-15', '2026-10-14', '2026-09-20', '2026-09-10', '2026-08-20'), 1):
            self.fake.releases.append({'id': number, 'tag_name': 'personal-memory-backup-' + date.replace('-', '') + 'T000000Z-aabbccdd', 'body': MARKER + '\n' + json.dumps(self.metadata), 'draft': False, 'published_at': date + 'T00:00:00Z'})
        self.fake.releases.append({'id': 88, 'tag_name': 'unrelated', 'body': MARKER, 'draft': False})
        self.assertEqual(self.client.prune(2, 2), 3)
        self.assertEqual(set(self.fake.deleted), {2, 4, 5})
        self.assertNotIn(88, self.fake.deleted)

    def test_incomplete_enumeration_makes_no_deletions_and_errors_redacted(self):
        self.client.upload(self.path, self.metadata)
        self.fake.releases = [{'id': n, 'tag_name': 'unrelated', 'body': '', 'draft': False} for n in range(1, 101)]
        self.fake.fail_page = True
        with self.assertRaises(BackupGitHubError) as caught:
            self.client.prune(1, 1)
        self.assertNotIn('secret-token', str(caught.exception))
        self.assertFalse(self.fake.deleted)

    def test_monthly_retention_uses_shanghai_calendar(self):
        self.client.upload(self.path, self.metadata)
        self.fake.releases = [
            {'id': 1, 'tag_name': 'personal-memory-backup-20260930T190000Z-aabbccdd', 'body': MARKER + '\n' + json.dumps(self.metadata), 'draft': False},
            {'id': 2, 'tag_name': 'personal-memory-backup-20260930T100000Z-aabbccdd', 'body': MARKER + '\n' + json.dumps(self.metadata), 'draft': False},
        ]
        self.assertEqual(self.client.prune(1, 2), 1)
        self.assertEqual(self.fake.deleted, [1])

    def test_invalid_repository_and_header_injection_rejected(self):
        for repo in ('https://github.com/a/b', 'a/b/../../c', 'a/b?token=oops', 'a/.'):
            with self.assertRaises(ValueError):
                GitHubClient('secret-token', repo, transport=self.fake)
        with self.assertRaises(ValueError):
            GitHubClient('secret\r\nInjected: bad', 'alice/memory', transport=self.fake)

    def test_transport_failures_cannot_echo_credentials(self):
        def failure(*args):
            raise OSError('secret-token echoed by proxy')
        client = GitHubClient('secret-token', 'alice/memory', transport=failure)
        with self.assertRaises(BackupGitHubError) as caught:
            client.check()
        self.assertNotIn('secret-token', str(caught.exception))

    def test_real_transport_does_not_follow_redirects(self):
        class Response:
            status = 302
            def getheaders(self):
                return [('Location', 'https://attacker.example/steal')]
            def read(self, limit):
                return b''
        with patch.object(backup_github.http.client, 'HTTPSConnection') as connection:
            connection.return_value.getresponse.return_value = Response()
            with self.assertRaises(BackupGitHubError):
                GitHubClient('secret-token', 'alice/memory').check()
            self.assertEqual(connection.call_count, 1)
            self.assertEqual(connection.call_args.args[0], 'api.github.com')


if __name__ == '__main__':
    unittest.main()
