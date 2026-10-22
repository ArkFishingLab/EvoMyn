import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import CJSON, host_fixture

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/round-voice-175c'


class RoundPairingTest(unittest.TestCase):
    def test_boot_pairing_and_health_are_ordered_in_one_bounded_worker(self):
        board = (BOARD / 'round_voice_175c.cc').read_text(encoding='utf-8')
        start = board.split('void StartLocalServices() {', 1)[1].split('\n    void ', 1)[0]
        self.assertNotIn('pairing_.Boot(', start)
        self.assertIn('local_services_started_.exchange(true)', start)
        self.assertIn('InitializeLocalServices()', start)
        self.assertIn('display_->BindUpdate', start)
        worker = board.split('void InitializeLocalServices() {', 1)[1].split('\n    void ', 1)[0]
        self.assertLess(worker.index('pairing_.Boot('), worker.index('update_.Start('))
        self.assertLess(worker.index('update_.Start('), worker.index('StartConsole('))
        self.assertLess(worker.index('StartConsole('), worker.index('ConfirmHealthyBoot('))
        self.assertIn('console_ready &&', worker)
        self.assertIn('(!pairing_configured || update_ready)', worker)

    def test_pairing_is_wired_to_physical_worker_and_ota_only(self):
        board = (BOARD / 'round_voice_175c.cc').read_text(encoding='utf-8')
        console = (BOARD / 'round_services.cc').read_text(encoding='utf-8')
        updater = (BOARD / 'round_update.cc').read_text(encoding='utf-8')
        self.assertIn('pairing_.Boot(', board)
        self.assertIn('pairing_.Control(', board)
        self.assertNotIn('self.pairing.', board)
        self.assertNotIn('services_.Start(', board)
        self.assertIn('worker_control(request)', console)
        self.assertIn('X-EvoMyn-Pairing', updater)
        self.assertIn('pairing_pending_', updater)
        self.assertIn('RoundUpdatePhase::Ready', updater)

    def test_durable_pairing_and_physical_wire_protocol(self):
        self.assertTrue((BOARD / 'round_pairing.cc').is_file(),
                        'durable pairing implementation is missing')
        self.assertTrue((BOARD / 'round_console_wire.h').is_file(),
                        'physical input framing must preserve invalid raw CR for rejection')
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            obj = build / 'json.o'
            executable = build / ('pairing.exe' if os.name == 'nt' else 'pairing')
            subprocess.run(shlex.split(os.getenv('CC', 'gcc' if os.name == 'nt' else 'cc')) +
                           ['-c', str(CJSON / 'cJSON.c'), '-o', str(obj)], check=True)
            subprocess.run(shlex.split(os.getenv('CXX', 'c++')) + [
                '-std=c++17', '-Wall', '-Wextra', '-Werror', f'-I{BOARD}', f'-I{CJSON}',
                str(host_fixture('native-round-pairing.cpp')),
                str(BOARD / 'round_pairing.cc'), str(obj), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
