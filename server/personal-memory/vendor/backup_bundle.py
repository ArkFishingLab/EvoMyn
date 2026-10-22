"""Streaming encrypted, allowlisted personal-memory backups.

Format v1: magic, big-endian header length, JSON header, GCM ciphertext, tag.
The entire prefix is authenticated as AAD. Only the recovery key can decrypt it.
"""
import base64
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import tarfile
import tempfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b'PMBACKUP\x01\n'
CHUNK = 1024 * 1024
CONFIG_FILES = ('compose.yaml', 'memory.env', 'nginx-memory.locations.conf')


class BackupBundleError(ValueError):
    pass


def _public_key(pem):
    try:
        key = serialization.load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)
    except (ValueError, TypeError) as exc:
        raise BackupBundleError('Invalid recovery public key.') from None
    if not isinstance(key, rsa.RSAPublicKey) or not 3072 <= key.key_size <= 8192:
        raise BackupBundleError('Recovery key must be RSA 3072–8192 bits.')
    return key


def public_key_fingerprint(pem):
    key = _public_key(pem)
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()


def _regular(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise BackupBundleError('Unsafe link or resource outside the permitted directory.')
    if not stat.S_ISREG(path.lstat().st_mode):
        raise BackupBundleError('Backup inputs must be regular files.')


def _resources(directory, root):
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise BackupBundleError('Unsafe resource directory.')
    if not directory.exists():
        return
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise BackupBundleError('Symbolic links are not permitted in resources.')
        if path.is_dir():
            yield from _resources(path, root)
        else:
            _regular(path, root)
            yield path


def _add_file(archive, path, name, root):
    _regular(path, root)
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as source:
        current = os.fstat(source.fileno())
        if not stat.S_ISREG(current.st_mode) or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise BackupBundleError('Backup input changed while being opened.')
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = current.st_size, 0o600, int(current.st_mtime)
        archive.addfile(info, source)


class _EncryptingWriter:
    def __init__(self, output, encryptor):
        self.output, self.encryptor = output, encryptor

    def write(self, data):
        self.output.write(self.encryptor.update(data))
        return len(data)

    def flush(self):
        self.output.flush()


def create_bundle(state_root, config_root, output, public_pem):
    """Create a new encrypted file; never replace an existing destination."""
    key = _public_key(public_pem)
    fingerprint = public_key_fingerprint(public_pem)
    state, config, output = Path(state_root).resolve(), Path(config_root).resolve(), Path(output)
    if output.resolve().is_relative_to(state / 'resources'):
        raise BackupBundleError('Backup output cannot be inside resources.')
    database = state / 'data/mnemosyne.db'
    _regular(database, state)
    if (state / 'data').is_symlink():
        raise BackupBundleError('Unsafe database directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        # Snapshot files live only in the private working directory and are removed.
        with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=output.parent) as temporary:
            snapshot = Path(temporary) / 'mnemosyne.db'
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=30)) as source:
                with closing(sqlite3.connect(snapshot)) as destination:
                    source.backup(destination, pages=256, sleep=0.05)
                    try:
                        integrity = destination.execute('PRAGMA integrity_check').fetchall()
                    except sqlite3.DatabaseError:
                        raise BackupBundleError('SQLite snapshot integrity check failed.') from None
                    if integrity != [('ok',)]:
                        raise BackupBundleError('SQLite snapshot integrity check failed.')
                    counts = {}
                    for field, table in (('archive_records', 'personal_archive_records'), ('planner_tasks', 'planner_tasks')):
                        exists = destination.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone()
                        counts[field] = destination.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] if exists else 0
            os.chmod(snapshot, 0o600)
            aes_key, nonce = os.urandom(32), os.urandom(12)
            wrapped = key.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            header = json.dumps({'version': 1, 'cipher': 'AES-256-GCM', 'wrap': 'RSA-OAEP-SHA256', 'nonce': base64.b64encode(nonce).decode(), 'wrapped_key': base64.b64encode(wrapped).decode(), 'key_fingerprint': fingerprint}, sort_keys=True, separators=(',', ':')).encode()
            prefix = MAGIC + struct.pack('>I', len(header)) + header
            encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(nonce)).encryptor()
            encryptor.authenticate_additional_data(prefix)
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
            created = True
            with os.fdopen(fd, 'wb') as target:
                target.write(prefix)
                with tarfile.open(fileobj=_EncryptingWriter(target, encryptor), mode='w|gz', format=tarfile.PAX_FORMAT) as archive:
                    manifest = json.dumps({'version': 1, 'key_fingerprint': fingerprint, **counts}, sort_keys=True).encode()
                    info = tarfile.TarInfo('manifest.json')
                    info.size, info.mode = len(manifest), 0o600
                    archive.addfile(info, io.BytesIO(manifest))
                    _add_file(archive, snapshot, 'state/data/mnemosyne.db', Path(temporary).resolve())
                    for resource in _resources(state / 'resources', state):
                        _add_file(archive, resource, 'state/' + resource.relative_to(state).as_posix(), state)
                    for name in CONFIG_FILES:
                        path = config / name
                        if path.exists() or path.is_symlink():
                            _add_file(archive, path, 'config/' + name, config)
                target.write(encryptor.finalize())
                target.write(encryptor.tag)
                target.flush()
                os.fsync(target.fileno())
        digest = hashlib.sha256()
        with output.open('rb') as source:
            for block in iter(lambda: source.read(CHUNK), b''):
                digest.update(block)
        return {'sha256': digest.hexdigest(), 'size': output.stat().st_size, 'key_fingerprint': fingerprint, **counts}
    except FileExistsError:
        raise BackupBundleError('Backup output already exists.') from None
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
