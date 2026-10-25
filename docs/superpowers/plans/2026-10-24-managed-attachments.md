# Managed attachments implementation plan

**Goal:** Import local attachments into state/resources, add/open attachments from the desktop, and let MCP clients add attachments using local paths.

**Architecture:** A shared, model-independent managed-file helper bounds copies, rejects linked/special/database files and resolves attachment IDs within resources. ArchiveStore owns revision-safe attachment metadata; existing file_path input imports a managed copy. Viewer uploads use existing Origin/CSRF protections and bounded binary streaming. Native opening is a narrow trusted-dashboard IPC resolving an ID through the backend, never accepting renderer paths. Preserve source files, old records and backups.

**Tech stack:** Python/SQLite, MCP, browser JavaScript, Electron.

- [x] Store and MCP: managed copy, multiple attachment metadata, legacy file_path compatibility, revision and failure cleanup tests.
- [x] Viewer: authenticated uploads, attachment list/add controls and download links, Chinese/English labels, no file paths in public API.
- [x] Desktop: restricted open-attachment bridge and backend resolver; package new source files and run isolated end-to-end acceptance.
- [x] Review copy bounds, same-name files, symlinks/reparse points, stale revisions, source removal, application behavior and MCP gate. Commit locally only; no installed database migration or publication.

Verified: PC suite 209 tests (1 platform skip), desktop backend 28, viewer HTTP 25, Node 121, staging 4 and public export 16 (1 platform skip). Front proxy has separate tests for a multi-megabyte upload, unchanged JSON limits and rejection of unauthorized uploads before reading the body. Real Electron acceptance exercised actual MCP import/append, source removal, UI upload, exact downloaded bytes and both languages. Reviews identified and corrected desktop runtime file lists, legacy attachment visibility and missing front-door upload forwarding.

**Shared contract:** record.attachments = [{id,name,size,sha256,file_path,href}]. Public API removes attachment.file_path. href = /api/files/{record_id}/{attachment_id}. ArchiveStore.add_attachments(record_id, file_paths, expected_revision=None, *, index=True) appends managed entries and returns updated record. MAX_ATTACHMENT_BYTES=50*1024*1024. Shared helper vendor/attachment_files.py exposes resolve_attachment(database, resources, record_id, attachment_id) -> pathlib.Path with strict managed containment; legacy primary attachment uses attachment_id='legacy'.
