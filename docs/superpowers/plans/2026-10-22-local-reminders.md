# Local reminders and editable memory categories

> **For agentic workers:** Use subagent-driven-development for desktop and firmware implementation, then spec and quality review. All tests use temporary state.

**Goal:** Keep reminders local to ESP, retire automatic completion ingestion from the desktop product, and allow changing a memory's category without losing its identity or attachments.

**Architecture:** Desktop no longer launches a completion receiver or exposes pairing/sync controls. ESP completion persists locally without consuming a bounded upload queue; old queued state remains readable and must never block completion. Existing archived records and credentials are preserved. Explicit voice recording continues through existing MCP tools, with the PC online.

**Tech stack:** Electron, Python/SQLite, browser JavaScript, ESP C++/NVS.

## Tasks

- [x] Desktop: in `desktop/backend/service.py`, `desktop/main.cjs`, `desktop/security.cjs`, and `desktop/ui/`, remove device-sync product controls and service lifecycle. Replace lifecycle tests with an upgrade fixture whose saved enabled pairing must not open a listener, while the dashboard and MCP still work. Reject obsolete enable commands. Preserve stored pairing and records. Remove obsolete packaged smoke assertions.
- [x] Firmware: inspect local planner, completion persistence and `round_services` startup; add host regression completing more than 16 events with no PC and loading a legacy full queue. Remove automatic completion queue creation/upload while preserving task completion durability, recurring occurrences, request replay and OTA. Update board documentation. No hardware flashing without authorization.
- [x] Memory editor: add regression assertions for category in update payload, update/default/custom category handling, stale-revision rejection, SQL category filtering, history and attachment preservation. Allow category in viewer and store updates; update SQL category alongside payload. Enable selector and retain attachment access with the existing resource-root restriction.
- [x] Documentation: replace automatic completion claims in root/module/desktop READMEs, architecture and workflow illustration with local completion and explicit voice recording. Mark compatibility utilities as legacy rather than a supported default flow.
- [x] Verification: run affected Python, JS and firmware host tests, repository checks, independent spec and quality reviews. Stage and build desktop installer; verify packaged smoke against temporary profile. Report firmware source versus installed hardware separately.

## Verification commands

```powershell
./artifacts/local-memory-mcp/.venv/Scripts/python.exe -X utf8 -m unittest discover -s server/personal-memory/tests
./artifacts/local-memory-mcp/.venv/Scripts/python.exe -X utf8 -m unittest discover -s server/personal-memory/viewer/tests
./artifacts/local-memory-mcp/.venv/Scripts/python.exe -X utf8 -m unittest discover -s desktop/tests
node --test server/personal-memory/viewer/tests/*.test.mjs desktop/tests/*.test.cjs
python tools/run_xiaozhi_host_tests.py
python tools/audit_repository.py
```
