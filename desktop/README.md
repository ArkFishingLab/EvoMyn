# EvoMyn · Windows / macOS 桌面应用

两平台共用业务源码及功能。macOS 14+ 的安装、原生构建、签名与双平台发布步骤见 [Mac 桌面说明](../docs/macos.md)；下面的 EXE、LocalAppData 和 PowerShell 示例对应 Windows。Mac 数据根目录为 `~/Library/Application Support/EvoMyn/`，子目录结构一致。

安装 `EvoMyn-Setup-0.2.15-x64.exe`，打开「EvoMyn」即可使用。安装包包含 Python 和所需依赖，无需另装 Python、Node.js 或 uv。首次使用语义检索会下载模型；模型与联网服务各自遵循其发布者的条款。

0.2.15 新增「应用设置 → 桌面偏好 → 语言」，支持中文 / English，默认中文。切换立即生效并保存在本机，覆盖桌面界面、记忆管理、能力和托盘；记忆内容与自定义分类保留原文。切换语言不会重启 MCP 或丢弃编辑草稿。

## 资料附件

新增或打开一条资料后，在详情里点击「添加附件」，可一次选择多个文件；每个文件最多 50 MiB。应用将副本保存到 `%LOCALAPPDATA%\PersonalMemory\service\state\resources\`，原文件不移动，同名文件分开保存。详情提供文件名、大小、打开和下载；文档、图片、音视频等常用格式使用系统默认应用打开，其他类型可下载后自行处理。删除记忆不会自动删除附件文件，以保留原有备份和历史引用。

Codex 等本机 MCP 客户端也可导入：新建资料时使用 `archive_record` 的 `file_path`，给已有记忆追加文件使用 `archive_attach(record_id, file_paths, expected_revision)`。例如让 Codex「把这个 PDF 加入我的资料，并附到这条记忆」，它可传入电脑上可访问的完整路径，自动复制到相同目录，无需手动管理资源文件夹。MCP 服务仍需开启。

附件文件不包含在 `archive_backup` 的数据库快照里；备份时请同时保留 `state/resources/`。本次只增加导入入口，不批量移动旧记录的外部文件。

## 设备本地提醒与主动记忆

提醒的创建、到时提示和完成状态保存在 ESP 设备本地。完成事项不自动写入桌面记忆库，也不依赖电脑在线；桌面不提供完成日志同步开关或接收服务。

需要保存为记忆时，可明确让小智通过已有 MCP 归档工具记录内容。此时需让电脑在线、桌面应用运行，并开启 MCP 服务和小智连接。关闭铃声、稍后提醒或取消事项不算完成，也不会自动归档。

升级保留旧配对文件、凭证及已经归档的记录；旧同步设置不会重新启动完成日志接收。设备固件 OTA 可以复用原有配对，但始终拒绝完成日志上传。

## ESP 设备更新

应用设置 → ESP 设备更新，分别显示「最新可下载」固件与「本机已准备」固件版本；后者不是设备已安装版本。点击「检查最新固件」，再点击「下载到本机」，即可准备设备更新；下载有进度提示，失败可重试。已配对且有有效固件时，打开应用自动启动 HTTPS 更新服务；最小化或关闭窗口至托盘后继续运行，彻底退出应用才停止。MCP 和小智连接的开关不影响设备更新。

设备与 PC 需在同一局域网；在设备上进入「设置 → 系统更新」，检查、下载并确认重启，桌面不会主动刷写设备。PC 地址变化、端口被占用或配置无效时，设置页会提示并提供重试；若桌面显示已允许更新、设备仍访问失败，应检查同一网络及 Windows 防火墙是否允许该应用的配对端口。

首次配置可在「高级：配对与手动导入」中导入原有配对运行目录。手动导入可信固件包的 `manifest.json`（同目录须有对应 SHA-256 命名的 `.bin`）保留在高级选项。没有配对信息时不会开放端口；这个入口只复用已写入设备的地址、身份与信任证书，不会给陌生设备自动配对。已有桌面配对文件会直接沿用，无需再次导入。

固件包需符合 `round-voice-175c`、ESP32-S3、`v2/32m` 分区和 `xiaozhi` 项目约定，最低 2.5.7；检查版本、镜像结构、板型标记、大小与 SHA-256 后才激活。设备也会再次校验并拒绝降级。固件缓存在 `%LOCALAPPDATA%\PersonalMemory\service\device-updates\`，升级应用后保留。桌面版本和固件版本独立编号；桌面更新不会自动下载或替换设备固件；在 ESP 设备更新中单独检查并下载兼容固件。下载器先验证 Ed25519 发布签名、类型、板型、版本、大小和 SHA-256，再由现有服务验证 ESP 镜像并原子激活。失败保留旧固件；拒绝替换为更旧版本，同版本缓存缺失或损坏时可重新下载。当前维护者的私有固件不包含在公开安装包中。若官方尚未发布兼容固件，设置页会提示稍后重试。

## 使用

- **记忆**：浏览、搜索、新增、编辑和删除本机记忆，默认分类也可改名和排序；**能力**：按功能包管理 MCP；**客户端接入**：导出本机客户端配置、按需连接小智；**应用设置**：桌面偏好、本地数据及更新。
- **MCP 开关**：位于左侧导航底部，控制应用拥有的执行进程。关闭后，已连接的客户端也不能继续调用工具，看板仍可浏览和编辑记忆。
- **能力列表与商城**：展示 PC 提供或可安装的 MCP 功能；设备自带的计划提醒不列入其中，仍在设备上使用。
- **小智云端连接**：单独控制云连接；同时需要 MCP 总开关开启。Codex、Claude 使用本机 stdio 转发，不需要云端连接。
- MCP 无需绑定小智即可使用。开启“小智连接”时才检查接入点，缺少时打开引导，说明控制台获取步骤；保存后连接，实际连通才显示已连接。取消或输错不会停止本地 MCP。暂停小智也会保留本地服务。
- 关闭窗口后保留托盘服务；托盘菜单或设置中的「退出」会停止后台。重复启动会打开已有窗口。
- 在「客户端接入」中导出 Codex TOML 或 Claude JSON，将其中配置合并到对应客户端。配置绑定本机安装位置，换电脑后重新导出。应用退出后，客户端需在应用重新开启后重新连接。

普通安装的数据位于 `%LOCALAPPDATA%\PersonalMemory\service\`：数据库是 `state\data\mnemosyne.db`，小智凭证是私有 `app\.env`。设置中的「打开数据目录」可直达数据库目录。安装代码、更新缓存与用户数据分开；升级及卸载默认保留用户数据。桌面版本创建自己的数据库，不自动搬移源码启动器的已有记录。需要搬移时先使用原服务的备份功能，保留原库，避免复制正在写入的 SQLite 文件。

源码 `Start.cmd` 是另一种运行方式。它的独立 stdio 进程不受桌面开关控制；使用桌面版本时，应停用旧入口并换成桌面应用导出的客户端配置。

### 手动备份

0.2.9 撤下 GitHub 云备份入口和配置流程。用户可通过 MCP 的 `archive_backup` 手动创建数据库快照，文件保存在 `%LOCALAPPDATA%\PersonalMemory\service\state\backups\`；包含记忆、历史和分类，不包含附件。附件另存 `state/resources/`。也可退出应用及共享客户端后，自行复制整个 `state/`。没有默认定时备份或云端上传；现有备份和配置保留。[完整步骤](../server/personal-memory/BACKUP.md)。

### 0.2.5 名称升级兼容

产品名称、可执行文件、快捷方式与安装包统一为 EvoMyn。保留 `com.personal-memory.desktop` 安装 ID、`%LOCALAPPDATA%\PersonalMemory` 数据目录与现有更新公钥，使升级继续使用原记录和配置。首次启动新程序时，仅迁移同一安装目录下旧程序的用户级开机启动项，并保留 Windows 中的禁用状态；隔离测试不读写正式启动项。

新导出的配置使用 `mcp_servers.evomyn` / `mcpServers.evomyn`。旧客户端配置的 Python、服务地址和脚本路径继续兼容；如需更换显示名称，请用新导出的条目替换旧 `personal-memory` 条目，不要同时保留两个相同服务。源码目录、环境变量、内部健康标识及备份格式保留原标识，第三方 Mnemosyne 来源名称不变。

## 应用内更新

设置 → 应用更新，支持 HTTPS 检查、下载、进度和「重启并安装」。更新说明使用发布者的 Ed25519 密钥签名，安装前再次校验文件大小和 SHA-256，并确认服务及登记的客户端转发进程退出。签名不符、降级或进程未退出时不会安装。

应用从 0.2.7 起支持内置更新源；当前维护地址为 `https://github.com/ArkFishingLab/EvoMyn/releases/latest/download/latest.json`。新版本会将空地址、无效地址和已保存的旧官方地址迁移到此源，其他有效的自定义 HTTPS 地址继续保留。已安装的旧版本仍使用当时内置的地址，可在应用设置中填入新地址后检查更新。在高级「更新来源」中清空并保存可恢复默认。0.2.6 及更早版本需要一次性填入上述地址，之后即可在应用内升级，不需要手动下载安装程序。

