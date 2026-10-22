> 历史 PC 提醒协议：当前圆盘以本地 NVS 为准，本文件仅供兼容维护，不是当前部署步骤。

# Planner service

PlannerStore is independent of Mnemosyne and imports only the Python standard library. It creates `planner_*` tables in the existing `/state/data/mnemosyne.db`. Archive tables, five categories and existing records remain unchanged. No production example entries are created. Links reference real `personal_archive_records.id` with SQLite foreign keys and explicit validation. Keep the existing state mount writable by UID 10001; archive viewer keeps its read-only mount.

## Deploy

Preserve `.env`, especially the existing MCP endpoint. Append these private settings (replace examples before start):

```dotenv
PLANNER_DEVICE_ID=02:00:00:00:00:01
PLANNER_DEVICE_TOKEN=<64 random hex characters, generated with secrets.token_hex(32)>
PLANNER_ALLOWED_HOSTS=localhost,127.0.0.1,<existing TLS hostname>
```

The device receives this token through its private provisioning/build settings. Never add it to the webpage, public repository, logs, or browser local storage. Memory MCP does not need device token access; it reads durable ACK state from SQLite.

```sh
docker compose build memory viewer planner
docker compose up -d memory viewer planner
```

Install `nginx-memory.locations.conf` inside the existing **TLS** server block, run `nginx -t`, then reload. `/memory/planner/` uses the same BasicAuth file as the read-only archive. Device `wss://<hostname>/planner/ws` uses its bearer token and exact Device-Id, without BasicAuth. Ports 8769 and 8770 are bound to host loopback only. Planner image loads no embedding model; its root filesystem is read-only and only state/tmp are writable. The old memory endpoint and `.env` values must not be replaced. Restarting memory publishes nine new planner MCP tools.

## Browser API (BasicAuth at Nginx)

Paths below are relative to `/memory/planner/`:

- `GET api/session`: session HttpOnly/Secure/SameSite cookie and CSRF token, expires in eight hours.
- `GET api/context`: actual current UTC seconds, UTC datetime, local date and Asia/Shanghai timezone.
- `GET api/tasks`: complete task list, including completed and cancelled history status.
- `GET api/archive-choices`: read-only existing archive IDs and titles only, without body/attachment/private metadata. The editor supports multi-selection and removing links; server-side FK validation rejects nonexistent IDs. All labels use textContent. The browser search filters title/body locally.
- `GET api/delivery?task_id=...`: saved/device_scheduled and current occurrence ID.
- `POST api/command`: JSON; requires same Origin+Host, cookie and `X-CSRF-Token`. Create body `{"op":"create","title":"...","request_id":"unique-id","kind":"task","due_at":"2026-10-20T09:00:00+08:00","repeat":"none","remind":true}`. This datetime illustrates syntax only; choose user-provided time after fetching context. Update body `{"op":"update","task_id":"...","changes":{"title":"..."},"expected_revision":1,"request_id":"..."}`. Complete/cancel use `op`, task_id, expected_revision, request_id. Snooze additionally requires occurrence_id and optional seconds.

Create defaults to `remind=false`, including dated tasks: a deadline is not reminder authorization. `due_at` is the deadline; `start_at`/`end_at` are independent event times; `remind_at` is an independent alarm time (e.g. 15:00 meeting with 14:50 reminder). All persist as UTC seconds. Only explicit `remind=true` enables occurrences, anchored at remind_at, otherwise start_at, otherwise due_at. Existing databases gain these nullable columns via idempotent migration without editing old records. The device task's due_at display uses start_at then due_at; reminder.at always uses the actual alarm anchor. Title maximum is 384 UTF-8 bytes. Server body maximum 32768 bytes. The device receives body prefix maximum 768 bytes. The browser uses textContent for user text. No browser API can delete history. Session GET/read requests rely on Nginx BasicAuth; never expose the planner HTTP port publicly.

## MCP tools

