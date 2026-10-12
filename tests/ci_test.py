#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Failure cases for CI coverage, dependency integrity and distributed release files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
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
                        "logical image vs fm1pkg.js: skipped (needs node and build/felucca.fwsc)",
                        "target: render cost 1 no budget (BUDGET_UPDATE=1 adds it)"):
            log.write_text(message + "\nALL HOST TESTS PASSED\n")
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, "incomplete test coverage"):
                ci.verify_tests(log)

    def test_only_the_unredistributed_vendor_fixture_skip_is_allowed(self):
        log = self.root / "tests.log"
        log.write_text("official V15 restore: skipped (needs FM-1_v15.fwsc in the repo root)\nALL HOST TESTS PASSED\n")
        with patch.object(ci.Path, "is_file", return_value=True):
            ci.verify_tests(log)

    def test_complete_tests_require_outputs(self):
        log = self.root / "tests.log"
        log.write_text("ALL HOST TESTS PASSED\n")
        with patch.object(ci.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "required test output missing"):
                ci.verify_tests(log)

    def release(self, root=None):
        root = root or self.root
        root.mkdir(parents=True, exist_ok=True)
        for name in ("felucca-1.6.fwsc", "felucca-1.6-app.bin", "LICENSE", "LICENSING.md",
                     "ATTRIBUTION.txt", "BUILD-PROVENANCE.json"):
            (root / name).write_text(name)
        raw = bytearray(ci.fm1_install.BLOCKS * ci.fm1_install.BLK)
        for i in range(ci.fm1_install.BLOCKS):
            raw[i * ci.fm1_install.BLK + ci.fm1_install.KEEP] = 0x7D
        for i, char in enumerate("FM-1_916"):
            raw[i * ci.fm1_install.BLK + ci.fm1_install.KEEP] = ord(char) + i + 1
        (root / "felucca-1.6.fwsc").write_bytes(raw + ci.fm1_install.LOADER_MARK)
        revision = ci.subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        (root / "BUILD-PROVENANCE.json").write_text(json.dumps({"revision": revision, "version": "1.6"}))
        for source in (ci.build.SRC / "LICENSES").glob("*.txt"):
            target = root / "LICENSES" / source.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
        self.checksums(root)

    def checksums(self, root=None):
        root = root or self.root
        files = sorted(p for p in root.rglob("*") if p.is_file() and p != root / "SHA256SUMS")
        (root / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n" for p in files))

    def bundle(self):
        output = self.root / "build"
        root = output / "release-1.6"
        self.release(root)
        (output / "ci").mkdir()
        metadata = json.loads((root / "BUILD-PROVENANCE.json").read_text())
        metadata["built_at_utc"] = "2026-10-12T09:00:00+00:00"
        (output / "ci/provenance.json").write_text(json.dumps(metadata))
        with patch.object(ci.build, "OUT", output):
            ci.finalize("1.6")
        return output, root

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

    def test_nested_checksum_file_is_also_covered(self):
        self.release()
        (self.root / "LICENSES/SHA256SUMS").write_text("extra manifest")
        with self.assertRaisesRegex(ValueError, "exactly all distributed files"):
            ci.package(self.root, "1.6")

    def test_malformed_checksum_lines_have_clear_errors(self):
        self.release()
        for line in ("", "abc", "0" * 64 + " file", "0" * 63 + "  file", "G" * 64 + "  file", "0" * 64 + "  "):
            (self.root / "SHA256SUMS").write_text(line + "\n")
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "malformed release checksum line"):
                ci.package(self.root, "1.6")

    def test_archive_is_identical_after_build_clock_and_file_metadata_changes(self):
        output, root = self.bundle()
        bundle = output / "felucca-1.6-release.tar.gz"
        original = bundle.read_bytes()
        diagnostic = output / "ci/provenance.json"
        metadata = json.loads(diagnostic.read_text())
        metadata["built_at_utc"] = "2026-10-12T10:00:00+00:00"
        diagnostic.write_text(json.dumps(metadata))
        for path in [root, *root.rglob("*")]:
            os.utime(path, (1_234_567, 1_234_567))
            path.chmod(0o700 if path.is_dir() else 0o600)
        with patch.object(ci.build, "OUT", output):
            ci.finalize("1.6")
        self.assertEqual(bundle.read_bytes(), original)
        self.assertEqual(json.loads(diagnostic.read_text())["built_at_utc"], metadata["built_at_utc"])
        self.assertNotIn("built_at_utc", json.loads((root / "BUILD-PROVENANCE.json").read_text()))
        epoch = int(ci.subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], text=True))
        self.assertEqual(int.from_bytes(original[4:8], "little"), epoch)
        self.assertEqual(original[3] & 8, 0)  # No output path in the gzip header.
        with tarfile.open(bundle) as archive:
            for info in archive.getmembers():
                self.assertEqual((info.uid, info.gid, info.uname, info.gname, info.mtime), (0, 0, "", "", epoch))
                self.assertEqual(info.mode, 0o755 if info.isdir() else 0o644)

    def test_release_page_assets_include_flat_licenses_and_valid_checksums(self):
        output, root = self.bundle()
        assets = self.root / "assets"
        ci.stage_release(root, output, assets, "1.6")
        for source in (ci.build.SRC / "LICENSES").glob("*.txt"):
            self.assertEqual((assets / source.name).read_bytes(), source.read_bytes())
        ci.verify_checksums(assets)
        self.assertNotIn("LICENSES/", (assets / "SHA256SUMS").read_text())
        self.assertIn("felucca-1.6-release.tar.gz", (assets / "SHA256SUMS").read_text())
        with tarfile.open(assets / "felucca-1.6-release.tar.gz") as archive:
            manifest = archive.extractfile("felucca-1.6/SHA256SUMS").read().decode()
            self.assertIn("LICENSES/Apache-2.0.txt", manifest)

    def test_release_page_staging_rejects_corrupt_archive(self):
        output, root = self.bundle()
        (output / "felucca-1.6-release.tar.gz").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "invalid release archive checksum"):
            ci.stage_release(root, output, self.root / "assets", "1.6")

    def test_release_page_staging_rejects_colliding_asset_names(self):
        output, root = self.bundle()
        for name in ("LICENSE", "SHA256SUMS"):
            path = root / "LICENSES" / name
            path.write_text("collision")
            with patch.object(ci.build, "OUT", output):
                ci.finalize("1.6")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "filenames collide"):
                ci.stage_release(root, output, self.root / "assets", "1.6")
            path.unlink()

    def test_publisher_cli_preserves_existing_repository_assets(self):
        output, root = self.bundle()
        shutil.copytree(root, self.root / "release")
        downloaded = self.root / "downloaded"
        downloaded.mkdir()
        for suffix in (".tar.gz", ".tar.gz.sha256"):
            shutil.copyfile(output / f"felucca-1.6-release{suffix}", downloaded / f"felucca-1.6-release{suffix}")
        existing = self.root / "assets/keep.txt"
        existing.parent.mkdir()
        existing.write_text("original asset")
        # The isolated publisher workspace still checks the actual source revision.
        env = dict(os.environ, GIT_DIR=ci.subprocess.check_output(
            ["git", "rev-parse", "--absolute-git-dir"], text=True).strip())
        result = ci.subprocess.run([sys.executable, str(ci.build.SRC / "tools/ci.py"), "stage-release", "1.6"],
                                   cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(existing.read_text(), "original asset")
        ci.verify_checksums(self.root / "release-assets")
        self.assertTrue((self.root / "release-assets/Apache-2.0.txt").is_file())


if __name__ == "__main__":
    unittest.main()
