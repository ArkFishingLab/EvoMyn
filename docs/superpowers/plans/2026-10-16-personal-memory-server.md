# Personal memory MCP deployment plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** Deploy an independent empty Mnemosyne personal archive on 203.0.113.10 and connect it to the user's Xiaozhi MCP endpoint.

**Architecture:** Reuse the three existing archive Python files without changing the desktop project. Run the official pinned stdio/WebSocket bridge in a dedicated Docker Compose project at /opt/personal-memory. Keep SQLite, backups, model cache and endpoint credentials outside the image. No public inbound port is required. Existing Evodo services remain separate.

**Tech Stack:** Debian Bookworm, Python 3.11, Mnemosyne 3.15.1, MCP 2.3.0, multilingual MiniLM, Docker Compose; 78/mcp-calculator bridge commit c537f71d61fd73b47d6c8955b5df6d3721acf4e4.

- [x] Package the source files, pinned bridge and model cache only; exclude desktop records, logs and secrets. Record hashes.
- [x] Add Docker build/Compose configuration with a non-root runtime, a private persistent database, bounded resources and automatic restart. Place the endpoint in a mode-0600 server file.
- [x] Build on the server using an already cached Debian base if Docker Hub is unavailable; install Python in the container, leaving system Python unchanged.
- [x] Run actual stdio tool discovery, record/update/list/history and semantic retrieval against a disposable temporary database. Confirm the production database starts empty.
- [x] Start the bridge, verify Xiaozhi connection and tool discovery, inspect resource use and confirm existing containers remain healthy.
- [x] Document operation, backups, endpoint replacement and the remaining physical voice test. Request independent code/config review and resolve material findings.

User confirmed: create a new empty server database and preserve the desktop database. Server deployment and endpoint connection are authorized. Never put credentials in this plan or source control.

Validation so far: container build passed, actual stdio smoke passed all nine-tool discovery and record/update/list/history/local semantic recall in a disposable database. Bridge EOF reconnect regression reproduced red, fixed, and independently reviewed green. Root-owned endpoint file is mode 0600; state/models belong to UID/GID 10001.

Server verification: cloud WebSocket connected, initialize and tools/list received, nine tools published. Production archive_status reports records=0 and pending_index=0. Existing Evodo voice/PostgreSQL remain healthy, control plane remains up. Docker boot is enabled. Cold semantic test cgroup peak=749,834,240 bytes, below configured 805,306,368-byte limit; production idle measurement=122.3 MiB. Endpoint file mode=0600.

Restart verification passed: cloud initialize/tool discovery completed again, production record and pending-index counts remain zero. Remaining acceptance: the user speaks an actual memory request through the physical device; this was not simulated as a completed voice test.
