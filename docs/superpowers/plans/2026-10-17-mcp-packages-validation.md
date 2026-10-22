# MCP 功能包开关验证

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

本轮需求：按大功能提供整组开关；说明现有开源目录、管理系统和便携包的复用方式。

实现：`vendor/mcp_packages.py` 固定记忆档案/计划提醒两组，每组9个工具；原子持久化配置。
`mcp_pipe.py` 在工具发现时过滤关闭组，并拦截旧云端工具列表中缓存的调用。
`mcp_admin.py` 沿用同源会话和 CSRF 检查，切换运行中功能时重连云端；停止时只保存配置。
`vendor/mcp_admin_web/` 按组显示开关和可折叠的工具清单，保留现有克制配色及字体。
关闭不删除记录、不取消圆盘已有提醒。本轮不实现第三方安装器。

验证结果：

- 21项管理、协议元数据和功能包单测通过，4项桥接回归通过，JS语法检查通过。
- 实测云端工具列表：记忆开启/计划关闭为9个；两个包关闭为0个；恢复后18个。
- 两条档案、三条计划跨开关操作保持一致，出发提醒仍有真实设备缓存回执。
- 实际点击页面计划开关，关闭后显示9个工具，恢复后18个；两包最终均开启。
- 桌面与390px视口检查完成，视口已恢复。
- 独立代码审查发现同目标重试不能刷新云端的问题；新增失败回归并修复，审查复核通过。
- 调用日志未插入模拟生产记录。

现成方案调查基于官方文档：MCP Registry（开源目录/API）、MCPHub（自托管网关与控制台）、
Smithery（目录及开源CLI）、MCPB（可移植服务包格式及安装工具链）。它们解决不同环节，
小智接入仍需通过桥接验证传输、运行依赖和工具兼容性。
