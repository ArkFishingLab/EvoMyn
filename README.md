# EvoMyn

把个人事实保存在自己的电脑上，通过标准 MCP 接入 Codex、Claude Code、小智和其他兼容客户端。提供可自定义分类的档案、检索、历史版本、记忆看板及能力管理；ESP32-S3 圆盘提醒固件是可选模块。

## Windows 桌面应用

从 [GitHub Releases](https://github.com/clover-Saber/EvoMyn/releases/latest) 下载 Windows x64 安装包。0.2.7 起内置官方更新源，后续可在「应用设置 → 应用更新」检查、下载并重启升级。0.2.6 及更早版本可在「更新来源」一次性填写 `https://github.com/clover-Saber/EvoMyn/releases/latest/download/latest.json`，随后在应用内升级。

安装「EvoMyn」后即可打开看板、管理 MCP、连接小智、常驻托盘和在应用内更新，无需另装 Python。桌面源码与构建、数据位置、签名更新发布说明见 [desktop/README.md](desktop/README.md)。圆盘烧录代码仍是独立的可选模块。

桌面数据默认在 `%LOCALAPPDATA%\PersonalMemory\service\state\data\mnemosyne.db`；不会自动覆盖旧源码启动器的数据库。桌面 MCP 开关真正停止应用拥有的执行服务，并阻止已连接客户端继续调用。请使用桌面版导出的客户端配置。

EvoMyn 0.2.5 统一了应用、看板和 MCP 的产品名称。为兼容旧版，Windows 安装标识、数据目录和更新签名公钥沿用原值；已有数据无需改名或迁移。新导出的 MCP 配置名称为 `evomyn`，旧的 `personal-memory` 条目仍可连接，替换配置时删除旧条目即可避免重复接入。

## 源码直接启动（可选）

1. 将源码放在固定目录，安装 **Python 3.11（推荐）或 uv**，首次启动需要联网下载依赖。
2. 双击 **Start.cmd**（或 **启动EvoMyn.cmd**）。启动器准备本地运行副本并打开[看板](http://127.0.0.1:18768/memory/)。
3. 双击 **Configure.cmd**（或 **接入配置.cmd**），进入[接入配置](http://127.0.0.1:18768/setup/)，下载本机 Codex TOML / Claude Code MCP JSON。
4. **Stop.cmd**（或 **停止EvoMyn.cmd**）停止本项目管理的后台服务，保留数据。

PC 功能无需硬件、公网地址或云服务器。小智云桥接按需配置，凭证只保存在本机私有配置中，不进入客户端配置。客户端使用 stdio；本项目没有通用 HTTP MCP 地址。停止看板后，由客户端自己管理的 stdio 进程仍可使用档案。

## 目录

| 路径 | 用途 |
| --- | --- |
| [server/personal-memory/](server/personal-memory/README.md) | PC 服务、MCP、看板与发行启动器的权威源码 |
| [desktop/](desktop/README.md) | Windows 桌面应用、托盘、更新与 NSIS 安装包构建 |
| [xiaozhi-firmware/](xiaozhi-firmware/README.md) | 小智固件及 `round-voice-175c` 圆盘板型 |
| [preview/](preview/README.md) | 圆屏交互网页预览 |
| [assets/](assets/README.md) | 可维护的圆盘图标矢量源 |
| [tools/](tools/README.md) / [tests/](tests/README.md) | 开发、导出、审计工具与跨模块测试 |
| [docs/](docs/README.md) | 架构、开发指南及有日期的历史验收证据 |
| `artifacts/` / `backups/` | 已忽略的本机运行数据、构建结果、历史归档与备份 |

运行副本位于 `artifacts/local-memory-mcp/`；数据库为 `state/data/mnemosyne.db`。源码与运行副本分开，已有配置和记录应保留。使用 MCP 的 `archive_backup` 创建一致性备份；不要覆盖正在使用的 SQLite 文件。

运行副本采用首次创建、后续复用的方式。更新源码或再次启动不会自动覆盖已安装代码和环境；更新运行副本前，按[开发指南](docs/development.md)先备份并检查差异。

## 可选圆盘与开发

圆盘在设备上保存和执行提醒，确认完成后可向 PC 归档。LAN HTTPS 网关及定制 OTA 默认关闭，需要所有者配置自己的证书、设备身份和地址。PC 默认不调度设备提醒。

固件使用 ESP-IDF 6.0.2；公开源码需先用自备 OFL 开放字体生成字库。完整开放字库硬件构建和实机验证仍需执行，不能以历史生产固件验收代替。见[固件构建说明](docs/round-open-source.md)。

开发及测试命令见[开发指南](docs/development.md)。干净发行包由 `tools/package_public_release.py` 生成，排除个人数据库、凭证、模型缓存和商业字体派生资源。项目自身代码采用 [MIT](LICENSE)，上游代码和依赖遵循[各自许可](THIRD_PARTY_NOTICES.md)。贡献前请读 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。

## 自定义记忆分类

在记忆页点击「管理分类」，可新增、改名和调整顺序。默认分类为人脉、日志、个人、事件、资料；原 `background` 编号保留，默认显示为「个人」，既有记录和历史不改写。默认分类可改名、排序；空的自定义分类可删除，有记忆的分类不能删除。分类最多 32 个，名称为 1～24 个字符且不能重复。

分类与记忆保存在同一 SQLite 数据库，随数据库一起备份和恢复。MCP 客户端先调用 `archive_status` 获取 `categories` 中的 `id` 与 `label`，再将分类编号传入 `archive_record` / `archive_list`；无需新增客户端配置。看板只修改分类设置，记录正文继续通过 MCP 保存。历史 Docker 只读挂载不开放分类编辑，请在可写的本地桌面版管理。
