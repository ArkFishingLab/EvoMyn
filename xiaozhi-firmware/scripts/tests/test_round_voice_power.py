import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "main" / "boards" / "round-voice-175c"


class RoundVoicePowerTest(unittest.TestCase):
    def test_pmic_key_idle_policy_and_touch_suppression(self):
        source = r"""
            #include <cassert>
            #include "round_power.h"
            using round_voice::ScreenPowerPolicy;
            using round_voice::TouchPowerGate;
            using Action = ScreenPowerPolicy::Action;

            int main() {
                // REG27: ONLEVEL[1:0]=10 means 1s; OFFLEVEL[3:2]=00
                // means 4s; IRQLEVEL[5:4]=01 retains 1.5s long IRQ.
                assert((ScreenPowerPolicy::kPowerKeyTiming & 0x03) == 0x02);
                assert((ScreenPowerPolicy::kPowerKeyTiming & 0x0c) == 0x00);
                assert((ScreenPowerPolicy::kPowerKeyTiming & 0x30) == 0x10);
                // Acknowledge only the W1C short-press flag, preserving every
                // other PMIC interrupt, including the hardware long press.
                assert(ScreenPowerPolicy::ShortPressAck(0xff) == 0x08);
                assert(ScreenPowerPolicy::ShortPressAck(0xf7) == 0);
                for (int status = 0; status < 256; ++status) {
                    assert(ScreenPowerPolicy::ShortPressAck(status) == (status & 0x08));
                }

                ScreenPowerPolicy power;
                assert(!power.manual_off());
                assert(power.Tick(59999, true) == Action::None);
                assert(power.Tick(60000, true) == Action::ScreenOff);
                assert(power.Tick(70000, true) == Action::None);
                assert(power.WakeUp(71000) == Action::Restore);
                assert(power.Tick(130999, true) == Action::None);
                assert(power.Tick(131000, true) == Action::ScreenOff);
                // A short press wakes an automatically blanked display.
                assert(!power.ToggleManualOff(131001));
                assert(power.ToggleManualOff(132000));
                assert(power.manual_off());
                assert(power.WakeUp(133000) == Action::None);
                assert(power.manual_off());
                assert(power.SetAutoEnabled(false, 134000) == Action::None);
                assert(power.manual_off());
                assert(power.Tick(1000000, true) == Action::None);
                assert(power.SetAutoEnabled(true, 1000000) == Action::None);
                assert(power.Tick(1060000, true) == Action::None);
                assert(power.manual_off());
                assert(power.WakeUp(1060001) == Action::None);
                assert(power.manual_off());
                assert(!power.ToggleManualOff(1061000));
                assert(!power.manual_off());
                assert(power.Tick(1120999, true) == Action::None);
                assert(power.Tick(1121000, true) == Action::ScreenOff);
                assert(power.SetAutoEnabled(false, 1122000) == Action::Restore);
                assert(power.Tick(2000000, true) == Action::None);

                ScreenPowerPolicy idle;
                assert(idle.Tick(59000, false) == Action::None);
                assert(idle.Tick(118999, true) == Action::None);
                assert(idle.Tick(119000, true) == Action::ScreenOff);
                assert(idle.Tick(358999, true) == Action::None);
                assert(idle.Tick(359000, true) == Action::None);
                assert(idle.Tick(360000, true) == Action::None);
                assert(idle.Tick(86400000, true) == Action::None);
                assert(idle.screen_off());
                assert(idle.WakeUp(86400001) == Action::Restore);
                assert(!idle.screen_off());

                ScreenPowerPolicy reminder;
                assert(reminder.Tick(60000, true, true) == Action::ScreenOff);
                assert(reminder.Tick(300000, true, true) == Action::None);
                assert(!reminder.ToggleManualOff(300001));
                assert(reminder.ToggleManualOff(300001));
                assert(reminder.WakeForReminder(300002) == Action::Restore);
                assert(!reminder.manual_off());
                assert(reminder.Tick(600002, true, true) == Action::ScreenOff);
                assert(reminder.Tick(600003, true, false) == Action::None);

                TouchPowerGate touch;
                assert(!touch.Consume(false, true));
                assert(touch.Consume(true, true));
                assert(touch.Consume(false, true)); // Held across PWR wake.
                assert(touch.Consume(false, false)); // Consume its release too.
                assert(!touch.Consume(false, true));
                assert(touch.Consume(true, false));
                assert(touch.Consume(true, true));
                assert(touch.Consume(true, false));
                assert(touch.Consume(false, false));
                assert(!touch.Consume(false, true));
            }
        """
        with tempfile.TemporaryDirectory() as directory:
            build_dir = Path(directory)
            source_path = build_dir / "round_power_test.cc"
            source_path.write_text(source, encoding="utf-8")
            executable = build_dir / ("round_power_test.exe" if os.name == "nt" else "round_power_test")
            compiler = shlex.split(os.environ.get("CXX", "c++"))
            subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror",
                                      f"-I{BOARD}", str(source_path), "-o", str(executable)],
                           check=True, cwd=build_dir)
            subprocess.run([executable], check=True, cwd=build_dir)


if __name__ == "__main__":
    unittest.main()
