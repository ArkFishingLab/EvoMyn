"""Exercise the actual OTA time-setting block without an ESP target."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ServerClockTest(unittest.TestCase):
    def test_utc_epoch_timezone_and_invalid_input(self):
        ota = (ROOT / "main/ota.cc").read_text(encoding="utf-8")
        start = ota.index("    has_server_time_ = false;")
        end = ota.index("    has_new_version_ = false;", start)
        block = ota[start:end]
        helper = ROOT / "main/server_clock.h"
        include = '#include "server_clock.h"' if helper.exists() else ""
        source = r'''
            #include <cassert>
            #include <cmath>
            #include <cstdint>
            #include <cstdio>
            #include <cstdlib>
            #include <ctime>
            #include <cstring>
            #include <limits>
            #include <optional>
            #include <string>
            #include <sys/time.h>
            #ifdef _WIN32
            using suseconds_t = decltype(timeval{}.tv_usec);
            tm* localtime_r(const time_t* time, tm* out) { *out = *localtime(time); return out; }
            #endif
            INCLUDE_HELPER
            struct cJSON { double valuedouble; int valueint; bool number = true; };
            cJSON json_root{}, server{}, stamp{}, offset{};
            cJSON* root = &json_root;
            bool has_offset = true, has_stamp = true, has_server_time_ = false;
            timeval captured{};
            std::string zone = "CST-8";
            cJSON* cJSON_GetObjectItem(cJSON*, const char* key) {
                if (!std::strcmp(key,"server_time")) return &server;
                if (!std::strcmp(key,"timestamp")) return has_stamp ? &stamp : nullptr;
                return has_offset ? &offset : nullptr;
            }
            bool cJSON_IsObject(cJSON* p) { return p != nullptr; }
            bool cJSON_IsNumber(cJSON* p) { return p && p->number; }
            int CaptureTime(const timeval* t, void*) { captured = *t; return 0; }
            int CaptureTimezone(const char*, const char* value, int) { zone = value; return 0; }
            void ApplyTimezone() {}
            #define settimeofday CaptureTime
            #define setenv CaptureTimezone
            #define tzset ApplyTimezone
            #define ESP_LOGW(...) ((void)0)
            #define ESP_LOGI(...) ((void)0)
            #define TAG "test"
            void Apply() { ACTUAL_OTA_BLOCK }
            int main() {
                // 2026-10-16 12:34:56 UTC must stay UTC in the system clock.
                stamp.valuedouble = 1792154096789.0;
                offset.valuedouble = 480; offset.valueint = 480;
                Apply();
                assert(has_server_time_);
                assert(captured.tv_sec == 1792154096);
                assert(captured.tv_usec == 789000);
                assert(zone == "UTC-8:00");
                // Fractional-hour and negative offsets change only TZ.
                offset.valuedouble = 330; offset.valueint = 330; Apply();
                assert(zone == "UTC-5:30" && captured.tv_sec == 1792154096);
                offset.valuedouble = -210; offset.valueint = -210; Apply();
                assert(zone == "UTC+3:30" && captured.tv_sec == 1792154096);
                // UTC+8 rolls 20:00 UTC into the next local calendar day.
                stamp.valuedouble = 1792180800000.0; Apply();
                assert(captured.tv_sec == 1792180800);
                offset.valuedouble = 480; offset.valueint = 480; Apply();
                auto local_epoch = static_cast<time_t>(captured.tv_sec + 8*3600);
                auto local = *gmtime(&local_epoch);
                assert(local.tm_mday == 17 && local.tm_hour == 4);
                has_offset = false; zone = "CST-8"; Apply();
                assert(zone == "CST-8" && has_server_time_);
                has_offset = true; offset.valuedouble = 900; offset.valueint = 900;
                Apply(); assert(zone == "CST-8");
                offset.valuedouble = 330.5; offset.valueint = 330;
                Apply(); assert(zone == "CST-8");
                for (double invalid : {0.0, -1.0, 1e30,
                     std::numeric_limits<double>::infinity(),
                     std::numeric_limits<double>::quiet_NaN()}) {
                    captured = {}; stamp.valuedouble = invalid; Apply();
                    assert(!has_server_time_ && captured.tv_sec == 0);
                }
                has_stamp = false; Apply(); assert(!has_server_time_);
            }
        '''.replace("INCLUDE_HELPER", include).replace("ACTUAL_OTA_BLOCK", block)
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            cpp = build / "server_clock_test.cc"
            cpp.write_text(source, encoding="utf-8")
            exe = build / ("clock.exe" if os.name == "nt" else "clock")
            compiler = shlex.split(os.environ.get("CXX", "c++"))
            subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror",
                f"-I{ROOT / 'main'}", str(cpp), "-o", str(exe)], check=True, cwd=build)
            subprocess.run([exe], check=True, cwd=build)


if __name__ == "__main__":
    unittest.main()
