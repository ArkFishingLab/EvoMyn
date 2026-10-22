# Round device reliability implementation plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

> **For agentic workers:** Use executing-plans task by task; request a focused code review before flashing.

**Goal:** Correct the round device clock and remove concrete connection/lifecycle problems found in an overall device audit.

**Architecture:** Keep the system clock in UTC and apply the server offset only through the C library timezone. Keep network retry policy board-local, run retry decisions on the existing application poll, and continue using the existing credential/connection worker. Gate explicit network switches during activation/upgrade rather than race protocol initialization. Preserve the verified UI and audio receive configuration.

**Tech stack:** ESP-IDF 6.0.2, C++/LVGL, Python host regressions, COM3 hardware verification.

## 1. Clock
- [x] Reproduce duplicate UTC+8 offset with a host regression using actual OTA time conversion.
- [x] Implement validated UTC milliseconds conversion and POSIX timezone handling; do not add offset to epoch.
- [x] Verify UTC+8 date rollover, negative/half-hour offsets, invalid input and missing timezone behavior.

## 2. Wi-Fi recovery
- [x] Test a pure retry policy for repeated outages, saved boot failure, authentication failure, cancellation and capped backoff.
- [x] Wire retry deadlines to the existing board main-task poll and ConnectSaved worker; never block event/timer tasks or expose passwords.
- [x] Keep manual switches and scanning serialized through current busy gates, cancel retry on new target or success.

## 3. Lifecycle and smoothness audit
- [x] Reject explicit Wi-Fi switches during activation/upgrade, preserving password input when busy. Add actual lifetime guard to queued protocol reset.
- [x] Check redraw/touch, manual screen-off, sleep, settings persistence, TLS and local credential exposure; fix only evidenced problems. Record residual security boundaries.
- [x] Run host suite, native LVGL render checks, formatting, firmware build and focused independent review.
- [x] Save artifacts, app-only flash, verify automatic connection and logged local time against host; document remaining physical checks.

## Evidence / scope
- OTA currently adds timezone_offset to timestamp; custom display also sets CST-8. This applies the same offset twice.
- RoundWifi stops reconnecting after 3 immediate retries and does not retry a saved network absent during boot.
- Main-task ResetProtocol can overlap ActivationTask protocol startup; prevent network switches in that interval.
- Independent review corrected two false positives (Ready is preserved across Offline; Chat has no bottom home bar).
- Review covers firmware/device flows. No server changes, destructive NVS operation, irreversible eFuse changes, or claimed full penetration test.

## Final verification
- 115 host tests: 113 passed, 2 unrelated UBSan checks skipped (runtime unavailable).
- Native rendering: 0 misaligned transfers and 0 transfers for 10 identical code updates (baseline 20).
- Candidate2 app: 3,240,592 bytes; SHA256 e210db75225497e76661c77622725f16a490aed15c2e80deb0789edd4f6d484e. App-only 0x200000 flash hash verified.
- Device connected automatically, entered Idle; Ota log local=2026-10-16 20:38:40 matched host. Exact host receipt timestamp recorded in clock-verification.json.
- Physical long-outage/password-change/weak-signal/long-power-key testing remains outstanding; do not claim exhaustive hardware or security validation.
