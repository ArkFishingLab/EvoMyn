# 统一能力商城验证

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

用户最终确认：统一能力商城，不设开源和自研分区；所有包标明来源。保留“我的能力”管理已安装功能。

本轮实现：

- 商城：统一卡片、搜索、详情、作者/来源/版本/许可、配置说明和官方目录链接。
- 我的能力：持久开关、来源、工具列表、详情、运行状态和调用记录。
- 首个第三方服务：固定 PyPI `mcp-server-time==2026.10.10`，MIT，官方社区来源。
- 实际后台安装到独立 venv，协议探测通过后发布安装回执；默认关闭，再手动启用。
- SDK1时间服务通过SDK2 stdio适配层调用，独立cwd和安全继承环境，无个人库/云端密钥环境传递。
- 固定允许的安装包和操作；同源session/CSRF、安装任务与启停互斥、超时、失败回执、可移除与重装。

验证证据：

- 30项 `test_mcp*.py` 通过；4项桥接回归通过；计划网页回归、商城JS语法检查通过。
- 实际从商城点击安装，界面显示安装进度，真实时间查询通过后变为已安装。
- 实际从我的能力点击开启；小智云端发布20个工具。
- 对只加载时间适配器的临时stdio服务器完成真实协议调用：北京时间正确，东京09:00转换为上海08:00。
- 实测 `remove -> install -> enable`：工具20→18→20，原2条记忆、3条计划完全一致。
- 时间调用结束后未留存 `mcp_server_time` 进程；没有往生产调用历史插入模拟记录。
- 搜索、详情弹窗、390px窄屏检查完成，临时视口已恢复。
- 独立审查发现移除后未验证MCP重启状态；新增失败回归并修复，审查复核通过。

最终状态：三个包均已安装开启，MCP正常连接，20个工具。精选目录当前3项，外部官方目录仅作为浏览入口；
未实现任意包自动适配或整个Registry的一键导入。
