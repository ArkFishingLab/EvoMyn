# 中文圆屏小智固件 Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** 基于小智 v2.5.2，为微雪 1.75C 实现语音、天气、设置三项中文界面；设置控制真实配网、音量和亮度。

**Architecture:** 保留上游语音、协议和驱动。新增独立 `round-voice-175c` 板型及显示子类，所有 UI 定制限制在板级目录。天气由独立后台任务请求，设备上选城市；网络与解析失败必须显示错误而非样例数据。原固件备份保留。

**Tech Stack:** ESP-IDF 6.0.2、C++、LVGL、小智 v2.5.2、Open-Meteo HTTPS、NVS。

- [x] 核对并复制小智 v2.5.2 源码至 `xiaozhi-firmware/`，阅读其 AGENTS.md。
- [x] 安装独立 ESP-IDF 6.0.2 和 ESP32-S3 工具链，保留旧环境。
- [x] 在 `main/boards/round-voice-175c/` 新增板型，更新 Kconfig、CMake 和 config.json 链，保留原版 C 引脚。
- [x] 新增三项原生 LVGL 界面，保留启动/激活信息，接入语音状态及聊天文本。
- [x] 设置绑定 Backlight::SetBrightness、AudioCodec::SetOutputVolume 与 WifiBoard::EnterWifiConfigMode；耗时工作通过主任务或独立任务执行。
- [x] 天气页提供设备端城市选择、HTTPS 实况、网络/解析失败状态和 NVS 城市保存。
- [x] 主机检查覆盖安全区、设置边界和天气数值有效性，实际 HTTPS 接口字段合约检查通过；上游主机测试 108 通过、2 项其他板型 UBSan 测试因主机无运行库跳过。
- [x] 使用 canonical 构建脚本配置板型与中文，随后 `idf.py build merge-bin` 完成构建；检查镜像与分区大小、中文字体和唯一 board factory。Windows 使用英文路径副本和响应文件。
- [x] 完成首次 COM3 分段烧录、五段哈希校验及 25 秒启动观察；PSRAM/显示/触摸/音频初始化正常，用户确认中文和打开设置正常。
- [x] 修复未使用 SPI 引脚抢占 GPIO0，补刷应用并校验；最终启动观察 20 秒无 GPIO0 冲突或崩溃。用户确认真实亮度控制及设备端城市选择正常。
- [ ] 待用户完成 Wi-Fi 配网后验证联网天气、音量听感；语音服务激活由用户完成。

## 约束

设备端默认由用户选择天气城市。不要把预览里的模拟网络或示例天气移植成真实结果。没有构建通过前，不刷入上游原版镜像冒充定制固件。
