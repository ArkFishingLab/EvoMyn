# EvoMyn naming implementation plan

**Goal:** Use EvoMyn as the project's only public product name and deliver a Windows installer and clean source archive.

**Architecture:** Rename presentation, release artifacts and newly exported MCP client entries. Keep the established Windows app ID, LocalAppData location, IPC names, health service identifiers, archive format and update trust key compatible with installed clients. Preserve historical reports, upstream attribution and private runtime data.

**Tech stack:** Electron, electron-builder/NSIS, Python MCP backend and static dashboards.

## Tasks

- [x] Replace public branding in desktop metadata, window/tray/UI, dashboard/setup/capability pages, MCP handshake names and active documentation. Release version 0.2.5; executable and installer prefix EvoMyn.
- [x] Export new client entries as `evomyn`, rename configuration downloads and source launcher wrappers, update existing fixtures and portable package metadata. Document retained compatibility identifiers.
- [x] Run desktop Node/Python, portable launcher/package checks and repository publication audit with isolated data. Stage reviewed backend sources and build the Windows installer.
- [x] Exercise the packaged executable with the isolated desktop/TLS acceptance flow. Sign offline update metadata with the existing key, package audited sources and write checksums plus release notes.

No firmware build/flash, production configuration edits, installation into the user's active profile or online publication is part of this change.
