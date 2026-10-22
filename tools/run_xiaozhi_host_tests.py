"""Run upstream assertions with Windows-safe temporary-directory cleanup.

Some upstream tests change cwd into a TemporaryDirectory. Windows cannot
remove the active cwd. Restore the project cwd only when cleaning that tree.
The unrelated ESP-VoCat sanitizer test is skipped if host UBSan is unavailable.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

project = Path(__file__).resolve().parents[1] / "xiaozhi-firmware"
os.chdir(project)
original_temporary_directory = tempfile.TemporaryDirectory


class WindowsTemporaryDirectory(original_temporary_directory):
    def cleanup(self):
        current = Path.cwd().resolve()
        target = Path(self.name).resolve()
        if current == target or target in current.parents:
            os.chdir(project)
        super().cleanup()


tempfile.TemporaryDirectory = WindowsTemporaryDirectory
compiler = shutil.which("c++")
ubsan = False
if compiler:
    with tempfile.TemporaryDirectory() as tmp:
        probe = subprocess.run(
            [compiler, "-fsanitize=undefined", "-x", "c++", "-", "-o", str(Path(tmp) / "probe.exe")],
            input="int main() { return 0; }", text=True, capture_output=True,
        )
        ubsan = probe.returncode == 0

suite = unittest.defaultTestLoader.discover(str(project / "scripts/tests"))


def configure_tests(node):
    if isinstance(node, unittest.TestSuite):
        for child in node:
            configure_tests(child)
    elif not ubsan and node.id().startswith("test_esp_vocat_i2c."):
        method = getattr(type(node), node._testMethodName)
        method.__unittest_skip__ = True
        method.__unittest_skip_why__ = "Host C++ toolchain has no usable UBSan runtime"


configure_tests(suite)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
