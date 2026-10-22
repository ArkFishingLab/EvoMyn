import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "main/boards/round-voice-175c"


class RoundRecoveryTest(unittest.TestCase):
    def test_outage_backoff_cancellation_and_authentication_failure(self):
        source = r'''
            #include <cassert>
            #include "wifi_recovery.h"
            #include "voice_navigation.h"
            using namespace round_voice;
            enum { WIFI_REASON_AUTH_FAIL, WIFI_REASON_AUTH_EXPIRE,
                   WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT, WIFI_REASON_HANDSHAKE_TIMEOUT,
                   WIFI_REASON_802_1X_AUTH_FAILED, WIFI_REASON_NO_AP_FOUND };
            ACTUAL_FAILURE_CLASSIFICATION
            int main() {
                WifiRecovery retry;
                retry.Failed(1000, true);
                assert(!retry.Take(2999, false));
                // Scanning/connecting must not consume or launch a retry.
                assert(!retry.Take(3000, true));
                assert(retry.Take(3100, false));
                assert(!retry.Take(3100, false));
                retry.Failed(4000, true);
                assert(!retry.Take(8999, false));
                assert(retry.Take(9000, false));
                retry.Failed(10000, true);
                assert(!retry.Take(19999, false));
                assert(retry.Take(20000, false));
                // A long outage must keep recovering after attempt three.
                int64_t now = 20000;
                for (int i = 0; i < 50; ++i) {
                    retry.Failed(now, true);
                    assert(!retry.Take(now + 29999, false));
                    now += 30000;
                    assert(retry.Take(now, false));
                }
                retry.Cancel();
                assert(!retry.Take(now + 1000000, false));
                retry.Failed(now, true);
                assert(retry.Take(now + 2000, false));
                // Wrong credentials require user action, never endless retries.
                retry.Failed(now, false);
                assert(!retry.Take(now + 1000000, false));
                retry.Failed(now, true); retry.Pause();
                assert(!retry.Take(now + 1000000, false));
                assert(!CanSwitchWifi(kDeviceStateActivating));
                assert(!CanSwitchWifi(kDeviceStateUpgrading));
                assert(!CanSwitchWifi(kDeviceStateStarting));
                assert(CanSwitchWifi(kDeviceStateIdle));
                assert(CanSwitchWifi(kDeviceStateWifiConfiguring));
                assert(CanSwitchWifi(kDeviceStateSpeaking));
                assert(!CanSwitchWifi(kDeviceStateIdle, true));
                assert(!CanSwitchWifi(kDeviceStateWifiConfiguring, true));
                assert(!AuthenticationFailed(WIFI_REASON_AUTH_EXPIRE, true));
                // AP authentication-response expiry happens before password
                // verification and must also retry on a cold boot.
                assert(!AuthenticationFailed(WIFI_REASON_AUTH_EXPIRE, false));
                assert(!AuthenticationFailed(WIFI_REASON_HANDSHAKE_TIMEOUT, true));
                assert(!AuthenticationFailed(WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT, true));
                assert(AuthenticationFailed(WIFI_REASON_AUTH_FAIL, true));
                assert(AuthenticationFailed(WIFI_REASON_802_1X_AUTH_FAILED, true));
                assert(AuthenticationFailed(WIFI_REASON_HANDSHAKE_TIMEOUT, false));
                assert(!AuthenticationFailed(WIFI_REASON_NO_AP_FOUND, false));
            }
        '''
        wifi = (BOARD / "round_wifi.cc").read_text(encoding="utf8")
        classification = wifi[wifi.index("bool AuthenticationFailed("):wifi.index("WifiSecurity Security(")]
        source = source.replace("ACTUAL_FAILURE_CLASSIFICATION", classification)
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            cpp = build / "recovery.cc"
            cpp.write_text(source, encoding="utf8")
            exe = build / ("recovery.exe" if os.name == "nt" else "recovery")
            compiler = shlex.split(os.environ.get("CXX", "c++"))
            subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror",
                f"-I{BOARD}", str(cpp), "-o", str(exe)], check=True, cwd=build)
            subprocess.run([exe], check=True, cwd=build)


if __name__ == "__main__":
    unittest.main()
