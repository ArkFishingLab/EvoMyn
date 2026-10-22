#!/usr/bin/env python3
"""Offline recovery: pip install cryptography; then --key private.pem --input
backup.pmbak --output recovered.tar.gz. Authenticates before publishing plaintext.
Inspect the recovered archive and restore it manually into a new directory.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b'PMBACKUP\x01\n'
CHUNK = 1024 * 1024


def decrypt_bundle(key_path, input_path, output_path):
    output = Path(output_path)
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; choose a new archive path.')
    try:
        key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or not 3072 <= key.key_size <= 8192:
            raise ValueError('Unsupported recovery key.')
        with Path(input_path).open('rb') as source:
            prefix = source.read(len(MAGIC) + 4)
            if len(prefix) != len(MAGIC) + 4 or not prefix.startswith(MAGIC):
                raise ValueError('Unsupported backup format.')
            header_size = struct.unpack('>I', prefix[-4:])[0]
            if not 0 < header_size <= 16384:
                raise ValueError('Invalid backup header.')
            raw_header = source.read(header_size)
            header = json.loads(raw_header)
            if header.get('version') != 1 or header.get('cipher') != 'AES-256-GCM' or header.get('wrap') != 'RSA-OAEP-SHA256':
                raise ValueError('Unsupported backup encryption.')
            nonce = base64.b64decode(header['nonce'], validate=True)
            wrapped = base64.b64decode(header['wrapped_key'], validate=True)
            if len(nonce) != 12 or len(wrapped) != key.key_size // 8:
                raise ValueError('Invalid backup header.')
            aes_key = key.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            if len(aes_key) != 32:
                raise ValueError('Invalid backup encryption key.')
            start = source.tell()
            source.seek(0, os.SEEK_END)
            remaining = source.tell() - start - 16
            if remaining < 0:
                raise ValueError('Incomplete backup.')
            source.seek(-16, os.SEEK_END)
            tag = source.read(16)
            source.seek(start)
            decryptor = Cipher(algorithms.AES(aes_key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(prefix + raw_header)
            # No user-visible output path is created before GCM authentication.
            with tempfile.TemporaryFile(prefix='.restore-', dir=output.parent) as temporary:
                while remaining:
                    block = source.read(min(CHUNK, remaining))
                    if not block:
                        raise ValueError('Incomplete backup.')
                    temporary.write(decryptor.update(block))
                    remaining -= len(block)
                temporary.write(decryptor.finalize())
                temporary.seek(0)
                fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
                try:
                    with os.fdopen(fd, 'wb') as target:
                        shutil.copyfileobj(temporary, target, CHUNK)
                        target.flush()
                        os.fsync(target.fileno())
                except Exception:
                    output.unlink(missing_ok=True)
                    raise
    except FileExistsError:
        raise ValueError('Output already exists; choose a new archive path.') from None
    except (InvalidTag, KeyError, TypeError, ValueError, UnicodeError):
        raise ValueError('Backup authentication failed, or the key/format is invalid.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        decrypt_bundle(args.key, args.input, args.output)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print('Authenticated archive saved. Inspect it before restoring into a new directory.')


if __name__ == '__main__':
    main()
