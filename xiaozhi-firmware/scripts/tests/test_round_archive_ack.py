import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import CJSON, host_fixture

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/round-voice-175c'


class ArchiveAckTest(unittest.TestCase):
    def test_receipt_cannot_discard_unsaved_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            obj = work / 'json.o'
            exe = work / ('ack.exe' if os.name == 'nt' else 'ack')
            subprocess.run(shlex.split(os.getenv('CC', 'gcc' if os.name == 'nt' else 'cc')) + ['-c', str(CJSON / 'cJSON.c'), '-o', str(obj)], check=True, cwd=work)
            subprocess.run(shlex.split(os.getenv('CXX', 'c++')) + ['-std=c++17', '-Wall', '-Wextra', '-Werror', f'-I{BOARD}', f'-I{CJSON}', str(host_fixture('native-archive-ack.cpp')), str(obj), '-o', str(exe)], check=True, cwd=work)
            subprocess.run([exe], check=True, cwd=work)


if __name__ == '__main__':
    unittest.main()
