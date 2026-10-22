# GitHub update source implementation plan

**Goal:** Publish the audited EvoMyn repository and a signed Windows release to clover-Saber/EvoMyn, embedding its fixed GitHub Releases update feed.

**Architecture:** Resolve missing or empty saved update preferences to `https://github.com/clover-Saber/EvoMyn/releases/latest/download/latest.json`, preserving valid custom HTTPS feeds. Publish versioned installers plus a signed `latest.json` with the existing trusted key. Keep all personal state, build output and signing keys ignored. Use the existing Git Credential Manager account for Git and GitHub CLI without displaying credentials.

**Tech Stack:** Electron, Node.js tests, Python isolated acceptance and packaging, Git, GitHub CLI, Ed25519.

**Public verification follow-up:** Keep the published 0.2.7 immutable and release 0.2.8 with Electron system-proxy transport. Real public download exposed Node HTTPS bypassing Windows proxy. Fix the first GitHub Windows CI findings (8.3 aliases in exporter/launcher fixtures and Unicode TLS trust fixture) without weakening guards or assertions.

- [x] Inspect remote refs, repository ownership and available credential access. Preserve any existing remote history; never force-push.
- [x] Add failing tests for default, legacy empty, invalid saved and valid custom update feeds in `desktop/tests/update-source.test.cjs`; implement `desktop/update-source.cjs`, wire `desktop/main.cjs` and the builder file list. Saving an empty feed restores the embedded default.
- [x] Verify the actual desktop shell exposes the built-in feed with an enabled update check. Update active docs and release versions to 0.2.7. Preserve application identity, data directory and update trust.
- [x] Run Node suites, targeted Python packaging/backend checks and real packaged Electron acceptance against isolated data. Build the Windows installer and sign the public GitHub download URL in `latest.json`.
- [x] Audit every source candidate and staged file; create the initial source commit and push to the supplied repository's default branch. Publish GitHub Release v0.2.7 and the system-proxy follow-up v0.2.8 with verified installers and signed latest.json, plus source/checksum assets.
- [x] Fetch the public fixed feed through the real updater, verify its signature and installer bytes, and inspect GitHub checks. Report the repository, release and initial setup path for older installations.

The user explicitly authorized pushing this repository and embedding the update source. Publishing the release assets makes the requested source usable; no production database changes, firmware flashing or private credential upload is included.
