# Optional round firmware source

The PC application can be used without rebuilding or flashing firmware. This optional
firmware contains XiaoZhi's MIT-licensed source and the custom `round-voice-175c`
board for the 1.75C AMOLED: ESP32-S3, 32 MB flash, 8 MB octal PSRAM, 466 x 466.
It is a distinct board identity; it is not compatible with the 1.75 non-C variant.
The upstream copyright and permission notice is retained in `LICENSE` inside this tree.
Small upstream system prompt `.ogg` files are retained as part of that MIT distribution.

In the whole repository, the maintained firmware is `xiaozhi-firmware/` and the
helpers are in root `tools/`. A clean distribution instead places this firmware in
`firmware/`, including its own `tools/`. Commands below distinguish these layouts;
the old vendor demonstration directory is not the active firmware source.

The public source export is separate from the public firmware binary. Version 2.5.10 has
passed a complete open-font build and native LVGL rendering checks. Physical device
acceptance remains separate; a successful build is not a claim of hardware validation.
No firmware image, flash dump, installed Windows font, generated Windows font subset,
device credential, private header, local SDK state or persistent device key is included.
The original project source and any connected device are not changed by the exporter.
The package exporter reads only the reviewed paths in the versioned
`tools/public_round_files.json` beside its export helper. New source filenames require
an explicit manifest update; extension matching does not add them automatically.
Source links and Windows reparse points, including junctions, are rejected before
their contents can be copied. A public package can be re-exported from its `firmware/`
tree with the same helper and manifest, without access to the original workspace.

## Offline host checks

The round protocol checks include their small native C++ fixtures and unmodified
cJSON 1.7.19 C sources under `tests/`. The parser comes from the already reviewed
`espressif/cjson` component 1.7.19~2; its MIT licence and byte hashes are retained in
`tests/support/cjson/LICENSE` and `SOURCE.json`. These files serve host tests only.
Production ESP-IDF builds continue to resolve the component declared in the firmware
manifest. Host checks do not require downloaded `managed_components/`, a model,
ESP-IDF, third-party Python packages, generated fonts, or a network connection.

Use Python 3.11 and a C/C++17 host compiler. In the whole repository run
`python -X utf8 -I -S tools/run_xiaozhi_host_tests.py`; on Linux in an exported
`firmware/` directory run
`python -X utf8 -I -S -m unittest discover -s scripts/tests -p 'test_round_*.py' -v`
for the exported board checks. The whole checkout also retains upstream CI workflow
fixtures for the complete host suite; those workflow files are outside this export.
`CC` and `CXX` may select the C and C++ compiler commands. The whole-repository
wrapper restores the working directory before temporary-tree cleanup on Windows
and explicitly skips the unrelated ESP-VoCat UBSan test if that runtime is absent.
The export manifest lists each host fixture explicitly; an export keeps them under
its own `tests/` directory and can re-export them without the original checkout.

## Regenerate fonts before the ESP-IDF build

The twelve generated font `warm_assets/*.inc` files are deliberately absent from
public exports and excluded from version control. A local installation may retain
its private build resources. The original UI fonts
were derived from Microsoft YaHei UI and Bahnschrift; no redistribution rights are
assumed for them. The public font path requires local **static TTF/OTF fonts under
the SIL Open Font License**, supplied with their OFL license text. No automatic
font download, installed-system-font lookup or private converter-cache lookup occurs.

A suitable choice is a static Noto Sans CJK Simplified Chinese OTF, with its original
OFL text, for all text and digits. You may supply a separate static OFL Latin font
for the 31 px and 64 px digits. Obtain fonts and license text from their publisher,
retain the license, and review any Reserved Font Names before redistributing changes.
Font appearance and line metrics will differ from the production Windows-font UI.

Use Python 3.11 or later, `fonttools==4.61.1`, and Node.js 22 with npm/npx. The converter
is pinned to `lv_font_conv@1.5.3`. Run these commands from the **whole repository
root**, or from the **exported `firmware/` directory**. The helper's default board
location supports both layouts. Replace the font paths with your own licensed files:

