"""Legacy pairing compatibility helpers; not started or exposed by the desktop app."""
from datetime import datetime, timezone
import io
import ipaddress
import json
from pathlib import Path
import re
import ssl
import threading
import uuid

from paths import atomic_json, private_permissions, reject_links

PAIRING_ERROR = '设备配对配置无效，请检查所选运行目录、局域网地址和 TLS 证书。'
START_ERROR = '旧版接收工具无法启动，请检查保存的地址、端口和证书。'
KEYS = frozenset(('DEVICE_GATEWAY_HOST', 'DEVICE_GATEWAY_PORT', 'DEVICE_GATEWAY_ALLOWED_HOSTS',
    'DEVICE_GATEWAY_CERT', 'DEVICE_GATEWAY_KEY', 'PLANNER_DEVICE_ID', 'PLANNER_DEVICE_TOKEN'))
FIELDS = frozenset(('version', 'pairing_id', 'enabled', 'host', 'port', 'allowed_hosts', 'device_id', 'token', 'cert', 'key'))


def bounded_file(path, maximum=65536):
    path = reject_links(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(PAIRING_ERROR)
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(PAIRING_ERROR)
    return data


def local_ipv4(host):
    address = ipaddress.IPv4Address(host)
    if not (address.is_loopback or any(address in ipaddress.IPv4Network(network)
            for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))):
        raise ValueError(PAIRING_ERROR)
    return address


def validate(config, cert, key):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    if set(config) != FIELDS or config['version'] != 1 or type(config['enabled']) is not bool:
        raise ValueError(PAIRING_ERROR)
    if not re.fullmatch('[a-f0-9]{32}', config['pairing_id']):
        raise ValueError(PAIRING_ERROR)
    address = local_ipv4(config['host'])
    if type(config['port']) is not int or not 1 <= config['port'] <= 65535:
        raise ValueError(PAIRING_ERROR)
    token, device = config['token'], config['device_id']
    if (not isinstance(token, str) or not 64 <= len(token) <= 4096 or not token.isascii()
            or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ValueError(PAIRING_ERROR)
    if (not isinstance(device, str) or not device or len(device.encode('utf-8')) > 128
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in device)):
        raise ValueError(PAIRING_ERROR)
    hosts = config['allowed_hosts']
    if not isinstance(hosts, list) or not 1 <= len(hosts) <= 16:
        raise ValueError(PAIRING_ERROR)
    for host in hosts:
        # A paired LAN address and its optional explicit port only. Never widen
        # the binding/Host policy to wildcard, public-address or browser routes.
        if host not in (str(address), str(address) + ':' + str(config['port'])):
            raise ValueError(PAIRING_ERROR)
    certificate = x509.load_pem_x509_certificate(cert)
    private_key = serialization.load_pem_private_key(key, password=None)
    encode = lambda value: value.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if encode(certificate.public_key()) != encode(private_key.public_key()):
        raise ValueError(PAIRING_ERROR)
    now = datetime.now(timezone.utc)
    if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
        raise ValueError(PAIRING_ERROR)
    if address not in certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress):
        raise ValueError(PAIRING_ERROR)


def credential_path(root, config, kind):
    if (kind not in ('cert', 'key') or not isinstance(config.get('pairing_id'), str)
            or not re.fullmatch('[a-f0-9]{32}', config['pairing_id'])):
        raise ValueError(PAIRING_ERROR)
    expected = 'device-sync/' + config['pairing_id'] + '/' + kind + '.pem'
    if config[kind] != expected:
        raise ValueError(PAIRING_ERROR)
    return reject_links(root / expected)


def load_config(root):
    try:
        path = reject_links(root / 'device-sync.json')
        if not path.exists():
            return None
        config = json.loads(bounded_file(path).decode('utf-8'))
        if not isinstance(config, dict) or set(config) != FIELDS:
            raise ValueError()
        cert = bounded_file(credential_path(root, config, 'cert'))
        key = bounded_file(credential_path(root, config, 'key'))
        validate(config, cert, key)
        return config
    except Exception:
        raise ValueError(PAIRING_ERROR) from None


