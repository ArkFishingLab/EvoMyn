# Wi-Fi 与智能体分离、屏幕验证码 Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** 设置拆分为 Wi-Fi 联网、配置智能体、音量、亮度；小智绑定验证码直接在圆屏显示，不把绑定引导到设备热点。

**Architecture:** 保留上游 Wi-Fi 热点配网和激活网络任务。Display 增加默认无操作的结构化激活信息通知；应用在收到实际验证码及生命周期变化时通知显示，板级界面负责独立智能体页面和安全区布局。验证码只存在运行内存，更新、失败、断网或配置完成时清除旧码。浏览器预览同步入口，明确不生成真实验证码。

**Tech Stack:** ESP-IDF 6.0.2、C++、LVGL、现有小智激活 API、Node 本地预览。

- [x] 先写并运行失败的主机测试：验证码保留前导零、替换、完成/失败/断网清除、无假码、设置与验证码框在圆屏安全区。
- [x] 增加通用激活信息接口，在现有后台激活流程传递真实码及结果；不更改网络协议。
- [x] 新建 Wi-Fi 页面与配置智能体页面，设置四项重排，激活码居中显示，联网后自动获取。
- [x] 同步网页预览，未连硬件时明确提示无真实验证码。
- [x] 主机测试、字库、格式、独立代码检查、目标固件构建与镜像检查。
- [x] 保留当前可启动镜像与原机完整备份；烧入 COM3，读启动日志，确认新设置入口；真实验证码需用户完成设备联网后验证。

后续 Wi-Fi 改为屏幕直接联网，见 2026-10-16-native-wifi.md；真实验证码仍待设备连接路由器后验证。
