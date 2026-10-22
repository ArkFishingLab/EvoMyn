# ESP 公共固件与首次配对

公共固件适用于 **round-voice-175c**：ESP32-S3、32 MB Flash、8 MB PSRAM、466 × 466 的 1.75C AMOLED。其他 ESP 设备、1.75 非 C 版及不同分区的固件不能混刷。

## 在应用中下载更新

EvoMyn 桌面 **0.2.14 或更新版本**：打开「应用设置 → ESP 设备更新」，点击「检查最新固件」，再点击「下载到本机」。下载器校验官方签名、板型、镜像和哈希后，将固件准备到本机；已经配对的设备可以在同一局域网通过「设置 → 系统更新」检查、安装并确认重启。

保持桌面应用运行即可提供更新，最小化到托盘仍然有效。MCP 与小智连接开关不影响固件服务。桌面显示的「本机已准备」是下载缓存版本，不是设备已安装版本。设备安装始终由用户确认。

## 为什么旧设备需要迁移一次

旧的私有 2.5.7 / 2.5.8 把 PC 地址、信任证书和配对凭证编译进应用镜像，没有保存到独立配置区。直接替换成公共镜像，Wi-Fi、小智激活和已有提醒仍在，但旧镜像里的桌面 OTA 配对不会自动出现在新镜像中。

有两条升级路径：

1. **已有私人构建环境**：先安装仅供自己使用的 2.5.9 过渡镜像。它会将原有编译配置保存到 `round_pairing/config`，提交并读回成功后才启用更新。重启验证后再更新到公共 2.5.10。私人过渡镜像包含该设备的凭证，不能上传或转发。
2. **首次使用，或已经跳过过渡版**：安装公共固件后，通过物理 USB 配对一次。无需擦除设备、重新设置 Wi-Fi 或删除提醒。配对保存后手动重启设备。

2.5.9 之后的配对保存在 NVS，普通 OTA 只替换应用分区。之后可连续使用公共固件更新，不需要每个版本重新配对。擦除整片 Flash、恢复出厂配置、配置损坏或更换 PC 地址不属于普通 OTA；应重新核对配对，不能通过清空全部 NVS 来修复升级。

## 通过 USB 首次配对

此步骤用于已经启动公共 **2.5.10 或更新版**的 `round-voice-175c`。工具位于[官方源码仓库](https://github.com/ArkFishingLab/EvoMyn)，从克隆后的仓库根目录运行，不在独立 MCP 压缩包中。先安装并启动一次 EvoMyn 桌面 0.2.14 或更新版，使桌面服务数据目录存在，然后从托盘菜单彻底退出应用。连接 USB 数据线，在 Windows 设备管理器确认端口号；以下 `COM7` 和 `192.168.1.20` 均须替换为自己的设备端口和电脑局域网 IPv4 地址。建议在路由器保留该电脑的地址。

使用 Python 3.11，在独立环境安装工具所需的三个依赖：

```powershell
python -m venv .venv-pairing
./.venv-pairing/Scripts/python.exe -m pip install pyserial==3.5 cryptography==50.0.2 filelock==4.1.1

# 只读查询：不需要桌面目录，不写入设备或 PC 配对配置。
./.venv-pairing/Scripts/python.exe tools/pair_esp_device.py --port COM7 --status

# 首次配对：--data-root 是桌面 service 目录，不是其中的 state/data。
./.venv-pairing/Scripts/python.exe tools/pair_esp_device.py --port COM7 --host 192.168.1.20 --data-root "$env:LOCALAPPDATA\PersonalMemory\service"
```

工具以 115200 波特率连接，打开前关闭 DTR/RTS，不发送复位或重启命令。它先读取并核对配对协议；旧固件、响应异常或桌面应用仍在运行时会拒绝配对写入。首次配对生成独立 CA、带电脑 IP 的 TLS 服务证书、随机令牌和设备身份，先以私有权限保存待提交配置，再通过 USB 写入设备，只有收到保存成功应答才提交桌面配置。服务证书有效期 825 天，CA 有效期 3650 天；工具不会自动轮换已有身份或证书。此流程不初始化或导入记忆数据库。

已有 `device-sync.json` 时直接复用地址、端口、令牌、设备身份、服务证书和私钥；`--host` 必须与原地址一致。CA 默认读取 `device-sync/<pairing_id>/ca.pem`。某些历史导入目录未带 CA，此时工具停止且保留原配置，需要提供当初签发服务证书的原始 CA：

```powershell
./.venv-pairing/Scripts/python.exe tools/pair_esp_device.py --port COM7 --host 192.168.1.20 --data-root "$env:LOCALAPPDATA\PersonalMemory\service" --ca "C:\your-original-pairing\ca.pem"
```

CA、证书链、服务私钥、有效期、IP 与 TLS 1.2 握手均须通过验证。不能用任意证书代替原 CA；地址不匹配、证书过期或配对损坏需要先恢复有效的原配对资料，工具不会覆盖它们。

出现 `Pairing saved` 后，**手动重启设备**，再运行上面的 `--status` 命令，确认 `configured` 为 `true`。`configured` 表示设备已有有效的已保存配对配置；保存成功后即可变为 `true`，但这不表示 OTA 已启用，新配对仍须重启后才能用于 OTA。然后启动桌面应用，在「应用设置 → ESP 设备更新」检查并下载固件；保持应用运行，在设备「设置 → 系统更新」完成后续 OTA。

USB 中断或 PC 配置提交失败时，保留 service 目录内的 `device-pairing-pending.json` 及其 `device-sync` 证书目录。设备可能已经保存，所以不要删除待提交文件或改用新凭证；手动重启设备后，用**相同参数**重新运行，工具会校验并复用同一身份完成提交。若待提交配置与已有桌面配置冲突，工具会停止，需先核对和恢复对应备份。待提交文件含私密配对信息，不能上传或转发。

## 配对的安全边界

每台设备使用自己的地址、CA 证书和凭证。公共固件不包含维护者的 PC 地址、设备身份或访问令牌。配对配置只通过物理 USB 写入，不提供远程 MCP 写配置接口；返回信息不会显示秘密。更新下载或等待重启期间拒绝修改配对，配置写入后需要重启，避免混用新旧凭证。

提醒的创建、到时提示和完成状态仍保存在设备。完成日程不会自动上传到记忆库；需要记录时，请明确让小智通过 MCP 保存。此处的桌面连接仅用于固件更新。

## 字体与发布文件

公共版本的界面字库由 **Noto Sans SC** 生成，附带 SIL Open Font License、字库来源和哈希。上游 Noto 字库、图标及 ESP-IDF 依赖的许可另附在发布包中。原先的 Windows 字体衍生资源和私人配对头文件不进入公共镜像。

固件使用独立的 `firmware-stable/firmware-latest.json` 签名源；版本附件位于 `firmware-v2.5.10`。固件 Release 不改变桌面应用的 latest Release。开发构建与许可证说明见 [开放字体与固件构建](round-open-source.md)。