`planner_get_context`, `planner_create`, `planner_list`, `planner_get`, `planner_delivery`, `planner_update`, `planner_complete`, `planner_cancel`, `planner_snooze`. All mutations require unique request IDs; retry with identical arguments uses the same ID and returns the original task/action. Reading delivery is dynamic: `saved=true` is never confused with actual scheduling. Task changes require expected_revision. `wait_ms` optionally waits at most 3000 ms for a real matching ACK. Completing a repeat task requires its real occurrence_id and completes only that instance, preserving task pending status, task revision and future occurrences. Explicit cancel or update(status=completed) ends the series. Quiet repeating tasks also have server-side completable instances without producing device alarms; browser/MCP uses delivery.current_occurrence_id. `planner_list` date filters use the original start_at→due_at→remind_at; clients expand daily/weekly rules for a selected calendar day (the supplied browser does this).

Delivery is read in one SQLite transaction: task revision, generated snapshot and occurrence ACK cannot come from different committed versions. `next_occurrence_id`/`next_occurrence` identify the next pending instance. `recent_fired_occurrence_id` identifies the most recently fired instance within seven days at the current task revision, excluding instances subsequently dismissed/snoozed. `current_occurrence_id`/`current_occurrence` prefer that recent fired instance; repeating tasks otherwise select the local calendar day's unfinished instance or the nearest earlier unfinished occurrence, independently of the device's five-minute alarm window. `current_occurrence_date` reports the plan's calendar date (event start/deadline day even when its alarm was on the previous day). Optional chosen_date=YYYY-MM-DD resolves exactly that rule instance, including historical dates; completed/non-rule days return no current instance and never substitute tomorrow. Browser day view passes its selected date. List view confirms the returned exact instance date before completion. When a user asks to snooze the alarm that just rang, use current/recent_fired, never substitute tomorrow's next repeat. Legacy `occurrence_id` and `device_scheduled` retain pending-instance/actual-ACK semantics; a fired instance remains actionable without claiming it is pending and scheduled. `revision` reports the coherent global snapshot revision. Occurrence action timestamps are added by an idempotent nullable-column migration.

## Device protocol

Handshake `/planner/ws`: `Authorization: Bearer <token>`, `Device-Id: 02:00:00:00:00:01`. Optional browser Origin must be HTTPS and an allowed hostname. Reject invalid handshake, binary/oversized JSON and unsupported commands. HTTP and WebSocket input is limited to64KiB and32 structural nesting levels, checked before the recursive JSON decoder; brackets in string values do not consume structural depth. HTTP rejects excessive depth with400; WebSocket closes invalid messages with1008 and remains available for subsequent connections. WebSocket ping interval/timeout is20 seconds; database polling at most one second. Server emits only snapshot and result messages, result before updated snapshot.

Snapshot shape:
```json
{"type":"snapshot","revision":8,"server_time":1792166400,"timezone":"Asia/Shanghai","tasks":[{"id":"plan-...","title":"...","body":"...","kind":"task","status":"pending","revision":1,"repeat":"none","due_at":1792167000}],"reminders":[{"id":"plan-...:1:1792167000","task_id":"plan-...","task_revision":1,"title":"...","at":1792167000}],"truncated":false}
```

Full replacement, pending tasks only: max32 tasks, max64 reminders, next seven days and at least now−300 seconds, sorted by occurrence time. Reminder IDs reference included task+revision. Byte size ≤65536 including JSON escaping; body is clipped only at UTF-8 boundaries. Overflow remains on server and truncated=true. Cancel/complete removes old local snapshot state. Daily/weekly preserve local wall time. Occurrence IDs are stable per task revision and original recurrence timestamp. Snooze creates `snooze-<op_id>`, preserving the series.

Snapshots also include optional `closed_reminders:[id,...]`, at most128 recent occurrence IDs in completed/dismissed/snoozed states, matching included tasks and their current revisions, acted on within seven days, newest action first. Fired is deliberately excluded because that may be the device's active alarm. Clients remove these IDs from waiting/active alarms; completing one daily/weekly occurrence does not remove the repeating task. Closed IDs participate in the same64KiB budget and truncation flag. This lets browser/MCP actions stop the matching device alarm even when completing an instance leaves task revision unchanged.

