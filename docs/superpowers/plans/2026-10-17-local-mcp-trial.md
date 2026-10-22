# Local PC MCP trial deployment

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** Stop the server's Xiaozhi MCP bridge and connect an independent Windows deployment to the same endpoint.

**Architecture:** Keep the server database and other services intact. Use an online SQLite snapshot and a private endpoint copy in the ignored local runtime directory. Use a dedicated Python environment and a copied model cache; do not modify the existing desktop archive. During this trial, device reminder delivery remains on the server and must not be falsely confirmed by the local copy.

**Tech stack:** Windows, Python 3.11, existing pinned Mnemosyne/MCP dependencies, outbound WebSocket bridge.

- [x] Inspect local runtime and existing deployment; install pinned dependencies in `artifacts/local-memory-mcp/.venv`.
- [x] Stop only the server `memory` service; verify its container is exited.
- [x] Make a consistent server database snapshot and download configuration without printing credentials.
- [x] Copy application/model files into the isolated runtime and give the trial planner a separate device identity, so copied acknowledgments cannot claim device delivery.
- [x] Run disposable-database archive and planner MCP smoke checks; query production-copy status without adding test records.
- [x] Start the local bridge hidden, verify cloud initialization and discovery of all 18 tools, and confirm the server bridge remains stopped.
- [x] Provide local start/stop/status commands and report reminder-delivery and server-viewer limitations explicitly.

The repository has no commits and the existing project is untracked. No worktree or commit is needed for this deployment-only trial. The runtime and all secrets stay under the existing ignored `artifacts/` directory. The user's deployment request authorizes execution in this chat without a separate plan approval.

Verified: SQLite snapshot and local quick_check passed; two archive records and two plans retained. Actual MCP stdio archive CRUD/history/semantic recall and planner idempotency/one-off/recurring completion passed in disposable databases. Cloud initialization and 18-tool publication passed after both initial launch and an actual stop/start. Server memory container remains exited; other server services remain healthy. Existing desktop archive was not changed. Physical voice invocation remains a separate acceptance step.
