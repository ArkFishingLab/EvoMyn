# Bilingual desktop UI implementation plan

**Goal:** Add a persisted Chinese/English choice in desktop settings while preserving current behavior, layout and personal content.

**Architecture:** Keep the default Chinese UI. A local translation catalog translates explicitly identified application copy only. Electron owns the validated language preference and synchronizes shell, embedded dashboards and tray. Language changes must preserve editor drafts and never mutate records or category labels in the database.

**Tech stack:** Electron, plain JavaScript, existing browser modules, Node test runner.

- [x] Add regression tests for language validation, fallback, text escaping and persistence boundaries.
- [x] Implement a shared catalog and static-copy markers; translate source literals rather than arbitrary DOM text.
- [x] Add a settings selector, persist the preference, update native menus and embedded pages without navigation or service changes.
- [x] Verify Chinese/English UI in an isolated application profile, including dynamic dialogs and unchanged user content. Run desktop and viewer checks. Keep changes on the local feature branch; no release or installation.

Verification: 112 desktop/viewer JavaScript tests passed; viewer Python 16 and staging 4 passed. Real Electron acceptance passed live switching, preserved editor drafts, abilities rendering and persistence across application restart. Independent specification and quality review findings were fixed and verified.