def import_pairing(root, directory):
    """Commit a validated copy last; a failed import keeps the previous pairing."""
    try:
        if not isinstance(directory, str) or not Path(directory).is_absolute():
            raise ValueError()
        source = reject_links(directory)
        from dotenv import dotenv_values
        values = dotenv_values(stream=io.StringIO(bounded_file(source / 'app/.env').decode('utf-8-sig')), interpolate=False)
        values = {key: value for key, value in values.items() if key in KEYS}
        identity = uuid.uuid4().hex
        config = {'version': 1, 'pairing_id': identity, 'enabled': False,
            'host': values['DEVICE_GATEWAY_HOST'], 'port': int(values.get('DEVICE_GATEWAY_PORT', '18773')),
            'allowed_hosts': [item.strip() for item in (values.get('DEVICE_GATEWAY_ALLOWED_HOSTS') or values['DEVICE_GATEWAY_HOST']).split(',')],
            'device_id': values['PLANNER_DEVICE_ID'], 'token': values['PLANNER_DEVICE_TOKEN'],
            'cert': 'device-sync/' + identity + '/cert.pem', 'key': 'device-sync/' + identity + '/key.pem'}
        files = {}
        for kind in ('cert', 'key'):
            path = Path(values['DEVICE_GATEWAY_' + kind.upper()])
            files[kind] = bounded_file(path if path.is_absolute() else source / path)
        validate(config, files['cert'], files['key'])
        parent = reject_links(root / 'device-sync')
        parent.mkdir(exist_ok=True)
        private_permissions(parent, directory=True)
        destination = reject_links(parent / identity)
        destination.mkdir()
        private_permissions(destination, directory=True)
        for kind, contents in files.items():
            target = destination / (kind + '.pem')
            with target.open('xb') as stream:
                private_permissions(target)
                stream.write(contents)
        # OpenSSL also checks usable TLS algorithms and chain/key compatibility.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(destination / 'cert.pem', destination / 'key.pem')
        atomic_json(root / 'device-sync.json', config)
        return config
    except Exception:
        raise ValueError(PAIRING_ERROR) from None


def receipt_status(root, config):
    empty = {'last_received_at': None, 'received_count': 0}
    if not config:
        return empty
    try:
        state = json.loads(bounded_file(root / 'state/device-sync-status.json', 2048))
        if (state.get('pairing_id') != config['pairing_id'] or type(state.get('received_count')) is not int
                or not 0 <= state['received_count'] < 2**53 or not isinstance(state.get('last_received_at'), str)):
            return empty
        stamp = datetime.fromisoformat(state['last_received_at'])
        if stamp.tzinfo is None:
            return empty
        return {'last_received_at': stamp.astimezone(timezone.utc).isoformat(), 'received_count': state['received_count']}
    except Exception:
        return empty


def serve(root):
    """Legacy standalone receiver; never called by the desktop application."""
    from device_gateway import create_device_server
    config = load_config(root)
    if not config or not config['enabled']:
        raise ValueError(START_ERROR)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(credential_path(root, config, 'cert'), credential_path(root, config, 'key'))
    receipt_lock = threading.Lock()
    state = receipt_status(root, config)

    def received():
        with receipt_lock:
            state['received_count'] += 1
            state['last_received_at'] = datetime.now(timezone.utc).isoformat()
            atomic_json(root / 'state/device-sync-status.json', {'pairing_id': config['pairing_id'], **state})

    server = create_device_server(host=config['host'], port=config['port'], tls_context=context,
        token=config['token'], device=config['device_id'], allowed_hosts=config['allowed_hosts'],
        archive_root=root / 'state', receipt_observer=received)
    try:
        print(json.dumps({'ready': True}), flush=True)
        server.serve_forever()
    finally:
        server.server_close()
