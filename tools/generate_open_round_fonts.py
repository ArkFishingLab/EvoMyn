"""Regenerate the optional public round firmware fonts from licensed local fonts.

No fonts are downloaded or taken from the operating system. See
docs/round-open-source.md before generating or redistributing font assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

TEXT_SIZES = (11, 13, 14, 15, 16, 17, 18, 19, 20, 27)
DIGIT_SIZES = (31, 64)
DIGIT_SYMBOLS = "0123456789:-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ASSET_NAMES = tuple(f"warm_font_{size}" for size in TEXT_SIZES) + tuple(
    f"warm_digits_{size}" for size in DIGIT_SIZES)
LV_FONT_CONV_VERSION = "1.5.3"


def font_commands(board: Path, text_font: Path, digits_font: Path,
                  symbols: str) -> list[list[str]]:
    """Return inspectable, pinned commands; caller controls all filesystem writes."""
    commands = []
    for name in ASSET_NAMES:
        digits = name.startswith("warm_digits_")
        commands.append([
            "npx", "--yes", f"lv_font_conv@{LV_FONT_CONV_VERSION}",
            "--size", name.rsplit("_", 1)[1], "--bpp", "4", "--format", "lvgl",
            "--font", str(digits_font if digits else text_font),
            "--symbols", DIGIT_SYMBOLS if digits else symbols,
            "--no-compress", "--no-kerning", "--lv-font-name", name,
            "--output", str(board / "warm_assets" / (name + ".inc")),
        ])
    return commands


def npx_prefix(npx: str, node: str | None) -> list[str]:
    """Avoid Windows batch argument reparsing of glyphs such as &, < and %."""
    if Path(npx).suffix.lower() not in {".cmd", ".bat"}:
        return [npx]
    cli = Path(npx).parent / "node_modules/npm/bin/npx-cli.js"
    if not node or not cli.is_file():
        raise ValueError("Use a Node.js/npm installation with node and node_modules/npm/bin/npx-cli.js "
                         "next to npx.cmd; passing font glyphs through a batch shell is unsafe")
    return [node, str(cli)]


def required_symbols(board: Path) -> str:
    """Include ASCII plus Unicode in public board sources, including UI text."""
    symbols = set(chr(value) for value in range(32, 127))
    symbols.update("•·：，。—（）？！")
    for path in sorted(board.iterdir()):
        if (path.is_symlink() or "private" in path.name.lower()
                or path.suffix not in {".h", ".cc", ".cpp"}):
            continue
        symbols.update(char for char in path.read_text(encoding="utf-8")
                       if ord(char) >= 128 and not char.isspace())
    return "".join(sorted(symbols))


def validate_font(path: Path, license_path: Path, symbols: str) -> dict:
    """Require explicit OFL evidence and complete glyph coverage before output."""
    if path.suffix.lower() not in {".ttf", ".otf"} or not path.is_file():
        raise ValueError(f"Expected a local .ttf/.otf font: {path.name}")
    if not license_path.is_file():
        raise ValueError("Provide the font's OFL license file with --license")
    license_text = license_path.read_text(encoding="utf-8-sig")
    if "SIL OPEN FONT LICENSE" not in license_text.upper():
        raise ValueError("This generator requires a SIL Open Font License font and its license text")
    try:
        from fontTools.ttLib import TTFont
    except ImportError as error:
        raise ValueError("Install fonttools==4.61.1 in a dedicated environment first") from error
    with TTFont(path) as font:
        if "fvar" in font:
            raise ValueError("Use a static font file; variable fonts must be instantiated first")
        cmap = font.getBestCmap() or {}
        missing = sorted({ord(char) for char in symbols} - cmap.keys())
        if missing:
            sample = ", ".join(f"U+{value:04X}" for value in missing[:16])
            raise ValueError(f"{path.name} lacks {len(missing)} required glyphs ({sample})")
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license": "SIL Open Font License", "license_file": license_path.name}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=(Path(__file__).resolve().parents[1]
                        / "main/boards/round-voice-175c"))
    parser.add_argument("--check", action="store_true", help="Check the twelve required assets only")
    parser.add_argument("--text-font", type=Path, help="Static OFL CJK font with Latin and symbols")
    parser.add_argument("--digits-font", type=Path, help="Static OFL Latin font; defaults to text font")
    parser.add_argument("--license", type=Path, help="OFL license accompanying the text font")
    parser.add_argument("--digits-license", type=Path, help="OFL license if digits use another font")
    parser.add_argument("--dry-run", action="store_true", help="Validate fonts and print commands without conversion")
    args = parser.parse_args(argv)
    if args.check:
        missing = [name + ".inc" for name in ASSET_NAMES
                   if not (args.board / "warm_assets" / (name + ".inc")).is_file()]
        if missing:
            print("Missing open font assets: " + ", ".join(missing), file=sys.stderr)
            print("Regenerate with --text-font <static-OFL-font.otf> --license <OFL.txt>; "
                  "see docs/round-open-source.md", file=sys.stderr)
            return 1
        print("All twelve round font assets are present.")
        return 0
    if not args.text_font or not args.license:
        parser.error("--text-font and --license are required (no proprietary fonts are supplied)")
    try:
        if not args.board.is_dir():
            raise ValueError("--board must point to the exported round-voice-175c directory")
        text_font = args.text_font.resolve()
        digits_font = (args.digits_font or args.text_font).resolve()
        digits_license = args.digits_license or args.license
        if args.digits_font and digits_font != text_font and not args.digits_license:
            raise ValueError("A separate digits font requires --digits-license")
        symbols = required_symbols(args.board)
        metadata = {"text": validate_font(text_font, args.license, symbols),
                    "digits": validate_font(digits_font, digits_license, DIGIT_SYMBOLS),
                    "converter": f"lv_font_conv@{LV_FONT_CONV_VERSION}",
                    "fonttools": "4.61.1", "generated": list(ASSET_NAMES)}
        if args.dry_run:
            print(json.dumps(font_commands(args.board, text_font, digits_font, symbols),
                             ensure_ascii=False, indent=2))
            return 0
        npx = shutil.which("npx")
        if not npx:
            raise ValueError("Node.js/npm are required; npx was not found in PATH")
        prefix = npx_prefix(npx, shutil.which("node"))
        # Finish all conversions before replacing assets, avoiding partial regeneration.
        with tempfile.TemporaryDirectory(prefix="round-open-fonts-") as temp:
            staging = Path(temp)
            (staging / "warm_assets").mkdir()
            for command in font_commands(staging, text_font, digits_font, symbols):
                subprocess.run(prefix + command[1:], check=True)
            output = args.board / "warm_assets"
            output.mkdir(exist_ok=True)
            for name in ASSET_NAMES:
                generated = staging / "warm_assets" / (name + ".inc")
                # lv_font_conv embeds its full invocation (including private paths).
                content = generated.read_text(encoding="utf-8")
                if content.startswith("/**"):
                    content = content[content.index("*/") + 2:].lstrip()
                (output / generated.name).write_text(
                    "/* Generated from OFL fonts; see open-font-provenance.json. */\n" + content,
                    encoding="utf-8")
            (output / "open-font-provenance.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            shutil.copyfile(args.license, output / "OFL-text.txt")
            shutil.copyfile(digits_license, output / "OFL-digits.txt")
        print("Generated twelve open font assets. Retain both OFL files and provenance on redistribution.")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Open font generation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
