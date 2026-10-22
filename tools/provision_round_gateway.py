"""Provision local TLS without printing device credentials or private keys."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'artifacts/local-memory-mcp'
PRIVATE = ROOT / 'artifacts/private-round'
DEFAULT_HEADER = ROOT / 'xiaozhi-firmware/main/boards/round-voice-175c/round_services_private.h'


def provision(host, *, runtime=RUNTIME, private_dir=PRIVATE, header=DEFAULT_HEADER):
    if ipaddress.ip_address(host).version != 4:
        raise ValueError('The device gateway currently requires an IPv4 --host.')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from dotenv import dotenv_values, set_key
    # A LAN IP must be chosen explicitly; never infer a particular developer's PC.
    runtime, private_dir, header = Path(runtime).resolve(), Path(private_dir).resolve(), Path(header).resolve()
    tls = private_dir / 'tls'
    env = runtime / 'app/.env'
    if not env.is_file():
        raise ValueError('Configure the runtime .env and device identity before provisioning.')
    config = dotenv_values(env)
    token = config.get('PLANNER_DEVICE_TOKEN')
    device = config.get('PLANNER_DEVICE_ID')
    if not token or len(token) < 64 or not device:
        raise ValueError('PLANNER_DEVICE_TOKEN (at least 64 characters) and PLANNER_DEVICE_ID are required.')
    tls.mkdir(parents=True, exist_ok=True)
    ca_path, cert_path, key_path = (tls / name for name in ('ca.pem', 'server.pem', 'server-key.pem'))
    files = [ca_path, cert_path, key_path, tls / 'ca-key.pem']
    if any(p.exists() for p in files) and not all(p.is_file() for p in files):
        raise ValueError('Incomplete TLS set; restore it before provisioning. No files were rotated.')
    if cert_path.exists():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if ipaddress.ip_address(host) not in names.get_values_for_type(x509.IPAddress):
            raise ValueError('Existing certificate does not match --host; use a separate private directory.')
    else:
        now = datetime.now(timezone.utc)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Round Private LAN Root')])
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
              .sign(ca_key, hashes.SHA256()))
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(ca_name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1095))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host)), x509.DNSName('localhost')]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        (tls / 'ca-key.pem').write_bytes(ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    settings = {
        'DEVICE_GATEWAY_HOST': host, 'DEVICE_GATEWAY_PORT': '18773',
        'DEVICE_GATEWAY_CERT': str(cert_path), 'DEVICE_GATEWAY_KEY': str(key_path),
        'DEVICE_GATEWAY_ALLOWED_HOSTS': host,
        'DEVICE_UPDATE_DIR': str(runtime / 'device-releases'),
    }
    for name, value in settings.items():
        set_key(env, name, value)
    header_text = ('#pragma once\n#define ROUND_SERVICE_BASE ' + json.dumps('https://' + host + ':18773') +
              '\n#define ROUND_SERVICE_TOKEN ' + json.dumps(token) +
              '\n#define ROUND_SERVICE_DEVICE ' + json.dumps(device) +
              '\n#define ROUND_SERVICE_CA ' + json.dumps(ca_path.read_text('ascii')) + '\n')
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(header_text, encoding='utf-8')
    archive_root = Path(config.get('PERSONAL_ARCHIVE_HOME', str(runtime / 'state')))
    db = archive_root / 'data/mnemosyne.db'
    if db.exists():
        backup = private_dir / 'before-migration.db'
        if not backup.exists():
            with sqlite3.connect(db) as source, sqlite3.connect(backup) as destination:
                source.backup(destination)
    print('TLS provisioned; private device header written; database backup preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='LAN IP reachable by the round device')
    parser.add_argument('--runtime', type=Path, default=RUNTIME)
    parser.add_argument('--private-dir', type=Path, default=PRIVATE)
    parser.add_argument('--header', type=Path, default=DEFAULT_HEADER)
    args = parser.parse_args()
    provision(args.host, runtime=args.runtime, private_dir=args.private_dir, header=args.header)
