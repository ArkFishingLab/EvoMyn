# Server memory viewer implementation plan

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

**Goal:** Reuse the desktop personal-archive viewer against the server's real MCP database and publish at https://203.0.113.10/memory/ with an independent login.

**Architecture:** Copy the existing white five-category UI and licensed assets, preserving title-only record lists and detail drawers. Add a standard-library read-only SQLite HTTP service in a separate, small Docker container using a read-only state mount. Expose it only on loopback and add one authenticated HTTPS Nginx location; preserve the existing Evodo routes. Store access credentials outside source control.

**Tech Stack:** Python 3.11 standard library, SQLite, copied HTML/CSS/ES modules, Docker Compose, Nginx Basic authentication over the existing valid HTTPS IP certificate.

- [x] Add failing HTTP tests for current database records, later MCP updates, rejected writes, safe attachments, static allowlist, disallowed Host and unavailable databases.
- [x] Implement the read-only server and adapt copied static URLs for the /memory/ prefix. Keep source attribution and local fonts.
- [x] Add a separate viewer container and authenticated Nginx route. Generate a distinct access password; preserve existing services and endpoint settings.
- [x] Run backend and inherited model tests; verify deployed anonymous requests are denied, authenticated requests work, and actual read-only DB access works.
- [x] Inspect desktop/mobile pages, category navigation, search and detail interaction against a disposable fixture; leave the production database free of fixture data.
- [x] Record deployment checks, access instructions, and a screenshot. Request independent review and resolve material findings.

Deployment verified: unauthenticated HTTPS requests return 401; independent login returns 200 for the page, records, script and dashboard API. TLS validates normally. Production remains at zero records. Existing certificate renewal timer is active. Browser QA used a disposable five-record fixture for search/detail/association checks, while deliverable screenshots show the actual empty server database. Phone width=390 with no horizontal overflow.
