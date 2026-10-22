# 开发与验证

Windows 桌面构建、隔离验证和更新签名另见 [desktop/README.md](../desktop/README.md)。桌面安装使用独立 LocalAppData 数据目录；不要用正式数据运行测试。

在仓库根目录运行以下命令。Windows 启动层要求 PowerShell；PC 推荐 Python 3.11，预览测试使用 Node.js 22 或更新的兼容版本。完整依赖固定在 `server/personal-memory/requirements.txt`。首次 `Start.cmd` 会准备独立运行副本并安装依赖；开发也可使用自己的虚拟环境。

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r server/personal-memory/requirements.txt
```

后续示例的 `python` 指已激活该环境的解释器。已安装的本机运行环境可复用作测试解释器，但测试必须使用临时库，不修改正式记录。源码修改应在权威模块完成，不直接覆盖私有安装。

根目录包装器调用 `tools/workspace.ps1 -Action Start|Stop|Configure|Status|Prepare`；支持 `-Workspace <目录>` 与 `-NoBrowser`。例如只准备源码运行副本或查看状态：

```powershell
./tools/workspace.ps1 -Action Prepare
./tools/workspace.ps1 -Action Status
```

首次准备创建忽略的运行目录，已有安装继续复用，不能据此假定源码修改已同步到正式服务。需要更新运行副本时先检查差异并备份。

## PC 与预览检查

```powershell
python -X utf8 -m unittest discover -s server/personal-memory/tests -p "test_*.py"
python -X utf8 -m unittest discover -s server/personal-memory/viewer/tests -p "test_*.py"
node --test server/personal-memory/tests/test_planner_web.cjs
node --test server/personal-memory/viewer/tests/*.test.mjs
node --test tests/preview-settings.test.mjs tests/round-layout.test.mjs
python -X utf8 -m unittest discover -s tests -p "test_*.py"
```

上面包含设备网关、客户端接入、能力开关、镜像发布器、备份、发行包和仓库策略检查。计划页面的旧模型测试用于兼容回归，不表示默认启用 PC 调度。默认 `PLANNER_OWNER=device`，未配置设备网关时不开放 LAN 监听。

## 原生固件检查与可选构建

```powershell
python tools/run_xiaozhi_host_tests.py
```

主机断言依赖可用的 C++ 编译器。缺少 UBSan 运行库时相关测试会显式跳过；预览与主机断言不能替代 ESP-IDF 构建和硬件测试。`tests/` 还保留针对圆盘模型与 LVGL 的原生 C++ 检查，见[测试索引](../tests/README.md)。

可选 ESP32-S3 `round-voice-175c` 使用 ESP-IDF 6.0.2（上游最低 6.0.1）。先按[开放字体说明](round-open-source.md)生成字库并检查许可，然后在已激活的 ESP-IDF 环境中构建。`tools/build_round.ps1` 接受 `-IdfPath`、`-BuildDir`、`-Python` 与仅检查参数的 `-Check`，不依赖维护者电脑路径或代理。镜像目录使用 ASCII 路径；helper 保留已有 `sdkconfig`，新镜像需先按[板型 README](../xiaozhi-firmware/main/boards/round-voice-175c/README.md)完成板型及 SDK 配置。

公共 2.5.10 已完成开放字体构建和原生渲染检查；实机测试单独验收。历史私人镜像使用不同字体和编译配对信息，不能作为公共附件。升级路径见[公共固件与首次配对](esp-firmware-update.md)。构建命令不自动烧录、修改设备配对或发布 OTA。

## 干净源码导出

```powershell
python tools/export_round_sources.py artifacts/round-source-export
python tools/package_public_release.py --output artifacts/public-release/evomyn-mcp.zip
python tools/package_public_release.py --output artifacts/public-release/evomyn-mcp-with-firmware.zip --include-firmware
python tools/audit_repository.py
```

导出器使用维护的文件白名单，拒绝符号链接与 Windows reparse point，不携带个人数据库、模型、凭证、私有 header、生成镜像或商业字体衍生资源。新增公开固件文件需同步 `tools/public_round_files.json`。导出输出是本机生成物，不应加入 Git。`MANIFEST.json` / `AUDIT.json` 记录内容及排除策略，不是数字签名。

## 文档与历史

[架构](architecture.md)描述当前边界；有日期的验收报告与旧实施计划仅作历史证据。更改服务默认值、入口或文件布局时，同时更新模块 README、测试和相关白名单。提交前阅读 [CONTRIBUTING.md](../CONTRIBUTING.md) 与 [SECURITY.md](../SECURITY.md)。
