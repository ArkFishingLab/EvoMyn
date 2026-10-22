# Public firmware pairing and font migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development for implementation and independent spec/quality review.

**Goal:** Publish a credential-free, redistributable ESP firmware that the existing EvoMyn desktop updater can download, with persistent pairing and a recoverable legacy upgrade path.

**Architecture:** Store desktop OTA pairing in one versioned NVS record, independent of the app partition. A private transitional build migrates existing compiled pairing once; the public build reads the same record and accepts explicit physical USB provisioning for fresh devices or legacy devices that skipped migration. Public assets are generated in a clean source export from Noto Sans SC under OFL. No changes to Wi-Fi, XiaoZhi activation, reminder storage or flash layout.

**Tech Stack:** ESP-IDF 6.0.2, C++/NVS, Python provisioning, LVGL font converter, signed GitHub firmware feed.

## Task 1 — Pairing persistence

- [x] Add failing host cases for valid restart, migrate-once, invalid/unknown schema, oversized values, commit failure and preservation of existing pairing.
- [x] Implement bounded versioned NVS configuration and certificate validation; prefer valid NVS over compiled fallback and require durable readback.
- [x] Add physical USB `pairing_status` and `pairing_set`, no secrets in responses, no remote MCP configuration, no automatic reboot.
- [x] Integrate updater without enabling retired archive synchronization; run firmware host suite.
- [x] Complete independent spec and code quality reviews.

## Task 2 — Provisioning and migration

- [x] Supply a USB provisioning helper using explicit port and private desktop configuration, with bounded serial replies and no credential logging; test using fixtures.
- [x] Prepare a private 2.5.9 bridge with open fonts for the existing paired device. Keep it local and separate from public assets.
- [x] Document that old 2.5.7/2.5.8 devices need this migration first, or one physical USB pairing after upgrading. Do not claim automatic migration from a binary that never saved credentials.

## Task 3 — Public build and publication

- [x] Export reviewed source to a fresh ASCII build directory; generate all twelve font assets from licensed Noto Sans SC with provenance and license copies.
- [x] Build public 2.5.10 using the existing board variant, preserving 32 MB flash, 8 MB PSRAM, 4 MB OTA slots and rollback policy.
- [x] Validate ESP descriptor/board marker/size/hash and absence of private credentials; retain font attribution, dependency notices and build provenance in release assets.
- [x] Run repository checks, review diff, commit and push authorized source.
- [x] Publish `firmware-v2.5.10` and signed `firmware-stable/firmware-latest.json` with `--latest=false` so desktop update discovery stays on the desktop release.
- [x] Download the public feed through the actual firmware verifier, import the real public image into an isolated desktop fixture and verify served bytes. Report physical acceptance separately.

## Authorization and boundaries

The user explicitly authorized public firmware implementation and publication. Device flashing, rebooting and changing actual pairing are not part of automated acceptance; prepare concrete migration artifacts and let the user confirm OTA on the device. Preserve the current installed database and runtime configuration. Never publish the private bridge or proprietary font derivatives.

## Verification record

Firmware host suite: 130 tests, 2 skipped (unavailable UBSan runtime). Repository suite: 83 tests, 3 platform/fixture skips; USB helper independently rerun with 17 passing tests after review fixes. Public and private transitional board builds passed ESP-IDF 6.0.2. Native LVGL rendering passed with open fonts, including clock bounds and partial refresh assertions. An isolated authenticated TLS gateway served the exact public image and returned 410 for retired archive upload without creating a database. Physical migration/OTA acceptance remains pending user installation.

Public release source: `752fa5c8f92a8ac99039cbea4e9d54c01f78b917`. Public image: 3,644,192 bytes, SHA-256 `164c58316e9faa4c69e606331a3a573d7043b4ea1e5c213d0c580d6ec8269482`. All seven GitHub version assets matched local sizes and digests before publication. The stable signed feed was published separately; an actual Electron system-network download through `FirmwareUpdater` and the existing Python importer reached `ready` in an isolated profile. Desktop `/releases/latest` remained `v0.2.14`. The private 2.5.9 migration image was prepared through the existing authenticated local desktop OTA service only; it was not published to GitHub or installed on a device.
