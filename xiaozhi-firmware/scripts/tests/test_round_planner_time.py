import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import host_fixture

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/round-voice-175c'


class PlannerCivilTime(unittest.TestCase):
    def test_beijing_calendar_and_timezone_independence(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / ('time.exe' if os.name == 'nt' else 'time')
            subprocess.run(shlex.split(os.environ.get('CXX', 'c++')) + [
                '-std=c++17', '-Wall', '-Wextra', '-Werror', f'-I{BOARD}',
                str(host_fixture('native-planner-time.cpp')), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

    def test_tools_require_civil_time_and_do_not_accept_model_epoch_arithmetic(self):
        source = (BOARD / 'round_voice_175c.cc').read_text(encoding='utf-8')
        self.assertIn('Property("due_local", kPropertyTypeString)', source)
        self.assertNotIn('Property("due_at",', source)
        self.assertIn('ParsePlannerBeijingTime', source)


if __name__ == '__main__':
    unittest.main()
