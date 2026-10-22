# Repository guidance

- Authoritative modules are `server/personal-memory/` and `xiaozhi-firmware/`. Read applicable nested `AGENTS.md` files before firmware edits; their board and build rules remain in force.
- Read `docs/development.md` for checks. Use isolated fixtures and temporary databases. Never add test records to the installed personal database.
- Root startup commands assemble or reuse the ignored runtime at `artifacts/local-memory-mcp/`. Preserve existing configuration, records and backups. Do not hand-edit generated runtime files as a source change.
- Keep credentials, private headers, databases, model caches, proprietary font derivatives and build output out of public source. Do not print secret values in diagnostics.
- Hardware flashing, production database changes, cloud configuration changes and publication require explicit authorization. A source or host-test change does not authorize these actions.
- Treat dated reports and earlier plans as historical evidence. Current operation is described by root/module READMEs and `docs/architecture.md`.
- Preserve upstream licences and notices. Verify the relevant checks before claiming completion, and distinguish host tests from full firmware builds and hardware acceptance.