After durable device caching: `{"type":"ack","revision":8,"ids":["..."]}`. Server validates IDs against the last sent snapshot for that device+revision. Only the exact current occurrence ACK at the current snapshot revision yields device_scheduled=true. An online socket is insufficient.

Snooze instance IDs have global ownership: two different clients cannot create the same `snooze-<op_id>`. A collision returns a controlled action failure (HTTP400 or WS result ok=false) and rolls back the full transaction, including occurrence status and global revision. Retrying the owning client's identical operation returns its original durable result. Device IDs should use MAC-prefixed 128-bit random operation IDs ≤64 ASCII characters. Browser generates web-UUID request IDs; online browser/MCP snooze operations are additionally derived deterministically as `web-`/`mcp-` plus the first48 SHA256 hex characters of request_id, preserving retries while isolating clients. Device operation IDs and offline occurrence IDs are never rewritten.

Actions: `{"type":"action","op_id":"unique-ascii-max64","action":"snooze","task_id":"...","occurrence_id":"...","expected_revision":1,"seconds":600,"at":1792167600}`. Complete requires no occurrence_id for single/non-repeating tasks; daily/weekly complete requires a real occurrence_id bound to that task+revision and marks only that occurrence completed. Snoozed repeating instances can also be completed without ending the series. Task snapshots now include repeat (none/daily/weekly); offline clients must hide only a completed repeat instance, not the full task. Browser repeat button says 完成本次, reads delivery.current_occurrence_id before submitting complete, and uses 结束系列 for cancellation. Other actions are complete/dismiss/fired/snooze. Optional at is the offline snooze target in UTC seconds, validated within ±7 days of receipt; omit to base seconds on server receipt. A target already in the past remains in the past. Fired/dismiss never complete a task; fired instances can later be snoozed. Responses: `{"type":"result","op_id":"...","ok":true,"revision":9}` or `{"type":"result","op_id":"...","ok":false,"error":"safe text"}`. Successful result revision is saved with idempotency record; retries get the original result. Firmware should keep local action overlays until snapshot revision reaches this value.

## Verify

```sh
python -m unittest discover -s tests -p 'test_planner*.py'
python -m unittest discover -s viewer/tests
node tests/test_planner_web.cjs
```

Automated tests use temporary DBs and no production data/model. Deployment smoke should check HTTP status through TLS with BasicAuth, 403 for invalid device credentials, then authenticated snapshot→ACK→delivery=true→action→result+new snapshot. Real-device acceptance may create explicitly labeled temporary reminders within the user's authorized test scope; cancel them, verify device removal, and clean up only their exact recorded IDs while preserving archive data. The image requires websockets15.0.1; store/MCP tests can run without Mnemosyne installed. Recurrence supported only daily/weekly. Overdue pending tasks remain in server/browser history but reminders older than five minutes are excluded from device snapshots; firmware applies missed-reminder behavior to offline cached instances. Existing ACKs become conservatively false after any global revision change until device reconfirms the full snapshot.

## Occurrence state and web retries

Device actions also accept `cancel` with task_id and expected_revision, without an occurrence_id.
This cancels the whole pending task/series, increments its revision and keeps history. Idempotent
retries return the original result; a stale revision or non-pending task is rejected. Device outbox
persists cancellation and suppresses all matching local alarms until the accepted snapshot arrives.

Completed is an absorbing state. Late fired/dismiss receipts for a completed instance return successful no-ops, without advancing global revision; completed cannot be snoozed. Fired also cannot regress dismissed/snoozed states. An explicit new snooze from fired/dismissed/snoozed is allowed. Nullable parent_occurrence_id links new snooze aliases to their source. Completing a base instance or any of its snooze aliases completes that whole original-occurrence family, closes its waiting/active alarms, and leaves every other daily/weekly instance unchanged. Existing pre-migration snoozes without a stored parent remain independent because no relationship is invented.

Browser write attempts are held only in session RAM. An unconfirmed identical form payload retries the same request_id; changing its payload creates a new ID, and opening an explicit new draft resets the old attempt. Repeat completion also retains the originally resolved occurrence_id through a response-loss retry, so it cannot advance to another day. Pending buttons prevent concurrent submissions. No device token or request state is stored in browser localStorage.