```powershell
python -m venv .venv-fonts
.venv-fonts/Scripts/python -m pip install fonttools==4.61.1
.venv-fonts/Scripts/python tools/generate_open_round_fonts.py --text-font C:/fonts/NotoSansCJKsc-Regular.otf --license C:/fonts/OFL.txt --dry-run
.venv-fonts/Scripts/python tools/generate_open_round_fonts.py --text-font C:/fonts/NotoSansCJKsc-Regular.otf --license C:/fonts/OFL.txt
.venv-fonts/Scripts/python tools/generate_open_round_fonts.py --check
```

On macOS/Linux the venv interpreter is `.venv-fonts/bin/python`. The first conversion
may download the pinned npm converter through npx; it does not download a font.
Use `--digits-font <font.ttf> --digits-license <OFL.txt>` for a separate Latin font.
The generator checks every required glyph and refuses incomplete or variable fonts.
If a static export is needed for a variable font, prepare it using the font publisher's
instructions first. Conversion uses 4 bpp, uncompressed LVGL output without kerning.

The generator retains each font's filename and SHA-256 plus converter version in
`warm_assets/open-font-provenance.json` and copies the two license texts. It removes
converter invocation comments so local absolute font paths do not enter the generated
source. Include those provenance/license files with any redistributed generated assets.
The generator leaves wrappers, icons and production source files unchanged.

## Build the optional firmware

Install and activate **ESP-IDF 6.0.2** for this source base; upstream policy supports
6.0.1 or later and prefers 6.1 where compatible. IDF 5.x is unsupported. Use the
ESP-IDF environment's Python for the firmware commands, rather than the font venv.
The component manifest `main/idf_component.yml` declares LVGL `~9.5.0`, esp-sr
`2.4.7` and other upstream dependencies; ESP-IDF Component Manager resolves them.
Vendored components, default large font bundles and build output are not shipped.
Registry dependencies and their individual licenses remain separate from this package.
The audited source defaults `sdkconfig.defaults` and `sdkconfig.defaults.esp32s3`
are retained; an existing workstation `sdkconfig` or lockfile is never copied.

```powershell
idf.py --version
python tools/generate_open_round_fonts.py --check
```

In the whole repository, change into `xiaozhi-firmware/` before the next commands.
In a source export, remain in its `firmware/` directory:

```powershell
python scripts/build.py --list-boards
python scripts/build.py round-voice-175c --name round-voice-175c --language zh-CN
```

The board variant selects 32 MB flash and `partitions/v2/32m.csv`; S3 defaults select
octal PSRAM. `scripts/build.py` creates fresh `sdkconfig` and build output in this
selected project. The source-only export intentionally fails early with instructions
when font assets are missing. A fresh full ESP-IDF build and display/hardware validation
are still required after font generation. No flashing command is part of these steps.

## Service defaults

`round_services_private.h` and any other private header are excluded. Public firmware
reads its own versioned pairing record from `round_pairing/config` in NVS. An unpaired
device has no desktop OTA service until explicitly paired over physical USB. Ordinary
OTA preserves pairing, Wi-Fi, XiaoZhi activation and local reminders. Old private
2.5.7/2.5.8 builds need one migration via a private 2.5.9 bridge, or USB pairing after
upgrading; see [pairing and update instructions](https://github.com/ArkFishingLab/EvoMyn/blob/main/docs/esp-firmware-update.md) in the full
repository. LAN completion archive upload remains retired. The upstream XiaoZhi activation/voice service and
public Open-Meteo weather integration remain as declared in source. This package does
not distribute access to a private server or pre-provision a device.

If you later add a local private configuration, keep it out of version control and
public source archives. An export does not configure Wi-Fi, read a serial port,
contact a device, transfer an image or publish a repository.
