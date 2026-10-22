"""Desktop-owned, authenticated OTA hosting; no completion ingestion or database."""
import hashlib
import json
from pathlib import Path
import re
import ssl
import tempfile

from device_sync import load_config, credential_path, bounded_file
from paths import reject_links, private_permissions

MINIMUM_FIRMWARE = (2, 5, 7)
IMPORT_ERROR = '固件包无效或不兼容，请选择官方发布包中的 manifest.json 与相邻固件文件。'


def release_provider(directory):
    from device_updates import ReleaseProvider
    directory = reject_links(directory)
    provider = ReleaseProvider(directory)

    def provide(path):
        # Validate each served path, including ancestors, before opening bytes.
        location = reject_links(directory / 'manifest.json')
        if location.exists():
            metadata = json.loads(bounded_file(location, 16384))
            digest = metadata.get('sha256') if isinstance(metadata, dict) else None
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('Invalid firmware digest')
            reject_links(directory / (digest + '.bin'))
        raw = provider('/updates/manifest')
        if raw is None:
            return None
        manifest = json.loads(raw[0])
        reject_links(directory / (manifest['sha256'] + '.bin'))
        if tuple(map(int, manifest['version'].split('.'))) < MINIMUM_FIRMWARE:
            raise ValueError('Firmware predates local-only reminders')
        return raw if path == '/updates/manifest' else provider(path)
    return provide


def import_release(root, manifest_path):
    """Validate a native-selected release, snapshot it, then switch atomically."""
    from device_updates import publish_release
    try:
        source = Path(manifest_path)
        if not source.is_absolute() or source.name != 'manifest.json':
            raise ValueError()
        source = reject_links(source)
        provider = release_provider(source.parent)
        raw = provider('/updates/manifest')
        if raw is None:
            raise ValueError()
        manifest = json.loads(raw[0])
        data, _ = provider(manifest['url'])
        if len(data) != manifest['size'] or hashlib.sha256(data).hexdigest() != manifest['sha256']:
            raise ValueError()
        destination = reject_links(root / 'device-updates')
        destination.mkdir(exist_ok=True)
        private_permissions(destination, directory=True)
        reject_links(destination / 'manifest.json')
        reject_links(destination / (manifest['sha256'] + '.bin'))
        # Import reads from an immutable private snapshot, not a potentially
        # changing selected source file. The publisher checks the image again.
        with tempfile.TemporaryDirectory(prefix='.import-', dir=destination) as temporary:
            snapshot = Path(temporary) / 'firmware.bin'
            snapshot.write_bytes(data)
            publish_release(snapshot, destination, version=manifest['version'], notes=manifest['notes'])
        return manifest
    except Exception:
        raise ValueError(IMPORT_ERROR) from None


def inspect(root):
    status = {'state': 'unconfigured', 'configured': False, 'running': False,
              'version': None, 'message': '首次使用需导入设备配对配置和兼容固件包。'}
    try:
        config = load_config(root)
    except Exception:
        return {**status, 'state': 'invalid-config', 'message': '设备配对配置无效或证书已过期，请重新导入有效配置。'}
    if config is None:
        return status
    status['configured'] = True
    try:
        release = release_provider(root / 'device-updates')('/updates/manifest')
        if release is None:
            return {**status, 'state': 'no-firmware', 'message': '设备已配对，请导入兼容固件包。'}
        manifest = json.loads(release[0])
    except Exception:
        return {**status, 'state': 'invalid-firmware', 'message': '固件校验未通过，请重新导入兼容固件包。'}
    return {**status, 'state': 'starting', 'version': manifest['version'], 'message': '正在启动设备更新服务…'}


def create_server(root):
    from device_gateway import create_device_server
    config = load_config(root)
    if not config or inspect(root)['state'] != 'starting':
        raise ValueError('Device OTA pairing and firmware required')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(credential_path(root, config, 'cert'), credential_path(root, config, 'key'))
    return create_device_server(host=config['host'], port=config['port'], tls_context=context,
        token=config['token'], device=config['device_id'], allowed_hosts=config['allowed_hosts'],
        update_provider=release_provider(root / 'device-updates'), archive_enabled=False)


def serve(root):
    server = create_server(root)
    try:
        print(json.dumps({'ready': True}), flush=True)
        server.serve_forever()
    finally:
        server.server_close()
