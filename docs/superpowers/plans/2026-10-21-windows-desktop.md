# Windows Desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Work in the existing unborn `codex/chinese-round-ui` checkout; no Git commit, worktree creation, public release, firmware flash or personal database migration is authorized by this task.

**Goal:** Deliver a Windows installer that contains the archive dashboard, a real MCP master switch, independent Xiaozhi switch, tray lifecycle and verified in-app updates.

**Architecture:** Electron owns a Python service supervisor through private JSON-line pipes. The dashboard stays available while the master switch stops the central MCP execution worker and cloud bridge. Codex/Claude stdio adapters forward to the owned central worker and cannot execute tools independently. Application code is installed separately from `%LOCALAPPDATA%/PersonalMemory` data. Updates use an Ed25519-pinned signed manifest and verified installer bytes; no fictional production feed is embedded.

**Tech Stack:** Electron 45.0.0, electron-builder 26.15.3 / NSIS x64 per-user installer, existing pinned Python 3.11 archive dependencies and portable CPython, Node crypto/https, Python unittest and Node test runner.

## Contracts

`desktop/backend/service.py --app-dir PATH --data-root PATH` reads one JSON command per stdin line and writes one response per stdout line; all diagnostics go to stderr. Requests are `{id,command,...}` and responses `{id,ok,result}` or `{id,ok:false,error}`. Supported commands are `status`, `start-mcp`, `stop-mcp`, `set-cloud` (`enabled:bool`), `save-endpoint` (`endpoint:wss-string`), `client-config` (`format:json|toml`), and `shutdown`.

Status contains `ready`, `mcp_enabled`, `cloud_enabled`, `cloud_configured`, `cloud_connected`, `dashboard_url`, `setup_url`, `capabilities_url`, and `data_root`. No endpoint or credential appears in status or downloaded client configuration. A closed stdin stops owned children. `shutdown` responds before exiting. Defaults: MCP enabled, cloud disabled.

Packaged `backend/application/` follows the reviewed PC release runtime layout (`app/`, `viewer/`, `dashboard.py`, `onboarding.py`, and other approved launcher files). `backend/python/` contains portable Python and pinned dependencies, not an existing virtualenv. The backend sibling scripts remain installed code. Any refreshed user runtime code uses an explicit allowlist and preserves `.env`, settings, package switches, models and database.

## 1. Central service and MCP gate

Files: `desktop/backend/{service.py,host.py,client.py,paths.py}`, `desktop/tests/test_backend*.py`.

- [x] Write isolated tests before implementation: `stop-mcp` leaves dashboard available, kills the execution worker/bridge, blocks an already-connected stdio client from writing; enabling restores service; cloud switch is independent and cannot bypass master off.
- [x] Implement the JSON-line supervisor and persisted boolean preferences, owned process cleanup, loopback bearer-authenticated internal RPC, and official MCP SDK stdio adapter. Keep the archive tools in `server/personal-memory/vendor/` authoritative.
- [x] Test real MCP initialize/list/call, master off/on, cloud error status, EOF shutdown, paths with spaces/Chinese, and data preservation with temporary databases and a local fake cloud server.

Example behavioral assertion:
```python
controller.command('stop-mcp')
assert controller.status()['dashboard_url']
assert not controller.status()['mcp_enabled']
assert existing_client.call_tool('archive_record', payload).is_error
```

## 2. Desktop window, tray and settings

Files: `desktop/{package.json,main.cjs,preload.cjs,service-client.cjs}`, `desktop/ui/{index.html,app.js,style.css}`, `desktop/tests/*.test.cjs`.

- [x] Write IPC/URL/control tests first, then implement a sandboxed local shell and isolated loopback WebContentsView. The embedded page never receives native IPC.
- [x] Implement real MCP/cloud toggles, visible asynchronous status/errors, client config export, data directory, startup preference and update panel. Closing hides to tray; explicit Quit awaits service cleanup; a second launch reveals the existing window.
- [x] Validate exact shell-frame sender for every IPC operation, deny unexpected navigation/popups/permissions, and allow only selected HTTP loopback routes for the dashboard view.

Example API:
```js
window.personalMemory.command('stop-mcp');
window.personalMemory.onStatus(renderStatus);
```

## 3. Signed updater and distributable runtime

Files: `desktop/{updater.cjs,update-trust.json,electron-builder.yml}`, `desktop/scripts/{stage-runtime.py,release-update.cjs}`, `desktop/tests/update*.test.cjs`.

- [x] Test valid/tampered signatures, downgrade rejection, unsupported architecture, invalid URLs, size/hash mismatch, interrupted download and installer path restrictions before updater implementation.
- [x] Implement HTTPS manifest check, consent-based download, progress and verified NSIS handoff. The manifest envelope is `{signed:base64Payload,signature:base64Ed25519Signature}`; signed payload contains version, platform, arch, installer URL, size and SHA-256. Private signing keys remain in ignored `.local/desktop-release/`.
- [x] Stage only reviewed application files and a redistributable Python runtime with pinned packages; exclude `.env`, private fonts, models, databases, logs and development caches. Preserve all required runtime package licences.
- [x] Produce `PersonalMemory-Setup-0.2.0-x64.exe`, SHA-256, and signed update metadata. No public update feed exists until the owner supplies a hosting location; the UI must state that accurately.

## 4. Verification, review and handoff

- [x] Run Node/Python desktop checks and relevant existing archive/setup tests. Have fresh agents review specification compliance then code quality, and resolve material findings.
- [x] Exercise the packaged executable with an isolated user-data directory: embedded dashboard, real MCP call, master off/on, independent cloud state, close-to-tray/reopen, explicit quit and no orphan worker.
- [x] Test the NSIS installer in an isolated installation directory and verify installed startup without system Python. Do not import or mutate the existing personal installation.
- [x] Document build, data location, local client settings, update signing/hosting and unsigned Windows installer limits; update root navigation and CI, retain firmware as its own optional source module.

Evidence before completion; a local updater verification test does not mean an external update server has been published or an Authenticode certificate has been supplied.

