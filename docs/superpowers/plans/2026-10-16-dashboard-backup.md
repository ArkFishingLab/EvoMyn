# Dashboard Backup Implementation Plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

> **For agentic workers:** Use subagent-driven-development for independent frontend and backup bundle/GitHub units; root integrates the manager/HTTP/deployment and verifies each boundary. Do not enable real uploads or schedules on behalf of the user.

**Goal:** Embed a working GitHub backup control panel in the existing personal-memory dashboard, with user-entered settings, connection check, manual encrypted backups, opt-in daily scheduling and history.

**Architecture:** Keep the archive viewer and database mounts read-only. Add a separate constrained backup container on loopback8780, routed through existing BasicAuth at /memory/backup/. It reads consistent SQLite snapshots, resources and selected deployment config; writes only its private backup-state. Browser generates an RSA3072 recovery private key and downloads it; server receives only the public PEM. GitHub token is write-only API input, never returned, logged, included in bundles or stored in browser storage. Encrypt compressed bundles using random AES256-GCM per backup with RSA-OAEP-SHA256 wrapped keys. GitHub private repositories only; draft upload/verify/publish; no remote access until explicit UI action or configured enabled schedule. Defaults: disabled,03:00 Asia/Shanghai,30 daily/12 monthly versions. No automatic production restore button.

**Tech Stack:** Python stdlib HTTP/SQLite/threading, packaged cryptography primitives, vanilla JS/WebCrypto, existing CSS shell, Docker/Nginx.

## Contracts and files

- vendor/backup_bundle.py: public_key_fingerprint(pem), create_bundle(state_root,config_root,output,public_pem) -> metadata; encrypted format + offline restore tool. Exclude backup-state/token/model/cache; reject symlink/outside attachments. Actual decrypt/auth and SQLite restore tests with disposable DBs.
- vendor/backup_github.py: GitHubClient(token,repository).check() -> repo info (private required), upload(path,metadata) -> {release_id,url,verified}; prune(daily,monthly) -> count (only marked own releases, after verified new upload). Fixed GitHub hosts, bounded responses, redacted errors, streamed upload, no unsafe credential redirects. Tests stub only transport; assert draft-before-publish/digest/private/retention ownership.
- vendor/backup_manager.py: config/state atomic0600, masked status, one job at a time, persistence and restart recovery, daily Shanghai scheduler opt-in, bounded local history. Inputs repository,token(optional retain),public_key(optional retain),time,enabled,keep_daily,keep_monthly. Snapshot config per job. Backups continue when page closed. Public state: config {repository,time,enabled,keep_daily,keep_monthly,token_configured,key_fingerprint}, running,last_success,next_run,history[{id,created_at,status,size,sha256,url,error,local_available}].
- vendor/backup_server.py: GET /api/session,/api/state,/api/download/<id>,/restore-tool.py; POST /api/config,/api/check,/api/run. JSON64KiB, exact Origin/Host,8h HttpOnly Secure SameSite cookie path/memory/backup/,CSRF for all writes; no plaintext secrets in GET. Safe IDs/files only. UI run/check use saved configuration,run is asynchronous202; config changes/duplicate run while running rejected409. No automatic upload in tests or deploy.
- viewer/static/backup.mjs + backup.css and index.html/personal.mjs integration: sidebar备份管理/#backup, inherited editorial light styling, status/config/key generation/check/manual/upload/history, accessible error/pending states; preserve archive routes and fifteen-second refresh without overwriting unsaved backup form.
- Dockerfile.backup,compose.yaml,nginx-memory.locations.conf: separate backup-state volume,readonly state/config mounts, no Docker socket,loopback8780,capabilities dropped, default disabled. Local authenticated proxy admits only specific backup POST paths with existing same-origin rules.

## Execution

- [x] Write failing tests for encryption+restore, GitHub transport/private/digest/retention, config redaction/scheduling/single-job/HTTP CSRF.
- [x] Implement bundle,GitHub,manager andHTTP; run isolated tests; inspect errors do not expose credentials.
- [x] Implement integrated dashboard and browser crypto recovery download; verify actual page at desktop/mobile widths, settings validation and disabled initial state.
- [x] Run existing viewer/planner tests and new backup tests, JS syntax/behavior checks; no firmware changes.
- [x] Deploy backup+viewer and Nginx route after retaining images/config and consistent DB backup. Verify unauthorized401,CSRF403,masked GET,disabled schedule,no outbound GitHub requests,existing records unchanged.
- [x] Open dashboard#backup through local authenticated proxy, show concrete result and state that user must fill repository/token and save recovery key before enabling.
