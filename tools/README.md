# 工具索引

在仓库根目录执行工具。默认使用[开发环境](../docs/development.md)；涉及设备的命令先查看 `--help` 或脚本参数，使用自己的地址、证书与凭证。工具不会因为存在源码就获得操作正式设备的授权。

| 工具 | 用途 |
| --- | --- |
| `workspace.ps1` | 根目录源码启动入口，支持 `Start` / `Stop` / `Configure` / `Status` / `Prepare` |
| `prepare_runtime.ps1` | 从维护的文件组装首次运行副本；复用既有安装并保留私有状态 |
| `audit_repository.py` | 只读检查 Git 跟踪/候选文件的公开边界 |
| `package_public_release.py` | 组装 PC 干净发行包，可选包含固件源码 |
| `export_round_sources.py` + `public_round_files.json` | 按固定文件清单导出圆盘源码 |
| `generate_open_round_fonts.py` | 验证 OFL 字体及生成 LVGL 字库，不搜索系统商业字体 |
| `build_round.ps1` | 在已激活的 ESP-IDF 环境中，通过 `-IdfPath` / `-BuildDir` / `-Python` 构建；`-Check` 只检查参数 |
| `run_xiaozhi_host_tests.py` | 运行上游主机断言，处理 Windows 临时目录及 UBSan 可用性 |
| `generate_warm_icons.cjs` | 从 `assets/warm-icons.json` 生成图标；`npm ci` 后运行 `npm run icons`，可用 `--output-dir` 指定临时输出 |
| `render_round_update.py` | 原生更新页渲染；先配置 `tests/warm-render` CMake，支持 `--build-dir` / `--board-dir` / `--lvgl-dir` / `--cxx` / `--cmake` / `--output-dir` |
| `qa_public_package.py` | 干净发行包验收辅助；使用隔离输出目录 |
| `current_memory.ps1` | 当前本机运行副本管理入口 |
| `round_device.py` | 设备维护与诊断辅助；设备连接需显式配置 |
| `provision_round_gateway.py` | 显式可选的 LAN 网关维护，必须 `--host`，可指定 `--runtime` / `--private-dir` / `--header`；会写本地凭证与信任材料 |

退役的专用部署、生产字体和一次性验收脚本保留在忽略的本机历史归档中，不再作为新用户入口。根目录 `Start.cmd` / `Stop.cmd` / `Configure.cmd` 是 Windows 使用入口；模块自身的发行启动器源码在 `server/personal-memory/local/`。

常用测试、导出及安全边界见[开发指南](../docs/development.md)。可选固件构建见[开放字库指南](../docs/round-open-source.md)。

`build_round.ps1` 保留已有构建镜像的 `sdkconfig`。新镜像第一次构建前，需在镜像目录按[圆盘板型 README](../xiaozhi-firmware/main/boards/round-voice-175c/README.md)配置板型与 SDK 选项；helper 不替使用者选择板型。开放字体应先生成到对应板型源码中。

更新页渲染需要可用的 C++/CMake、LVGL 源码及字库。例如先配置主机渲染构建，再把同一目录传给渲染器；目录需替换为自己的实际位置：

```powershell
cmake -S tests/warm-render -B artifacts/warm-render-build -DLVGL_SOURCE_DIR=<LVGL源码目录> -DROUND_BOARD_DIR=<含字库的板型目录>
python tools/render_round_update.py --build-dir artifacts/warm-render-build --board-dir <含字库的板型目录> --lvgl-dir <LVGL源码目录> --output-dir artifacts/update-preview
npm ci
npm run icons -- --output-dir artifacts/icon-preview
```

网关配置工具不属于默认启动流程。只有所有者明确配置可选设备网关时才运行，先准备设备身份和私有运行配置，并将生成物保留在忽略目录。
