"""Stage reviewed application files and a redistributable Python installation.

Run with a Python 3.11 environment containing the pinned service requirements.
Never copies an installed application, its configuration, database or model cache.
"""
import argparse
import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'desktop/build/runtime'


def application_files(workspace):
    workspace = Path(workspace)
    spec = importlib.util.spec_from_file_location('desktop_release_sources', workspace / 'tools/package_public_release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    payload = {}
    for source, target in release.PUBLIC_FILES.items():
        if not (target.startswith('app/') or target.startswith('viewer/') and '/tests/' not in target
                or target in {'dashboard.py', 'onboarding.py', 'launcher.py', 'manage.ps1', 'requirements.txt'}):
            continue
        if target.endswith(('.cmd', '.ps1')):
            continue
        if target == 'app/.env.example':
            continue  # Desktop creates its own private configuration, no template required.
        path = workspace / source
        release.reject_linked_ancestors(path)
        data = path.read_bytes()
        if target == 'viewer/static/style.css':
            css = re.sub(r'(?im)^\s*@font-face\s*\{[^}]*\}\s*', '', data.decode('utf-8'))
            data = css.replace('"Workspace Sans",', '"Segoe UI Variable",').encode('utf-8')
        payload[target] = data
    release.audit_payload(payload, release.private_credential_corpus(workspace))
    return payload


def checked_file(path):
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.exists() and getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Runtime source must not traverse linked paths')
    if not path.is_file():
        raise ValueError('Missing runtime distribution file')


def private_artifact(relative):
    parts = {part.lower() for part in relative.parts}
    return (any(part == '.env' or part.startswith('.env.') for part in parts)
        or bool(parts & {'model_cache', '.cache', '.git', 'state', 'backups'})
        or relative.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.onnx', '.safetensors', '.pkl', '.bin', '.pt', '.h5', '.key', '.pfx', '.p12'})


def dependency_files():
    """Resolve installed metadata for only the declared requirements and extras.

    RECORD is the allowlist, and its hashes must still match the wheel bytes.
    Unrelated installed tools and injected package files never enter the stage.
    """
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    pending = [Requirement(line.strip()) for line in (ROOT / 'server/personal-memory/requirements.txt').read_text().splitlines() if line.strip()]
    visited, selected = {}, {}
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        dist = importlib.metadata.distribution(name)
        if requirement.specifier and dist.version not in requirement.specifier:
            raise ValueError('Dependency version does not satisfy declared requirements: ' + name)
        extras = visited.get(name, set()) | set(requirement.extras)
        if name in visited and extras == visited[name]:
            continue
        visited[name] = extras
        selected[name] = dist
        for text in dist.requires or ():
            child = Requirement(text)
            if child.marker is None or any(child.marker.evaluate({'extra': extra}) for extra in extras | {''}):
                pending.append(child)
    result = {}
    for dist in selected.values():
        if dist.files is None:
            raise ValueError('Distribution RECORD required for desktop staging')
        for record in dist.files:
            relative = Path(str(record))
            if relative.is_absolute() or '..' in relative.parts:
                continue  # Console launchers outside site-packages are unused.
            if relative.name in {'direct_url.json', 'REQUESTED', 'INSTALLER'} or relative.suffix in {'.pyc', '.pyo'}:
                continue
            source = Path(dist.locate_file(record))
            checked_file(source)
            if record.hash:
                actual = base64.urlsafe_b64encode(hashlib.new(record.hash.mode, source.read_bytes()).digest()).rstrip(b'=').decode()
                if actual != record.hash.value:
                    raise ValueError('Installed distribution bytes do not match RECORD: ' + dist.metadata['Name'])
            elif relative.name != 'RECORD':
                raise ValueError('Unhashed installed distribution file')
            result[relative.as_posix()] = source
    return result, {name: dist.version for name, dist in sorted(selected.items())}


def copy_python(python_home, packages, output, package_files, target_platform='win32'):
    python_home, packages, output = map(Path, (python_home, packages, output))
    if output.exists():
        raise ValueError('Python stage destination must be absent')

    excluded = {'__pycache__', 'test', 'tests', '.pytest_cache', '_virtualenv.pth', '_virtualenv.py',
                'site-packages', 'ensurepip', 'idlelib', 'tkinter', 'turtledemo'}
    def copy(source, relative):
        checked_file(source)
        if any(part in excluded for part in relative.parts) or relative.suffix in {'.pyc', '.pyo'}:
            return
        if 'onnxruntime/datasets/' in relative.as_posix():
            return  # Upstream demonstration models are not runtime dependencies.
        if target_platform == 'darwin' and relative.name.startswith('_tkinter.'):
            return  # The headless service does not ship Tcl/Tk.
        if private_artifact(relative):
            raise ValueError('Private configuration, database or model in runtime source: ' + relative.as_posix())
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        shutil.copymode(source, target)
    binaries = ('python.exe', 'pythonw.exe', 'python3.dll', 'python311.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt')
    directories_to_copy = ('Lib', 'DLLs')
    site_packages = Path('Lib/site-packages')
    if target_platform == 'darwin':
        binaries = ('bin/python3.11', 'lib/libpython3.11.dylib')
        directories_to_copy = ('lib/python3.11', 'share/licenses')
        site_packages = Path('lib/python3.11/site-packages')
        for name in binaries:
            checked_file(python_home / name)
    for name in binaries:
        source = python_home / name
        if source.exists():
            copy(source, Path(name))
    for directory in directories_to_copy:
        for parent, directories, files in os.walk(python_home / directory, followlinks=False):
            for name in directories:
                candidate = Path(parent) / name
                if candidate.is_symlink() or getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Linked Python source directory')
            directories[:] = [name for name in directories if name not in excluded]
            for name in files:
                copy(Path(parent) / name, (Path(parent) / name).relative_to(python_home))
    # Only files named by the requirement closure's validated RECORDs are copied.
    for name, source in package_files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not Path(source).absolute().is_relative_to(packages.absolute()):
            raise ValueError('Invalid distribution file path')
        if 'site-packages' in excluded:
            excluded.remove('site-packages')
        copy(Path(source), site_packages / relative)


def audit_stage(output):
    spec = importlib.util.spec_from_file_location('desktop_stage_audit', ROOT / 'tools/package_public_release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    corpus = release.private_credential_corpus(ROOT)
    for parent, directories, files in os.walk(output, followlinks=False):
        for name in directories + files:
            release.reject_linked_ancestors(Path(parent) / name)
        for name in files:
            file = Path(parent) / name
            relative = file.relative_to(output)
            if private_artifact(relative):
                raise ValueError('Private artifact found in final desktop runtime')
            data = file.read_bytes()
            if any(value in data for value in corpus):
                raise ValueError('Private credential found in runtime distribution')
            # This exact reviewed wheel metadata contains a public Codecov
            # badge token. It is not an authentication credential. No exception
            # applies to local credentials or a different distribution payload.
            if (relative.as_posix() in ('python/Lib/site-packages/huggingface_hub-1.33.0.dist-info/METADATA',
                    'python/lib/python3.11/site-packages/huggingface_hub-1.33.0.dist-info/METADATA')
                    and hashlib.sha256(data).hexdigest() == 'bee565776d66f486d224f74024b656a69ed42e2639d80b18811fca4365adc42e'):
                public_badge = b'https://codecov.io/gh/huggingface/huggingface_hub/branch/main/graph/badge.svg' + b'?' + b'token=RXP95LE2XL'
                data = data.replace(public_badge, b'https://codecov.io/public-badge')
            release.audit_payload({relative.as_posix(): data}, corpus)


def pinned_dependencies():
    # These distributions are sufficient to assert that the staging environment
    # is the pinned application environment, rather than the user's global Python.
    names = {'mnemosyne-memory': '3.15.1', 'mcp': '2.3.0', 'filelock': '4.1.1',
             'fastembed': '0.9.0', 'onnxruntime': '1.31.0', 'websockets': '15.0.1',
             'python-dotenv': '1.2.2', 'cryptography': '50.0.2'}
    for name, version in names.items():
        if importlib.metadata.version(name) != version:
            raise ValueError('Install the exact server/personal-memory/requirements.txt before staging: ' + name)
    return names


def stage(output=OUTPUT):
    if sys.platform not in ('win32', 'darwin') or sys.version_info[:2] != (3, 11):
        raise ValueError('Use native Windows or macOS Python 3.11 to stage this release')
    machine = platform.machine().lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine)
    if not arch or (sys.platform == 'win32' and arch != 'x64'):
        raise ValueError('Unsupported runtime architecture')
    output = Path(os.path.abspath(output))
    # Only generated desktop build output may be replaced. Never accept a runtime,
    # source checkout, drive root, or parent computed outside this build tree.
    allowed = (ROOT / 'desktop/build').resolve()
    if output == allowed or allowed not in output.parents:
        raise ValueError('Stage output must be a child of desktop/build')
    for ancestor in [output, *output.parents]:
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Linked staging destinations are unsupported')
    payload = application_files(ROOT)
    versions = pinned_dependencies()
    package_files, all_versions = dependency_files()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    application = output / 'application'
    for name, data in payload.items():
        file = application / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT / name, application / name)
    # uv's interpreter alias is a versioned junction; select the actual installed
    # prefix once, then reject any further linked file/ancestor during copying.
    copy_python(Path(sys.base_prefix).resolve(strict=True), Path(sysconfig.get_paths()['purelib']), output / 'python', package_files, sys.platform)
    uv = Path(shutil.which('uv.exe') or shutil.which('uv') or '')
    checked_file(uv)
    uv_version = subprocess.check_output([str(uv), '--version'], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    if not uv_version.startswith('uv 0.10.7 '):
        raise ValueError('Install uv 0.10.7 for the reviewed optional marketplace installer')
    (output / 'tools').mkdir()
    uv_target = output / 'tools' / ('uv.exe' if sys.platform == 'win32' else 'uv')
    shutil.copyfile(uv, uv_target)
    shutil.copymode(uv, uv_target)
    for name in ('uv-LICENSE-MIT', 'uv-LICENSE-APACHE'):
        shutil.copyfile(ROOT / 'desktop/assets/licenses' / name, output / 'tools' / name)
    audit_stage(output)
    source_manifest = [{'path': name, 'sha256': hashlib.sha256(data).hexdigest()} for name, data in sorted(payload.items())]
    (output / 'RUNTIME-SOURCES.json').write_text(json.dumps({'schema': 1, 'python': '3.11', 'platform': sys.platform, 'arch': arch,
        'pinned_distributions': versions, 'distribution_closure': all_versions,
        'marketplace_installer': {'version': uv_version, 'sha256': hashlib.sha256(uv.read_bytes()).hexdigest()}, 'application': source_manifest,
        'private_configuration': False, 'bundled_models': False}, indent=2) + '\n', encoding='utf-8')
    print('Staged portable Python and', len(payload), 'reviewed application files; no private runtime data')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    stage(parser.parse_args().output)
