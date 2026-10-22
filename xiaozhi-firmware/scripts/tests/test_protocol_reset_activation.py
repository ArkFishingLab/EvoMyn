import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ProtocolResetActivationTest(unittest.TestCase):
    def test_queued_reset_cannot_destroy_starting_protocol(self):
        application = (ROOT / "main/application.cc").read_text(encoding="utf8")
        method = application[application.index("void Application::ResetProtocol() {"):]
        # This method currently ends the translation unit; keep extraction explicit.
        method = method[:method.index("\n}") + 2]
        source = r'''
            #include <atomic>
            #include <cassert>
            #include <functional>
            #include <memory>
            #include <vector>
            #define ESP_LOGW(...) ((void)0)
            #define TAG "test"
            enum { kDeviceStateIdle, kDeviceStateNotifying };
            struct Protocol {
                bool opened = true;
                bool IsAudioChannelOpened() { return opened; }
                void CloseAudioChannel() { opened = false; }
            };
            struct Application {
                std::atomic<bool> activation_in_progress_{false};
                std::atomic<bool> protocol_started_{true};
                std::atomic<unsigned> protocol_generation_{0};
                std::unique_ptr<Protocol> protocol_ = std::make_unique<Protocol>();
                std::vector<std::function<void()>> jobs;
                bool IsActivationInProgress() const { return activation_in_progress_.load(); }
                int GetDeviceState() { return kDeviceStateIdle; }
                void StopNotification() {}
                void Schedule(std::function<void()> job) { jobs.push_back(std::move(job)); }
                void Drain() { auto pending = std::move(jobs); jobs.clear(); for(auto& f:pending) f(); }
                void ResetProtocol();
            };
            ACTUAL_RESET
            int main() {
                Application app;
                app.ResetProtocol();
                // Activation may start after scheduling but before execution.
                app.activation_in_progress_ = true;
                app.Drain();
                assert(app.protocol_ && app.protocol_->opened && app.protocol_started_);
                assert(app.protocol_generation_ == 0);
                app.activation_in_progress_ = false;
                app.ResetProtocol(); app.Drain();
                assert(!app.protocol_ && !app.protocol_started_);
                assert(app.protocol_generation_ == 1);
            }
        '''.replace("ACTUAL_RESET", method)
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            cpp = build / "reset.cc"
            cpp.write_text(source, encoding="utf8")
            exe = build / ("reset.exe" if os.name == "nt" else "reset")
            compiler = shlex.split(os.environ.get("CXX", "c++"))
            subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror",
                str(cpp), "-o", str(exe)], check=True, cwd=build)
            subprocess.run([exe], check=True, cwd=build)


if __name__ == "__main__":
    unittest.main()
