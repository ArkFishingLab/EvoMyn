"""Trusted local ESP32-S3 release publication and fixed, authenticated OTA reads.

Image layout follows ESP-IDF esp_app_desc.h / esp_app_format.h and esptool's
24-byte extended header, segment checksums, and optional SHA-256 image digest.
This publishes application images only, never merged flash or encrypted images.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import struct
import tempfile
from pathlib import Path

MAX_FIRMWARE = 4 * 1024 * 1024
BOARD_MARKER = b'ROUND-VOICE-175C:v2/32m:OTA1'
MANIFEST_FIELDS = frozenset(('board', 'version', 'sha256', 'size', 'url', 'notes', 'partition', 'project'))
HASH = re.compile(r'[0-9a-f]{64}\Z')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+\Z')
FIRMWARE_PATH = re.compile(r'/updates/firmware/([0-9a-f]{64})\.bin\Z')


def _version(value):
    if not isinstance(value, str) or len(value) > 31 or not VERSION.fullmatch(value):
        raise ValueError('Version must be numeric x.y.z, at most 31 ASCII bytes')
    return value


def _notes(value):
    if not isinstance(value, str): raise ValueError('Release notes must be UTF-8 text')
    try: encoded = value.encode('utf-8', errors='strict')
    except UnicodeError: raise ValueError('Release notes must be UTF-8 text') from None
    if len(encoded) > 2048 or '\x00' in value: raise ValueError('Release notes exceed 2048 UTF-8 bytes')
    return value


def validate_firmware(data, *, version, project='xiaozhi', require_board_marker=False):
    """Validate an unsigned app image and its exact descriptor before serving it."""
    _version(version)
    if not isinstance(data, bytes) or not 288 <= len(data) <= MAX_FIRMWARE:
        raise ValueError('Application image must fit the 4 MiB OTA partition')
    if data[0] != 0xE9 or not 1 <= data[1] <= 16 or data[23] not in (0, 1):
        raise ValueError('Invalid ESP application header')
    if struct.unpack_from('<H', data, 12)[0] != 9:
        raise ValueError('Firmware must target ESP32-S3')
    if struct.unpack_from('<I', data, 28)[0] < 256 or struct.unpack_from('<I', data, 32)[0] != 0xABCD5432:
        raise ValueError('Missing ESP application description')
    def cstring(start):
        raw = data[start:start + 32]
        if b'\x00' not in raw: raise ValueError('Unterminated application description')
        try: return raw.split(b'\x00', 1)[0].decode('ascii', errors='strict')
        except UnicodeError: raise ValueError('Invalid application description text') from None
    if cstring(48) != version or cstring(80) != project:
        raise ValueError('Firmware descriptor does not match requested version/project')
    offset = 24; checksum = 0xEF
    for _ in range(data[1]):
        if offset + 8 > len(data): raise ValueError('Truncated segment header')
        size = struct.unpack_from('<I', data, offset + 4)[0]
        offset += 8
        if size > MAX_FIRMWARE or offset + size > len(data): raise ValueError('Truncated image segment')
        for byte in data[offset:offset + size]: checksum ^= byte
        offset += size
    checksum_position = offset + (15 - offset % 16) % 16
    image_end = checksum_position + 1
    if checksum_position >= len(data) or data[checksum_position] != checksum:
        raise ValueError('Invalid ESP image checksum')
    expected_size = image_end + (32 if data[23] else 0)
    if len(data) != expected_size: raise ValueError('Truncated or unsupported trailing image data')
    if data[23] and not hmac.compare_digest(hashlib.sha256(data[:image_end]).digest(), data[image_end:]):
        raise ValueError('Invalid ESP image digest')
    if require_board_marker and BOARD_MARKER not in data:
        raise ValueError('Missing or mismatched round board/partition marker')
    return {'version': version, 'project': project, 'chip_id': 9}


def _manifest(value):
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise ValueError('Invalid release manifest fields')
    _version(value['version']); _notes(value['notes'])
    if (value['board'] != 'round-voice-175c' or value['partition'] != 'v2/32m'
            or value['project'] != 'xiaozhi'):
        raise ValueError('Release board/partition/project mismatch')
    digest = value['sha256']
    if not isinstance(digest, str) or not HASH.fullmatch(digest): raise ValueError('Invalid firmware hash')
    if type(value['size']) is not int or not 288 <= value['size'] <= MAX_FIRMWARE:
        raise ValueError('Invalid firmware size')
    if value['url'] != '/updates/firmware/' + digest + '.bin': raise ValueError('Invalid firmware URL')
    return value


def _bounded_read(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing, oversized or untrusted release file')
    with path.open('rb') as stream: data = stream.read(limit + 1)
    if len(data) > limit: raise ValueError('Release file exceeds size limit')
    return data


def _atomic_write(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix='.release-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def publish_release(build_bin, output_dir, *, version, notes):
    """Validate exact build metadata, then atomically switch the current manifest."""
    _version(version); _notes(notes)
    data = _bounded_read(Path(build_bin), MAX_FIRMWARE)
    validate_firmware(data, version=version, require_board_marker=True)
    digest = hashlib.sha256(data).hexdigest()
    manifest = _manifest(dict(board='round-voice-175c', version=version, sha256=digest,
        size=len(data), url='/updates/firmware/' + digest + '.bin', notes=notes,
        partition='v2/32m', project='xiaozhi'))
    root = Path(output_dir).resolve(); root.mkdir(parents=True, exist_ok=True)
    # Publish the immutable content before exposing a manifest that references it.
    _atomic_write(root / (digest + '.bin'), data)
    _atomic_write(root / 'manifest.json', json.dumps(manifest, ensure_ascii=False,
                  sort_keys=True, separators=(',', ':')).encode('utf-8'))
    return manifest


class ReleaseProvider:
    def __init__(self, directory): self.directory = Path(directory).resolve()

    def __call__(self, path):
        match = FIRMWARE_PATH.fullmatch(path)
        if path != '/updates/manifest' and match is None: return None
        location = self.directory / 'manifest.json'
        if not location.exists(): return None
        def unique_pairs(items):
            result = {}
            for key, value in items:
                if key in result: raise ValueError('Duplicate manifest field')
                result[key] = value
            return result
        try:
            raw = _bounded_read(location, 16384)
            manifest = _manifest(json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs))
        except (UnicodeError, RecursionError, json.JSONDecodeError):
            raise ValueError('Invalid release manifest') from None
        data = _bounded_read(self.directory / (manifest['sha256'] + '.bin'), MAX_FIRMWARE)
        if len(data) != manifest['size'] or hashlib.sha256(data).hexdigest() != manifest['sha256']:
            raise ValueError('Published firmware size/hash mismatch')
        validate_firmware(data, version=manifest['version'], require_board_marker=True)
        if path == '/updates/manifest': return raw, 'application/json'
        if match.group(1) != manifest['sha256']: return None
        return data, 'application/octet-stream'


def main():
    parser = argparse.ArgumentParser(description='Validate and publish an exact ESP32-S3 application build')
    parser.add_argument('--build-bin', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--notes', required=True)
    args = parser.parse_args()
    try:
        result = publish_release(args.build_bin, args.output_dir, version=args.version, notes=args.notes)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Release rejected: ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == '__main__': main()
