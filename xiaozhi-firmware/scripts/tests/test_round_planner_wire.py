import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import CJSON, host_fixture

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/round-voice-175c'


class PlannerWireTest(unittest.TestCase):
    def test_bounded_wire_and_persistent_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            obj = work / 'json.o'
            exe = work / ('wire.exe' if os.name == 'nt' else 'wire')
            subprocess.run(shlex.split(os.getenv('CC', 'gcc' if os.name=='nt' else 'cc')) + ['-c', str(CJSON/'cJSON.c'), '-o', str(obj)],check=True,cwd=work)
            subprocess.run(shlex.split(os.getenv('CXX','c++')) + ['-std=c++17','-Wall','-Wextra','-Werror',
                f'-I{BOARD}',f'-I{CJSON}',str(host_fixture('native-planner-wire.cpp')),
                str(BOARD/'planner_wire.cc'),str(obj),'-o',str(exe)],check=True,cwd=work)
            subprocess.run([exe],check=True,cwd=work)


if __name__=='__main__':unittest.main()
