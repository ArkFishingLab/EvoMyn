# 测试索引

测试分布在模块附近；在仓库根目录运行[开发指南](../docs/development.md)中的命令。

| 位置 | 范围 |
| --- | --- |
| `server/personal-memory/tests/` | MCP、云桥接、能力管理、备份、接入配置、启动器、设备 HTTPS/OTA 及旧计划兼容性 |
| `server/personal-memory/viewer/tests/` | 查看器 HTTP/模型与前端行为 |
| `tests/test_*.py` | 发行包、固件源码导出及仓库策略 |
| `tests/preview-settings.test.mjs` / `round-layout.test.mjs` | 网页圆屏预览与布局 |
| `tests/*.cpp` | 圆盘模型、提醒/归档/更新协议、Wi-Fi、激活及导航的原生断言 |
| `tests/warm-render/` | 基于 LVGL 的原生渲染辅助与输出检查 |
| `xiaozhi-firmware/scripts/tests/` | 上游固件主机检查；通过 `tools/run_xiaozhi_host_tests.py` 执行 |

PC Python 检查使用临时数据库、测试证书与离线模型替身；不要把测试指向正式数据。Node 检查不要求硬件。原生 C++ 检查需要对应主机编译器和 LVGL 头文件/库，具体参数以各测试源码和固件脚本为准。

一轮通过只能证明所执行的检查范围。请在结果中保留跳过项，区分网页预览、原生渲染、ESP-IDF 构建和实机声音/网络/供电测试。历史验收数量不作为当前测试数量。
