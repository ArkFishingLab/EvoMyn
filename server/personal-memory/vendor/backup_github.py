"""Private GitHub release backup transport. Never follows HTTP redirects."""
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import ssl
from urllib.parse import quote
import uuid

API_VERSION = '2026-03-10'
MARKER = '<!-- personal-memory-encrypted-backup:v1 -->'
TAG_PREFIX = 'personal-memory-backup-'
TAG_PATTERN = re.compile(r'^personal-memory-backup-\d{8}T\d{6}Z-[a-f0-9]{8}$')
MAX_RESPONSE = 2 * 1024 * 1024
MAX_ASSET = 2_000_000_000
CHUNK = 1024 * 1024


class BackupGitHubError(ValueError):
    pass


def _https_transport(method, host, path, headers, body):
    connection = http.client.HTTPSConnection(host, timeout=30, context=ssl.create_default_context())
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise BackupGitHubError('GitHub response exceeded the permitted size.')
        return response.status, dict(response.getheaders()), data
    finally:
        connection.close()


class GitHubClient:
    def __init__(self, token, repository, *, transport=None):
        if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', repository) or repository.split('/')[1] in ('.', '..'):
            raise BackupGitHubError('Use a GitHub repository in owner/name format.')
        if not isinstance(token, str) or not 1 <= len(token) <= 512 or not re.fullmatch(r'[A-Za-z0-9_.-]+', token):
            raise BackupGitHubError('A valid GitHub token is required.')
        self._token, self.repository = token, repository
        self._base = '/repos/' + repository
        self._transport = transport or _https_transport
        self._verified_release_id = None

    def _request(self, method, path, *, host='api.github.com', payload=None, body=None, size=None, expected=(200,)):
        if host not in ('api.github.com', 'uploads.github.com') or not path.startswith(self._base + '/') and path != self._base:
            raise BackupGitHubError('Invalid GitHub request target.')
        headers = {'Authorization': 'Bearer ' + self._token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': API_VERSION, 'User-Agent': 'personal-memory-backup/1'}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode()
            headers['Content-Type'] = 'application/json'
            headers['Content-Length'] = str(len(body))
        elif body is not None:
            headers['Content-Type'] = 'application/octet-stream'
            headers['Content-Length'] = str(size)
        try:
            status, response_headers, raw = self._transport(method, host, path, headers, body)
            if status not in expected:
                messages = {401: 'GitHub authentication failed.', 403: 'GitHub access denied or rate limit reached.', 404: 'GitHub repository or release is unavailable; check token permissions.', 409: 'Repository is empty; create an initial commit before backing up.', 422: 'GitHub rejected the backup release request.'}
                raise BackupGitHubError(messages.get(status, 'GitHub request failed (HTTP ' + str(int(status)) + ').'))
            if isinstance(raw, (bytes, str)):
                if len(raw) > MAX_RESPONSE:
                    raise BackupGitHubError('GitHub response exceeded the permitted size.')
                raw = json.loads(raw) if raw else None
            return raw, response_headers
        except BackupGitHubError:
            raise
        except Exception:
            # Upstream exceptions and error bodies can echo credentials; never propagate.
            raise BackupGitHubError('GitHub is unavailable or returned an invalid response.') from None

    def check(self):
        repository, _ = self._request('GET', self._base)
        if not isinstance(repository, dict) or repository.get('private') is not True:
            raise BackupGitHubError('Backups require a private GitHub repository.')
        if repository.get('full_name', '').lower() != self.repository.lower():
            raise BackupGitHubError('GitHub repository identity did not match.')
        branch = repository.get('default_branch')
        if not isinstance(branch, str) or not branch:
            raise BackupGitHubError('Repository is empty; create an initial commit before backing up.')
        if repository.get('permissions', {}).get('push') is False:
            raise BackupGitHubError('GitHub token requires repository contents write access.')
        commits, _ = self._request('GET', self._base + '/commits?per_page=1')
        if not isinstance(commits, list) or not commits:
            raise BackupGitHubError('Repository is empty; create an initial commit before backing up.')
        return {'repository': self.repository, 'private': True, 'default_branch': branch}

    def upload(self, path, metadata):
        self._verified_release_id = None
        repository = self.check()  # Recheck privacy for every upload, even after a prior check.
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise BackupGitHubError('Backup upload must be a regular local file.')
        size = path.stat().st_size
        if not 0 < size <= MAX_ASSET:
            raise BackupGitHubError('Backup exceeds the supported release asset size.')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(CHUNK), b''):
                digest.update(block)
        sha256 = digest.hexdigest()
        if metadata.get('sha256') != sha256 or metadata.get('size') != size:
            raise BackupGitHubError('Local backup verification failed.')
        tag = TAG_PREFIX + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        body = MARKER + '\n' + json.dumps({'sha256': sha256, 'size': size, 'format': 'PMBACKUP-v1'}, sort_keys=True)
        release, _ = self._request('POST', self._base + '/releases', payload={'tag_name': tag, 'target_commitish': repository['default_branch'], 'name': 'Encrypted memory backup ' + tag[len(TAG_PREFIX):], 'body': body, 'draft': True, 'prerelease': False, 'make_latest': 'false'}, expected=(201,))
        release_id = self._id(release)
        if release.get('draft') is not True or release.get('tag_name') != tag:
            raise BackupGitHubError('GitHub did not create the expected draft release.')
        # Deliberately construct the fixed upload host/path, ignoring upstream upload_url.
        with path.open('rb') as source:
            asset, _ = self._request('POST', self._base + '/releases/' + str(release_id) + '/assets?name=' + quote('backup.pmbak'), host='uploads.github.com', body=source, size=size, expected=(201,))
        asset_id = self._id(asset)
        asset, _ = self._request('GET', self._base + '/releases/assets/' + str(asset_id))
        if not isinstance(asset, dict) or asset.get('state') != 'uploaded' or asset.get('size') != size or asset.get('digest') != 'sha256:' + sha256:
            # Fail closed; leave a draft for inspection. No publishing or retention.
            raise BackupGitHubError('GitHub asset SHA-256 verification failed; the release remains a draft.')
        published, _ = self._request('PATCH', self._base + '/releases/' + str(release_id), payload={'draft': False, 'make_latest': 'false'})
        if self._id(published) != release_id or published.get('draft') is not False or published.get('tag_name') != tag:
            raise BackupGitHubError('GitHub release publication could not be confirmed.')
        self._verified_release_id = release_id
        return {'release_id': release_id, 'url': 'https://github.com/' + self.repository + '/releases/tag/' + tag, 'verified': True}

    @staticmethod
    def _id(value):
        identifier = value.get('id') if isinstance(value, dict) else None
        if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0:
            raise BackupGitHubError('GitHub returned an invalid object identifier.')
        return identifier

    def prune(self, daily, monthly):
        if self._verified_release_id is None:
            raise BackupGitHubError('Retention requires a verified backup from this client first.')
        if type(daily) is not int or type(monthly) is not int or not 1 <= daily <= 365 or not 1 <= monthly <= 120:
            raise BackupGitHubError('Invalid backup retention limits.')
        self.check()
        all_releases, seen_ids = [], set()
        for page in range(1, 101):
            releases, headers = self._request('GET', self._base + '/releases?per_page=100&page=' + str(page))
            if not isinstance(releases, list) or len(releases) > 100:
                raise BackupGitHubError('GitHub release enumeration is incomplete.')
            for release in releases:
                identifier = self._id(release)
                if identifier in seen_ids:
                    raise BackupGitHubError('GitHub release enumeration changed; retention cancelled.')
                seen_ids.add(identifier)
                all_releases.append(release)
            link = next((v for k, v in headers.items() if k.lower() == 'link'), '')
            if len(releases) < 100:
                if 'rel="next"' in link:
                    raise BackupGitHubError('GitHub release enumeration is incomplete.')
                break
        else:
            raise BackupGitHubError('Too many GitHub releases; retention cancelled.')
        owned = []
        for release in all_releases:
            tag, body = release.get('tag_name'), release.get('body')
            if release.get('draft') is not False or not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag) or not isinstance(body, str) or not body.startswith(MARKER + '\n'):
                continue
            try:
                created = datetime.strptime(tag[len(TAG_PREFIX):len(TAG_PREFIX)+16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8)))
                details = json.loads(body[len(MARKER)+1:])
                if not re.fullmatch('[a-f0-9]{64}', details.get('sha256', '')) or not isinstance(details.get('size'), int):
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
            owned.append((created, release['id']))
        if self._verified_release_id not in {item[1] for item in owned}:
            raise BackupGitHubError('Verified release missing from enumeration; retention cancelled.')
        owned.sort(reverse=True)
        keep, days, months = {self._verified_release_id}, set(), set()
        for created, identifier in owned:
            day, month = created.strftime('%Y-%m-%d'), created.strftime('%Y-%m')
            if day not in days and len(days) < daily:
                days.add(day)
                keep.add(identifier)
            if month not in months and len(months) < monthly:
                months.add(month)
                keep.add(identifier)
        deleted = 0
        for _, identifier in owned:
            if identifier not in keep:
                self._request('DELETE', self._base + '/releases/' + str(identifier), expected=(204,))
                deleted += 1
        return deleted
