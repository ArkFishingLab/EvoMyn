"""Opt-in online acceptance using the packaged Python, isolated from user data.

Run with the packaged interpreter; --backend is Contents/Resources/backend on
macOS or resources/backend on Windows. Downloads the model and a pinned MCP
provider into a NEW output directory. Never run against an installed data home.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backend', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
backend = args.backend.resolve(strict=True)
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(backend / 'scripts'))
from paths import prepare, environment

root = prepare(backend / 'application', output / 'service')
os.environ.update(environment(root))
os.environ['PATH'] = str(backend / 'tools') + os.pathsep + os.environ.get('PATH', '')
for name in ('MNEMOSYNE_NO_EMBEDDINGS', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
    os.environ.pop(name, None)
sys.path.insert(0, str(root / 'app'))
from archive_store import ArchiveStore
from mcp_marketplace import Marketplace
from market_tools import call_time_server

store = ArchiveStore()
record = store.save({'category': 'resource', 'title': 'Fixture: bicycle repair',
                     'body': 'A mechanic replaced the damaged front wheel of my bicycle.'})
assert record['index_status'] == 'indexed', record
with store.connection(readonly=True) as connection:
    vectors = connection.execute('SELECT COUNT(*) FROM memory_embeddings').fetchone()[0]
assert vectors > 0, 'Real embeddings were not generated'
query = 'bicycle wheel replacement'
hits = store.search(query, top_k=5)
assert any(hit['id'] == record['id'] and hit['retrieval'] == 'mnemosyne' for hit in hits), hits
ranked = store.mem.recall(query, top_k=5, source='personal-archive')
assert any(hit['id'] == record['memory_id'] and hit.get('dense_score', 0) > 0 for hit in ranked), ranked
print('Packaged ONNX / SQLite vector semantic retrieval passed', flush=True)

market = Marketplace(root / 'app')
market.install('worldtime', progress=lambda value: print(value, flush=True))
market.packages.set('worldtime', True)
result = asyncio.run(call_time_server(market.packages.python('worldtime'),
                                     'get_current_time', {'timezone': 'Asia/Shanghai'}))
assert result.get('timezone') == 'Asia/Shanghai' and result.get('datetime'), result
if sys.platform == 'darwin':
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(backend.parents[2])], check=True)
report = {'python': sys.executable, 'semanticRetrieval': True,
          'embeddingRows': vectors, 'marketplaceInstallAndCall': True,
          'macSignaturePreserved': sys.platform == 'darwin'}
(output / 'acceptance-result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report), flush=True)
