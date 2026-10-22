# 一键启动及开源封装验收

> 历史证据：本文记录当时的部署与验收，不是当前安装要求；地址、设备身份和个人路径已替换为示例。当前入口见项目 README 与 docs/architecture.md。

2026-10-21。PC 发布版本 0.1.0；圆盘固件仍为 2.5.6，本次未重新烧录。

## 交付物

- 本机入口：根目录 `启动个人空间.cmd`、`停止个人空间.cmd`、`接入配置.cmd`；桌面“个人空间 MCP”快捷方式。
- PC 源码包：`artifacts/public-release/personal-memory-mcp.zip`，82 个文件，约 200 KB。
- 含可选固件源码：`artifacts/public-release/personal-memory-mcp-with-firmware.zip`，1,053 个文件，约 3.6 MB。
- 两包均附 `.sha256`、`.manifest.json`、`.audit.json`；ZIP 内保留 README、MIT 许可和第三方声明。
- 配置页：`http://127.0.0.1:18768/setup/`。下载本机 Codex TOML / Claude Code MCP JSON，不包含云端凭证。

发布包是源码及首次安装启动器，未打包 Python 解释器、模型缓存或硬件镜像。
Windows 首次需要 Python 3.11（推荐）或已有 uv，并能够联网安装 Python 依赖；再次启动复用本地环境。
macOS/Linux 标准 Python 层有兼容实现，一键脚本和管理页进程控制本次仅验收 Windows。
尚未创建或上传公开 GitHub 仓库；干净 ZIP 可作为公开仓库内容。

## 实现与隔离

公开包按需启动标准 stdio MCP，默认空白库，不要求小智接入点或圆盘。
后台看板与各本地客户端固定使用本目录 `state/data/mnemosyne.db`。
小智 WebSocket 桥接只在用户配置接入点后启动；局域网设备 HTTPS 网关默认关闭。
云端接入点写入 `.env`，页面不回显，写入要求本地 Host、同源 Origin、CSRF 和有界请求。
标准 stdio 和云端均遵守能力开关；本地客户端重新连接后刷新工具列表。

启动器持有跨进程生命周期锁，只停止经 PID 代次、程序、命令、实例和根目录验证的自有进程树。
Windows venv 的解释器重定向器与服务子进程 PID 不同，使用实例 nonce 和服务标识确认就绪，
TCP 状态检查包含自有后代。错误或占用端口不会接管其他程序。
本机旧运行目录保留原进程管理器，通过独立入口复用，避免再建立重复的小智连接。
连续和并发启动均保持同一看板进程；原小智连接进程保留，原库表计数、档案和历史内容未改变。

## 实际验证

1. 把实际 PC ZIP 解压到包含中文和空格的新目录，运行 Windows PowerShell 5.1 bootstrap，创建全新 `.venv` 并安装真实依赖。
2. 使用隔离端口和空白库实际启动看板、配置页和标准 MCP。完成 initialize、tools/list、archive_status，获得 9 个档案工具。
3. 通过 stdio 写入隔离日志，HTTP 看板读取到同一条记录；关闭档案组并重连后，标准客户端工具列表为空。
4. 重复启动复用原进程，停止后确认服务关闭，再启动后数据保留。验收中没有使用真实小智凭证，没有下载语义模型。
5. 导出的实际源码运行 Python 套件：**181 项，179 通过、2 项 Windows 符号链接权限跳过**。
6. 查看器 Python 检查 **7 项通过**，网页模型/计划/备份 Node 检查 **13 项通过**。
7. 发布导出器检查 **15 项，14 通过、1 项符号链接权限跳过**；固件导出/字体工具检查 **12 项，11 通过、1 项符号链接权限跳过**。实际 Windows junction 防护检查均执行通过。
8. 独立规格和代码审查提出的进程重定向、未固定固件源文件集合、junction 跟随、可选模块重打包、关闭世界时间仍发布工具等问题均已修复并复验。
9. 本机入口实际运行成功，并发两次启动未增加看板或小智桥接进程。数据库与 2.5.6 发布清单再次核对通过。

证据：`artifacts/public-release/bootstrap-acceptance.log`、`acceptance-first-run.json`、
隔离新用户目录中的 `acceptance.json`、`extracted-tests-final.log`、`viewer-tests.log`、`web-tests.log`、
`current-start-*.log`；设备/原库核对另见 `artifacts/round-local-upgrade-20261021/production-final-result.json`。
隔离验收目录含测试数据库和本机环境，不能当作发布包分发。

## 公开内容检查

PC 文件采用逐文件白名单，可选固件使用 `tools/public_round_files.json` 固定 963 个审核过的源路径，
新加入的任意笔记或源文件不会自动进入发行包。读取前检查符号链接及 Windows reparse/junction。
审计对比本机私有配置中的凭证，并检查私钥与常见服务 token 模式，报告不包含凭证值。
不分发真实 `.env`、数据库、日志、模型、用户路径配置、商业字体子集、私有头文件或编译镜像。

两个公开布局可重新打包且文件内容确定；清单哈希提供完整性检查，不等同于发布者数字签名。
固件保留上游 MIT 源码和必要提示音，默认未配置私有网关。
开放字体生成工具真实生成 12 个字体资源的流程已验证；本次没有对开放字库重新完成 ESP-IDF 全构建或硬件验收。

## 后续发布方法

在当前工作区运行：

```powershell
python tools/package_public_release.py
python tools/package_public_release.py --include-firmware --output artifacts/public-release/personal-memory-mcp-with-firmware.zip
```

发布前重新运行测试及打包审计，只上传干净源码包内容。不要上传 `artifacts/local-memory-mcp` 或验收目录。
如需增加源文件，显式更新白名单并审核对应文件；不要把整目录直接改为递归打包。
