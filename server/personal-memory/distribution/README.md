# EvoMyn

把个人事实存放在自己的电脑上，通过 MCP 接入 Codex、Claude Code、小智和其他兼容客户端。
提供可自定义分类的档案、检索、历史版本、记忆看板和能力管理。圆盘固件为可选模块。

## Windows 一键启动

1. 将整个文件夹解压到一个固定位置，不要在 ZIP 内运行。
2. 首次运行需要 **Python 3.11（推荐）或已安装 uv**，以及可下载依赖的网络。
3. 双击 **Start.cmd**。首次会在本目录创建 `.venv`、安装依赖，然后自动打开看板。
4. 后续双击同一文件即可启动或打开已有看板。**Stop.cmd** 停止本包启动的后台服务，保留数据。

默认看板：[EvoMyn](http://127.0.0.1:18768/memory/)。
双击 **Configure.cmd** 或进入[接入配置](http://127.0.0.1:18768/setup/)，获取本机客户端配置、填写可选的小智接入点。
服务只监听本机回环地址，普通 PC 使用不需要公网 IP、云服务器或圆盘。

如果没有 Python 或 uv，启动器会给出安装提示。首次安装失败可查看 `logs/bootstrap.log` 后重试。
不要随意搬动已安装的文件夹；迁移位置后删除旧 `.venv` 并重新运行 Start，以重建解释器路径。

## 接入 Codex、Claude Code 和其他 MCP 客户端

配置页生成**真实绝对路径**，不用手工填写安装目录，也不会把小智密钥写入客户端配置。
本地客户端按需启动 stdio 进程，多个客户端与看板共享同一份 `state/data/mnemosyne.db`。
关闭后台看板后，本地客户端仍可按需启动 MCP；Stop 不会终止由 Codex/CC 自己管理的进程。

### Codex

在配置页下载 Codex TOML，将对应 `[mcp_servers.evomyn]` 段合并到 Codex 的 `~/.codex/config.toml`，保留已有设置。
也可以在 PowerShell 中运行以下命令，其中路径替换为本机实际解压位置：

```powershell
codex mcp add evomyn -- 'D:/EvoMyn/.venv/Scripts/python.exe' -X utf8 'D:/EvoMyn/launcher.py' stdio
```

启动器也支持输出配置：

```powershell
./.venv/Scripts/python.exe launcher.py client-config --format toml
```

### Claude Code / 通用 MCP

在配置页下载通用 MCP JSON，将 `mcpServers.evomyn` 合并到 Claude Code 的项目 `.mcp.json`
或客户端支持的 MCP 配置中。不要覆盖原有其他服务。重新连接后可调用 `archive_status` 验证连接。

```json
{
  "mcpServers": {
    "evomyn": {
      "command": "D:/EvoMyn/.venv/Scripts/python.exe",
      "args": ["-X", "utf8", "D:/EvoMyn/launcher.py", "stdio"]
    }
  }
}
```

此包实现标准 **stdio MCP**；没有提供可直接填写 URL 的通用 HTTP MCP 端点。
只支持远程 URL 的客户端需要自行提供兼容的 stdio 网关。

## 接入小智

打开接入配置页，粘贴小智控制台提供的 `wss://…` MCP 接入点，保存后自动启动或重新连接。
留空保留已有配置；勾选停用可关闭小智桥接。
接入点仅写入本机 `app/.env`，页面不回显，也不写入客户端配置。

能力页可启停小智桥接、查看云端连接和调用元数据。当前调用记录来自小智桥接；
由 Codex/CC 管理的独立 stdio 进程不显示为小智后台进程。
能力开关改变后，重新连接本地客户端以刷新工具列表。
商城目前提供经适配的内置能力和世界时间，**不是任意第三方 MCP 的自动安装器**。
世界时间的安装需要 uv，可在能力页按需安装，默认不预装。

## 数据与模型

| 目录 | 用途 |
| --- | --- |
| `state/data/mnemosyne.db` | 原始档案、历史版本及 Mnemosyne 数据 |
| `state/` | 本包运行状态及备份；不要只复制单个正在写入的 SQLite 文件 |
| `app/models/` | 本地语义模型缓存 |
| `app/.env` | 私有本机配置 |
| `logs/` | 运行日志；调用元数据不保存参数和原文 |
| `.venv/` | 本机 Python 环境，可重建 |

原始事实先持久保存，语义索引失败时标记 pending，可调用 `archive_retry_index` 重试。
首次使用语义索引可能下载多语言模型；看板和标准连接检查不要求预下载模型。
可以先使用 `archive_status`、`archive_list` 和原文筛选功能。
通过 `archive_backup` 获取一致性备份；迁移或更新前先备份，并保留本机配置。
当前不提供 GitHub 云备份配置；本地快照不包含附件，`state/resources/` 需另存。直接复制整个 `state/` 前，应退出应用和所有共享该库的客户端。
开源发行包始终为空白库，不携带作者的记录、模型缓存、服务器凭证或固件镜像。

端口占用时，启动器会说明冲突而不会接管其他进程。可在 `app/.env` 修改
`DASHBOARD_PORT`、`ARCHIVE_PORT`、`ADMIN_PORT` 为互不重复的空闲端口。

## 可选圆盘固件

包含固件的源码包在 `firmware/` 提供 ESP32-S3 1.75C 板型及本地提醒、日志补传、定制 OTA、熄屏待机。
PC 功能可独立使用；未配置局域网设备网关时不启动 LAN 监听。
固件详细说明见 `firmware/docs/round-open-source.md`，使用 ESP-IDF 6.0.2。

为避免分发本机商业字体的派生资源，源码包不含 Windows 字体子集或已烧录镜像。
自行提供具有再分发权限的开放字体（如 OFL 字体），按说明生成字库后构建。
Wi-Fi、设备凭证、固定 CA 和网关地址需由设备所有者自行配置；包中没有作者的设备接入信息。
本次验证覆盖源代码导出及字体生成工具；重新生成开放字库后的完整硬件构建与声学验证由使用者执行。

## 开发与开源

项目自身代码采用 MIT，第三方来源见 `THIRD_PARTY_NOTICES.md` 和各模块保留的 LICENSE。
依赖版本列在 `requirements.txt`。建议在提交中只保留源码，不加入 `.env`、`state/`、日志、模型或私有固件。
解压包内 `MANIFEST.json` 记录文件 SHA-256，`AUDIT.json` 记录发布排除策略；它们不是数字签名。

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p "test_*.py"
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s viewer/tests -p "test_*.py"
```

Windows 的首次安装、启动、重复启动、停止和 stdio 接入有实测。
Python 启动层兼容 POSIX，但一键脚本及能力页的进程管理目前以 Windows 为目标，未宣称 macOS/Linux 一键可用。
提交问题时提供版本和去除凭证的日志片段，不要上传 `.env`、数据库或完整小智接入点。

## 自定义记忆分类

在记忆页点击「管理分类」，可新增、改名和调整顺序。默认分类为人脉、日志、个人、事件、资料；原 `background` 编号保留，默认显示为「个人」，既有记录和历史不改写。默认分类可改名、排序；空的自定义分类可删除，有记忆的分类不能删除。分类最多 32 个，名称为 1～24 个字符且不能重复。

分类与记忆保存在同一 SQLite 数据库，随数据库一起备份和恢复。MCP 客户端先调用 `archive_status` 获取 `categories` 中的 `id` 与 `label`，再将分类编号传入 `archive_record` / `archive_list`；无需新增客户端配置。桌面应用与本地 dashboard 支持直接新增、编辑和删除记忆；MCP 读写同一份库。独立运行的 viewer 不接受正文写入，历史 Docker 只读挂载也不开放分类编辑。

## 在桌面管理记忆

在记忆页点击「新增记忆」，选择分类后填写标题、正文、时间及标签；打开详情可编辑或删除。编辑保留原有扩展字段、步骤、关联和附件登记，不改变分类编号。MCP 总开关关闭时仍可管理记忆。

保存采用版本检查：其他客户端修改过的记录不会被直接覆盖。原文先写入本地数据库，语义索引在后台处理；索引失败不丢失已保存内容。删除需确认，会移除该记录及其修改历史，并清理其他活动记录中指向它的关联；磁盘附件和已有备份仍保留。最小删除标记防止旧请求或设备重试把它重新创建。
