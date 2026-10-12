#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Failure cases for CI coverage, dependency integrity and distributed release files."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ci


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_versions_follow_package_identity_limits(self):
        for value in ("1.6", "1.6.2", "1.6.2.1", "1.6-rc1"):
            self.assertEqual(ci.version(value), value)
        for value in ("v1.6", "12.0", "1.10", "1.6/../../x", "$(echo bad)", "1.6\nVERSION=x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ci.version(value)

    def test_cached_sdk_corruption_is_rejected(self):
        with patch.dict(ci.build.SDK_SHA256, {"uboot.boot": hashlib.sha256(b"good").hexdigest()}, clear=True):
            path = self.root / "cpu/wl82/tools/uboot.boot"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"good")
            ci.check_sdk(self.root)
            path.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                ci.check_sdk(self.root)

    def test_failed_sdk_download_never_replaces_cache(self):
        with patch.dict(ci.build.SDK_SHA256, {"uboot.boot": "0" * 64}, clear=True), \
                patch.object(ci.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(ValueError):
                ci.fetch_sdk(self.root)
            self.assertFalse((self.root / "cpu/wl82/tools/uboot.boot").exists())

    def test_success_message_does_not_hide_skipped_tests(self):
        log = self.root / "tests.log"
        for message in ("== skip the sanitizer runs (the compiler has no ASan / UBSan)",
                        "target: skip (build/felucca.dis missing)",
                        "target: render cost 1 no budget (BUDGET_UPDATE=1 adds it)"):
            log.write_text(message + "\nALL HOST TESTS PASSED\n")
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, "incomplete test coverage"):
                ci.verify_tests(log)

    def test_complete_tests_require_outputs(self):
        log = self.root / "tests.log"
        log.write_text("ALL HOST TESTS PASSED\n")
        with patch.object(ci.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "required test output missing"):
                ci.verify_tests(log)

    def release(self):
        for name in ("felucca-1.6.fwsc", "felucca-1.6-app.bin", "LICENSE", "LICENSING.md",
                     "ATTRIBUTION.txt", "BUILD-PROVENANCE.json"):
            (self.root / name).write_text(name)
        raw = bytearray(ci.fm1_install.BLOCKS * ci.fm1_install.BLK)
        for i in range(ci.fm1_install.BLOCKS):
            raw[i * ci.fm1_install.BLK + ci.fm1_install.KEEP] = 0x7D
        for i, char in enumerate("FM-1_916"):
            raw[i * ci.fm1_install.BLK + ci.fm1_install.KEEP] = ord(char) + i + 1
        (self.root / "felucca-1.6.fwsc").write_bytes(raw + ci.fm1_install.LOADER_MARK)
        revision = ci.subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        (self.root / "BUILD-PROVENANCE.json").write_text(json.dumps({"revision": revision, "version": "1.6"}))
        for source in (ci.build.SRC / "LICENSES").glob("*.txt"):
            target = self.root / "LICENSES" / source.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
        self.checksums()

    def checksums(self):
        files = sorted(p for p in self.root.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (self.root / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(self.root)}\n" for p in files))

    def test_release_corruption_and_omitted_licenses_fail(self):
        self.release()
        ci.package(self.root, "1.6")
        (self.root / "felucca-1.6.fwsc").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "invalid release checksum"):
            ci.package(self.root, "1.6")
        self.checksums()
        (self.root / "LICENSES/Apache-2.0.txt").unlink()
        self.checksums()
        with self.assertRaisesRegex(ValueError, "release file missing"):
            ci.package(self.root, "1.6")

    def test_release_checksums_cover_every_file_without_path_escape(self):
        self.release()
        (self.root / "extra.txt").write_text("unlisted")
        with self.assertRaisesRegex(ValueError, "exactly all distributed files"):
            ci.package(self.root, "1.6")
        self.checksums()
        with (self.root / "SHA256SUMS").open("a") as out:
            out.write("0" * 64 + "  ../outside\n")
        with self.assertRaisesRegex(ValueError, "invalid release checksum"):
            ci.package(self.root, "1.6")

    def test_stale_release_provenance_fails_even_with_valid_checksums(self):
        self.release()
        (self.root / "BUILD-PROVENANCE.json").write_text(json.dumps({"revision": "stale", "version": "1.6"}))
        self.checksums()
        with self.assertRaisesRegex(ValueError, "provenance does not match"):
            ci.package(self.root, "1.6")

    def test_wrong_package_product_fails_even_with_valid_checksums(self):
        self.release()
        path = self.root / "felucca-1.6.fwsc"
        raw = bytearray(path.read_bytes())
        raw[7 * ci.fm1_install.BLK + ci.fm1_install.KEEP] = ord('5') + 8
        path.write_bytes(raw)
        self.checksums()
        with self.assertRaisesRegex(ValueError, "release product"):
            ci.package(self.root, "1.6")


if __name__ == "__main__":
    unittest.main()
