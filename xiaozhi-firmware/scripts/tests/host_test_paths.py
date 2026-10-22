"""Locate reviewed host fixtures in a whole checkout or standalone source export."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def host_fixture(name):
    for tests in (ROOT / 'tests', ROOT.parent / 'tests'):
        candidate = tests / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError('Missing maintained host-test fixture: ' + name)


CJSON = host_fixture('support/cjson')
