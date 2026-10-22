# Personal MCP One-Click Distribution Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Deliver a clean, shareable Windows-first MCP/dashboard package with standard stdio client support and optional round-device sources.

**Architecture:** Reuse the existing server and viewer, with a portable runtime root, generated local configuration, a supervised launcher and a small loopback onboarding page. A source-allowlist exporter creates a fresh public distribution, never copying the current runtime, credentials, database, models or Microsoft font derivatives. Xiaozhi cloud is optional; Codex/Claude Code use the same archive through stdio.

**Tech Stack:** Python 3.11+, PowerShell/CMD bootstrap, existing MCP 2.3 SDK, dotenv, unittest, local HTTP/CSRF controls, ZIP manifests, ESP-IDF optional sources.

Work in place: the repository has no HEAD and all existing work is uncommitted. Do not create commits, push repositories, erase state, or replace the running private configuration. Use separate temporary runtime directories for acceptance.

### 1. Portable launcher and lifecycle

- [x] Test config creation without overwriting existing env/data, standard stdio without cloud credentials, duplicate start reuse, occupied ports, and guarded stop of owned processes only.
- [x] Add `server/personal-memory/local/launcher.py` with `start`, `stop`, `status`, `stdio`, `configure`, `client-config` commands and injectable runtime root for tests.
- [x] Add Windows double-click Start/Stop/Configure entries and PowerShell bootstrap, installing Python 3.11 dependencies in a local venv once, logging failures and opening the dashboard only after health readiness.
- [x] Add a current-workspace shortcut that uses the already running private runtime; never create a second cloud connection or overwrite it.

### 2. New-user onboarding and client interoperability

- [x] Make viewer/management launch with an empty database and no Xiaozhi token, defaulting to device-owned reminders and disabling the optional LAN gateway until configured.
- [x] Provide a loopback configuration page for optional cloud endpoint, saving without returning/logging credentials, with same-origin and CSRF protections.
- [x] Generate Codex TOML and Claude Code/standard MCP JSON with absolute executable/script paths and a shared local data directory; no token in generated client files.
- [x] Verify actual MCP initialize/tools/list/archive status through stdio in a fresh runtime and that dashboard reads the same database.

### 3. Public sources, licences and distribution

- [x] Add a deterministic allowlist exporter and tests proving private headers, env files, databases, state/logs, generated Windows font data, caches and arbitrary additions cannot enter a release.
- [x] Include the PC server, viewer source, launcher, tests, README, dependency pins, MIT licence and upstream notices.
- [x] Include optional firmware sources and an open-font regeneration path; do not redistribute Microsoft YaHei/Bahnschrift subsets or private firmware images.
- [x] Create a source ZIP plus SHA-256/file manifest and an audit result. No GitHub repository is published in this task.

### 4. Acceptance and handoff

- [x] Test a fresh extracted package in a path with spaces/Chinese text, including first-run, repeated Start, dashboard/browser opening, stdio clients, Stop and restart.
- [x] Run focused launcher/export/onboarding tests and the existing MCP/device/viewer checks affected by the changes.
- [x] Independently review scope and process/config isolation; fix important findings before marking complete.
- [x] Deliver double-click entry and clean ZIP paths, supported OS/runtime requirements, client connection steps and remaining hardware build limitations.

Evidence and remaining platform/hardware limits: `docs/open-source-package-20261021.md`.
