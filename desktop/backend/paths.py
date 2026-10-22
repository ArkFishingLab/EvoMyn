"""Reviewed runtime layout and user-owned configuration boundaries."""
import json
import os
from pathlib import Path
import shutil
import uuid

VENDOR = ('archive_store.py', 'archive_categories.py', 'backup_bundle.py', 'backup_github.py', 'backup_manager.py',
    'backup_server.py', 'device_archive.py', 'device_gateway.py', 'device_updates.py',
    'market_tools.py', 'mcp_admin.py', 'mcp_marketplace.py', 'mcp_observability.py',
    'mcp_packages.py', 'mcp_pipe.py', 'mcp_server.py', 'planner_server.py',
    'planner_store.py', 'planner_tools.py', 'restore_backup.py', 'runtime.py')
FILES = (tuple('app/' + name for name in VENDOR) + ('dashboard.py', 'onboarding.py',
    'viewer/server.py', 'viewer/index.html', 'viewer/SOURCE.json', 'viewer/LICENSE') +
    tuple('app/' + directory + '/' + name for directory in ('mcp_admin_web', 'planner_web')
        for name in ('index.html', 'style.css', 'app.js')) +
    tuple('viewer/static/' + name for name in ('style.css', 'personal.mjs', 'personal-shared.mjs',
        'personal-native.css', 'personal-model.mjs', 'favicon.svg', 'backup.mjs', 'backup.css', 'brand-fonts.css', 'categories.mjs', 'categories.css', 'record-editor.mjs', 'record-editor.css', 'editor-model.mjs')))


def reject_links(path):
    path = Path(path).absolute()
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (candidate.exists() and
            getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Linked runtime paths are not supported')
    return path


def private_permissions(path, directory=False):
    """Restrict secrets to the file owner and SYSTEM, also on Windows."""
    if os.name != 'nt':
        os.chmod(path, 0o700 if directory else 0o600)
        return
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    flags = 'OICI' if directory else ''
    sddl = f'D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;OW)'
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError('Private runtime permissions could not be created')
    try:
        if not advapi.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise OSError('Private runtime permissions could not be applied')
    finally:
        kernel.LocalFree(descriptor)


def atomic_json(path, value):
    reject_links(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            private_permissions(temporary)
            json.dump(value, stream, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(app_dir, data_root):
    app_dir, data_root = reject_links(app_dir).resolve(), reject_links(data_root).resolve()
    if app_dir == data_root or data_root.is_relative_to(app_dir) or app_dir.is_relative_to(data_root):
        raise ValueError('Application and data directories must be separate')
    # Validate the complete source set before replacing any runtime code. Never
    # discover source by recursively copying a user or installation directory.
    for name in FILES:
        source = reject_links(app_dir / name)
        if not source.is_file():
            raise ValueError('The reviewed application layout is incomplete')
        reject_links(data_root / name)
    data_root.mkdir(parents=True, exist_ok=True)
    private_permissions(data_root, directory=True)
    for name in FILES:
        source, target = app_dir / name, data_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    for name in ('state/data', 'state/data/mnemosyne.db', 'state/backups', 'logs'):
        reject_links(data_root / name)
    for name in ('state/data', 'logs'):
        (data_root / name).mkdir(parents=True, exist_ok=True)
    reject_links(data_root / 'app/.env')
    private_permissions(data_root / 'app', directory=True)
    try:
        with (data_root / 'app/.env').open('x', encoding='utf-8') as stream:
            os.chmod(data_root / 'app/.env', 0o600)
            stream.write('# Optional write-only cloud endpoint.\nPLANNER_OWNER=device\n')
    except FileExistsError:
        pass
    private_permissions(data_root / 'app/.env')
    return data_root


def environment(root):
    from dotenv import dotenv_values
    values = dotenv_values(root / 'app/.env', interpolate=False)
    # Configured service ports and inherited Python injection must never select
    # another installation, arbitrary import code or a production database.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTHON', 'PERSONAL_ARCHIVE_', 'MCP_', 'DEVICE_GATEWAY_'))}
    env.update({key: value for key, value in values.items() if key in
        ('MCP_ENDPOINT', 'PLANNER_OWNER') and value is not None})
    env.setdefault('PLANNER_OWNER', 'device')
    env.update(PERSONAL_ARCHIVE_HOME=str(root / 'state'),
        MNEMOSYNE_DESKTOP_DATA_ROOT=str(root),
        MCP_EVENT_LOG=str(root / 'logs/events.jsonl'),
        PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    return env
