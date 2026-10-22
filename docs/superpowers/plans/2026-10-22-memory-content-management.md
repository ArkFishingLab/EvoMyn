# Memory Content Management Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the isolated interface task; the main agent owns persistence, API integration and release verification. Do not access the installed personal database.

**Goal:** Let users create, edit and delete memories in the Windows desktop app, while clearly allowing default categories to be renamed and reordered.

**Architecture:** The viewer accepts an explicit ArchiveStore supplied by the local dashboard; standalone/read-only viewers remain read-only. Mutations use same-origin POST, CSRF and optimistic revision checks, persist through ArchiveStore, and index asynchronously. Deletion removes the record/history, unlinks active records and keeps only a minimal tombstone to prevent stale writes or device replay recreating it.

**Tech Stack:** Python HTTP/SQLite, native HTML dialogs and JavaScript modules, Electron packaging.

## Persistence and API

- [x] Add failing tests in `server/personal-memory/tests/test_archive_editing.py` for revision conflicts, deletion, relationship cleanup, deletion replay and stale indexing. Use `isolated_store` from existing device tests.
- [x] Extend `vendor/archive_store.py` with deferred indexing, safe deletion and tombstone lookup; update `vendor/device_archive.py` to recognize deleted completion receipts.
- [x] Add writable API tests using a temporary real ArchiveStore; keep the existing standalone read-only HTTP tests. Contract: `GET /api/editor` returns `{enabled, csrf}`; `POST /api/records` supports `{action:'create',record}`, `{action:'update',id,revision,changes}` and `{action:'delete',id,revision}`. Success returns `{record}` or `{deleted:id}`. Stale revision returns 409.
- [x] Implement explicit writable opt-in in `viewer/server.py`, wire `record_store=store` from `local/dashboard.py`, preserve validation and raw record history, reject file paths and unknown editor fields, and expose only safe record fields to browsers.

## Interface

- [x] Add an accessible new-memory dialog and detail edit/delete actions; edit title, body, date range and tags, select a category when creating, preserve metadata and associations when editing. Editing category is excluded by the existing storage contract.
- [x] Confirm irreversible deletion by title; explain that history is removed but disk attachments and existing backups are retained. Keep forms open with values intact on failed requests; prevent duplicate submits and warn before discarding changes.
- [x] Show clear default-category rename/reorder guidance. Respect editor capability and API failures; preserve existing restrained visual style and mobile layout.
- [x] Add front-end behavior tests, run Node tests, and exercise the flows in an isolated browser/packaged fixture.

## Integration and delivery

- [x] Include new modules/assets/tests in public-release and runtime manifests; update README and architecture statements that still describe the memory content as read-only.
- [x] Run backend, viewer, desktop and source-packaging checks from `docs/development.md`; perform independent spec and quality reviews.
- [ ] Build the next Windows release, validate isolated CRUD and update assets, commit/push and publish signed GitHub update under the standing release authorization. Never insert acceptance records into the installed database.
