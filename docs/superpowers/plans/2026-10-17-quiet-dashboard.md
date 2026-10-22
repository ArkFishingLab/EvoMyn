# Quiet personal workspace redesign

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** Give the local archive and planner one refined, restrained visual language while retaining their current behavior and live data.

**Architecture:** Reuse the existing DOM identifiers and JavaScript handlers. Replace the archive's inherited presentation stylesheet with a small shared design system; the planner imports it and adds its list/form rules. Preserve local-only labels and backup-service limitations when publishing source assets to the running trial. Asset changes do not restart the reminder WebSocket or edit records.

**Design (revised after user feedback):** White and neutral gray, charcoal actions, consistent sans-serif typography, a narrow sidebar, fine rules and flat lists. Remove decorative English, promotional subtitles, duplicate counters, empty overview panels and repeated footer branding. Keep record metadata and operational feedback.

- [x] Inspect current templates, handlers, font assets, and local deployment; back up source and runtime assets.
- [x] Build shared styling and matching archive/planner layouts, preserving all existing form IDs and action hooks.
- [x] Publish static files to the local runtime without restarting data or reminder services.
- [x] Run existing planner/model checks and inspect both pages, filters, record details, and unsaved forms in the browser.
- [x] Check mobile width and preserve the redesigned local planner as the visible deliverable.

This repository has no commits; work in place and keep unrelated firmware and service state untouched. Only the local runtime is published; the remote server's UI is not redeployed.

Validation: planner web search/link/date-completion/retry/double-submit checks passed; seven archive model checks and seven viewer HTTP checks passed. Browser QA covered desktop archive/planner, real record detail, status filtering, search empty state, day view, and an unsaved editor. At 390px viewport, document width remained 390px; mobile navigation and both pages were visually inspected. Restored the normal viewport and left the planner visible. Static assets were deployed without restarting MCP, dashboard, or reminder transport, and without changing records.

Refinement: the archive now displays one complete record list, rather than overview statistics and repeated sections. Total count appears once next to the heading. The local disabled backup entry is omitted via a runtime flag; the deployed source still supports enabled backups. Planner labels and status text were shortened. Existing planner browser logic checks and all seven archive model checks passed again. Actual browser inspection confirmed the new font was loaded, archive search returned the matching record, and both pages fit a 390px viewport without horizontal overflow. Local Microsoft YaHei UI regular/bold webfont copies are in the ignored runtime only; system font files are not added to source control.
