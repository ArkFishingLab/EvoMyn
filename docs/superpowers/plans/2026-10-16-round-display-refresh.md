# Round display refresh and saved Wi-Fi correction

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

User reports correct design but layout too low, poor real-device text/icon quality and corruption on click. Later clarification: glyphs/icons look broken or fuzzy. Initial instruction to avoid flashing was superseded by explicit instruction to fix and flash again, also reuse Wi-Fi passwords.

- [x] Move native and browser content up 12px without moving full-screen backgrounds; dynamic keyboard/waveform placement retains translation.
- [x] Compare upstream Waveshare 1.75 implementation: its 2x2 invalidate-area alignment hook was omitted in the custom display.
- [x] Reproduce with actual LVGL partial refresh: old callback path emits two unaligned transfers after clock/network label updates.
- [x] Restore board-local alignment callback; same regression emits zero unaligned transfers and all six pages render.
- [x] Generate the actual Microsoft YaHei UI face used by approved CSS instead of default Microsoft YaHei in the same TTC.
- [x] Reuse saved credentials for selected networks, retain startup auto-connect, and request a new password only after authentication failure; preserve existing NVS on transient failure.
- [x] Review, build, save distinct artifacts, app-only flash and inspect boot logs; physical quality remains subject to user confirmation.

No lowering of SPI speed, random buffering changes or vendor edits is included without evidence. Original and previously working application backups remain intact.

App-only flash and hash verification passed. Fresh boot initialized CST9217 and connected the saved Wi-Fi automatically, with no panic in 22 seconds. Await user visual confirmation after repeated page changes.
