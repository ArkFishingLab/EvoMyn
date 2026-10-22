# Firmware online updates implementation plan

**Goal:** Let desktop users check the latest compatible ESP firmware and download it into the desktop-managed OTA cache without manually importing files.

**Architecture:** A separate signed firmware feed hosted on GitHub is consumed in Electron through the existing bounded, system-proxy-aware HTTPS transport. A firmware controller verifies an Ed25519 envelope and board/project/partition/version/size/hash before downloading into a private temporary directory. The existing Python import command validates the actual ESP image and atomically activates it. Desktop application releases and firmware feeds remain independent.

**Tech stack:** Electron/Node, Python OTA publisher/provider, ESP-IDF.

- [x] Add failing controller tests for signature, compatibility, bounded download, hash mismatch, cancellation, retry and activation failure preserving the existing firmware.
- [x] Implement `desktop/firmware-updater.cjs` with check/download/status/cancel; only fixed argument-free renderer actions can trigger it. Reuse desktop update trust with an explicit firmware payload type to prevent cross-use of signed installers.
- [x] Wire the controller into `desktop/main.cjs`, native IPC and settings. Display latest downloadable version separately from locally prepared version, check/download progress and error states. Keep manual import under advanced options. Prepared version also survives an unpaired service restart.
- [x] Add a firmware signing utility using the existing release key and an explicit board/project/partition contract. Stable firmware feed must not follow the desktop `releases/latest` redirect.
- [x] Audit the existing 2.5.8 binary: it embeds private pairing configuration and proprietary font derivatives. Do not publish it. Removing the header alone disables subsequent OTA because no NVS pairing loader exists. A private bridge to persistent pairing, followed by an OFL-font public build, remains a separate migration prerequisite.
- [x] Run isolated tests (76 Node tests; 9 Python OTA tests), spec review, build desktop 0.2.14 and run packaged smoke. No personal records changed or device installation triggered.
- [x] Complete independent quality review; fix the concurrent desktop-install/firmware-download race and verify both start orders plus failure recovery.
- [ ] Publish desktop changes when authorized. Public firmware remains pending the pairing/font migration; no public binary or feed has been published.

Existing reminder-time source changes remain preserved. Never modify the personal database or trigger hardware installation during tests.
