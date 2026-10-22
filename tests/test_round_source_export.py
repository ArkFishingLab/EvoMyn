"""Public firmware export must not inherit the workstation's private assets."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    path = ROOT / "tools" / (name + ".py")
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class RoundSourceExportTests(unittest.TestCase):
    def test_public_host_checks_include_licensed_cjson_and_native_fixtures(self):
        import hashlib
        import json
        exporter = module("export_round_sources")
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "firmware"
            exporter.export_round_sources(ROOT, dest)
            support = dest / "tests/support/cjson"
            metadata = json.loads((support / "SOURCE.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["component_version"], "1.7.19~2")
            for name in ("cJSON.c", "cJSON.h", "LICENSE"):
                self.assertEqual(hashlib.sha256((support / name).read_bytes()).hexdigest(),
                                 metadata["sha256"][name])
            self.assertTrue((dest / "tests/native-local-planner.cpp").is_file())
            self.assertTrue((dest / "tests/native-round-update-wire.cpp").is_file())
            self.assertTrue((dest / "scripts/tests/host_test_paths.py").is_file())
            self.assertFalse((dest / "managed_components").exists())

    @unittest.skipUnless(os.name == "nt", "Windows host-fixture junction regression")
    def test_public_host_fixture_rejects_junction_ancestor_before_copy(self):
        import _winapi
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            firmware = workspace / "xiaozhi-firmware"
            firmware.mkdir(parents=True)
            (firmware / "LICENSE").write_text("MIT License")
            external = Path(temp) / "external"
            external.mkdir()
            (external / "cJSON.c").write_text("NOT_PUBLIC")
            support = workspace / "tests/support"
            support.mkdir(parents=True)
            _winapi.CreateJunction(str(external), str(support / "cjson"))
            dest = Path(temp) / "export"
            with self.assertRaisesRegex(ValueError, "[Rr]eparse|[Ll]ink"):
                module("export_round_sources").export_round_sources(workspace, dest)
            self.assertFalse(dest.exists())

    def test_export_requires_exporter(self):
        self.assertIsNotNone(module("export_round_sources"), "public exporter is missing")

    def test_export_excludes_private_fonts_build_outputs_and_unconfigured_services(self):
        exporter = module("export_round_sources")
        self.assertIsNotNone(exporter, "public exporter is missing")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            firmware = workspace / "xiaozhi-firmware"
            files = {
                "LICENSE": "MIT License\nCopyright test\n",
                "CMakeLists.txt": "project(xiaozhi)\n",
                "main/idf_component.yml": "dependencies: {}\n",
                "main/Kconfig.projbuild": 'config TEST\n    bool "Test"\n',
                "main/boards/round-voice-175c/config.json": '{}\n',
                "main/boards/round-voice-175c/config.h": '#pragma once\n',
                "main/boards/round-voice-175c/round_voice_175c.cc": '#define ROUND_SERVICE_TOKEN ""\n',
                "main/boards/round-voice-175c/warm_font_20.cc": '#include "warm_assets/warm_font_20.inc"\n',
                "main/boards/round-voice-175c/warm_icons.cc": '// native simple icons\n',
                "main/boards/round-voice-175c/warm_assets/warm_font_20.inc": 'PROPRIETARY\n',
                "main/boards/round-voice-175c/round_services_private.h": 'SECRET\n',
                "main/boards/round-voice-175c/planner_private.h": 'SECRET\n',
                "main/assets/lang_config.h": 'GENERATED\n',
                "main/assets/common/exclamation.ogg": 'AUDIO\n',
                "build/config.h": 'SECRET\n',
                "sdkconfig.defaults": 'CONFIG_COMPILER_OPTIMIZATION_SIZE=y\n',
                "managed_components/vendor/font.c": 'VENDOR\n',
                "components/vendor/font.c": 'VENDOR\n',
                "main/boards/round-voice-175c/firmware.bin": 'BINARY\n',
                "main/boards/round-voice-175c/credentials.json": 'SECRET\n',
                "main/boards/round-voice-175c/nvs.csv": 'SECRET\n',
                "main/personal-notes.md": 'UNREVIEWED\n',
                "main/unreviewed.cc": 'UNREVIEWED\n',
                ".git/config": 'PRIVATE REMOTE\n',
                "partitions/v2/32m.csv": '# partition\n',
            }
            for name, content in files.items():
                target = firmware / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            dest = Path(temp) / "export"
            notes = exporter.export_round_sources(workspace, dest)
            self.assertTrue((dest / "LICENSE").is_file())
            self.assertTrue((dest / "main/boards/round-voice-175c/warm_icons.cc").is_file())
            self.assertTrue((dest / "tools/generate_open_round_fonts.py").is_file())
            self.assertTrue(any("font" in note.lower() for note in notes))
            exported = [p for p in dest.rglob("*") if p.is_file()]
            self.assertFalse(any(p.suffix in {".inc", ".bin", ".ttf"} for p in exported))
            self.assertTrue((dest / "main/assets/common/exclamation.ogg").is_file())
            self.assertFalse(any("private" in p.name.lower() for p in exported))
            self.assertFalse((dest / "build").exists())
            self.assertFalse((dest / "managed_components").exists())
            self.assertFalse((dest / "components").exists())
            self.assertNotIn("SECRET", "\n".join(p.read_text(encoding="utf-8") for p in exported))
            self.assertFalse((dest / "main/personal-notes.md").exists())
            self.assertFalse((dest / "main/unreviewed.cc").exists())

    def test_export_refuses_nonempty_and_source_destinations(self):
        exporter = module("export_round_sources")
        self.assertIsNotNone(exporter, "public exporter is missing")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            (workspace / "xiaozhi-firmware").mkdir()
            with self.assertRaises(ValueError):
                exporter.export_round_sources(workspace, workspace / "xiaozhi-firmware")
            dest = workspace / "dest"
            dest.mkdir()
            (dest / "sentinel").write_text("keep")
            with self.assertRaises(ValueError):
                exporter.export_round_sources(workspace, dest)
            self.assertEqual((dest / "sentinel").read_text(), "keep")

    def test_export_refuses_source_destination_with_parent_traversal(self):
        exporter = module("export_round_sources")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            (workspace / "xiaozhi-firmware").mkdir()
            (workspace / "other").mkdir()
            candidate = workspace / "other/../xiaozhi-firmware/export"
            with self.assertRaisesRegex(ValueError, "outside"):
                exporter.export_round_sources(workspace, candidate)
            self.assertFalse((workspace / "xiaozhi-firmware/export").exists())

    def test_font_check_reports_all_twelve_missing_assets(self):
        generator = ROOT / "tools/generate_open_round_fonts.py"
        self.assertTrue(generator.exists(), "open font generator is missing")
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(generator), "--board", temp, "--check"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("warm_font_11.inc", result.stderr)
            self.assertIn("warm_digits_31.inc", result.stderr)
            self.assertIn("warm_digits_64.inc", result.stderr)
            self.assertIn("--text-font", result.stderr)

    def test_font_commands_are_pinned_and_use_digits_font(self):
        generator = module("generate_open_round_fonts")
        self.assertIsNotNone(generator, "open font generator is missing")
        commands = generator.font_commands(Path("board"), Path("text.otf"), Path("digits.ttf"), "中文ABC")
        self.assertEqual(len(commands), 12)
        for command in commands:
            self.assertIn("lv_font_conv@1.5.3", command)
            name = command[command.index("--lv-font-name") + 1]
            font = command[command.index("--font") + 1]
            self.assertEqual(font, "digits.ttf" if name.startswith("warm_digits") else "text.otf")
            self.assertEqual(command[command.index("--bpp") + 1], "4")
            self.assertIn("--no-kerning", command)

    def test_windows_npx_prefix_bypasses_cmd_glyph_metacharacters(self):
        generator = module("generate_open_round_fonts")
        self.assertIsNotNone(generator, "open font generator is missing")
        self.assertTrue(hasattr(generator, "npx_prefix"), "Windows shell-free npx execution is missing")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = root / "node_modules/npm/bin/npx-cli.js"
            cli.parent.mkdir(parents=True)
            cli.write_text("// fixture")
            cmd = root / "npx.cmd"
            self.assertEqual(generator.npx_prefix(str(cmd), "node.exe"), ["node.exe", str(cli)])
            self.assertEqual(generator.npx_prefix("/usr/bin/npx", "/usr/bin/node"), ["/usr/bin/npx"])

    def test_export_rejects_symlinks_without_reading_targets(self):
        exporter = module("export_round_sources")
        self.assertIsNotNone(exporter, "public exporter is missing")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            firmware = workspace / "xiaozhi-firmware"
            board = firmware / "main/boards/round-voice-175c"
            board.mkdir(parents=True)
            (firmware / "LICENSE").write_text("MIT License")
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "leak.h").write_text("SECRET")
            try:
                (board / "linked").symlink_to(outside, target_is_directory=True)
                (board / "leak.h").symlink_to(outside / "leak.h")
            except OSError:
                self.skipTest("symlinks are unavailable on this host")
            dest = Path(temp) / "export"
            with self.assertRaisesRegex(ValueError, "[Rr]eparse|[Ll]ink"):
                exporter.export_round_sources(workspace, dest)
            self.assertFalse(dest.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_export_rejects_windows_junction_before_target_read(self):
        exporter = module("export_round_sources")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            source = workspace / "xiaozhi-firmware"
            board = source / "main/boards/round-voice-175c"
            board.mkdir(parents=True)
            (source / "LICENSE").write_text("MIT License")
            external = Path(temp) / "external"
            external.mkdir()
            (external / "header.h").write_text("EXTERNAL MUST NOT BE READ")
            junction = board / "linked"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(external)],
                                    capture_output=True, text=True)
            if result.returncode:
                self.skipTest("junction creation unavailable")
            try:
                self.assertFalse(junction.is_symlink(), "regression specifically exercises a junction")
                with self.assertRaisesRegex(ValueError, "[Rr]eparse|[Ll]ink"):
                    exporter.export_round_sources(workspace, Path(temp) / "export")
                self.assertFalse((Path(temp) / "export").exists())
                self.assertEqual((external / "header.h").read_text(), "EXTERNAL MUST NOT BE READ")
            finally:
                junction.rmdir()

    def test_public_layout_reexports_identically_with_packaged_helpers(self):
        exporter = module("export_round_sources")
        if not (ROOT / "xiaozhi-firmware/LICENSE").is_file():
            self.skipTest("production firmware source is not installed")
        with tempfile.TemporaryDirectory() as temp:
            public = Path(temp) / "public"
            first = public / "firmware"
            exporter.export_round_sources(ROOT, first)
            (public / "tools").mkdir()
            for name in ("export_round_sources.py", "public_round_files.json"):
                shutil.copyfile(ROOT / "tools" / name, public / "tools" / name)
            second = Path(temp) / "second"
            result = subprocess.run([sys.executable, str(public / "tools/export_round_sources.py"),
                                     str(second), "--workspace", str(public)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            first_files = {path.relative_to(first).as_posix(): path.read_bytes()
                           for path in first.rglob("*") if path.is_file()}
            second_files = {path.relative_to(second).as_posix(): path.read_bytes()
                            for path in second.rglob("*") if path.is_file()}
            self.assertEqual(first_files, second_files)

    def test_font_validation_refuses_missing_coverage_and_non_ofl_license(self):
        if not importlib.util.find_spec("fontTools"):
            self.skipTest("fonttools is an optional firmware-authoring dependency")
        generator = module("generate_open_round_fonts")
        self.assertIsNotNone(generator, "open font generator is missing")
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        with tempfile.TemporaryDirectory() as temp:
            font_path = Path(temp) / "fixture.ttf"
            license_path = Path(temp) / "OFL.txt"
            builder = FontBuilder(1000, isTTF=True)
            builder.setupGlyphOrder([".notdef", "A"])
            builder.setupCharacterMap({65: "A"})
            pen = TTGlyphPen(None)
            empty = pen.glyph()
            builder.setupGlyf({".notdef": empty, "A": empty})
            builder.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
            builder.setupHorizontalHeader(ascent=800, descent=-200)
            builder.setupNameTable({"familyName": "Round Test Fixture", "styleName": "Regular"})
            builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
            builder.setupPost()
            builder.save(font_path)
            license_path.write_text("All rights reserved")
            with self.assertRaisesRegex(ValueError, "SIL Open Font License"):
                generator.validate_font(font_path, license_path, "A")
            license_path.write_text("SIL OPEN FONT LICENSE Version 1.1\nTest fixture only")
            with self.assertRaisesRegex(ValueError, "U\\+0042"):
                generator.validate_font(font_path, license_path, "AB")
            metadata = generator.validate_font(font_path, license_path, "A")
            self.assertEqual(metadata["file"], "fixture.ttf")
            self.assertEqual(len(metadata["sha256"]), 64)

    def test_actual_firmware_export_lists_the_round_variant_and_omits_fonts(self):
        if not (ROOT / "xiaozhi-firmware/LICENSE").is_file():
            self.skipTest("production firmware source is not installed")
        exporter = module("export_round_sources")
        self.assertIsNotNone(exporter, "public exporter is missing")
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "firmware"
            exporter.export_round_sources(ROOT, dest)
            files = [path for path in dest.rglob("*") if path.is_file()]
            self.assertFalse(any("private" in path.name.lower() for path in files))
            self.assertFalse(any(path.suffix.lower() in {".bin", ".inc", ".ttf", ".otf"} for path in files))
            self.assertTrue((dest / "main/boards/round-voice-175c/warm_font_27.cc").is_file())
            self.assertTrue((dest / "sdkconfig.defaults.esp32s3").is_file())
            board = dest / "main/boards/round-voice-175c/round_voice_175c.cc"
            self.assertIn('#define ROUND_SERVICE_TOKEN ""', board.read_text(encoding="utf-8"))
            result = subprocess.run([sys.executable, str(dest / "scripts/build.py"), "--list-boards"],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("round-voice-175c", result.stdout)


if __name__ == "__main__":
    unittest.main()
