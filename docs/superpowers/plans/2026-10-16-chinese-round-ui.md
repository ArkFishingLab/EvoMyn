# 中文圆屏界面 Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** 为 466 × 466 圆屏提供全中文、触控目标完整可见的布局，保留原应用功能。

**Architecture:** 先备份设备 Flash，核对出厂源码。布局使用圆弦安全区约束，先交付交互预览；只有取得完整应用源码、构建通过并验证功能未减少后，才写入设备。

**Tech Stack:** ESP-IDF / ESP-Brookesia / LVGL；本地 HTML 交互预览与 Node 几何验证。

- [x] 读取启动信息，确认 ESP32-S3、466 × 466、32 MB Flash。
- [x] 完整备份 Flash，校验长度和 SHA-256，保存原分区表及恢复说明。
- [x] 下载对应型号厂商公开源码，检查与出厂固件的差异。
- [x] 确认公开工程缺少出厂应用完整实现；不使用它覆盖原设备。
- [x] 在 `tests/round-layout.test.mjs` 验证圆弦安全区、上下对称和触控框四角边界。
- [x] 在 `preview/round-layout.mjs` 实现几何函数，并用于 `preview/index.html` 的内容布局。
- [x] 完成中文首页、语音/天气布局；按最新要求用指南针和设置替换音乐/相册，加入联网流程、音量和亮度预览；显式标注模拟状态。
- [x] 在浏览器验证翻页、返回、窄窗口以及圆屏裁切；交付预览文件。
- [ ] 取得完整出厂应用源码后完成 LVGL 集成。当前阻塞：公开源码只有演示工程及出厂二进制；本机 ESP-IDF 为 5.4.2，新版 BSP 要求至少 5.5。
- [ ] 完整构建、字体覆盖检查、原功能回归及上机检查通过后交付固件。

## 验证与恢复

运行 `node --test tests/round-layout.test.mjs` 验证布局数学约束。交互预览是设计验证，不代表设备固件已完成。

原始备份只保存在本地 `backups/`，可能包含设备配置，不提交版本库。

## 追加需求：指南针与设置

- [x] 移除音乐和相册入口与页面。
- [x] 加入指南针方向演示；注明真实指北缺少磁力计。
- [x] 加入模拟联网流程、音量与亮度设置；保存浏览器设置并即时反映预览亮度。
- [x] 校验设置持久化、无线网络关闭时禁用网络列表以及方向角显示。
- [ ] 设备端 Wi-Fi、ES8311 音量和 AMOLED 亮度接口集成仍受前述源码/工具链限制，未刷机。

## 最新调整

- [x] 按用户要求移除指南针入口、页面和演示代码。
- [x] 首页改为语音对话、天气、设置三项，设置居中；联网、音量和亮度保持。
