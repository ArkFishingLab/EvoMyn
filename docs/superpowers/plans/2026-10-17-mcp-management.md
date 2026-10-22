# Local MCP management implementation plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** Add a restrained dashboard page that reports and controls the current local Xiaozhi MCP bridge independently of the archive/planner viewer.

**Architecture:** A loopback-only admin handler behind the existing dashboard serves status, observed tool-call metadata, and fixed start/stop/restart operations. Use the existing verified-PID Windows launcher, with JSON status and live bridge TCP evidence. Add protocol observation that records only lifecycle/tool names/results/timing; never record arguments, response text, endpoints, or credentials. Keep the dashboard/reminder service independent of the MCP process.

**Tech stack:** Python standard-library HTTP/process orchestration, PowerShell process guard, existing WebSocket bridge, shared dashboard CSS and vanilla JS.

- [x] Write and run failing tests for protocol result tracking/redaction and disconnected calls.
- [x] Implement the observer and integrate it with the bridge; rerun bridge regressions.
- [x] Write failing tests for admin status, stale process evidence, fixed commands, same-origin/session/CSRF checks, and HTTP method/body restrictions.
- [x] Implement the admin controller/HTTP handler and update the Windows launch script for fixed actions, restart, JSON status and live connection probing.
- [x] Create the management page and add the navigation entry to archive/planner pages, preserving the neutral type and spacing.
- [x] Copy source modules/static assets to the isolated runtime, back up the wrapper/launcher, and restart only the dashboard and MCP bridge as required.
- [x] Verify real stop/start/restart, dashboard availability during MCP stop, cloud 18-tool publication, preserved records/reminders, and responsive UI. Leave MCP running and the management page visible.

Validation: 14 admin/observer tests and 2 bridge tests pass; planner web regression passes. Real HTTP restart (5.28s), stop (1.16s), start (5.09s) return successfully. Archive records and 3 planner tasks remain identical across the lifecycle operations. Final connection is live with 18 registered tools, no invented tool calls. Independent review identified rotation durability; a separate atomic lifecycle/tool checkpoint now preserves current status, covered by regression tests. The Windows inherited-pipe response hang is also covered by a failing-before/passing-after regression. The management page was inspected at desktop and 390px width and the viewport reset.

Source files: `vendor/mcp_observability.py`, `vendor/mcp_admin.py`, `vendor/mcp_admin_web/*`, `local/manage.ps1`, `local/dashboard.py`; tests in `tests/test_mcp_observability.py` and `tests/test_mcp_admin.py`. No database/schema change is required. No arbitrary server/endpoint editing is in scope. Persist secrets only in the existing private runtime .env. The repository is unborn/untracked, so work in place without creating an empty worktree or commits.
