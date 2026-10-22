# Planner implementation plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

> **For agentic workers:** Use subagent-driven-development; review spec compliance then code quality before release. Continue within authorized firmware/MCP deployment scope.

**Goal:** Implement homepage-voice planning via Xiaozhi custom MCP, web management, synchronized persistent device reminders and local screen/ringing actions.

**Architecture:** Separate structured planner tables alongside the personal archive. Server adds MCP tools, authenticated device WSS push and a same-origin authenticated planner web page. Board-local firmware client persists bounded snapshots/outbox, schedules locally and reuses existing audio/display through main-task callbacks. No dedicated voice input on planner pages. Preserve the current clock/RX/UI fixes and existing memory records.

**Tech stack:** Python stdlib SQLite/HTTP + existing websockets15, MCP2.3; ESP-IDF6/C++/LVGL; Nginx TLS; Docker.

## Wire contract v1

Endpoint: `wss://203.0.113.10/planner/ws`. Headers `Authorization: Bearer <device-only token>` and `Device-Id: <device-id>`. Secrets provisioned privately, never committed/logged. Device opens outbound connection independent of Xiaozhi MQTT.

Server snapshot (one complete JSON message, <=64 KiB):
```
{"type":"snapshot","revision":1,"server_time":1792154320,"timezone":"Asia/Shanghai",
 "tasks":[{"id":"task-...","title":"...","body":"...","kind":"task","status":"pending","revision":1,"due_at":1792200600}],
 "reminders":[{"id":"occ-...","task_id":"task-...","task_revision":1,"title":"...","at":1792200600}],"truncated":false}
```
All wire times are integer UTC epoch seconds; due_at nullable. Bounds: <=32 device tasks, <=64 reminder instances; IDs<=128 ASCII bytes; title<=384 UTF-8 bytes; device body<=768 bytes. Server exposes next7days and recent due instances (>=now-300), ordered by time. Server retains full records beyond device cache and reports truncation. Every reminder must refer to a snapshot task with matching revision. Full snapshots remove cancelled/old entries.

Device persists snapshot before `{"type":"ack","revision":1,"ids":["occ-..."]}`. Server must never claim device scheduled unless current version AND actual instance ID were acknowledged.

Device outbox message:
```
{"type":"action","op_id":"device-random-...","action":"complete|dismiss|snooze|fired",
 "task_id":"task-...","occurrence_id":"occ-...","expected_revision":1,"seconds":600}
```
Nonrepeating complete only needs task_id and expected_revision; recurring complete also requires its real occurrence_id and only completes that occurrence family; occurrence actions need occurrence_id. Responses `{"type":"result","op_id":"...","ok":true,"revision":N}` or `ok:false,error:<safe text>`. Operations idempotent by op_id, validate task/occurrence/revision and authenticated device. Snooze creates a distinct occurrence. Fired/dismiss never complete a task. State changes push snapshots (server may check SQLite revision every second), heartbeat via WebSocket ping.

Snapshots also carry tasks.repeat and bounded closed_reminders IDs (completed/dismissed/snoozed, not fired), so remote instance completion stops queued and active local alarms. Snooze IDs are exactly snooze-<op_id>; device op IDs are MAC-prefixed 128-bit random values, max64 characters. Successful accepted overlays persist until snapshot revision reaches the result revision.

## Tasks

- [x] Backend TDD: PlannerStore schema/migration, time validation, CRUD/repeat, occurrences, history, idempotency, delivery ACK semantics and archive links. Preserve old archive APIs/DB.
- [x] Server transport/web TDD: authenticated WSS + HTTP planner UI/write API, origin/CSRF/size validation, no token exposed to browser, bound loopback Docker ports. MCP tools + descriptions/context; prompt updates. No real sample records.
- [x] Board model TDD: bounded snapshot validation, due scheduling/clock jump, local fired dedupe, offline complete/dismiss/snooze overlay and outbox ACK; persistence.
- [x] Firmware client: independent WSS worker, private configuration, reconnect/backoff, bounded parse/persist/send, no network or NVS waits in main/audio task.
- [x] Native planner UI: homepage next reminder + list entry, list/detail/alarm, local complete/snooze/dismiss callbacks, reminders volume incl silent. No planner voice-input button. Use native fonts/aligned transfers.
- [x] Power/audio integration: pending reminders inhibit automatic power-off; alarm explicitly wakes screen (never blindly toggles), stops conversation then local bounded repeating chime with audio-thread isolation, completes/stops within timeout and respects separate volume.
- [x] Spec and quality review; run backend tests, host regressions, native renderer, formatting and build.
- [x] Deployment: consistent DB backup, private device credential, retain prior images/config, Nginx route validation/reload, Docker health/MCP tool discovery; preserve existing site.
- [x] App-only flash (0x200000), real device snapshot ACK, temporary reminder/ringing/user confirmation, offline snooze replay and test cleanup. Report physical limits honestly.

## Verification state

Backend deployed; actual MCP stdio 18-tool discovery and planner mutations passed in an isolated database. Cloud published18 tools; production HTTPS/auth/CSRF/read-only archive routes and authenticated WSS checked. Firmware built for ESP32-S3 and app-only flashed/hash verified. Host119 tests ran:117 passed and2 unrelated UBSan checks skipped; local audio queue/chime asset bounds checked separately. Native LVGL render/aligned refresh checks passed.

Hardware acceptance, 2026-10-16 22:33–22:41 Asia/Shanghai: the real device durably acknowledged reminder snapshots. The user confirmed screen-off wake/ringing/stopping and an offline alarm after disabling the hotspot. A completed single task reached the server. Offline snooze replay preserved the device's target22:49:00 (tap22:39:00 +600seconds), rather than moving it ten minutes after reconnection; the device acknowledged this new occurrence at global revision9. All three explicitly labeled test tasks were cancelled/completed then removed, archive rows compared equal before/after, database integrity was ok. Device cached final revision11 with0tasks/0reminders. Evidence: artifacts/planner/hardware-acceptance.json and server state/backups/planner-hardware-20261016.json.

Not physically exercised in this acceptance: a complete spoken create→MCP round trip, alarm interruption during an active voice response, power-loss recovery, battery endurance and prolonged repeated use. Automated tests cover the associated model/queue paths but are not physical confirmation. True power-off cannot ring; offline cold boot needs a valid synchronized clock.
