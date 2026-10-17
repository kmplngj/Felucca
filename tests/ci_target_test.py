#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Target-only integrity, cache invalidation and workflow scope failure guards."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ci
import ci_target as T
import fm1_pr_test as F


ROOT = Path(__file__).resolve().parents[1]


def step_script(name):
    block = (ROOT / ".github/workflows/build.yml").read_text().split(f"      - name: {name}\n", 1)[1]
    script = block.split("        run: |\n", 1)[1].split("\n      - ", 1)[0]
    return "\n".join(line[10:] for line in script.splitlines())


class Target(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        F.Download.setUpClass()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "build"
        (self.output / "ci").mkdir(parents=True)
        self.identity = {"revision": "a" * 40, "dirty": False}
        self.engines = {"revision": "b" * 40}
        self.ci = SimpleNamespace(
            build=SimpleNamespace(OUT=self.output, SRC=self.root, SDK_SHA256={"file": "c" * 64}),
            resolved_identity=lambda: self.identity, engine_provenance=lambda: self.engines,
            fm1_install=ci.fm1_install, TOOLCHAIN=ci.TOOLCHAIN, SDK_REF=ci.SDK_REF)
        self.metadata = {"build_identity": self.identity, "revision": self.identity["revision"], "engines": self.engines}
        self.record = self.output / "ci/provenance.json"
        self.record.write_text(json.dumps(self.metadata))
        (self.output / "build-identity.json").write_text(json.dumps(self.identity))
        (self.output / "felucca.fwsc").write_bytes(F.Download.raw)
        (self.root / "tools").mkdir()
        (self.root / "tools/get_toolchain.sh").write_text("installer fixture")

    def test_target_package_gets_explicit_scope_and_verified_digest(self):
        T.package(self.ci, "target")
        data = json.loads(self.record.read_text())
        self.assertEqual(data["validation"]["scope"], "target")
        self.assertIn("sanitizer", data["validation"]["omitted"])
        self.assertEqual((self.output / "ci/package.sha256").read_text().split()[0],
                         hashlib.sha256(F.Download.raw).hexdigest())
        self.assertEqual(F.P.verify_download(self.output, self.identity["revision"], "target"),
                         self.output / "felucca.fwsc")
        with self.assertRaisesRegex(ValueError, "validation scope"):
            F.P.verify_download(self.output, self.identity["revision"], "full")

    def test_full_package_preserves_reproducible_release_provenance(self):
        before = self.record.read_bytes()
        T.package(self.ci, "full")
        self.assertEqual(self.record.read_bytes(), before)
        T.package(self.ci, "target")
        with self.assertRaisesRegex(ValueError, "Cannot label"):
            T.package(self.ci, "full")

    def test_legacy_ci_without_identity_or_engine_apis_keeps_full_build_support(self):
        del self.ci.resolved_identity
        del self.ci.engine_provenance
        legacy = {"revision": "a" * 40, "version": ""}
        self.record.write_text(json.dumps(legacy))
        (self.output / "build-identity.json").unlink()
        with patch.object(T.subprocess, "check_output", return_value="a" * 40):
            T.package(self.ci, "full")
        self.assertEqual(json.loads(self.record.read_text()), legacy)
        with patch.object(T.subprocess, "check_output", return_value="b" * 40), \
                self.assertRaisesRegex(ValueError, "provenance"):
            T.package(self.ci, "full")
        for check in (T.preflight, T.provenance, lambda ci: T.package(ci, "target")):
            with self.assertRaisesRegex(ValueError, "use --validation full"):
                check(self.ci)

    def test_corrupt_package_or_identity_and_pin_mismatches_prevent_delivery(self):
        (self.output / "felucca.fwsc").write_bytes(b"corrupt")
        with self.assertRaises(ci.fm1_install.InstallError):
            T.package(self.ci, "target")
        self.assertFalse((self.output / "ci/package.sha256").exists())
        (self.output / "felucca.fwsc").write_bytes(F.Download.raw)
        for key, value in (("revision", "c" * 40), ("engines", {"revision": "c" * 40}),
                           ("build_identity", {"revision": "c" * 40})):
            self.record.write_text(json.dumps(self.metadata | {key: value}))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "provenance"):
                T.package(self.ci, "target")
        self.record.write_text(json.dumps(self.metadata))
        (self.output / "build-identity.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "build identity"):
            T.package(self.ci, "target")

    def test_cache_key_changes_for_each_dependency_pin_and_install_recipe(self):
        key = T.cache_key(self.ci)
        self.assertEqual(key, T.cache_key(self.ci))
        for obj, attr, value in ((self.ci, "TOOLCHAIN", "new compiler"),
                                  (self.ci, "SDK_REF", "new SDK"),
                                  (self.ci.build, "SDK_SHA256", {"file": "d" * 64})):
            with patch.object(obj, attr, value):
                self.assertNotEqual(T.cache_key(self.ci), key)
        (self.root / "tools/build.py").write_text("unrelated build implementation change")
        self.assertEqual(T.cache_key(self.ci), key)
        (self.root / "tools/get_toolchain.sh").write_text("new installer recipe")
        self.assertNotEqual(T.cache_key(self.ci), key)

    def test_target_preflight_needs_no_host_emulator_or_browser_dependencies(self):
        features = SimpleNamespace(check=lambda feature: True)
        piano = self.root / "assets/samples-cc0/PIANO"
        piano.mkdir(parents=True)
        (piano / "sample.wav").touch()
        self.ci.build.toolchain = lambda: SimpleNamespace(name=ci.TOOLCHAIN)
        self.ci.build.tc = lambda *args: "clang version 4.0.1"
        self.ci.check_sdk = lambda root: None
        with patch.dict(sys.modules, {"PIL": SimpleNamespace(features=features)}), \
                patch.dict(os.environ, {"AC79_SDK": str(self.root)}, clear=True):
            T.preflight(self.ci)
            for variable in ("GOLDEN_UPDATE", "BUDGET_UPDATE"):
                with patch.dict(os.environ, {variable: "1"}), self.assertRaisesRegex(ValueError, "never update"):
                    T.preflight(self.ci)
        self.ci.build.tc = lambda *args: "wrong compiler"
        with patch.dict(sys.modules, {"PIL": SimpleNamespace(features=features)}), self.assertRaisesRegex(ValueError, "expected"):
            T.preflight(self.ci)

    def test_target_provenance_needs_no_node_emscripten_or_daisysp(self):
        tc = self.root / ci.TOOLCHAIN
        compiler = tc / "pi32v2/bin/clang"
        compiler.parent.mkdir(parents=True)
        compiler.write_bytes(b"compiler fixture")
        self.ci.build.toolchain = lambda: tc
        self.ci.build.tc = lambda *args: "clang version 4.0.1"
        self.ci.build.CFLAGS = ["-Os"]
        features = SimpleNamespace(version=lambda feature: "fixture")
        modules = {"PIL": SimpleNamespace(__version__="fixture", features=features),
                   "fontTools": SimpleNamespace(__version__="fixture"),
                   "brotli": SimpleNamespace(__version__="fixture")}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}, clear=True), \
                patch.object(T.platform, "platform", return_value="fixture runner"), \
                patch.object(T.subprocess, "check_output", return_value="a" * 40) as command:
            T.provenance(self.ci)
        command.assert_called_once_with(["git", "rev-parse", "HEAD"], text=True)
        data = json.loads(self.record.read_text())
        self.assertEqual(data["compiler_sha256"], hashlib.sha256(compiler.read_bytes()).hexdigest())
        self.assertEqual(data["engines"], self.engines)
        self.assertNotIn("emscripten", data)
        self.assertNotIn("node", data)

    def test_actual_scope_gate_rejects_unverified_prs_releases_and_automatic_events(self):
        script = step_script("Validate requested scope")
        valid = dict(os.environ, VALIDATION="target", GITHUB_EVENT_NAME="workflow_dispatch",
                     VERIFIED_PR="392", SOURCE_REF="a" * 40, VERSION="")
        result = subprocess.run(["bash", "-e", "-c", script], env=valid, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for change in ({"GITHUB_EVENT_NAME": "pull_request"}, {"VERIFIED_PR": ""},
                       {"SOURCE_REF": ""}, {"VERSION": "1.6"}, {"VALIDATION": "unknown"}):
            with self.subTest(change=change):
                result = subprocess.run(["bash", "-e", "-c", script], env=valid | change, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
        # Normal PR/manual/release callers retain the full scope without PR inputs.
        result = subprocess.run(["bash", "-e", "-c", script], env=valid | {
            "VALIDATION": "full", "GITHUB_EVENT_NAME": "push", "SOURCE_REF": "", "VERIFIED_PR": "", "VERSION": "1.6"},
            capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_target_summary_explicitly_discloses_omitted_validation(self):
        script = step_script("Summarize validation and limits").replace("${{ job.status }}", "success").replace(
            "${{ needs.workflow-checks.outputs.full }}", "true")
        summary = self.root / "summary.md"
        subprocess.run(["bash", "-e", "-c", script], cwd=self.root,
                       env=dict(os.environ, VALIDATION="target", GITHUB_STEP_SUMMARY=str(summary)), check=True)
        self.assertIn("TARGET ONLY", summary.read_text())
        self.assertIn("tests were omitted", summary.read_text())


if __name__ == "__main__":
    unittest.main()
