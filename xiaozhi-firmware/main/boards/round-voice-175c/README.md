# 当前版本：2.5.10 · Warm Graphite

已按确认的 466×466 视觉稿移植，参见项目根目录 README 和 `docs/superpowers/plans/2026-10-16-warm-round-firmware.md`。
`warm_ui.*` 负责无平台依赖的 LVGL 页面，`round_display.*` 绑定真实联网/激活/会话状态，
`round_power.h` 和板型实现负责 PMIC 电源键与触摸隔离。
PWR 短按亮灭屏、长按 1 秒开机/4 秒关机；BOOT 仍为语音入口。
旧版功能说明保留如下，新首页已以确认视觉稿为准。

## 待办与提醒

首页语音仍是唯一的新建入口。新增待办清单、详情、到点提醒、稍后十分钟、
只停铃和独立提醒音量（0 为静音仅亮屏）。详情页提供“已完成”和红色“取消”，
取消整个事项（重复事项则结束系列）；稍后十分钟仅在到点响铃页提供。
重复事项的完成按钮只完成当前实例，不在设备上猜造完成实例。

`local_planner.h` / `planner_wire.*` 负责本地权威状态、校验与请求去重；
`planner_client.*` 独立工作任务保存 NVS，`planner_ui.*` 绘制页面。
通过设备侧 `self.planner.get_context/list/create/update/complete/cancel` 操作，PC 不再维护实时计划。
2.5.8 的创建/修改工具必须传 `due_local`：北京时间 `YYYY-MM-DD HH:MM`（24 小时制，
仅无提醒时显式传空字符串），不再接受模型计算的 `due_at`。例如“明天下午一点半”
先通过 `get_context` 确定日期，再传次日 `13:30`；设备严格验证日期并转换 UTC。
保存回执和列表返回可核对的 `due_local`，界面固定按北京时间显示，不受全局 TZ 变更影响。
旧 NVS 继续存 UTC 秒，无数据迁移，不自动修改旧提醒；升级后需重新连接小智以刷新工具参数。
最多 32 个事项，近期完整请求回执 128 条。完成状态与请求回执一同持久化；
容量满时新建会按事项保存顺序回收一个已完成事项，保留防重放标记，未完成事项不会被回收。
请求先排队，重复同一 request_id 查询直到 saved=true；只有成功持久化才确认保存。
创建、到点响铃和完成均由 ESP 本地执行，不依赖电脑在线。停止铃声和取消不记完成。
2.5.7 不再生成或自动上传完成日志，也不启动 `round_services.*` 旧归档任务。
旧版最多 16 条归档日志仍原样兼容读取和保存，满队列不再阻止新的本地完成。
需要记录为个人记忆时，用户可主动语音记录，沿用现有云端 MCP，此时电脑仍需在线。
旧 `planner/cache` 保留，新主状态使用 `planner/local_v2`，支持一次性导入旧 PC 快照。
铃声占有音频输出时会中止远程播报，单次最多30秒，停止后恢复原对话音量。

## 对话收音

此板型默认轮流对话（`CONFIG_USE_DEVICE_AEC=n`，上游 auto listening 模式）：
云端播报期间关闭语音上传，等实际播放队列排空后恢复聆听，避免扬声器回声被
云端识别成用户插话。待机唤醒词和屏幕/BOOT主动打断保留；AFE唤醒检测仍按
参考输入启用回声消除。未调低全局麦克风增益或改变其他板型的VAD参数。

不再闲置自动关机，约 60 秒无操作关闭面板，PWR 仍可亮灭屏；长按真正关机后不能响铃。
断电重启若时钟无效，需先联网校时，界面会提示；运行中断网可执行已保存提醒。
启动时已错过超过120秒的旧提醒只记为错过，不逐条补响。

公共版本从独立的 `round_pairing/config` NVS 记录读取桌面 OTA 地址、CA 和设备凭证，
通过物理 USB 首次配对，普通 OTA 保留该记录。配置由专用任务校验和提交，
不通过远程 MCP 写入，也不启用旧归档上传。保存后需手动重启设备。
私人 2.5.9 过渡构建可将不提交的 `round_services_private.h` 配置迁移一次；
已有有效 NVS 配对优先，读取、校验或提交失败不会清空配对来恢复。
旧私有 2.5.7/2.5.8 需先迁移，或升级公共版后 USB 配对一次。
未配对时本地提醒仍可用。详见项目根目录 [公共固件与首次配对](../../../../docs/esp-firmware-update.md)。

公共发布使用 Noto Sans SC 生成十二个界面字库，附 OFL、来源及哈希，
不包含原 Windows 字体衍生资源。完整 ESP-IDF 构建和原生渲染已验证；
2.5.10 的实机 OTA、触摸、音频与字体显示仍需设备验收。

