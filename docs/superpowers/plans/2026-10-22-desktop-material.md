# Desktop visual refinement plan

**Goal:** Refine the app's desktop feel using quiet neutral surfaces, a persistent navigation rail and compact controls, informed by the installed Codex application's visual tokens.

**Architecture:** The trusted shell owns the rail and native pages. The sandboxed dashboard uses the same authored visual tokens without acquiring native APIs. Dashboard geometry follows one small pure layout module and is checked against actual shell bounds.

**Tech stack:** Electron, HTML, authored CSS/SVG, Node tests and isolated Electron acceptance.

- [x] Add geometry and real-page layout assertions before implementation; reproduce old top-navigation failure.
- [x] Author shared neutral tokens, navigation icons and sidebar; flatten client/settings cards into readable rows. Keep existing four sections and optional Xiaozhi flow.
- [x] Adapt embedded memory/categories/market to the same visual rhythm; keep backup, search, capability switches and links.
- [x] Inspect actual native and embedded captures at 1180 and 880 px widths; verify focus, scrolling, navigation race, SDK calls and cloud reconnection in isolated profiles.
- [x] Review changes, build Windows 0.2.3, test packaged app, verify source/installer hashes, sign offline release metadata and deliver audited sources.

Reference work is read-only. Do not redistribute Codex code, icons or fonts. Preserve production data and cloud configuration. Execute inline; no commit in this unborn repository.
