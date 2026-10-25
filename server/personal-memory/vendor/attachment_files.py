"""Bounded managed attachment copies and SDK-independent ID resolution."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote
from uuid import uuid4

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


def unlinked_path(value):
    """Inspect the original path components before resolving any links."""
    path = Path(os.path.abspath(Path(value).expanduser()))
    for item in (*reversed(path.parents), path):
        try: info = item.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('附件路径不能包含符号链接或 reparse point。')
    return path


def checked_file(value, database, resources=None):
    path = unlinked_path(value)
    database = Path(database).absolute()
    if resources is not None:
        root = unlinked_path(resources)
        if not path.is_relative_to(root) or path == root:
            raise ValueError('附件不在受管理资料目录中。')
    if path.is_relative_to(database.parent) or str(path).casefold().startswith(str(database).casefold() + '-'):
        raise ValueError('数据库及其辅助文件不能作为附件。')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode): raise ValueError('附件必须是普通文件。')
    for protected in (database, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))):
        if protected.exists() and os.path.samefile(path, protected):
            raise ValueError('数据库及其辅助文件不能作为附件。')
    return path


def cleanup_imports(entries):
    for entry in entries:
        path = Path(entry['file_path'])
        path.unlink(missing_ok=True)
        try: path.parent.rmdir()
        except OSError: pass


def import_attachment(source, database, resources, record_id):
    source = checked_file(source, database)
    initial = source.stat()
    if not stat.S_ISREG(initial.st_mode): raise ValueError('附件必须是普通文件。')
    if initial.st_size > MAX_ATTACHMENT_BYTES: raise ValueError('附件大小超过 50 MiB。')
    root = unlinked_path(resources)
    root.mkdir(parents=True, exist_ok=True)
    root = unlinked_path(root)
    ident = uuid4().hex
    folder = root / ident
    folder.mkdir()
    target = folder / source.name
    temporary = folder / ('.' + uuid4().hex + '.tmp')
    digest, size = hashlib.sha256(), 0
    try:
        # No-follow where supported, plus descriptor identity checks on Windows.
        descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as src, temporary.open('xb') as dst:
            opened = os.fstat(src.fileno())
            checked_file(source, database)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino):
                raise ValueError('附件在导入期间发生变化。')
            while chunk := src.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES: raise ValueError('附件大小超过 50 MiB。')
                digest.update(chunk)
                dst.write(chunk)
            final = os.fstat(src.fileno())
            if size != initial.st_size or final.st_mtime_ns != initial.st_mtime_ns:
                raise ValueError('附件在导入期间发生变化。')
            dst.flush()
            os.fsync(dst.fileno())
        unlinked_path(folder)
        temporary.replace(target)
        return {'id': ident, 'name': source.name, 'size': size, 'sha256': digest.hexdigest(),
                'file_path': str(target), 'href': '/api/files/' + quote(record_id, safe='') + '/' + ident}
    except BaseException:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        folder.rmdir()
        raise


def resolve_attachment(database, resources, record_id, attachment_id):
    if not isinstance(record_id, str) or not isinstance(attachment_id, str): raise KeyError(record_id)
    with closing(sqlite3.connect(Path(database).absolute().as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT payload FROM personal_archive_records WHERE id=?', (record_id,)).fetchone()
    if not row: raise KeyError(record_id)
    record = json.loads(row[0])
    if attachment_id == 'legacy':
        value = record.get('file_path')
    else:
        entries = record.get('attachments', [])
        matches = [entry for entry in entries if isinstance(entry, dict) and entry.get('id') == attachment_id]
        value = matches[0].get('file_path') if len(matches) == 1 else None
    if not isinstance(value, str) or not value: raise KeyError(attachment_id)
    return checked_file(value, database, resources)
