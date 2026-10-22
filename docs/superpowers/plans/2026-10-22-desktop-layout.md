# Desktop layout implementation plan

**Goal:** Give the Windows app one navigation system and a client-neutral connection center.

**Architecture:** Keep the trusted Electron shell separate from the unprivileged dashboard. The shell owns navigation, the MCP master, client connections and app preferences. Desktop-only CSS removes duplicate web navigation while preserving standalone pages.

**Tech stack:** Electron, HTML/CSS/JavaScript, existing Python MCP service.

- [x] Add failing real-app acceptance assertions: exports belong to connections, settings exclude service switches, one master, embedded primary navigation hidden.
- [x] Reorganize `desktop/ui/index.html` and event bindings in `app.js`: local client cards first, optional Xiaozhi configuration second; settings contain startup, data and updates.
- [x] Refine `style.css`, align shell/view bounds in `main.cjs`, and add desktop-only dashboard presentation. Preserve category navigation, backup, marketplace and all security boundaries.
- [x] Exercise all four pages at normal/minimum window sizes, independent MCP/cloud switches, configured reconnect and actual SDK calls using isolated profiles.
- [x] Run desktop tests, inspect captured pages, obtain independent code review, build and verify the Windows installer and audited source archive.

No production profile, cloud configuration or firmware changes; no Git commit in this unborn repository. Execute inline, as continuation of the user's authorized desktop implementation.
