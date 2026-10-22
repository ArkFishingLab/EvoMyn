"""Build an audited public source archive from an explicit, reviewed file list.

This deliberately does not archive a directory tree. Runtime configuration is
read only to detect accidental credential reuse; its contents never leave memory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from urllib.parse import urlsplit
import zipfile


PACKAGE = 'evomyn-mcp'
VERSION = '0.2.8'
BASE = 'server/personal-memory'
VENDOR_FILES = (
    'archive_store.py', 'archive_categories.py', 'backup_bundle.py', 'backup_github.py', 'backup_manager.py',
    'backup_server.py', 'device_archive.py', 'device_gateway.py', 'device_updates.py',
    'market_tools.py', 'mcp_admin.py', 'mcp_marketplace.py', 'mcp_observability.py',
    'mcp_packages.py', 'mcp_pipe.py', 'mcp_server.py', 'planner_server.py',
    'planner_store.py', 'planner_tools.py', 'restore_backup.py', 'runtime.py',
)
PC_TESTS = (
    'test_archive_categories.py', 'test_backup_bundle.py', 'test_backup_github.py', 'test_backup_manager.py',
    'test_backup_server.py', 'test_backup_wal.py', 'test_bridge.py',
    'test_device_archive.py', 'test_device_archive_dashboard.py',
    'test_device_archive_gateway.py', 'test_device_owner.py', 'test_device_updates.py',
    'test_mcp_admin.py', 'test_mcp_marketplace.py', 'test_mcp_observability.py',
    'test_mcp_packages.py', 'test_planner.py', 'test_planner_server.py',
    'test_planner_tools.py', 'test_planner_web.cjs', 'test_local_launcher.py',
    'test_local_onboarding.py',
)
VIEWER_STATIC = (
    'style.css', 'personal.mjs', 'personal-shared.mjs', 'personal-native.css',
    'personal-model.mjs', 'favicon.svg', 'backup.mjs', 'backup.css', 'categories.mjs', 'categories.css',
)
FIRMWARE_SUPPORT_FILES = (
    'tools/export_round_sources.py', 'tools/public_round_files.json',
    'tools/generate_open_round_fonts.py', 'docs/round-open-source.md',
)

PUBLIC_FILES = {
    **{f'{BASE}/vendor/{name}': f'app/{name}' for name in VENDOR_FILES},
    **{f'{BASE}/vendor/{directory}/{name}': f'app/{directory}/{name}'
       for directory in ('mcp_admin_web', 'planner_web')
       for name in ('index.html', 'style.css', 'app.js')},
    **{f'{BASE}/tests/{name}': f'tests/{name}' for name in PC_TESTS},
    **{f'{BASE}/viewer/static/{name}': f'viewer/static/{name}' for name in VIEWER_STATIC},
    **{f'{BASE}/viewer/{name}': f'viewer/{name}'
       for name in ('index.html', 'server.py', 'LICENSE', 'SOURCE.json')},
    **{f'{BASE}/viewer/tests/{name}': f'viewer/tests/{name}'
       for name in ('backup.test.mjs', 'model.test.mjs', 'test_server.py')},
    **{f'{BASE}/local/{name}': name for name in (
        'launcher.py', 'dashboard.py', 'bootstrap.ps1', 'manage.ps1',
        'Start.cmd', 'Stop.cmd', 'Configure.cmd', 'onboarding.py',
    )},
    **{f'{BASE}/distribution/{name}': name
       for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')},
    f'{BASE}/distribution/public-fonts.css': 'viewer/static/brand-fonts.css',
    f'{BASE}/distribution/.env.example': 'app/.env.example',
    f'{BASE}/distribution/.gitignore': '.gitignore',
    f'{BASE}/requirements.txt': 'requirements.txt',
    'tools/package_public_release.py': 'tools/package_public_release.py',
    'tests/test_public_release.py': 'tests/test_public_release.py',
}

# Values are never embedded in error messages or audit reports.
SENSITIVE_KEY = re.compile(r'(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY|ENDPOINT|AUTH|CREDENTIAL)', re.I)
CREDENTIAL_PATTERNS = (
    re.compile(rb'(?:^-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----[ \t]*\r?$|-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----(?:\r?\n|\\n)[A-Za-z0-9+/=]{16,})', re.M),
    re.compile(rb'(?:wss?|https?)://[^\s\x22\x27<>]+[?&](?:token|access_token|api_key|secret)=[A-Za-z0-9_./%+~-]{8,}', re.I),
    re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b'),
)


class ReleaseError(RuntimeError):
    """A release could not be assembled or passed to its destination safely."""


def reject_linked_ancestors(path: Path) -> None:
    for candidate in reversed((path, *path.parents)):
        if candidate.is_symlink():
            raise ReleaseError('Release paths must not traverse links')
        if candidate.exists() and getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ReleaseError('Release paths must not traverse directory junctions')


def checked_source(workspace: Path, relative: str) -> Path:
    """Reject symlinks and Windows junction/reparse traversal at every level."""
    path = workspace
    for part in PurePosixPath(relative).parts:
        if part in ('.', '..') or '/' in part or '\\' in part:
            raise ReleaseError('Invalid source allowlist path')
        path = path / part
        if not path.exists() or path.is_symlink():
            raise ReleaseError(f'Missing or linked public source: {relative}')
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
        if attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise ReleaseError(f'Linked public source: {relative}')
    if not path.is_file() or not path.resolve().is_relative_to(workspace):
        raise ReleaseError(f'Invalid public source: {relative}')
    return path


def private_credential_corpus(workspace: Path) -> set[bytes]:
    """Read local env/private-header secrets for comparison, without exporting them."""
    secrets = set()
    excluded = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'models',
                'managed_components', 'build', '.cache', 'public-release'}
    for root, directories, files in os.walk(workspace, followlinks=False):
        directories[:] = [name for name in directories if name not in excluded
                          and not (Path(root) / name).is_symlink()
                          and not (getattr((Path(root) / name).lstat(), 'st_file_attributes', 0) & 0x400)]
        for name in files:
            is_env = name == '.env' or name.startswith('.env.') and not name.endswith('.example')
            if not is_env and not (name.endswith(('.h', '.hpp')) and 'private' in name.lower()):
                continue
            candidate = Path(root) / name
            if candidate.is_symlink() or candidate.stat().st_size > 1024 * 1024:
                continue
            for line in candidate.read_text(encoding='utf-8-sig', errors='ignore').splitlines():
                match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)', line) if is_env else re.match(r'\s*#define\s+(\w+)\s+\x22([^\x22]*)\x22', line)
                if match and SENSITIVE_KEY.search(match[1]):
                    value = match[2].strip()
                    if value.startswith(('\x22', '\x27')):
                        quoted = re.match(r'''(["'])(.*?)\1\s*(?:#.*)?$''', value)
                        value = quoted[2] if quoted else value.strip('\x22\x27')
                    else:
                        value = re.sub(r'\s+#.*$', '', value)
                    if len(value) >= 8 and not value.startswith(('${', '<', 'YOUR_', 'your-')):
                        secrets.add(value.encode('utf-8'))
                    for token in re.findall(r'[?&](?:token|access_token|api_key|secret)=([^&\s]+)', value, re.I):
                        if len(token) >= 8:
                            secrets.add(token.encode('utf-8'))
    return secrets


def audit_payload(payload: dict[str, bytes], corpus: set[bytes]) -> None:
    for name, data in payload.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ReleaseError('Unsafe public archive entry')
        # Reserved test domains may hold intentionally invalid URL fixtures. This
        # exception never applies to a value recovered from private configuration.
        is_test = name.startswith(('tests/', 'viewer/tests/'))
        suspicious = False
        for index, pattern in enumerate(CREDENTIAL_PATTERNS):
            for match in pattern.finditer(data):
                if is_test and index == 1:
                    hostname = urlsplit(match[0].decode('utf-8')).hostname or ''
                    if hostname.endswith(('.test', '.invalid')):
                        continue
                suspicious = True
        if suspicious or any(value in data for value in corpus):
            raise ReleaseError(f'Credential audit failed for public file: {name}')


def portable_test_source(data: bytes) -> bytes:
    """Adapt only reviewed test source paths to the public directory layout."""
    text = data.decode('utf-8')
    for quote in ('\x22', "'"):
        text = text.replace(quote + 'vendor/' , quote + 'app/')
        text = text.replace(quote + 'vendor' + quote, quote + 'app' + quote)
        text = text.replace(quote + '../vendor/', quote + '../app/')
        text = text.replace(quote + 'local/dashboard.py' + quote, quote + 'dashboard.py' + quote)
        text = text.replace(quote + 'local/launcher.py' + quote, quote + 'launcher.py' + quote)
        text = text.replace(quote + 'local/onboarding.py' + quote, quote + 'onboarding.py' + quote)
    return text.encode('utf-8')


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def build_public_release(workspace, output=None, include_firmware=False):
    workspace = Path(os.path.abspath(workspace))
    reject_linked_ancestors(workspace)
    workspace = workspace.resolve()
    staging = workspace / 'artifacts' / 'public-release'
    reject_linked_ancestors(staging)
    staging.mkdir(parents=True, exist_ok=True)
    output = Path(os.path.abspath(output)) if output else staging / f'{PACKAGE}.zip'
    reject_linked_ancestors(output)
    if output.suffix.lower() != '.zip':
        raise ReleaseError('Output must be a .zip path')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.drive.lower() != staging.drive.lower():
        raise ReleaseError('Output must use the workspace drive for atomic publication')
    payload = {'VERSION': (VERSION + '\n').encode('ascii')}
    corpus = private_credential_corpus(workspace)
    public_layout = not (workspace / BASE).exists()
    for source, destination in sorted(PUBLIC_FILES.items()):
        data = checked_source(workspace, destination if public_layout else source).read_bytes()
        if source.startswith(f'{BASE}/tests/'):
            data = portable_test_source(data)
        if destination == 'viewer/static/style.css':
            data = re.sub(rb'^@font-face\{[^}]*\}\s*', b'', data, flags=re.M)
        payload[destination] = data
    notes = []
    with tempfile.TemporaryDirectory(prefix='build-', dir=staging) as temp:
        temp = Path(temp)
        if include_firmware:
            for relative in FIRMWARE_SUPPORT_FILES:
                payload[relative] = checked_source(workspace, relative).read_bytes()
            module_path = checked_source(workspace, 'tools/export_round_sources.py')
            spec = importlib.util.spec_from_file_location('release_round_sources', module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            firmware = temp / 'firmware'
            firmware.mkdir()
            notes = module.export_round_sources(workspace, firmware)
            for folder, directories, files in os.walk(firmware, followlinks=False):
                for name in directories + files:
                    path = Path(folder) / name
                    if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                        raise ReleaseError('Linked optional firmware source')
                for name in files:
                    path = Path(folder) / name
                    payload['firmware/' + path.relative_to(firmware).as_posix()] = path.read_bytes()
        audit_payload(payload, corpus)
        audit = {'schema': 1, 'status': 'passed', 'version': VERSION, 'source_policy': 'explicit allowlist',
                 'credential_checks': ['private environment/header values', 'credential URL',
                                       'private keys', 'common service tokens'],
                 'symlink_policy': 'rejected', 'bundled_fonts': False,
                 'optional_firmware': bool(include_firmware), 'notes': notes,
                 'payload_files': len(payload)}
        audit_data = json_bytes(audit)
        audit_payload({'AUDIT.json': audit_data}, corpus)
        payload['AUDIT.json'] = audit_data
        manifest = {'schema': 1, 'package': PACKAGE, 'version': VERSION,
                    'hash_algorithm': 'sha256', 'excludes': ['MANIFEST.json'],
                    'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                              for name, data in sorted(payload.items())]}
        manifest_data = json_bytes(manifest)
        payload['MANIFEST.json'] = manifest_data
        staged_zip = temp / 'release.zip'
        with zipfile.ZipFile(staged_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(f'{PACKAGE}/{name}', date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, data, compresslevel=9)
        staged_manifest = temp / 'manifest.json'
        staged_audit = temp / 'audit.json'
        staged_checksum = temp / 'checksum.sha256'
        staged_manifest.write_bytes(manifest_data)
        staged_audit.write_bytes(audit_data)
        archive_sha256 = hashlib.sha256(staged_zip.read_bytes()).hexdigest()
        staged_checksum.write_bytes((archive_sha256 + '  ' + output.name + '\n').encode('utf-8'))
        manifest_path = output.with_suffix('.manifest.json')
        audit_path = output.with_suffix('.audit.json')
        checksum_path = output.with_suffix('.sha256')
        os.replace(staged_manifest, manifest_path)
        os.replace(staged_audit, audit_path)
        os.replace(staged_checksum, checksum_path)
        os.replace(staged_zip, output)
    return {'zip': output, 'manifest': manifest_path, 'audit': audit_path,
            'checksum': checksum_path, 'sha256': archive_sha256, 'files': len(payload)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--include-firmware', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = build_public_release(args.workspace, args.output, args.include_firmware)
    except (ReleaseError, OSError, ValueError) as error:
        parser.exit(1, f'Public export failed: {error}\n')
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
