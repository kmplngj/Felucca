#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable patch/pin and refusal contracts; real execution has a separate opt-in test."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import emulator_trace as helper


class TraceContracts(unittest.TestCase):
    def setUp(self):
        (ROOT / "build").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="emulator-trace-contract-", dir=ROOT / "build")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "donor"
        self.source.mkdir()
        helper.run(["git", "-c", "init.templateDir=", "init", "--quiet", self.source])
        (self.source / "input.rs").write_text("// reviewed fixture\n")
        helper.run(["git", "-C", self.source, "add", "input.rs"])
        helper.run(["git", "-C", self.source, "-c", "user.name=Trace test", "-c", "user.email=trace@example.invalid", "commit", "--quiet", "-m", "fixture"])
        self.pin = {"commit": helper.git(self.source, "rev-parse", "HEAD"),
                    "source_sha256": {"input.rs": helper.sha((self.source / "input.rs").read_bytes())},
                    "rust_toolchain": "1.99.1"}

    def test_reviewed_patch_and_mixed_license_closure(self):
        pin = helper.read_pin()
        self.assertEqual(pin["schema_version"], 1)
        self.assertEqual(pin["crates"], ["fm1-emu", "fm1-core", "fm1-isa", "fm1-soc"])
        self.assertEqual(len(pin["source_sha256"]), 31)
        self.assertEqual(helper.sha((helper.DATA / "LICENSE-MIT-fm1-emu.txt").read_bytes()), pin["source_sha256"]["LICENSE"])
        self.assertEqual(pin["licenses"]["GPL-3.0-only"]["files"], ["crates/fm1-soc/src/usb.rs"])
        patch_text = (helper.DATA / "retired-trace.patch").read_text()
        self.assertEqual(patch_text.count("diff --git "), 1)
        self.assertIn("# SPDX-License-Identifier: MIT", patch_text)
        self.assertIn("crates/fm1-emu/src/main.rs", patch_text)

    def test_clean_checkout_is_accepted(self):
        helper.check_checkout(self.source, self.pin)

    def test_wrong_commit_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unsupported emulator commit"):
            helper.check_checkout(self.source, dict(self.pin, commit="0" * 40))

    def test_dirty_tracked_source_is_refused(self):
        (self.source / "input.rs").write_text("// unreviewed\n")
        with self.assertRaisesRegex(ValueError, "must be clean"):
            helper.check_checkout(self.source, self.pin)

    def test_staged_source_is_refused(self):
        (self.source / "input.rs").write_text("// staged\n")
        helper.run(["git", "-C", self.source, "add", "input.rs"])
        with self.assertRaisesRegex(ValueError, "must be clean"):
            helper.check_checkout(self.source, self.pin)

    def test_untracked_source_is_refused(self):
        (self.source / "extra.rs").write_text("// extra\n")
        with self.assertRaisesRegex(ValueError, "must be clean"):
            helper.check_checkout(self.source, self.pin)

    def test_subdirectory_is_refused(self):
        subdir = self.source / "nested"
        subdir.mkdir()
        with self.assertRaisesRegex(ValueError, "checkout root"):
            helper.check_checkout(subdir, self.pin)

    def test_source_hash_mismatch_is_refused(self):
        bad = dict(self.pin, source_sha256={"input.rs": "0" * 64})
        with self.assertRaisesRegex(ValueError, "source bytes differ"):
            helper.check_checkout(self.source, bad)

    def test_symlinked_source_is_refused(self):
        real = self.source / "input.rs"
        link = self.source / "link.rs"
        link.symlink_to(real)
        with self.assertRaisesRegex(ValueError, "symlinked source"):
            helper.inventory(self.source, ["link.rs"])

    def test_outside_ignored_build_is_refused(self):
        with self.assertRaisesRegex(ValueError, "ignored build"):
            helper.ignored_path(ROOT / "tools")

    def test_existing_or_overlapping_output_is_refused(self):
        for out in (self.directory, self.source / "new-output"):
            with self.subTest(out=out), self.assertRaisesRegex(ValueError, "new and separate"):
                helper.build(self.source, out)

    def test_missing_compiler_does_not_patch_source(self):
        with patch.object(helper, "read_pin", return_value=self.pin), patch.object(helper.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "cargo is unavailable"):
                helper.build(self.source, self.directory / "missing-compiler")
        helper.check_checkout(self.source, self.pin)
        self.assertFalse((self.directory / "missing-compiler").exists())

    def test_narrow_workspace_retains_reviewed_settings(self):
        pin = helper.read_pin()
        original = ('[workspace]\nmembers = ["unrelated"]\n'
                    '[workspace.package]\nversion="0.2.0"\nedition="2021"\nlicense="MIT"\n'
                    '[profile.release]\nopt-level=3\nlto=true\n')
        result = tomllib.loads(helper.workspace_manifest(original, pin))
        self.assertEqual(result["workspace"]["members"], ["crates/" + c for c in pin["crates"]])
        self.assertEqual(result["profile"], {"release": {"opt-level": 3, "lto": True}})
        with self.assertRaisesRegex(ValueError, "package settings"):
            helper.workspace_manifest(original.replace('edition="2021"', 'edition="2024"'), pin)
        with self.assertRaisesRegex(ValueError, "build profile"):
            helper.workspace_manifest(original.replace('opt-level=3', 'opt-level=1'), pin)

    def test_incomplete_or_unknown_receipt_is_refused(self):
        for receipt in ({}, {"schema_version": 1, "kind": "felucca-emulator-trace-build", "status": "incomplete"}):
            path = self.directory / "receipt.json"
            path.write_text(json.dumps(receipt))
            with self.subTest(receipt=receipt), self.assertRaisesRegex(ValueError, "incomplete build receipt"):
                helper.verify(path)

    def test_flags_and_wrappers_cannot_enter_fixed_build(self):
        with patch.dict(helper.os.environ, {"RUSTFLAGS": "-C opt-level=0", "RUSTC_WRAPPER": "other", "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER": "other", "RUSTUP_TOOLCHAIN": "other"}):
            env = helper.build_environment(self.directory, "1.99.1")
        self.assertNotIn("RUSTFLAGS", env)
        self.assertNotIn("RUSTC_WRAPPER", env)
        self.assertNotIn("CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER", env)
        self.assertEqual(env["RUSTUP_TOOLCHAIN"], "1.99.1")


if __name__ == "__main__":
    unittest.main()
