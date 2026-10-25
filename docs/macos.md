# macOS 桌面构建与验收

Windows 和 macOS 使用同一份 `desktop/`、`server/personal-memory/` 业务源码和产品版本。`feat/macos-support` 是适配工作分支，验收后合并主分支；不长期维护两套业务分支。Windows 保留原来的安装身份、数据目录、NSIS 升级方式和 `latest.json` 更新入口。

Intel Mac 的 ONNX Runtime 固定为仍提供 macOS x64 安装包的 1.23.2；Windows 和 Apple Silicon 维持 1.31.0。其余直接依赖版本一致，构建器按平台标记校验依赖。

## 安装与数据

- macOS 最低 14.0：目前固定版本的 ONNX、NumPy 和 SQLite 原生库要求此版本。
- Apple Silicon（M 系列）使用 `EvoMyn-<版本>-mac-arm64.dmg`；Intel 使用 `...-mac-x64.dmg`。两种架构必须分别原生构建，不能把 ARM Python 放进 Intel Electron 中。
- 打开 DMG，将 EvoMyn 拖入 Applications 后启动。Python、uv 和服务依赖均已内置；首次语义检索需下载模型，扩展商城按需联网安装。
- Mac 数据根目录为 `~/Library/Application Support/EvoMyn/`，服务数据在 `service/state/`，凭证在私有 `service/app/.env`。卸载应用不会删除这些数据。Windows 仍为 `%LOCALAPPDATA%\PersonalMemory\`。备份需包含数据库与 `state/resources/` 附件。
- 关闭窗口后菜单栏服务继续运行；点击 Dock 图标重新显示窗口，菜单栏或应用菜单退出会停止服务。编辑菜单支持系统复制、粘贴等快捷键。
- LAN 固件更新可能需要允许系统的本地网络访问。现有配对、设备侧确认和镜像校验规则与 Windows 相同。

## 原生构建

在对应架构的 Mac 上安装 Node.js 22+ 与 uv 0.10.7，使用 uv 管理的可搬移 CPython 3.11.14。不要使用 Homebrew 或系统 Framework Python 作为打包基底。在仓库根目录运行：

```sh
uv venv --python 3.11.14 --python-preference only-managed .venv-desktop
uv pip install --python .venv-desktop/bin/python -r server/personal-memory/requirements.txt
.venv-desktop/bin/python -B desktop/scripts/stage-runtime.py
cd desktop
npm ci
# 本机验收包，无 Apple 发布签名或公证
EVOMYN_MAC_ADHOC=1 npm run dist:mac -- --arm64
# Intel Mac 使用 --x64；修改原有 SVG 图标后执行 npm run icons:mac
```

输出位于 `desktop/dist/`：DMG 用于首次安装，ZIP 用于正式签名后的应用更新。stage 按发行版 RECORD 白名单校验并复制依赖；保留许可证，排除个人配置、数据库、模型和缓存。构建钩子拒绝平台或架构不一致的运行时。

`EVOMYN_MAC_ADHOC=1` 仅生成本机测试包，关闭 hardened runtime 以允许 ad-hoc Python 加载原生库。该包不具备 Apple Developer ID 信任，跨电脑下载后可能被 Gatekeeper 阻止；不能把它当作已公证公开发行包，也不能据此声称自动替换更新已经实机验收。

正式发布必须提供 Developer ID Application 证书（electron-builder 的 `CSC_LINK` / `CSC_KEY_PASSWORD` 或本机钥匙串）、Apple 公证凭证（如 `APPLE_ID`、`APPLE_APP_SPECIFIC_PASSWORD`、`APPLE_TEAM_ID`），并取消 `EVOMYN_MAC_ADHOC`。正式配置启用 hardened runtime 和 JIT entitlement，要求代码签名及公证；须再次实机检查 Python、ONNX、扩展安装、登录启动和从旧版升级。不要提交证书、密码或私钥。签名配置见 [electron-builder 官方说明](https://www.electron.build/code-signing-mac.html)。

## 双平台检查与打包

`checks.yml` 保留 Windows 检查，并在 Apple Silicon / Intel 的 macOS runner 上运行同一组桌面测试。`desktop-builds.yml` 可从 Actions 手动选择同一个分支或标签，分别生成 Windows x64、Mac arm64、Mac x64 安装包并运行打包版 MCP、界面控制和退出验收。测试包作为 Actions artifact 保存 14 天，不自动创建 Release。runner 架构见 [GitHub 官方列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

本机隔离检查：

```sh
TMPDIR=/private/tmp .venv-desktop/bin/python -B -m unittest discover -s desktop/tests -p 'test_*.py'
TMPDIR=/private/tmp PYTHON="$PWD/.venv-desktop/bin/python" node --test desktop/tests/*.test.cjs
.venv-desktop/bin/python tools/audit_repository.py
```

`TMPDIR` 使用系统临时目录的真实路径，因为 macOS `/var` 是链接，而运行时安全策略拒绝用户提供的链接路径。附件上传内部临时目录已独立处理此系统差异，普通用户无需配置变量。

打包版验收脚本：`acceptance-language.cjs`、`acceptance-attachments.cjs` 接收 `EVOMYN_ACCEPTANCE_APP`（指向 `.app/Contents/MacOS/EvoMyn`）；`acceptance-onboarding.py` 接收 `--exe`。均使用独立测试数据。真实模型及商城安装是另一个显式联网检查，运行时必须来自安装包：

```sh
desktop/dist/mac-arm64/EvoMyn.app/Contents/Resources/backend/python/bin/python3.11 -B \
  desktop/scripts/acceptance-native.py \
  --backend desktop/dist/mac-arm64/EvoMyn.app/Contents/Resources/backend \
  --output desktop/build/native-acceptance-new
```

输出目录必须尚不存在，模型、测试库和扩展只写入该目录。确认测试完成后再重新打包，避免替换正在使用的解释器。主界面 smoke 使用 `PERSONAL_MEMORY_HOME`、目录内 `.desktop-smoke-fixture` 标记及 `--smoke-test`。macOS 父窗口截图不包含独立的 WebContentsView，看板视觉验收应使用附件/语言脚本的内容截图或实际窗口截图。

## 同一版本发布两平台

每次使用同一个源码标签和版本号，先完成所有平台构建及验收，再把 EXE、DMG、ZIP 和对应更新说明放进同一个草稿 Release，核对齐全后发布：

| 平台 | 安装包 | 签名更新说明 |
| --- | --- | --- |
| Windows x64 | EXE | `latest.json` |
| macOS arm64 | DMG；更新用 ZIP | `latest-darwin-arm64.json` |
| macOS x64 | DMG；更新用 ZIP | `latest-darwin-x64.json` |

Mac 更新说明仍由现有 Ed25519 发布私钥签名；签名脚本增加 `--platform darwin --arch arm64`（或 `x64`），`--installer` 指向已签名、公证后的 ZIP，`--output` 指向表中对应文件名，`--url` 使用版本专属 HTTPS 下载地址。不要生成新密钥替代现有客户端信任。

客户端先验证平台、架构、版本、签名和 SHA-256，再把 ZIP 通过临时带随机令牌的本机地址交给 Electron 原生 Squirrel.Mac。后者保留 Apple 签名校验与替换流程；Windows 仍调用 NSIS。正式签名更新需使用两版已签名应用单独验收，单元测试不能替代这个步骤。
