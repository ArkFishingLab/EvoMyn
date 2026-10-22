# Desktop-managed device OTA Implementation Plan

> **For agentic workers:** Use subagent-driven-development for implementation and independent review. Do not flash hardware or publish private firmware.

**Goal:** Opening EvoMyn automatically serves a validated, compatible ESP firmware over the existing paired HTTPS endpoint, independently of MCP; exiting stops it.

**Architecture:** A desktop-owned `device-ota` child serves only authenticated fixed OTA GET routes. It reuses validated legacy pairing without enabling archive ingestion. A private per-user firmware cache survives desktop updates. Settings show firmware version, readiness and actionable configuration errors, with native dialogs for pairing and release import. Firmware matching uses the existing explicit board/project/partition contract and image checks, rather than pretending the desktop and firmware version numbers are interchangeable. No private firmware is bundled into public source or installer.

**Tech Stack:** Electron, Python HTTPS gateway, existing firmware image publisher/provider and Windows owned-process lifecycle.

## Task 1: Backend and lifecycle
- [x] Write failing isolated tests for authenticated OTA-only routes, invalid image rejection, private-cache preservation, missing pairing/release, process startup/exit and MCP independence.
- [x] Add `desktop/backend/device_ota.py`; extend `vendor/device_gateway.py` with explicit OTA-only mode, retaining legacy default behavior.
- [x] Add fixed host role, supervised startup/status/retry/stop and native pipe commands. No new public MCP RPC mutation methods.
- [x] Validate release import before atomic activation; preserve existing cache on failure. Reuse legacy pairing validation, never start its archive receiver.

## Task 2: Native settings and IPC
- [x] Add concise ESP device update section to existing settings; ready/version/errors and same-network guidance.
- [x] Add strict IPC actions with native file/folder selection; renderer never supplies paths, credentials or arbitrary URLs.
- [x] Tests for command allowlist and UI states, including cancel and retry. Retain existing layout and independent MCP control.

## Task 3: Verification and deployment
- [x] Update current documentation and checks; build local 0.2.13 installer.
- [x] Run isolated backend/JS/packaged tests and independent spec/quality review. OTA Python tests: 7 passed; desktop JavaScript tests: 58 passed. Packaged smoke verified OTA startup, MCP independence and clean shutdown with isolated fixtures.
- [ ] Seed this user's private OTA cache with already authorized 2.5.7, replace temporary helper with app ownership, verify authenticated manifest/binary and archive rejection. Do not change personal records or trigger device installation.
- [ ] Report actual verified scope and remaining device-side acceptance. Public release only with applicable authorization; never include private artifacts.
