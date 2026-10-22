# Whole Repository Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Track each task with checkboxes.

**Goal:** Make this entire working repository understandable, cloneable and safe to publish, preserving the running personal installation and all historical files locally.

**Architecture:** Keep the two authoritative source modules at `server/personal-memory/` and `xiaozhi-firmware/` to preserve firmware and test paths. Root commands prepare an ignored runtime from reviewed source files on a new clone, while reusing the existing private installation on this PC. Local archives, caches, backup images, generated proprietary fonts and credentials remain excluded. Root documentation, CI and a candidate-file audit describe and enforce this boundary.

**Tech Stack:** PowerShell/CMD, Python unittest, Node built-in tests, existing ESP-IDF/CMake firmware, Git candidate-file enumeration.

Do not commit or publish, create a new worktree from this unborn repository, delete files, reset Git state, move active databases, rotate credentials, or flash hardware. Archive obsolete files with an explicit move manifest and verified in-workspace absolute destinations.

### 1. Inventory and local archives

- [x] Record the current README, directory roles and source entry points before edits.
- [x] Move the unused original vendor demo `firmware/`, ignored vendor checkout and loose render/screenshot outputs to an ignored local archive; retain backups and active source paths.
- [x] Record all moves and add directory/module maps, including historical deployment status.

### 2. Root startup works from source clones

- [x] Test creating a runtime from an empty checkout fixture, preserving an existing `.env`/database, rejecting linked destinations and not creating duplicate cloud sessions.
- [x] Add a dependency-free PowerShell source-runtime assembler and root Start/Stop/Configure wrappers.
- [x] Reuse the installed private runtime and legacy manager on this PC; use the portable launcher for newly assembled runtimes.
- [x] Exercise new-clone preparation and startup in an isolated directory, plus repeated current-workspace startup.

### 3. Portable development tools

- [x] Remove personal machine paths/proxy settings from maintained build and rendering helpers; require/configure SDK, compiler, mirror and font inputs explicitly.
- [x] Keep original private maintenance scripts locally archived; document public replacements and open-font asset generation.
- [x] Replace personal deployment address/MAC examples with reserved examples or required environment configuration.
- [x] Verify Python/PowerShell syntax, native checks and public source-export behavior after these changes.

### 4. Repository policies and documentation

- [x] Rewrite the root and module READMEs around current operation; retain the old root README in the local archive.
- [x] Add root MIT licence, upstream notices, contribution/security guidance, AGENTS rules, documentation/tool/test indexes and portable local-config templates.
- [x] Sanitize historical maintained docs and mark them as dated evidence rather than current instructions.
- [x] Extend ignore rules for generated/private files without hiding maintained source.

### 5. Audit, CI and handoff

- [x] Add tests and a read-only audit of Git tracked/candidate files for private material, generated artifacts, linked paths and personal path leakage; never print credential contents.
- [x] Add CI for the PC, preview and repository-policy checks using isolated fixtures; native firmware checks where the required host toolchain is available.
- [x] Run the relevant complete checks, rebuild the clean distribution, verify current data/service state and independently review the resulting repository.
- [x] Report the final structure, launch commands, archive location and remaining platform/hardware verification limits.

## Verification record

- Root checks: 66 tests, 3 Windows symlink-permission skips.
- Clean Python/candidate-only firmware checkout: 125 tests, 2 unavailable-UBSan skips; standalone exported round tests: 11 passed.
- Viewer: 7 passed; Node: 23 passed; installed public package real MCP/shared-data/lifecycle acceptance passed.
- Git publication candidates audited with no issues; no Git commit or remote publication performed.
- Current installation verified connected and healthy; private records retained. Full OFL-font ESP-IDF build and hardware acceptance remain outside this repository organization.
