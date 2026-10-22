import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import CJSON, host_fixture


ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/round-voice-175c'


class RoundUpdateTest(unittest.TestCase):
    def test_only_new_compatible_trusted_manifest_can_install(self):
        self.assertTrue((BOARD / 'round_update_policy.h').exists(),
                        'custom OTA compatibility policy is missing')
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            executable = build / ('update.exe' if os.name == 'nt' else 'update')
            subprocess.run(shlex.split(os.getenv('CXX', 'c++')) + [
                '-std=c++17', '-Wall', '-Wextra', '-Werror', f'-I{BOARD}',
                str(host_fixture('native-round-update.cpp')), '-o', str(executable)],
                check=True, cwd=build)
            subprocess.run([executable], check=True, cwd=build)

    def test_manifest_parser_rejects_ambiguous_and_unbounded_json(self):
        self.assertTrue((BOARD / 'round_update_wire.cc').exists(),
                        'custom OTA manifest parser is missing')
        cjson = CJSON
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            obj = build / 'json.o'
            executable = build / ('manifest.exe' if os.name == 'nt' else 'manifest')
            subprocess.run(shlex.split(os.getenv('CC', 'gcc' if os.name == 'nt' else 'cc')) +
                           ['-c', str(cjson / 'cJSON.c'), '-o', str(obj)], check=True, cwd=build)
            subprocess.run(shlex.split(os.getenv('CXX', 'c++')) + [
                '-std=c++17', '-Wall', '-Wextra', '-Werror', f'-I{BOARD}', f'-I{cjson}',
                str(host_fixture('native-round-update-wire.cpp')),
                str(BOARD / 'round_update_wire.cc'), str(obj), '-o', str(executable)],
                check=True, cwd=build)
            subprocess.run([executable], check=True, cwd=build)


if __name__ == '__main__':
    unittest.main()
