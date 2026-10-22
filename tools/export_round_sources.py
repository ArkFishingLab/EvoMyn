"""Create a source-only public copy of the optional round firmware.

This deliberately never opens private headers, firmware binaries, SDK state,
installed fonts or generated font includes. It never builds or flashes a device.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat

BOARD = Path("main/boards/round-voice-175c")
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".s", ".cmake", ".json",
                   ".yml", ".yaml", ".py", ".txt", ".md", ".sh", ".csv"}
SOURCE_NAMES = {"LICENSE", "CMakeLists.txt", "Kconfig", "Kconfig.projbuild", ".clang-format"}
EXCLUDED_DIRS = {".git", ".github", "build", "releases", "managed_components", "components",
                 "__pycache__", "node_modules", "warm_assets", ".vscode", "backups"}
EXCLUDED_NAMES = {"lang_config.h", "dependencies.lock"}
AUDITED_DEFAULTS = {"sdkconfig.defaults", "sdkconfig.defaults.esp32s3"}
TOOLS_ROOT = Path(__file__).resolve().parent


def _reject_reparse(path: Path) -> None:
    metadata = path.lstat()
    if (metadata.st_file_attributes & 0x400 if hasattr(metadata, "st_file_attributes") else False) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"Reparse point or link is forbidden in firmware source: {path.name}")


def _validate_source_links(source: Path) -> None:
    """Check metadata before traversal; Windows junctions are not is_symlink()."""
    _reject_reparse(source)
    for directory, children, files in os.walk(source, followlinks=False):
        parent = Path(directory)
        _reject_reparse(parent)
        children[:] = sorted(name for name in children if name not in EXCLUDED_DIRS)
        for name in children + files:
            _reject_reparse(parent / name)
        if parent.relative_to(source) == Path("main/boards"):
            children[:] = [name for name in children if name in {"common", "round-voice-175c"}]


def _reviewed_files(section: str = "files") -> list[Path]:
    manifest = TOOLS_ROOT / "public_round_files.json"
    _reject_reparse(manifest)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (data.get("version") != 1 or not isinstance(data.get("files"), list)
            or not isinstance(data.get(section, []), list)):
        raise ValueError("Unsupported public firmware source manifest")
    result = []
    for name in data.get(section, []):
        path = Path(name)
        if (not isinstance(name, str) or path.is_absolute() or ".." in path.parts
                or "\\" in name or ":" in name or not _public_source(path)):
            raise ValueError("Unsafe entry in public firmware source manifest")
        if section == "workspace_files" and path.parts[0] != "tests":
            raise ValueError("Workspace firmware fixtures must be under tests")
        result.append(path)
    return result


def _checked_fixture(root: Path, relative: Path) -> Path | None:
    """Check every root-fixture ancestor before reading through it."""
    original = root
    for part in relative.parts:
        original /= part
        try:
            _reject_reparse(original)
        except FileNotFoundError:
            return None
    if not original.is_file():
        raise ValueError("Public host fixture must be a file")
    return original


def _public_source(path: Path) -> bool:
    name = path.name.lower()
    if (any(marker in name for marker in ("private", "credential", "secret"))
            or name in EXCLUDED_NAMES):
        return False
    if path.suffix.lower() == ".csv" and path.parts[0] != "partitions":
        return False
    if name.startswith("sdkconfig"):
        return path.as_posix() in AUDITED_DEFAULTS
    if "key" in name and path.suffix.lower() not in {".c", ".cc", ".cpp", ".h", ".hpp"}:
        return False
    # Small upstream prompt sounds are needed by gen_lang.py / Lang::Sounds.
    if path.suffix.lower() == ".ogg":
        return path.parts[:2] == ("main", "assets")
    return path.name in SOURCE_NAMES or path.suffix.lower() in SOURCE_SUFFIXES


def _audit_text(content: str, relative: Path) -> None:
    # Refuse rather than silently rewrite source credentials. No secret contents
    # are printed when a candidate fails this guard.
    sensitive = (r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----",
                 r"(?i)[A-Z]:[/\\]Users[/\\]", r"/Users/[^/]+/",
                 r"\b101\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    if any(re.search(pattern, content) for pattern in sensitive):
        raise ValueError(f"Source contains private deployment material: {relative.as_posix()}")
    if relative.as_posix() in AUDITED_DEFAULTS:
        if re.search(r"(?im)^CONFIG_\w*(?:PASSWORD|TOKEN|SECRET|SSID|PRIVATE_KEY)\w*=", content):
            raise ValueError(f"Credential option in source defaults: {relative.name}")


def export_round_sources(workspace: Path, dest: Path) -> list[str]:
    """Export into an absent/empty destination and return human-readable notes.

    The destination is the firmware project root (CMakeLists.txt/main/scripts),
    so callers can place it under firmware/source in a larger public package.
    """
    workspace = Path(os.path.abspath(workspace))
    _reject_reparse(workspace)
    source = workspace / "xiaozhi-firmware"
    if not source.exists():
        source = workspace / "firmware"
    if source.exists():
        _reject_reparse(source)
    dest = Path(os.path.abspath(dest))
    if dest.exists():
        _reject_reparse(dest)
    if dest == source or source in dest.parents:
        raise ValueError("Firmware export destination must be outside the production source tree")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError("Firmware export destination must be empty")
    if not (source / "LICENSE").is_file():
        raise ValueError("Upstream firmware LICENSE is required")
    _validate_source_links(source)
    staged = []
    for relative in _reviewed_files():
        original = source / relative
        if not original.exists():
            continue
        _reject_reparse(original)
        if original.suffix.lower() == ".ogg":
            if original.stat().st_size > 256 * 1024:
                raise ValueError(f"Unexpected large prompt asset: {relative.as_posix()}")
            staged.append((original, relative, None))
        else:
            content = original.read_text(encoding="utf-8-sig")
            _audit_text(content, relative)
            staged.append((original, relative, content))
    # Host tests live beside the firmware in a whole checkout, and inside the
    # firmware tree in a standalone export. Preserve third-party fixture bytes
    # exactly so their recorded hashes remain valid on Windows and Linux.
    fixture_root = source if source.name == "firmware" else workspace
    for relative in _reviewed_files("workspace_files"):
        original = _checked_fixture(fixture_root, relative)
        if original is not None:
            _audit_text(original.read_text(encoding="utf-8-sig"), relative)
            staged.append((original, relative, None))
    # Validate all selected text before creating an export with partial content.
    dest.mkdir(parents=True, exist_ok=True)
    for original, relative, content in staged:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            shutil.copyfile(original, target)
        else:
            target.write_text(content, encoding="utf-8")
    generator = dest / "tools/generate_open_round_fonts.py"
    generator.parent.mkdir(exist_ok=True)
    if source.name == "firmware":
        generator_source = source / "tools/generate_open_round_fonts.py"
        docs = source / "docs/round-open-source.md"
    else:
        generator_source = TOOLS_ROOT / "generate_open_round_fonts.py"
        docs = TOOLS_ROOT.parent / "docs/round-open-source.md"
    _reject_reparse(generator_source)
    _reject_reparse(docs)
    shutil.copyfile(generator_source, generator)
    (dest / "docs").mkdir(exist_ok=True)
    shutil.copyfile(docs, dest / "docs/round-open-source.md")
    (dest / "README.md").write_text(
        "# Optional round-voice-175c firmware source\n\n"
        "Source-only public export of XiaoZhi plus the custom 1.75C board.\n"
        "Read [build and font instructions](docs/round-open-source.md) first.\n"
        "Regenerate the twelve OFL font assets before configuring ESP-IDF.\n"
        "Private LAN services are unconfigured. No compiled image is supplied.\n\n"
        "The upstream MIT notice is retained in LICENSE.\n", encoding="utf-8")
    (dest / BOARD / "README.md").write_text(
        "# round-voice-175c\n\nESP32-S3 / 32 MB flash / 8 MB octal PSRAM; "
        "466 x 466 AMOLED 1.75C.\n"
        "This is a distinct board identity. See docs/round-open-source.md at the project root.\n"
        "Local reminders work without the optional, unconfigured private LAN service.\n",
        encoding="utf-8")
    # Fail early with a useful action instead of twelve C++ include errors.
    cmake = dest / "CMakeLists.txt"
    if cmake.exists():
        check = ("# Public source export: original Windows-derived fonts are omitted.\n"
                 "foreach(ROUND_FONT warm_font_11 warm_font_13 warm_font_14 warm_font_15 "
                 "warm_font_16 warm_font_17 warm_font_18 warm_font_19 warm_font_20 "
                 "warm_font_27 warm_digits_31 warm_digits_64)\n"
                 '  if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/main/boards/round-voice-175c/'
                 'warm_assets/${ROUND_FONT}.inc")\n'
                 '    message(FATAL_ERROR "Missing open round fonts. Run python '
                 'tools/generate_open_round_fonts.py --text-font <static-OFL-font.otf> '
                 '--license <OFL.txt>; see docs/round-open-source.md")\n'
                 "  endif()\nendforeach()\n\n")
        content = cmake.read_text(encoding="utf-8")
        if not content.startswith(check):
            cmake.write_text(check + content, encoding="utf-8")
    return [
        "Optional firmware source included; no compiled images or production SDK state.",
        "Original Windows-derived font assets omitted; explicitly regenerate twelve OFL font assets before building.",
        "Small upstream prompt audio retained under the upstream MIT distribution notice.",
        "Private service headers omitted; LAN archive and custom update services are unconfigured.",
        "Source defaults retained after credential/path checks; ESP-IDF dependencies resolve separately.",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--workspace", type=Path, default=TOOLS_ROOT.parent)
    args = parser.parse_args()
    try:
        for note in export_round_sources(args.workspace, args.dest):
            print(note)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Firmware source export failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
