"""Exercise the actual desktop guide against an isolated local TLS MCP fixture."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import ssl
import subprocess
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[2]


async def acceptance(executable, app_dir, output, legacy_empty_feed=False):
    output = Path(output).absolute()
    allowed = (ROOT / 'desktop/build').resolve()
    if allowed not in output.parents or output.exists():
        raise ValueError('Use a new isolated output directory below desktop/build')
    for candidate in (output, *output.parents):
        if candidate.is_symlink() or candidate.exists() and getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked acceptance output unsupported')
    output.mkdir(parents=True)
    (output / '.desktop-smoke-fixture').write_text('isolated onboarding fixture')
    if legacy_empty_feed:
        (output / 'preferences.json').write_text(json.dumps({'updateFeed': '', 'startAtLogin': False}), encoding='utf-8')
    completed = []

    async def peer(websocket):
        try:
            async def exchange(request):
                await websocket.send(json.dumps(request))
                while True:
                    response = json.loads(await websocket.recv())
                    if response.get('id') == request['id']:
                        return response['result']
            await exchange({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'isolated-onboarding', 'version': '1'}}})
            await websocket.send(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
            tools = await exchange({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            assert 'archive_status' in [tool['name'] for tool in tools['tools']]
            result = await exchange({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'archive_status', 'arguments': {}}})
            assert not result.get('isError')
            completed.append({'tools': len(tools['tools']), 'archive_status': True})
            await websocket.wait_closed()
        except __import__('websockets').exceptions.ConnectionClosed:
            pass

    with tempfile.TemporaryDirectory(prefix='onboarding-tls-') as temporary:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'isolated-local-fixture')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .sign(key, hashes.SHA256()))
        certfile, keyfile = Path(temporary) / 'ca.pem', Path(temporary) / 'key.pem'
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile, keyfile)
        async with serve(peer, '127.0.0.1', 0, ssl=context) as server:
            port = server.sockets[0].getsockname()[1]
            env = {**os.environ, 'PERSONAL_MEMORY_HOME': str(output), 'MNEMOSYNE_NO_EMBEDDINGS': '1',
                'PERSONAL_MEMORY_SMOKE_ENDPOINT': f'wss://127.0.0.1:{port}/isolated-onboarding-fixture/mcp',
                'SSL_CERT_FILE': str(certfile)}
            env.pop('PERSONAL_MEMORY_SMOKE_EXPECT_VERSION', None)
            arguments = [str(executable)] + ([str(app_dir)] if app_dir else []) + ['--smoke-onboarding', '--background']
            process = await asyncio.create_subprocess_exec(*arguments, env=env, cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 150)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
            (output / 'electron-stderr.log').write_bytes(stderr)
            result = json.loads((output / 'onboarding-result.json').read_text('utf-8'))
            result['tls_sessions'] = completed
            (output / 'acceptance-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            assert process.returncode == 0 and completed, result
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--app-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--legacy-empty-feed', action='store_true')
    args = parser.parse_args()
    logging.getLogger('websockets.server').setLevel(logging.CRITICAL)
    asyncio.run(acceptance(args.exe.resolve(), args.app_dir.resolve() if args.app_dir else None, args.output, args.legacy_empty_feed))
