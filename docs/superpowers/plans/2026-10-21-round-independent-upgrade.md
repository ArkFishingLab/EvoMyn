# Round Independent Firmware Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make the round device own reminders, receive custom OTA updates, and remain available with its screen off.

**Architecture:** A durable device worker owns reminders and a completion outbox. A private, authenticated LAN HTTPS gateway stores completed journals and serves a pinned firmware release; Xiaozhi activation and voice networking remain separate. Screen power policy controls the panel without terminating timers or networking.

**Tech Stack:** ESP-IDF 6.0.2, ESP32-S3, C++/cJSON/NVS/LVGL, Python HTTPS/ArchiveStore, native C++ and Python unittest.

Execution is authorized in the current chat. Work in the existing uncommitted workspace; do not commit unrelated source or erase device data.

### 1. Preserve device and existing records

- [x] Identify COM3, ESP32-S3 and 32MB flash.
- [x] Read all flash to the private artifact directory; verify length 33554432 and SHA256.
- [x] Back up the active archive/planner database using SQLite backup before migration.
- [x] Keep old NVS planner/cache while writing the new planner/local_v2 key.

### 2. Authoritative local planner

Files: board `local_planner.*`, `planner_client.*`, `planner_wire.*`, `round_voice_175c.cc`; `tests/native-local-planner*`; `scripts/tests/test_round_local_planner*`.

- [x] First run missing-model tests and observe failure.
- [x] Implement create/query/update/complete/cancel, revisions, durable request receipts, repeat scheduling and bounded outbox.
- [x] Verify only explicit completion creates a journal; full outbox and failed persistence cannot report saved success.
- [x] Queue UI/MCP commands on the model worker; return queued state until the same request ID confirms durable save.
- [x] Migrate cache and pending overlays without inventing past completion journals.
- [x] Import existing PC tasks by stable ID without replacing newer device state.

### 3. Completion gateway and transport

Files: `server/personal-memory/vendor/device_archive.py`, `device_gateway.py`, `local/dashboard.py`; board `round_services.*`; gateway tests.

- [x] Test journal replay, conflicting IDs, save failures, concurrent duplicates, strict auth and bounded input before adding handlers.
- [x] Save journal in ArchiveStore with stable event identity; acknowledge only after durable save, preserving index-pending success.
- [x] Provision an ACL-protected LAN certificate and embed only its public CA and device credential in an ignored private header.
- [x] Upload from a dedicated TLS worker, verify exact receipt, durably dequeue only after ACK.
- [x] Exercise offline completion/reboot/reconnect against an isolated archive before enabling the real library.
- [x] Retire PC planner tools/UI and the project relay after physical migration succeeds; retain the database backup.

### 4. Custom OTA

Files: board `round_update.*`, `round_update_policy.h`, `round_display.*`; fixed-path release provider and publisher under personal-memory; manifest tests.

- [x] First test wrong board, invalid size/hash/path, same version and corrupt input rejection.
- [x] Add authenticated HTTPS manifest and fixed hash-addressed firmware download using the same pinned CA.
- [x] Validate board/partition metadata and image SHA256 before changing boot partition.
- [x] Add settings version, notes, check, explicit install confirmation, progress and reboot state.
- [x] Preserve Wi-Fi/agent/local planner NVS and use existing dual-slot rollback.
- [x] Build a second release and perform a real OTA cycle; separately report any destructive fault tests not performed.

### 5. Screen-off standby

Files: board `round_power.h`, `round_voice_175c.cc`; `scripts/tests/test_round_voice_power.py`.

- [x] First assert no idle shutdown after 5 minutes or 24 hours, plus auto screen-off after 60 seconds.
- [x] Replace idle dim/shutdown with panel off on battery and USB power, preserving physical long-press/low-battery protection.
- [x] Test the short-press handler, reminder wake, and touch-release gating.
- [x] Verify more than 6 minutes of physical standby, wake and reminder execution; report current/temperature measurements only if actually obtained.
- [ ] Manually verify acoustic voice wake, physical long-press/low-battery shutdown, power-cut faults, battery current, temperature and endurance.

### 6. Integration and acceptance

- [x] Run native planner/power/update tests, Python gateway tests, then `tools/run_xiaozhi_host_tests.py`.
- [x] Format touched C++ files, synchronize the ASCII build mirror and build only round-voice-175c.
- [x] Flash application only after validating the complete backup; inspect boot and connectivity privately.
- [x] Use a physical USB diagnostic interface to exercise the same MCP handlers and durable state.
- [x] Record exact firmware versions, application hash/size, test results and hardware gaps in a dated verification document; update README checkboxes honestly.

Final deployed release: **2.5.6**, installed through the production LAN gateway and confirmed healthy on 2026-10-21.
Evidence and hardware limits: `docs/round-local-upgrade-20261021.md`.
