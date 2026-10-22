# Xiaozhi connection onboarding

**Goal:** Improve optional Xiaozhi onboarding while keeping MCP independently usable by Codex, Claude and other clients. The user corrected the initial cloud-first proposal during implementation.

**Architecture:** The master starts the local MCP service directly and preserves the independent cloud switch. Only an explicit Xiaozhi enable checks its endpoint and opens the native guide if missing; cancel or invalid input never stops existing MCP. Saving connects Xiaozhi and enables the master if needed. Startup never forces a cloud account or guide. The historical HTTP setup page also receives acquisition instructions.

**Scope:** Preserve private configuration/data and the independent cloud stop switch. Do not configure the user's cloud account or publish anything. Build a new 0.2.1 installer and signed offline metadata using the existing trusted key; verify with isolated fixtures.

- [x] Add failing coordinator tests for missing/saved endpoint, independent startup, optional cloud mode, bad/failed saves, and stopped cloud recovery.
- [x] Implement coordinator, shell setup page and exact official-console action. Hide duplicate service lifecycle controls inside the desktop capability view; source launcher keeps its controls.
- [x] Test guide content, IPC boundaries, real isolated Electron setup/cancel/local flow, and local TLS save/connect flow. Verify relevant existing backend/setup tests and source audit.
- [x] Build and verify 0.2.1 installer, sign metadata, refresh source archive and delivery notes.


