# Manual backup product scope

**Goal:** Remove the deferred GitHub cloud-backup workflow from EvoMyn's current user interface; preserve manual local SQLite snapshots and all existing data.

**Architecture:** Stop mounting the cloud backup panel, remove its navigation and assets from the active page, and redirect old backup bookmarks to the memory overview. Keep the historical backend and encrypted restore tool for compatibility without starting a cloud service. Clarify current manual backup and restore instructions.

**User steering:** Device-native planner/reminders must also be absent from installed capabilities and the marketplace. Exclude the device-owned planner from the shared catalog, retain existing tool gating and saved settings, and leave optional legacy PC ownership compatible.

- [x] Remove the active cloud backup UI and update existing real-window acceptance for six default navigation entries and old backup bookmarks.
- [x] Document `archive_backup`, snapshot locations, attachment limitations, and safe manual restore. Preserve private configuration and backup files.
- [x] Build 0.2.9, run viewer/model, desktop and public-export checks, and exercise the packaged desktop against isolated records.
- [x] Audit and push the change; publish signed 0.2.9 to the existing built-in update feed and verify the published manifest/assets.

No installed database or backup file is modified. GitHub remains the source/update host; personal backup uploads are deferred.