## 系统更新

设置内提供检查、版本说明、确认下载、进度及重启。`round_update.*` 校验可信来源、
板型/分区标记、项目、递增版本、大小及完整 SHA-256，写入非当前 OTA 槽。
确认重启才切换启动分区，启动后至少等待 30 秒并检查显示/提醒恢复，再确认健康启动。
拒绝通用固件更新入口，小智官方激活和语音接入仍保留。
实机已验证下载中断、未确认启动回退及正式网关升级至 2.5.6。
2.5.7 的本地完成变更尚需实机验收，保留系统更新入口和 OTA 校验流程。
2.5.8 的时间输入变更需实机语音验收；已有时间错误的提醒需用户确认后修改。
2.5.6 将“系统更新”入口改为与设置主条目一致的 20px，更新正文 17px，主按钮 18px。
物理断电、声学、电流和续航尚未验收；详细证据见项目 `docs/round-local-upgrade-20261021.md`。

# 中文圆屏 1.75C

基于 XiaoZhi ESP32 v2.5.2 的独立定制板型，硬件驱动来自上游
`waveshare/esp32-s3-touch-amoled-1.75` 的 **1.75C** 变体。
这是 `round-voice-175c`，不是上游原版板型；不要与 1.75 非 C 版混用。

硬件：ESP32-S3、32 MB Flash、8 MB PSRAM、466 × 466 CO5300、CST9217、
ES8311 / ES7210、AXP2101。保持 C 版 MCLK=16、LCD RESET=1、触摸 RESET=2。

## 功能

- 中文三项首页：语音对话、天气、设置。没有音乐、相册或指南针。
- 圆屏安全区内放置主要文本和触控框，语音与配网长文本换行并支持纵向滚动。
- 设置的音量、亮度调用真实 codec / AMOLED 接口，并保存至 NVS。
  亮度范围 5–100%，避免误调黑屏。
- “Wi-Fi 联网”在设备屏幕扫描网络，选择后用圆屏键盘输入密码；支持手动添加隐藏网络。
  显示真实连接结果，获得 IP 后保存，下次启动自动连接。此板型只启用 STA 模式。
- “配置智能体”与 Wi-Fi 联网分开：联网后直接在屏幕显示小智服务器下发的验证码，
  无网络、请求失败和已配置状态各自显示，不需要连接设备热点。
- 天气页在设备上选择 40 个城市之一；城市保存在 `round_ui/weather_city`。
  点击刷新通过 Open-Meteo HTTPS 查询当前温度、湿度、天气及风速。
  超时、无网络、字段缺失或数值越界显示失败，不使用样例天气。
- 本地 common 字库在联网前加载；语音服务仍使用上游激活和协议流程。

## 构建

ESP-IDF 6.0.2，Python 3.11。上游最低 SDK 为 6.0.1，不能使用 IDF 5.x。

```powershell
python scripts/build.py round-voice-175c --name round-voice-175c --language zh-CN
```

Windows 工具链在中文路径下可能无法解析 `-I` 目录。可使用自己指定的 ASCII 路径
构建镜像，例如 `D:/round-build`，源码以工作区内本目录为准；构建前同步修改。
仓库根目录的 `tools/build_round.ps1 -IdfPath <SDK目录> -BuildDir <镜像目录>`
复用已激活的 ESP-IDF 环境并同步源码，保留镜像已有的 `sdkconfig` 与下载依赖。
`-Python` 可指定该环境解释器，`-Check` 仅检查参数。新镜像首次使用时，需先在镜像内
按本节选择 `round-voice-175c` 板型及对应 `sdkconfig`，不要直接依赖默认板型。
手工复制时排除 `build`、`releases`、`.git`、`sdkconfig` 和 `sdkconfig.old`。
Windows 首次配置需启用响应文件，避免大量依赖头文件超过进程命令行长度限制：

```powershell
idf.py -DIDF_TARGET=esp32s3 -DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON reconfigure
python scripts/build.py round-voice-175c --name round-voice-175c --language zh-CN
```

主机断言：工作区 `tests/native-round-model.cpp`；上游测试通过工作区
`tools/run_xiaozhi_host_tests.py` 在 Windows 兼容的临时目录清理环境运行。
运行时需要 Python UTF-8 模式、Git Bash 在 PATH。此包装不修改上游断言；
无 UBSan 运行库时明确跳过两项其他板型的 sanitizer 检查。

构建通过不代表触摸、声学或网络已通过实机检查。烧录前核对 `flasher_args.json`
和 32 MB 分区配置，保留工作区 `backups/` 的原机完整镜像。

源码：https://github.com/78/xiaozhi-esp32/releases/tag/v2.5.2

天气文档：https://open-meteo.com/en/docs
