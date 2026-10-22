# Desktop Device Completion Sync Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the independent category migration and gateway backend tasks. The primary agent owns desktop UI, integration, deployment and release verification. Tests use temporary data only.

**Goal:** Completed ESP schedules are durably archived into the desktop application's journal, retrying after PC downtime; fresh databases default to Personal, People, Journal, Resources.

**Architecture:** A desktop-owned optional TLS gateway uses the existing device completion protocol and the exact desktop state directory. Its lifecycle is independent of the MCP switch, follows desktop exit/startup, and reports sanitized status. Import an explicitly selected existing paired gateway configuration; preserve device identity, certificate and address so firmware need not change. Persist completion receipts through ArchiveStore and acknowledge only after commit. Existing device NVS outbox retries after outages.

**Tech Stack:** Python supervised process, private configuration/TLS, existing HTTPS gateway, Electron native commands, SQLite category migration.

## Gateway
- [ ] Add isolated tests for credential-safe config import, TLS startup and failures, persistent enable/disable, same desktop database, MCP-off delivery, offline/restart replay and exact-once receipts.
- [ ] Implement desktop/backend/device_sync.py and fixed gateway child role; configure only from selected paired runtime directory or portable pairing JSON. Copy validated cert/key into a private desktop subdirectory; no arbitrary process targets or database paths.
- [ ] Wire supervisor status/import/toggle commands and clean shutdown. Startup or invalid gateway failures must not prevent the memory UI from starting.
- [ ] Show device sync setup, independent toggle, listening/error state and last receipt in application settings. Never display token/private-key material. Explain shared LAN reachability and PC sleep/offline behavior.

## Categories
- [ ] Fresh defaults: background(个人), people(人脉), journal(日志), resource(资料), in that order. Preserve stable IDs.
- [ ] Migrate untouched old defaults once; remove empty untouched event category, retain occupied or customized event as a normal category. Preserve custom names/order, all records/history and backups.
- [ ] Update model fallback and meaningful migration/default tests. Do not edit installed personal DB during testing.

## Delivery
- [ ] Verify existing firmware outbox replay/ACK/restart behavior using host tests; read nested firmware instructions before any edits.
- [ ] Exercise real TLS completion delivery against a temporary desktop service, restart and replay, then confirm the same journal through desktop and MCP.
- [ ] Run affected checks, independent specification and quality reviews, package next Windows release and publish signed update to ArkFishingLab/EvoMyn under existing authorization.
- [ ] If an existing device pairing is available, integrate it without changing credentials and verify actual-device receipts when the device is available; never fake personal completion events or flash without authorization.
