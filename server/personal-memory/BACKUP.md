# 看板备份管理

入口：个人信息库左侧「备份管理」，路由 `/memory/#backup`。

此功能已部署，初始状态没有仓库、Token 或恢复公钥，每日自动备份关闭。部署及验证没有请求 GitHub 或上传真实数据。GitHub 上传协议通过隔离的模拟传输测试，真实仓库仍须由用户配置后验证。

## 在页面配置

1. 准备一个已初始化（有 README 或提交）的 GitHub **私有仓库**。
2. 为该仓库创建 Fine-grained Personal Access Token，Contents 权限为 Read and write，在页面填写仓库和 Token。Token 保存后不回显；留空表示保留已存 Token。
3. 点击「生成并下载恢复私钥」。私钥在浏览器中生成，只下载到本机，服务器仅接收公钥。单独保存私钥并勾选确认，然后保存配置。丢失私钥无法解密既有备份。更换密钥后，旧备份仍需原私钥。
4. 验证仓库连接，再点击「立即备份并上传」。如需每日执行，勾选开关并保存。默认时间为北京时间 03:00。
5. 页面显示执行状态、成功时间、GitHub 版本链接和本机可下载的加密文件。

这是上传到仓库 Releases 的加密备份资产，不是将明文数据库作为 Git 提交推送。GitHub Token 不写入备份，也不存放在浏览器 storage 中。服务器将 Token 存于仅服务账户可读的配置文件。用户应自行管理 Token 的权限和有效期。

## 内容、校验与保留

- 通过 SQLite backup API 创建数据库一致性快照，并执行 integrity_check；包含个人档案、计划、提醒、设备同步记录。
- 包含 state/resources 下的普通资源文件；拒绝符号链接或越界路径。
- 包含选定的部署配置副本：compose.yaml、memory.env、nginx-memory.locations.conf。memory.env 含服务密钥，因此整个归档只以加密形式落盘和上传。
- 不包含模型、缓存、源 state/backups、backup-state、backup-config 原目录，也不包含备份服务的 GitHub Token。
- 压缩内容使用随机 AES-256-GCM 密钥加密；RSA-OAEP-SHA256 公钥封装该密钥，格式头也纳入认证。
- GitHub 先创建草稿、流式上传、比对资产 SHA-256 和大小，验证后发布。无法取得有效摘要时保留草稿并报告失败，不发布、不清理旧备份。
- 仅清理本应用专用标记和标签的已发布备份版本。默认保留最近 30 个不同日期及 12 个不同月份各自最新的一份，二者取并集。其他 Releases 和草稿不清理。删除 Release 不删除其 Git 标签。
- 本机保留最近七次任务对应的加密文件；历史最多 100 条。云端保留与本机下载有效期相互独立。
- 单个任务运行时禁止重复启动或改配置；关掉网页不影响后台任务。服务重启会将中断任务标为失败。每日计划每个北京时间自然日最多触发一次；当日错过执行时间且计划已启用，恢复运行后会补触发一次，不补跑以前日期。

## 部署与权限

服务目录为 /opt/personal-memory。backup 容器以 UID/GID 10001 运行，去除所有 capabilities，根文件系统只读；仅 /backup 和临时目录可写。端口仅绑定 127.0.0.1:8780，通过现有 TLS Nginx 和 BasicAuth 提供接口。写操作额外验证 Origin、会话 cookie 和 CSRF。

配置快照由部署人员维护；每次更改 .env、compose.yaml 或 Nginx location 后同步：

```sh
cd /opt/personal-memory
install -d -m 700 -o 10001 -g 10001 backup-config backup-state
install -m 600 -o 10001 -g 10001 .env backup-config/memory.env
install -m 600 -o 10001 -g 10001 compose.yaml backup-config/compose.yaml
install -m 600 -o 10001 -g 10001 nginx-memory.locations.conf backup-config/nginx-memory.locations.conf
docker compose build backup planner viewer
docker compose up -d --no-build planner backup viewer
nginx -t && systemctl reload nginx
```

先将 Nginx location 源文件安装到既有 TLS server 的 include 路径，再检查并 reload。不要将这些 location 加入未加密的公网 server。backup-config、backup-state 和 .env 必须排除 Git 和 Docker build context。

planner 在可写数据库目录保持一个只读 SQL 连接，使空闲 WAL 数据库的辅助文件仍可被只读挂载的 backup 读取。该连接不持有读事务，不阻塞 checkpoint。backup 的启动依赖 planner 健康；备份源 /state 始终只读挂载。

## 离线恢复

从页面下载加密备份、对应的恢复私钥和离线恢复工具。用 Python 3.10+ 和 cryptography 在可信本机运行：

```sh
python -m pip install cryptography
python restore_backup.py --key recovery.pem --input backup.mbackup --output recovered.tar.gz
```

输出必须为不存在的新文件。认证或私钥错误时不会交付可用明文输出。先检查归档清单，在隔离的新目录解压并检查数据库完整性及记录；配置文件包含密钥，不要公开。

生产恢复应手工执行：先保留当前一致性备份，停止 memory、planner、viewer、backup 全部读写服务，再恢复所选数据库和资源。不要把旧 -wal/-shm 与恢复的数据库混用。核对配置和文件 UID/GID/权限后启动服务并验证，失败时恢复先前快照。页面没有直接覆盖生产数据的按钮，restore_backup.py 仅解密归档，不自动替换线上文件。

## 本次上线与回滚

上线前的一致性数据库副本：
state/backups/before-dashboard-backup-20261016T154837Z.db。

原 compose 和 Nginx include 已分别保留为 compose.before-dashboard-backup.yaml、
/etc/nginx/personal-memory.locations.before-dashboard-backup.conf。旧镜像标记：
personal-memory-viewer:before-dashboard-backup、personal-memory-planner:before-dashboard-backup。
回滚时停止 backup、恢复原 compose/Nginx include，并为 viewer/planner 选择上述旧镜像后重建容器；nginx -t 通过再 reload。无需回退生产数据库：本功能没有修改档案或计划的数据结构/内容。

