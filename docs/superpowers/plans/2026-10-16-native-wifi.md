# 屏幕内 Wi-Fi 联网 Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** 不再打开设备热点或网页；本机扫描真实 Wi-Fi、圆屏选择/手动输入 SSID、触屏键盘输入密码、显示连接结果并保存成功网络。

**Architecture:** 为独立 round-voice-175c 板型增加站点模式 Wi-Fi 控制器，直接使用 ESP-IDF STA/scan/event API，避免与上游热点管理器或自动扫描竞争。保留 Board 网络接口与应用事件。原型 UI 使用圆屏安全区内自绘键盘，SSID/密码严格按字节上限验证，只有获取 IP 后保存，不记录密码。上游其他板型不改。

- [x] 测试先行：SSID/密码字节界限、开放/WPA/WPA3、拒绝不支持认证、键盘及扫描页触控安全区。
- [x] 板级 STA 控制器：初始化、真实扫描、后台连接、超时/错误、成功保存、断线重连。
- [x] 替换板型 StartNetwork、网络状态、配网工具，去除本板所有旧热点入口。
- [x] Wi-Fi 列表、手动添加、输入框、圆屏键盘、显示/隐藏密码、连接按钮与返回。
- [x] 更新设备使用说明（网页预览继续明确为旧的模拟流程），独立代码检查、字库/主机测试、构建与镜像校验。
- [ ] 保留上版镜像后更新 COM3，确认无 SoftAP/DNS/HTTP 配网服务，用户在设备上验证实际联网。

验证：三组原生 C++ 断言通过；10 项预览测试通过；上游 110 项中 108 通过、2 项缺少 UBSan 跳过。152 个界面汉字均被 common 字库覆盖；独立复查的三项连接问题已修正。ESP32-S3 镜像 checksum/hash 有效，应用 3,027,680 字节，分区与资源包未变。COM3 应用烧录哈希校验通过；实际路由器连接需用户在屏幕输入密码后验证。
