#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Comparator fixtures use images, not mocked pixel counters."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from PIL import Image
import ui_compare as compare
import ui_render


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        Path("build").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir="build", prefix="ui-compare-test-")
        self.base = Path(self.temp.name)
        self.before, self.after, self.out = [self.base / n for n in ("before", "after", "report")]
        self.manifest = {"schema": 1,
                         "settings": {"width": 240, "height": 240, "mode": "RGB", "pixel_format": "RGB565-to-RGB888",
                                      "fm4": 0, "icons": 1, "slice": 1, "version": "test"},
                         "provenance": {"capture": "before-render", "revision": "fixture", "renderer_sha256": "fixture",
                                        "renderer": "tests/ui_render.c", "generator": "tests/ui_render.py",
                                        "inputs": {"font": "fixture", "generator": "fixture"}},
                         "scenes": []}
        self.image = Image.new("RGB", (240, 240), "black")
        self.write(self.before, self.image)
        self.write(self.after, self.image)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, directory, image, name="home", style="FLAT", palette="GREY", manifest=None):
        directory.mkdir(exist_ok=True)
        file = directory / f"{palette}_{style}_{name}.png"
        image.save(file)
        data = copy.deepcopy(manifest or self.manifest)
        data["scenes"] = [{"palette": palette, "style": style, "name": name, "file": file.name,
                           "sha256": compare.sha256(file), "required": True}]
        (directory / "manifest.json").write_text(json.dumps(data))
        return data

    def run_compare(self, **kwargs):
        return compare.compare(self.before, self.after, self.out, **kwargs)

    def test_identical_and_sheets(self):
        result = self.run_compare()
        self.assertEqual(result["status"], "identical")
        self.assertEqual(result["changed_pixels"], 0)
        self.assertIsNone(result["scenes"][0]["bbox"])
        self.assertTrue((self.out / result["sheets"][0]).is_file())
        self.assertTrue((self.out / "summary.json").is_file())

    def test_single_pixel_any_rgb_channel(self):
        for channel in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            image = self.image.copy()
            image.putpixel((12, 23), channel)
            self.write(self.after, image)
            result = self.run_compare()
            self.assertEqual(result["changed_pixels"], 1)
            self.assertEqual(result["scenes"][0]["bbox"], (12, 23, 13, 24))

    def test_moved_element(self):
        a, b = self.image.copy(), self.image.copy()
        for x in (10, 11):
            a.putpixel((x, 20), (255, 255, 255))
            b.putpixel((x + 5, 20), (255, 255, 255))
        self.write(self.before, a)
        self.write(self.after, b)
        result = self.run_compare()
        self.assertEqual(result["changed_pixels"], 4)
        self.assertEqual(result["scenes"][0]["bbox"], (10, 20, 17, 21))

    def test_dimension_and_mode_mismatch(self):
        for image in (Image.new("RGB", (239, 240)), Image.new("RGBA", (240, 240))):
            self.write(self.after, image)
            self.assertEqual(self.run_compare()["status"], "invalid")

    def test_normal_scene_cannot_override_dimensions(self):
        data = self.write(self.after, Image.new("RGB", (239, 240)))
        data["scenes"][0]["dimensions"] = [239, 240]
        (self.after / "manifest.json").write_text(json.dumps(data))
        self.assertEqual(self.run_compare()["status"], "invalid")

    def test_filmstrip_dimensions_are_positive_integers(self):
        for dimensions in ([0, 240], [True, 240], ["480", 240], [480]):
            data = self.write(self.after, self.image)
            data["scenes"][0].update(kind="filmstrip", dimensions=dimensions)
            (self.after / "manifest.json").write_text(json.dumps(data))
            self.assertEqual(self.run_compare(filmstrips=True)["status"], "invalid")

    def test_missing_file_and_missing_required_scene(self):
        (self.after / "GREY_FLAT_home.png").unlink()
        self.assertEqual(len(self.run_compare()["missing"]), 1)
        self.write(self.after, self.image, name="new")
        result = self.run_compare()
        self.assertEqual(result["added"], ["GREY/FLAT/new"])
        self.assertEqual(result["removed"], ["GREY/FLAT/home"])
        self.assertEqual(len(result["missing"]), 2)

    def test_missing_optional_file_still_reported(self):
        data = self.write(self.after, self.image)
        data["scenes"][0]["required"] = False
        (self.after / "manifest.json").write_text(json.dumps(data))
        (self.after / "GREY_FLAT_home.png").unlink()
        self.assertFalse(self.run_compare()["missing"][0]["required"])

    def test_incompatible_settings(self):
        for field, value in (("fm4", 1), ("icons", 0), ("slice", 0), ("pixel_format", "other")):
            manifest = copy.deepcopy(self.manifest)
            manifest["settings"][field] = value
            self.write(self.after, self.image, manifest=manifest)
            self.assertEqual(self.run_compare()["status"], "invalid")

    def test_version_change_is_provenance(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["settings"]["version"] = "next-release"
        self.write(self.after, self.image, manifest=manifest)
        self.assertEqual(self.run_compare()["status"], "identical")

    def test_duplicate_unknown_selection_and_unverified_provenance(self):
        manifest = self.write(self.after, self.image)
        manifest["scenes"] *= 2
        (self.after / "manifest.json").write_text(json.dumps(manifest))
        self.assertEqual(self.run_compare()["status"], "invalid")
        self.write(self.after, self.image)
        self.assertEqual(self.run_compare(names=["absent"])["status"], "invalid")
        manifest = copy.deepcopy(self.manifest)
        manifest["provenance"]["capture"] = "conversion-only"
        self.write(self.after, self.image, manifest=manifest)
        self.assertEqual(self.run_compare()["status"], "invalid")

    def test_hash_and_path_validation(self):
        (self.after / "GREY_FLAT_home.png").write_bytes(b"changed")
        self.assertEqual(self.run_compare()["status"], "invalid")
        manifest = self.write(self.after, self.image)
        manifest["scenes"][0]["file"] = "../escape.png"
        (self.after / "manifest.json").write_text(json.dumps(manifest))
        self.assertEqual(self.run_compare()["status"], "invalid")

    def test_palette_style_name_pairing_not_filenames(self):
        for palette, style in (("MONO", "LINE"), ("GREEN", "FLAT"), ("GREY", "LARGE"), ("GREY", "LARGE-LINE")):
            self.write(self.before, self.image, palette=palette, style=style)
            data = self.write(self.after, self.image, palette=palette, style=style)
            old = self.after / data["scenes"][0]["file"]
            old.rename(self.after / "renamed.png")
            data["scenes"][0]["file"] = "renamed.png"
            (self.after / "manifest.json").write_text(json.dumps(data))
            self.assertEqual(self.run_compare()["status"], "identical")

    def test_filmstrips_only_when_selected(self):
        for directory in (self.before, self.after):
            data = self.write(directory, self.image)
            strip = Image.new("RGB", (480, 240))
            strip.save(directory / "strip.png")
            data["scenes"].append({"palette": "GREY", "style": "FILMSTRIP", "name": "bpm_roll", "kind": "filmstrip",
                                   "dimensions": [480, 240], "file": "strip.png", "sha256": compare.sha256(directory / "strip.png"), "required": True})
            (directory / "manifest.json").write_text(json.dumps(data))
        self.assertEqual(len(self.run_compare()["scenes"]), 1)
        self.assertEqual(len(self.run_compare(filmstrips=True)["scenes"]), 2)

    def test_report_and_strict_exit_codes(self):
        def run(strict):
            cmd = [sys.executable, "tests/ui_compare.py", str(self.before), str(self.after), "--out", str(self.out)]
            return subprocess.run(cmd + (["--strict"] if strict else []), capture_output=True).returncode
        self.assertEqual(run(True), 0)
        self.write(self.after, Image.new("RGB", (240, 240), "white"))
        self.assertEqual(run(False), 0)
        self.assertEqual(run(True), 1)
        self.write(self.after, Image.new("RGB", (239, 240)))
        self.assertEqual(run(False), 0)
        self.assertEqual(run(True), 2)

    def test_malformed_container_shapes_keep_report_and_exit_contract(self):
        variants = [[]]
        for field, value in (("settings", []), ("provenance", []), ("scenes", {}), ("scenes", [None])):
            data = copy.deepcopy(self.write(self.after, self.image))
            data[field] = value
            variants.append(data)
        data = copy.deepcopy(self.write(self.after, self.image))
        data["provenance"]["inputs"] = []
        variants.append(data)
        for data in variants:
            (self.after / "manifest.json").write_text(json.dumps(data))
            for strict, expected in ((False, 0), (True, 2)):
                cmd = [sys.executable, "tests/ui_compare.py", str(self.before), str(self.after), "--out", str(self.out)]
                result = subprocess.run(cmd + (["--strict"] if strict else []), capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                summary = json.loads((self.out / "summary.json").read_text())
                self.assertEqual(summary["status"], "invalid")

    def test_explicit_filmstrip_selection_requires_a_capture(self):
        self.assertEqual(self.run_compare(filmstrips=True)["status"], "invalid")

    def test_conversion_uses_current_filmstrip_inventory(self):
        capture, slot = self.base / "capture", self.base / "slot"
        (capture / "ppm").mkdir(parents=True)
        slot.mkdir()
        self.image.save(capture / "ppm/GREY_home.ppm")
        (capture / "scenes.txt").write_text("GREY_home\n")
        (capture / "render_settings.json").write_text(json.dumps(self.manifest["settings"]))
        strip = Image.new("RGB", (480, 240))
        strip.save(slot / "GREY_current.ppm")
        strip.save(slot / "GREY_stale.ppm")
        (capture / "filmstrips.txt").write_text("GREY_current.ppm\n")
        ui_render.convert(SimpleNamespace(out=capture, slot=slot, provenance=self.manifest["provenance"]))
        manifest = json.loads((capture / "manifest.json").read_text())
        self.assertEqual([s["name"] for s in manifest["scenes"] if s.get("kind") == "filmstrip"], ["current"])
        self.assertTrue((slot / "GREY_stale.ppm").exists())
        self.assertFalse((capture / "filmstrips/GREY_stale.png").exists())

    def test_report_cannot_modify_inputs(self):
        with self.assertRaises(ValueError):
            compare.compare(self.before, self.after, self.before)

    def test_failed_recapture_invalidates_old_success_manifest(self):
        result = subprocess.run([sys.executable, "tests/ui_render.py", str(self.after),
                                 "--renderer", str(self.base / "renderer"), "--cc", "false"],
                                capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.after / "manifest.json").exists())

    def test_deterministic_paginated_sheets(self):
        images = [(f"scene {n}", (self.image, self.image, self.image)) for n in range(25)]
        self.out.mkdir()
        files = compare.write_sheets(self.out, images)
        self.assertEqual(files, ["comparison_001.png", "comparison_002.png", "comparison_003.png"])
        hashes = [compare.sha256(self.out / file) for file in files]
        compare.write_sheets(self.out, images)
        self.assertEqual(hashes, [compare.sha256(self.out / file) for file in files])


if __name__ == "__main__":
    unittest.main()
