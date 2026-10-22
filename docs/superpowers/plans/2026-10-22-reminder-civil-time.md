# Reminder civil-time correction

**Evidence:** Read-only diagnostics on firmware 2.5.7 show the device UTC clock within two seconds of PC, while stored reminder deadlines do not match the requested civil time. Private diagnostic records remain outside public source. The public device tool accepts an integer UTC epoch directly; no civil-time conversion exists at that boundary. These wrong stored times cannot be fixed by changing display offsets. The original cloud tool arguments were not captured, so speech recognition and model interpretation still require hardware acceptance.

**Goal:** Eliminate model epoch arithmetic at the scheduling boundary. Require explicit Beijing `due_local` (`YYYY-MM-DD HH:MM`, empty for no reminder), parse and validate on device, return resolved civil time in receipts/listing, and use the same fixed Beijing formatting in reminder UI.

- [x] Add failing native tests for 13:30, midnight, calendar/leap-day bounds, malformed/epoch input, and process-TZ independence.
- [x] Implement bounded board-local civil-time helper and wire create/update, receipts/context/list/UI. Existing NVS remains UTC and is not migrated or reinterpreted. Required input prevents an old epoch-only call silently creating an undated item.
- [x] Verify host tests and full ESP32-S3 build; update source export allowlist and board docs. Host suite: 127 tests, 2 skipped; ESP-IDF 6.0.2 board build passed.
- [x] Prepare an offline OTA 2.5.8 package after verification.
- [ ] Publish to the active local OTA source with authorization; user confirms device installation and verifies a real voice reminder. Never change existing reminders or inject test reminders into physical hardware.

Desktop automatic OTA work remains in the working tree and is not discarded. Device reminder diagnosis takes priority; no USB flashing.