发布文件位于 [GitHub Releases](https://github.com/ArkFishingLab/EvoMyn/releases/latest)，记录、配置和数据库仍在本机。也可选择签名说明及对应 EXE 导入离线更新。更新签名与 Windows Authenticode 是两种机制；当前安装包没有 Windows 发布者证书，Windows 可能显示未识别发布者。

0.2.8 起的检查与下载使用 Electron 系统网络栈，支持 Windows 系统代理和 PAC；仍逐跳校验 HTTPS，限制重定向次数和文件大小，并检查更新签名及哈希。旧版在需要系统代理的网络中可能无法直接下载，可先在应用内导入本机签名更新包升级一次。

## 构建

在 Windows x64 上使用 Python 3.11、Node.js 22+ 和 uv 0.10.7。建议新建干净虚拟环境，避免混入本机工具。以下从仓库根目录执行：

```powershell
uv venv --python 3.11 .venv-desktop
uv pip install --python .venv-desktop/Scripts/python.exe -r server/personal-memory/requirements.txt
./.venv-desktop/Scripts/python.exe -X utf8 desktop/scripts/stage-runtime.py
cd desktop
npm ci
npm test
npm run dist
```

输出：`desktop/dist/EvoMyn-Setup-0.2.15-x64.exe`。`npm run pack` 仅生成解包程序，`npm start` 运行开发窗口（也需要先 stage）。构建目录、安装包、数据库和密钥不进入 Git。依赖闭包由已安装发行版的 RECORD 白名单及哈希验证后复制，最终再次检查私有数据与凭证；不会复制已有个人服务。

## 发布更新

首次独立 fork 需要生成自己的发布密钥。在发布任何安装包之前，移走 fork 中的 `update-trust.json` 后运行 `node scripts/release-update.cjs --init-key`。已经发布的应用必须继续使用原来的密钥；丢失密钥无法向原客户端发布受信更新。

```powershell
# desktop/ 内；使用当前已备份的发布密钥签名
node scripts/release-update.cjs --installer dist/EvoMyn-Setup-0.2.15-x64.exe --version 0.2.15 --url https://github.com/ArkFishingLab/EvoMyn/releases/download/v0.2.15/EvoMyn-Setup-0.2.15-x64.exe --output dist/latest.json
gh release create v0.2.15 dist/EvoMyn-Setup-0.2.15-x64.exe dist/latest.json --repo ArkFishingLab/EvoMyn --target main --title "EvoMyn 0.2.15" --notes "新增中英文切换和记忆附件管理，支持桌面与 MCP 导入附件。" --draft
# 确认附件齐全后发布
gh release edit v0.2.15 --repo ArkFishingLab/EvoMyn --draft=false --latest
```

后续发布应同时更新版本号、版本标签、安装包名称和签名说明中的版本专属下载地址。每个正式 Release 均附同名 `latest.json`，固定的 `/releases/latest/download/latest.json` 会指向最新正式版本。先创建草稿并上传全部文件，检查后再发布，避免用户读取不完整版本。省略 `--url` 仍可生成离线说明。

私钥默认 `.local/desktop-release/update-key.pem`（仓库根目录下），仅本机保存并单独备份，不上传 GitHub。公开的 `update-trust.json` 只有公钥。Fork 发布者还需要将 `desktop/update-source.cjs` 的默认源改为自己的仓库。保持旧版本附件可下载，不能仅替换安装包而不重新签名。

## 发布设备固件

设备固件使用独立的固定签名源 `https://github.com/ArkFishingLab/EvoMyn/releases/download/firmware-stable/firmware-latest.json`，不跟随桌面应用的 latest Release。源与下载均使用系统代理、无配对凭证的 HTTPS 连接和有界流式传输。公共包必须先完成隐私、许可证与板型审查；签名不替代这些审查或硬件验收。

公共 2.5.10 使用开放字体，将配对保存在设备独立 NVS 中；应用 0.2.14 可直接从此源检查并下载。旧私有 2.5.7/2.5.8 先用仅供自己的 2.5.9 过渡版保存配对，或升级后通过 USB 配对一次，详见[固件更新与首次配对](../docs/esp-firmware-update.md)。维护者的私有镜像包含设备凭证，不能作为公共附件。

先用 `server/personal-memory/vendor/device_updates.py` 校验应用镜像并生成本地发布目录，再签名已有 `manifest.json`：

```powershell
# desktop/ 内；不会创建或轮换密钥
node scripts/release-firmware.cjs --manifest ../artifacts/public-firmware/release-2.5.10/manifest.json --url https://github.com/ArkFishingLab/EvoMyn/releases/download/firmware-v2.5.10/firmware-2.5.10.bin --output ../artifacts/public-firmware/release-2.5.10/firmware-latest.json
```

工具默认复用 `.local/desktop-release/update-key.pem` 并比对已安装的公钥，只输出签名说明。先发布并验证版本专属的固件附件，再将 `firmware-latest.json` 更新至 `firmware-stable` Release。固件 Release 应标记为非最新桌面版本（`--latest=false`），避免影响桌面 `/releases/latest/download/latest.json`。签名载荷有独立的 `evomyn-firmware` 类型，不能作为桌面安装包使用。检查、下载均不会命令设备安装；设备安装仍由用户在设备上确认。

## 验证与目录

```powershell
# 仓库根目录；解释器需具备上面的依赖
python -X utf8 -m unittest discover -s desktop/tests -p "test_*.py"
node --test desktop/tests/*.test.cjs
```

`backend/` 管理真实 MCP 执行与进程所有权；`main.cjs` 管理窗口、隔离的看板、托盘和权限；`updater.cjs` 校验更新；`ui/` 是桌面设置界面；`scripts/` 负责可复现的运行时准备和签名。MCP 与看板业务的权威源码仍在 `server/personal-memory/`。圆盘烧录源码与构建说明位于 `xiaozhi-firmware/` 和 `docs/round-open-source.md`，不随桌面更新自动烧录。

安装包保留 CPython、Electron/Chromium、各 Python 发行版的许可证；`uv` 使用 MIT 或 Apache-2.0 双许可证，文本在 `assets/licenses/` 与安装后的 `resources/backend/tools/`。项目自身许可见根目录 `LICENSE`。

