# EvoMyn MCP 后端

本目录是 PC 服务的权威源码。日常使用从仓库根目录 `Start.cmd` / `Configure.cmd` / `Stop.cmd` 开始；维护的文件会被组装到忽略的 `artifacts/local-memory-mcp/`。源码目录本身不保存正式数据库、模型或凭证。

## 当前入口与能力

默认[看板](http://127.0.0.1:18768/memory/)提供可自定义分类的档案、搜索、关联、历史版本及能力管理；[接入配置](http://127.0.0.1:18768/setup/)生成本机 stdio MCP 配置。Codex、Claude Code 等客户端按需启动独立进程并共享同一档案库。配置页不覆盖客户端已有配置，也不把云端凭证写入下载的 TOML / JSON。

小智通过可选的出站 WebSocket 桥接使用这些工具；无硬件、无云服务器也可使用 PC 档案。商城提供已适配能力，世界时间按需安装到独立环境，不接受任意安装命令或地址。能力开关同时限制工具发现与调用；改变后重新连接客户端以刷新工具列表。

默认 `PLANNER_OWNER=device`。提醒由 ESP 设备保存与执行，PC 不启动旧计划调度、计划 HTTP 或同步 WebSocket；旧计划页面返回退役提示，原有数据库表保持不动。保留的 `PLANNER_OWNER=pc` 代码及测试用于兼容历史部署，需明确配置。设备完成日志接口只供旧部署兼容；可选 OTA 网关默认关闭。

## 源码与运行布局

| 源码 | 运行副本中的职责 |
| --- | --- |
| `local/launcher.py` / `bootstrap.ps1` | 安装、启动、停止、状态及客户端 stdio 入口 |
| `local/dashboard.py` / `onboarding.py` | 回环看板前门及凭证只写的接入配置 |
| `vendor/` | 档案适配、MCP、能力管理、设备网关与旧计划兼容模块 |
| `viewer/` | 档案浏览、内容编辑与分类设置 |
| `distribution/` | 干净发行包的文档、许可、样式及配置模板 |
| `tests/` | 使用隔离数据和测试凭证的回归检查 |

运行副本的 `app/.env` 保存私有配置，`state/data/mnemosyne.db` 保存原文和历史版本，`app/models/` 保存模型缓存，`logs/` 保存本机日志。原文先持久化，语义索引失败后可重试；首次语义检索可能联网下载模型。备份由用户按需手动执行：`archive_backup` 创建 SQLite 一致性快照，附件需另存 `state/resources/`。当前不提供 GitHub 云备份配置。恢复前停止所有共享该库的进程，另存旧文件，勿混用旧 WAL/SHM。[BACKUP.md](BACKUP.md)说明备份和恢复步骤。

## 开发与来源

在仓库根目录执行：

```powershell
python -X utf8 -m unittest discover -s server/personal-memory/tests -p "test_*.py"
python -X utf8 -m unittest discover -s server/personal-memory/viewer/tests -p "test_*.py"
node --test server/personal-memory/tests/test_planner_web.cjs
node --test server/personal-memory/viewer/tests/backup.test.mjs server/personal-memory/viewer/tests/model.test.mjs
```

更多入口见[开发指南](../../docs/development.md)。`vendor/mcp_pipe.py` 基于 `78/mcp-calculator` 的固定提交，并修复子进程退出后的桥接状态；日志仅保留方法名、工具数量和调用元数据，不保存参数或档案正文。查看器来源和许可保留在 `viewer/SOURCE.json`、`viewer/LICENSE`；完整来源见[第三方声明](../../THIRD_PARTY_NOTICES.md)。

根目录默认启动不依赖 Docker、Nginx 或远程服务器。`compose.yaml`、Dockerfile 和 `PLANNER.md` 保留给历史/高级部署，不能直接作为默认 Windows 安装步骤。[agent-prompt-device.txt](agent-prompt-device.txt)是设备提醒模式的角色规则草稿；云端是否采用由所有者决定。
## 历史设备完成日志接口（兼容保留）

此接口仅用于旧部署兼容，不再作为桌面应用功能。当前固件在本地完成提醒，不再生成或上传完成日志。若需记录经历，请通过小智调用记忆 MCP，PC 需在线。以下为旧接口格式与部署参考。

历史设备专用 HTTPS 网关缺省关闭。圆盘保存提醒和完成事件，PC 仅将用户实际确认完成的事件写入档案的 `journal` 分类；标题、正文和补充说明原样保留，不生成总结。不创建或更新 PC planner 待办。默认由设备管理提醒；PC 旧计划页面及同步进程已退役，保留其数据而不自动迁移。

圆盘内置的计划提醒不出现在「我的能力」和能力商城中；已有旧开关配置保留，但不会在设备模式启用 PC 计划工具。显式选择历史 PC 模式的兼容路径不变。

`local/dashboard.py` 读取以下配置启动独立后台监听器（不经 dashboard 反向代理）：

| 配置 | 含义 |
| --- | --- |
| `DEVICE_GATEWAY_HOST` | 绑定的 PC 局域网 IP，填写所有者的实际 LAN 地址；必须显式设置 |
| `DEVICE_GATEWAY_PORT` | 默认 `18773` |
| `DEVICE_GATEWAY_CERT` / `DEVICE_GATEWAY_KEY` | 本地 TLS 证书链与私钥文件；证书需要被设备信任并匹配访问地址 |
| `DEVICE_GATEWAY_ALLOWED_HOSTS` | 可选的逗号分隔 Host 白名单；默认只允许绑定 IP（以及该 IP 加监听端口） |
| `PLANNER_DEVICE_TOKEN` / `PLANNER_DEVICE_ID` | 复用已有设备身份；token 至少 64 个无空白 ASCII 字符，设备 ID 必须完全一致 |
| `DEVICE_UPDATE_DIR` | 可选，本地已发布固件目录；不配置则 OTA 路由不提供内容 |
| `PERSONAL_ARCHIVE_HOME` | 沿用现有档案根目录；未配置时使用 dashboard 所在目录的 `state/` |

任何网关配置出现但 HOST/CERT/KEY 不完整时启动失败；没有配置则不启动监听器。网关模块启动时不导入模型，首个有效归档请求在独立工作线程中初始化 `ArchiveStore`。TLS 最低 1.2；仅开放固定路由，不接收命令、文件路径或模型提示。无需修改小智官方激活、语音或其他云端配置。

设备请求：`POST https://<PC-IP>:18773/device/archive`，携带 `Authorization: Bearer <device token>`、`Device-Id: <device id>`、`Content-Type: application/json` 和明确的 `Content-Length`。不允许浏览器 Origin 或跨站请求，也不返回 CORS 授权。设备应校验服务器证书。

```json
{
  "event_id": "<稳定的完成事件编号>",
  "device_id": "<与 Device-Id 一致>",
  "task_id": "<圆盘任务编号>",
  "title": "<原始标题>",
  "body": "<原始提醒正文>",
  "scheduled_at": 1792166400,
  "completed_at": 1792166450,
  "note": "<用户实际补充说明，可以为空>"
}
```

所有字段必填，不接受额外字段。时间是整数 UTC epoch 秒；`scheduled_at` 可以为 `0` 或 `null`，`completed_at` 必须是有效的正值。字段最大 UTF-8 字节数分别为：event/device/task ID 128、title 384、body 8192、note 4096；title 与各 ID 不能为空，body/note 可为空或仅空白。请求总长最多 16384 字节，JSON 递归深度最多 4，重复键与非法 UTF-8 均拒绝。档案日期按既有档案的北京时间转换，原始 epoch 同时保存于 `fields`。原始 body 保留在 `fields.body`；为空或仅空白时，仅将档案展示正文设为原始 title，事件指纹仍按完整原始输入计算。

仅在真实 journal 原记录已持久保存、且其不可变首个历史版本中的事件身份和内容摘要可重新读取验证后，返回：

```json
{"ok":true,"event_id":"<原事件编号>","record_id":"device-journal-<sha256>","index_status":"pending"}
```

`index_status` 为 `pending` 表示原文已保存、语义索引待重试；索引成功时为 `indexed`。设备可凭 `ok:true`、匹配的 event_id 和非空 record_id 确认完成日志已入库。稳定 record_id 由 device_id/event_id 推导，首个历史版本中的去重关系和原文在同一次 `ArchiveStore.save` 提交中保存，沿用正常历史版本与索引流程；不存在“原文成功但另一个去重事务失败”的窗口。重试同一事件与相同内容返回同一 record_id，不增加记录或版本；同事件不同内容返回 `409`。写盘/读取失败返回 `503`，设备保留原 event_id 和完整原始内容重试，不能另造事件编号。幂等回执不会重复调用语义模型。之后用户可以合法修改档案正文或替换 fields；设备重试仍以不可变首个历史版本验证原始事件，返回原 record_id 与当前版本的索引状态，不覆盖用户编辑。

后续 OTA 的扩展接口为 `create_device_server(..., update_provider=provider)`，也可设置返回服务器的 `update_provider` 属性。只有经过相同设备鉴权的固定 `GET /updates/manifest` 和 `GET /updates/firmware/<64位小写sha256>.bin` 会调用 `provider(path)`；provider 返回 `(bytes, 'application/json' 或 'application/octet-stream')`，找不到返回 `None`。默认不提供 OTA 内容，发布者负责将哈希映射到已核验的可信固件；URL 不解释为文件系统路径。

隔离测试使用临时数据库、自签测试证书和离线模型替身，覆盖真实 ArchiveStore 保存、版本历史、并发重试、提交后异常恢复、错误无回执、TLS、身份/Host/Origin、请求边界和固定 OTA 扩展，不操作正式数据：

```powershell
python -m unittest discover -s server/personal-memory/tests -p 'test_device_archive*.py'
```


本地固件发布使用 `vendor/device_updates.py`，不读取设备密钥、不连接设备：

```powershell
python server/personal-memory/vendor/device_updates.py --build-bin <本次构建的xiaozhi.bin> --output-dir <DEVICE_UPDATE_DIR目录> --version 1.2.3 --notes "本次版本说明"
```

发布器要求固件 app_desc 的 version 与命令行精确一致，版本是最多 31 字符的数字 `x.y.z`，project 必须是 `xiaozhi`，芯片必须是 ESP32-S3。强制包含与设备一致的 `ROUND-VOICE-175C:v2/32m:OTA1` 板型/分区标记，并验证各段边界、ESP XOR 校验和与镜像附加 SHA-256，拒绝超过 4 MiB、截断或带不支持尾部数据的镜像。本工具面向未加密、未签名的应用 `.bin`，不接受 merged flash 镜像。先原子写入 `<sha256>.bin`，再原子切换 `manifest.json`，发布中断保留之前的可用 manifest。

Manifest 是固定平面字段：`board=round-voice-175c`、`version`、`sha256`、整数 `size`、固定相对 `url=/updates/firmware/<sha256>.bin`、最多 2048 UTF-8 字节的 `notes`、`partition=v2/32m`、`project=xiaozhi`。provider 每次读取都会检查完整字段、文件大小/SHA-256、镜像元数据与板型/分区标记；只服务当前 manifest 对应的 hash，不接受任意路径，文件被篡改时返回 503。相同哈希的重复发布与下载均保持相同固件内容。



## 自定义记忆分类

在记忆页点击「管理分类」，可新增、改名和调整顺序。默认分类为个人、人脉、日志、资料；原 `background` 编号保留，默认显示为「个人」，既有记录和历史不改写。默认分类可改名、排序；空的自定义分类可删除，有记忆的分类不能删除。分类最多 32 个，名称为 1～24 个字符且不能重复。升级时，未定制的旧默认分类调整为四类；有内容的「事件」保留为普通分类。已改名、重排或新增分类的目录保留原设置，记录和历史不改写。

分类与记忆保存在同一 SQLite 数据库，随数据库一起备份和恢复。MCP 客户端先调用 `archive_status` 获取 `categories` 中的 `id` 与 `label`，再将分类编号传入 `archive_record` / `archive_list`；无需新增客户端配置。桌面应用与本地 dashboard 支持直接新增、编辑和删除记忆；MCP 读写同一份库。独立运行的 viewer 不接受正文写入，历史 Docker 只读挂载也不开放分类编辑。

## 在桌面管理记忆

在记忆页点击「新增记忆」，选择分类后填写标题、正文、时间及标签；打开详情可编辑或删除。编辑保留原有扩展字段、步骤、关联和附件登记，可更换所属分类，记录编号保持不变。MCP 总开关关闭时仍可管理记忆。

保存采用版本检查：其他客户端修改过的记录不会被直接覆盖。原文先写入本地数据库，语义索引在后台处理；索引失败不丢失已保存内容。删除需确认，会移除该记录及其修改历史，并清理其他活动记录中指向它的关联；磁盘附件和已有备份仍保留。最小删除标记防止旧请求或设备重试把它重新创建。

MCP 可调用 `archive_attach(record_id, file_paths, expected_revision)` 为已有记录添加附件：每次 1～20 个普通文件，每个最多 50 MiB。`archive_record(file_path=...)` 也会自动导入。文件复制到运行目录的 `resources/`，保留 Unicode 原文件名与原件；同名文件独立保存。附件返回稳定 ID、名称、大小、SHA-256 和下载链接；编辑记录不重复复制，替换附件保留历史文件。符号链接、Windows reparse point、特殊文件和个人数据库及其辅助文件不能导入。旧记录的外部路径不会直接开放下载，重新导入后使用受管理副本。
