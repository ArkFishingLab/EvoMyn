# Warm Graphite round firmware implementation plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

> **For agentic workers:** Use subagent-driven-development for the independent PMIC task and review; execute display integration in this session.

**Goal:** Reproduce the approved localhost:18766 circular interface in native LVGL, flash the device, and add PWR short-press screen toggle with hardware long-press power control.

**Architecture:** Preserve the working board, Wi-Fi and activation implementation. Replace board-local display composition with the approved 466px geometry, exact colors and SVG icons, and sized Chinese/numeric fonts. Read real application state, Wi-Fi, battery and activation data. PWR handling stays board-local and separate from automatic dimming.

**Tech Stack:** ESP-IDF 6.0.2, LVGL 9, AXP2101, CO5300, native C++ host tests.

## Tasks

- [x] Preserve current app/source snapshot; inspect approved HTML and board constraints.
- [x] Add failing layout/state tests for round safe regions, visual geometry, real chat state and PMIC screen toggle behavior.
- [x] Generate board-local fonts/icons from the approved design; reproduce home, chat, settings, Wi-Fi, password and activation pages with real data.
- [x] Implement verified PMIC key polling and manual display off/on, retaining saved brightness and hardware long press.
- [x] Run host tests and format checks; compile the actual board in the ASCII build directory and check OTA partition size.
- [x] Review behavior and source, fix significant findings, preserve app artifact and app-only flash if USB available.
- [x] Capture boot logs; verify device identity, no panic and key IRQ behavior. Ask for physical screen/key validation only where necessary.

## Verification details

Layout tests cover bounds of interactive controls inside a radius219 safe circle and compare approved positions: home voice(174,193,118,118), settings(159,358,148,46), title(133,77,200,44), settings rows(87,154,292,57)/(87,211,292,57), slider labels and 256px tracks. Chat visual/state must map actual Listening/Speaking/Connecting/Idle rather than preview demonstration content. Existing Wi-Fi credential and activation tests must remain green. Never erase NVS or overwrite the original backup. Keep UI and PMIC changes board-local. A generic Application::EndConversation operation additionally cancels connection work, resets playback and closes the channel; late TTS/STT callbacks reject closed channels.

The workspace is an existing unborn codex/chinese-round-ui branch with untracked project contents; preserve it and the existing ASCII build copy rather than creating an empty Git worktree. User explicitly authorized implementation and flashing; no additional execution-choice checkpoint is needed.

## Result

App-only COM3 flash verified SHA256, 3,237,136 bytes with 23% OTA space free. Native LVGL framebuffer renders all six pages. Real serial logs captured PWR short press screen off then screen on; no panic during capture. Physical long press and visual confirmation are recorded separately from software checks.

User confirmed: new interface normal, short PWR off/on normal, settings opens normally. Long-hold on/off configured and policy-tested; physical confirmation not yet received.
