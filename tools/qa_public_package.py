"""Functional acceptance in an extracted, isolated public package only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
assert (root / 'MANIFEST.json').is_file() and 'public-release' in root.parts
python = root / '.venv/Scripts/python.exe'
launcher = root / 'launcher.py'
env = root / 'app/.env'
if env.exists():
    from dotenv import dotenv_values
    assert not dotenv_values(env).get('MCP_ENDPOINT'), 'Use a blank QA runtime without cloud credentials'
env.write_text('MCP_ENDPOINT=\nPLANNER_OWNER=device\nDASHBOARD_PORT=61768\nARCHIVE_PORT=61770\nADMIN_PORT=61772\nMNEMOSYNE_NO_EMBEDDINGS=1\n', encoding='utf-8')
base = 'http://127.0.0.1:61768'


def command(action):
    # A uv-managed parent injects PYTHONHOME for its own interpreter. The
    # extracted fixture may use a different Python installation or version.
    child_env = {key: value for key, value in os.environ.items()
                 if key not in {'PYTHONHOME', 'PYTHONPATH', 'UV_INTERNAL__PYTHONHOME'}}
    process = subprocess.run([str(python), '-X', 'utf8', str(launcher), '--root', str(root),
                              action, '--no-browser', '--json'], capture_output=True,
                             encoding='utf-8', timeout=100, env=child_env)
    if process.returncode:
        raise AssertionError('Isolated ' + action + ' failed: ' + process.stderr[-2000:])
    return json.loads(process.stdout)


def get(path):
    with urllib.request.urlopen(base + path, timeout=15) as response:
        return response.read()


async def mcp_roundtrip(create=False, disabled=False):
    params = StdioServerParameters(command=str(python), args=['-X', 'utf8', str(launcher),
        '--root', str(root), 'stdio'], env={'PYTHONUTF8': '1', 'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows')})
    with (root / 'logs/stdio-acceptance.stderr.log').open('w', encoding='utf-8') as errors:
        async with stdio_client(params, errlog=errors) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                if disabled:
                    assert names == [], names
                    return
                assert len(names) == 9 and 'archive_status' in names
                status = await session.call_tool('archive_status')
                assert not status.is_error, status
                value = status.structured_content
                if not value: value = json.loads(status.content[0].text)
                assert str(root / 'state/data/mnemosyne.db') == value['database']
                if create:
                    saved = await session.call_tool('archive_record', {'category': 'journal',
                        'title': '开源包隔离验收', 'body': '仅用于新用户安装包验收。'})
                    assert not saved.is_error, saved
                return names


try:
    first = command('start')
    health = json.loads(get('/healthz'))
    assert health['ok'] and health['service'] == 'personal-memory-mcp'
    second = command('start')
    repeated = json.loads(get('/healthz'))
    assert health['pid'] == repeated['pid'] and health['instance'] == repeated['instance']
    assert 'EvoMyn'.encode() in get('/memory/')
    assert b'Codex' in get('/setup/') and b'Claude Code' in get('/setup/')
    config = json.loads(get('/setup/clients/claude.json'))
    assert config['mcpServers']['evomyn']['command'] == str(python)
    baseline = len(json.loads(get('/memory/api/records'))['records'])
    names = anyio.run(mcp_roundtrip, True, False)
    records = json.loads(get('/memory/api/records'))['records']
    assert len(records) == baseline + 1 and any(record['title'] == '开源包隔离验收' for record in records)
    switches = root / 'mcp-packages.json'
    switches.write_text(json.dumps({'archive': False, 'planner': False, 'worldtime': False}), encoding='utf-8')
    anyio.run(mcp_roundtrip, False, True)
    switches.write_text(json.dumps({'archive': True, 'planner': False, 'worldtime': False}), encoding='utf-8')
    command('stop')
    state = command('status')
    assert not state['dashboard']['running'] and not state['bridge']['running'], state
    command('start')
    assert len(json.loads(get('/memory/api/records'))['records']) == baseline + 1
    result = dict(ok=True, first_install=baseline == 0, baseline_records=baseline, chinese_space_path=True, repeated_start_reused=True,
                  actual_mcp_initialize=True, tools=names, same_archive_as_dashboard=True,
                  stdio_package_switches=True, stop_and_restart=True, data_preserved=True,
                  cloud_credentials_used=False, embedding_model_downloaded=False)
    (root.parent / 'acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS: extracted fresh install, real MCP stdio, shared dashboard data, package switches, Start reuse, Stop/restart.')
finally:
    command('stop')
