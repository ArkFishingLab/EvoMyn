# Custom memory categories implementation plan

**Goal:** Let EvoMyn users manage memory categories, keeping five defaults and displaying background as 个人.

**Architecture:** Store the category catalog beside archive records in SQLite, with stable IDs and an initially seeded default set. Share a model-free catalog between the archive SDK adapter and viewer. Keep archive records read-only in the dashboard while allowing bounded, same-origin category mutations with CSRF validation. Existing record IDs and category IDs remain compatible; category metadata travels with database backups.

**Tech stack:** Python sqlite3, MCP, vanilla JavaScript/CSS and Electron.

## Tasks

- [x] Add isolated catalog/store and viewer API tests covering persistence, legacy background labels, custom MCP writes, duplicate/invalid names, ordering, deletion protection and CSRF rejection. Run to establish failing behavior.
- [x] Implement `vendor/archive_categories.py`; integrate ArchiveStore validation, indexing and status plus MCP instructions. Register the module and test in public/runtime allowlists. Preserve default IDs for device journals and resource attachments.
- [x] Add `/api/categories` read/write support without loading Mnemosyne. Keep record mutations rejected. Provide category metadata in record responses for UI refresh.
- [x] Add a compact category management dialog to the existing dashboard. Support add, rename, move up/down and delete empty custom categories; escape labels and preserve unsaved edits during refresh. Test dynamic counts/filtering and exercise the real UI against an isolated database.
- [x] Update active docs, build EvoMyn 0.2.6, run relevant suites and packaged acceptance, sign offline metadata with the existing key, and deliver audited installer/source archives.

No production database mutation, cloud configuration change, firmware flash or publication is included. Defaults keep stable IDs and can be renamed/reordered; empty custom categories can be deleted. Populated categories cannot be deleted.
