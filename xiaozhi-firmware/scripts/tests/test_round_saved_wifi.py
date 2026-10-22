import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "main" / "boards" / "round-voice-175c"


class RoundSavedWifiTest(unittest.TestCase):
    def test_saved_credentials_selection_and_preservation(self):
        source = r"""
            #include <cassert>
            #include <string>
            #include <vector>
            #include "wifi_model.h"
            using namespace round_voice;
            struct Saved { std::string ssid, password; };

            int main() {
                const std::vector<Saved> saved = {
                    {"First", "first-password"}, {"Home", "old-password"},
                    {"Open", ""}, {"SAE", "short"}, {"Broken", "bad"}
                };
                // Selecting an existing row must reuse its own credential,
                // rather than the default network or an empty edit field.
                auto home = FindSavedWifiCredentials(saved, "Home", WifiSecurity::Personal);
                assert(home == &saved[1]);
                assert(home->password == "old-password");
                assert(FindSavedWifiCredentials(saved, "home", WifiSecurity::Personal) == nullptr);
                assert(FindSavedWifiCredentials(saved, "New", WifiSecurity::Personal) == nullptr);
                assert(FindSavedWifiCredentials(saved, "Open", WifiSecurity::Open) == &saved[2]);
                assert(FindSavedWifiCredentials(saved, "SAE", WifiSecurity::Sae) == &saved[3]);
                assert(FindSavedWifiCredentials(saved, "SAE", WifiSecurity::Unknown) == &saved[3]);
                // An AP security change or unusable saved entry must request
                // fresh input, while leaving all stored records untouched.
                assert(FindSavedWifiCredentials(saved, "Open", WifiSecurity::Personal) == nullptr);
                assert(FindSavedWifiCredentials(saved, "Home", WifiSecurity::Open) == nullptr);
                assert(FindSavedWifiCredentials(saved, "Home", WifiSecurity::Unsupported) == nullptr);
                assert(FindSavedWifiCredentials(saved, "Broken", WifiSecurity::Personal) == nullptr);
                assert(saved.size() == 5);
                assert(saved[1].password == "old-password");
                assert(saved[4].password == "bad");
            }
        """
        with tempfile.TemporaryDirectory() as directory:
            build_dir = Path(directory)
            source_path = build_dir / "round_saved_wifi_test.cc"
            source_path.write_text(source, encoding="utf-8")
            executable = build_dir / ("round_saved_wifi_test.exe" if os.name == "nt" else "round_saved_wifi_test")
            compiler = shlex.split(os.environ.get("CXX", "c++"))
            subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror",
                                      f"-I{BOARD}", str(source_path), "-o", str(executable)],
                           check=True, cwd=build_dir)
            subprocess.run([executable], check=True, cwd=build_dir)


if __name__ == "__main__":
    unittest.main()
