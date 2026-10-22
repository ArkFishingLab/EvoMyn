"""Read-only publication audit of tracked and unignored Git candidate files.

Ignored local state is never treated as publication input. Local env/header values
are read by the existing release helper solely to catch accidental secret reuse.
Reports contain candidate paths and rule names, never matched source contents.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import urlsplit


_spec = importlib.util.spec_from_file_location(
    'repository_release_policy', Path(__file__).with_name('package_public_release.py'))
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

PROFILE_PATH = re.compile(
    r'(?:[A-Za-z]:[\\/]+Users[\\/]+|/(?:Users|home)/)([\w.-]+)', re.I)
PROFILE_PLACEHOLDERS = {
    'user', 'username', 'your-user', 'your_username', 'you', 'public',
    'default', 'runner', 'runneradmin', 'root', 'example', 'name',
}
CACHE_PARTS = {'__pycache__', 'node_modules', '.venv', 'venv', '.cache',
               'build', 'managed_components', '.pytest_cache', '.mypy_cache'}


def git_candidates(workspace: Path) -> list[str]:
    result = subprocess.run(
        ['git', '-C', str(workspace), 'ls-files', '--cached', '--others',
         '--exclude-standard', '-z'], capture_output=True, check=False)
    if result.returncode:
        raise ValueError('git-candidate-enumeration-failed')
    return sorted({os.fsdecode(name) for name in result.stdout.split(b'\0') if name})


def path_rule(relative: str) -> str | None:
    path = PurePosixPath(relative)
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if name == '.env' or name.startswith('.env.') and not name.endswith('.example'):
        return 'private-environment'
    if name.endswith(('.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3',
                      '.sqlite-wal', '.sqlite-shm', '.sqlite3-wal', '.sqlite3-shm')):
        return 'private-database'
    if name.endswith(('.key', '.pem', '.crt', '.p12', '.pfx', '.jks')):
        return 'private-certificate'
    if path.parts[:5] == ('server', 'personal-memory', 'viewer', 'static', 'fonts'):
        return 'private-webfont'
    if name.endswith(('_private.h', '_private.hpp')):
        return 'private-header'
    if name.endswith('.inc') and ('warm_assets' in parts or 'font' in name):
        return 'generated-font'
    if path.parts and path.parts[0].lower() in {'artifacts', 'backups', 'vendor-board'}:
        return 'local-artifact'
    if parts & CACHE_PARTS or any(part.startswith('.venv-') for part in parts) or name.endswith(('.pyc', '.pyo')):
        return 'generated-cache'
    return None


def is_test_source(relative: str) -> bool:
    path = PurePosixPath(relative)
    return bool({'tests', 'test'} & set(path.parts[:-1])) or path.name.startswith('test_')


def inspect_candidate(workspace: Path, relative: str, corpus: set[bytes]) -> list[dict]:
    issues = []

    def add(rule):
        issue = {'path': relative, 'rule': rule}
        if issue not in issues:
            issues.append(issue)

    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative:
        add('unsafe-path')
        return issues
    # Inspect ancestors before reading or testing existence through a junction.
    source = workspace
    for part in path.parts:
        source = source / part
        try:
            info = source.lstat()
        except FileNotFoundError:
            # An unstaged deletion is absent from the eventual source tree.
            return issues
        except OSError:
            add('unreadable-path')
            return issues
        if source.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            add('linked-path')
            return issues
    if not source.is_file():
        add('non-file-candidate')
        return issues
    rule = path_rule(relative)
    if rule:
        add(rule)
        return issues
    try:
        data = source.read_bytes()
    except OSError:
        add('unreadable-path')
        return issues
    if any(value in data for value in corpus):
        add('private-credential-reuse')
    for index, pattern in enumerate(release.CREDENTIAL_PATTERNS):
        for match in pattern.finditer(data):
            if index == 1 and is_test_source(relative):
                try:
                    host = urlsplit(match[0].decode('utf-8')).hostname or ''
                except (UnicodeError, ValueError):
                    host = ''
                if host.endswith(('.test', '.invalid')):
                    continue
            add('credential-pattern')
    if any(match[1].lower() not in PROFILE_PLACEHOLDERS
           for match in PROFILE_PATH.finditer(data.decode('utf-8', errors='ignore'))):
        add('personal-profile-path')
    return issues


def audit_repository(workspace: Path) -> dict:
    workspace = Path(os.path.abspath(workspace))
    release.reject_linked_ancestors(workspace)
    candidates = git_candidates(workspace)
    corpus = release.private_credential_corpus(workspace)
    issues = [issue for relative in candidates
              for issue in inspect_candidate(workspace, relative, corpus)]
    return {'schema': 1, 'status': 'failed' if issues else 'passed',
            'scope': 'git tracked and unignored candidates',
            'candidate_files': len(candidates), 'issues': issues}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        report = audit_repository(args.workspace)
    except (OSError, ValueError, release.ReleaseError):
        # Tool failures can include private paths in OS messages. Keep diagnostics
        # as fixed rules, just like content findings.
        report = {'schema': 1, 'status': 'failed',
                  'issues': [{'path': '.', 'rule': 'audit-input-error'}]}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
