import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from host_test_paths import CJSON, host_fixture

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/round-voice-175c'
STUBS = {
    'esp_random.h': '#pragma once\n#include <cstdint>\nuint32_t esp_random();\n',
    'esp_mac.h': '#pragma once\n#include <cstdint>\n#define ESP_MAC_WIFI_STA 0\nint esp_read_mac(uint8_t*, int);\n',
    'freertos/FreeRTOS.h': '#pragma once\n#define pdPASS 1\n#define pdMS_TO_TICKS(x) (x)\n',
    'freertos/task.h': '#pragma once\n#include "FreeRTOS.h"\nusing TaskFunction_t = void(*)(void*);\nint xTaskCreate(TaskFunction_t,const char*,unsigned,void*,int,void*);\nvoid vTaskDelay(unsigned);\n',
    'nvs.h': '#pragma once\n#include <cstddef>\nusing nvs_handle_t=int;\n#define ESP_OK 0\n#define ESP_ERR_NVS_NOT_FOUND 1\n#define NVS_READONLY 1\n#define NVS_READWRITE 2\nint nvs_open(const char*,int,nvs_handle_t*);\nint nvs_get_blob(nvs_handle_t,const char*,void*,size_t*);\nint nvs_set_blob(nvs_handle_t,const char*,const void*,size_t);\nint nvs_commit(nvs_handle_t);\nvoid nvs_close(nvs_handle_t);\n',
}


class LocalPlannerTest(unittest.TestCase):
    def test_nvs_failure_rollback_migration_and_nonblocking_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name, content in STUBS.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            obj = work / 'json.o'
            exe = work / ('client.exe' if os.name == 'nt' else 'client')
            subprocess.run(shlex.split(os.getenv('CC', 'gcc' if os.name == 'nt' else 'cc')) + ['-c', str(CJSON/'cJSON.c'), '-o', str(obj)], check=True)
            subprocess.run(shlex.split(os.getenv('CXX', 'c++')) + ['-std=c++17', '-Wall', '-Wextra', '-Werror',
                            f'-I{BOARD}', f'-I{CJSON}', f'-I{work}',
                            str(host_fixture('native-local-planner-client.cpp')),
                            str(BOARD/'planner_client.cc'), str(BOARD/'planner_wire.cc'),
                            str(obj), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_nonblocking_device_tools_and_no_legacy_network(self):
        board = (BOARD / 'round_voice_175c.cc').read_text(encoding='utf-8')
        for name in ('get_context', 'list', 'create', 'update', 'complete', 'cancel'):
            self.assertIn('self.planner.' + name, board)
        client = (BOARD / 'planner_client.cc').read_text(encoding='utf-8')
        self.assertNotIn('CreateWebSocket', client)
        self.assertNotIn('planner_private.h', client)
        self.assertIn('"local_v2"', client)
        self.assertNotIn('nvs_set_blob(handle, "cache"', client)

    def test_local_authority_transactions_migration_and_journal(self):
        self.assertTrue((BOARD / 'local_planner.h').exists(), 'Local authoritative planner is missing')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            obj = work / 'json.o'
            exe = work / ('local.exe' if os.name == 'nt' else 'local')
            subprocess.run(shlex.split(os.getenv('CC', 'gcc' if os.name == 'nt' else 'cc')) + ['-c', str(CJSON/'cJSON.c'), '-o', str(obj)], check=True)
            subprocess.run(shlex.split(os.getenv('CXX', 'c++')) + ['-std=c++17', '-Wall', '-Wextra', '-Werror',
                            f'-I{BOARD}', f'-I{CJSON}',
                            str(host_fixture('native-local-planner.cpp')),
                            str(BOARD/'planner_wire.cc'), str(obj), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
