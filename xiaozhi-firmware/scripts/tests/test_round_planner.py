import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import host_fixture

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "main/boards/round-voice-175c"


class RoundPlannerTest(unittest.TestCase):
    def test_offline_reminder_state_and_clock_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            exe = build / ("planner.exe" if os.name == "nt" else "planner")
            compiler = shlex.split(os.environ.get("CXX", "c++"))
            subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror",
                f"-I{BOARD}", str(host_fixture("native-planner-model.cpp")),
                "-o", str(exe)], check=True, cwd=build)
            subprocess.run([exe], check=True, cwd=build)


if __name__ == "__main__":
    unittest.main()
