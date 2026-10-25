#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Failure cases for CI coverage, dependency integrity and distributed release files."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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
        self.engine = {"path": "firmware/engines", "repository": "https://example.invalid/engines",
                       "revision": ci.subprocess.check_output(["git", "ls-tree", "HEAD", "firmware/engines"],
                                                             text=True).split()[2], "license": "MIT"}
        self.source_files = {"LICENSE": (0o644, b"GPL-3.0-only fixture"),
                             "firmware/engines/LICENSE": (0o644, b"MIT fixture")}

    def tearDown(self):
        self.temp.cleanup()

    def test_engine_provenance_rejects_missing_mismatched_or_dirty_sources(self):
        repo = self.root / "firmware/engines"
        repo.mkdir(parents=True)
        pin = "a" * 40
        row = f"160000 commit {pin}\tfirmware/engines\n"
        with patch.object(ci.build, "SRC", self.root):
            with patch.object(ci.subprocess, "check_output", return_value=row):
                with self.assertRaisesRegex(ValueError, "uninitialized"):
                    ci.engine_provenance()
            (repo / "src").mkdir()
            (repo / "src/felucca_engine.h").touch()
            for actual, dirty in (("b" * 40, ""), (pin, " M src/dsp.c\n"), (pin, "?? extra.c\n")):
                with patch.object(ci.subprocess, "check_output", side_effect=[row, actual, dirty]):
                    with self.assertRaisesRegex(ValueError, "committed pin"):
                        ci.engine_provenance()
            with patch.object(ci.subprocess, "check_output", side_effect=[row, pin, "", "https://example.com/engines.git"]):
                self.assertEqual(ci.engine_provenance()["revision"], pin)
            with patch.object(ci.subprocess, "check_output", return_value=""):
                with self.assertRaisesRegex(ValueError, "gitlink"):
                    ci.engine_provenance()

    def test_versions_follow_package_identity_limits(self):
        for value in ("1.6", "1.6.2", "1.6.2.1", "1.6-rc1"):
            self.assertEqual(ci.version(value), value)
        for value in ("v1.6", "12.0", "1.10", "1.6/../../x", "$(echo bad)", "1.6\nVERSION=x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ci.version(value)

    def test_release_display_identity_uses_target_version_normalization(self):
        for release in ("1.0-RC1", "1.6.1", "1.6-rc2"):
            with self.subTest(release=release), patch.dict(os.environ, {"VERSION": release, "GITHUB_ACTIONS": "false", "FELUCCA_PROFILE": "standard"}):
                self.assertEqual(ci.resolved_identity()["version"], ci.build.resolve(["--release", release])["version"])
        with patch.dict(os.environ, {"VERSION": "1.0-RC1", "GITHUB_ACTIONS": "false", "FELUCCA_PROFILE": "standard"}):
            self.assertEqual(ci.resolved_identity()["version"], "v1.0-rc1")

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
                        "SKIP: required sanitizer runs unavailable",
                        "target: skip (build/felucca.dis missing)",
                        "logical image vs fm1pkg.js: skipped (needs node and build/felucca.fwsc)",
                        "target: render cost 1 no budget (BUDGET_UPDATE=1 adds it)",
                        "regress: CPU cpu/mix/idle: 1 instructions / sample, no baseline (BUDGET_UPDATE=1 adds it)"):
            log.write_text(message + "\nALL HOST TESTS PASSED\n")
            with self.subTest(message=message), patch.dict(os.environ, FELUCCA_COVERAGE_REPORT='', FELUCCA_COVERAGE_ID=''), self.assertRaisesRegex(ValueError, "incomplete test coverage"):
                ci.verify_tests(log)

    def test_cpu_skip_words_without_semantic_evidence_cannot_grant_exception(self):
        log = self.root / "tests.log"
        for message in (
                "regress: CPU: 2 of 2 counts unavailable (perf_event_open failed: Operation not permitted); the budget is not checked",
                "regress: CPU: no baseline for this host (BUDGET_UPDATE=1 sh tests/run_tests.sh writes it); the budget is not checked"):
            log.write_text(message + "\nALL HOST TESTS PASSED\n")
            with self.subTest(message=message), patch.dict(os.environ, FELUCCA_COVERAGE_REPORT='', FELUCCA_COVERAGE_ID=''), self.assertRaisesRegex(ValueError, 'explicit report'):
                ci.verify_tests(log)

    def workflow_job(self, name):
        workflow = (ci.build.SRC / ".github/workflows/build.yml").read_text()
        return re.split(r"\n  [a-z][a-z-]*:\n", workflow.split("\n  " + name + ":\n", 1)[1], maxsplit=1)[0]

    def test_required_check_allows_cancellation_and_waits_for_independent_runners(self):
        aggregate = self.workflow_job("build")
        self.assertIn("    name: Target, host and emulator\n", aggregate)
        self.assertIn("    if: ${{ !cancelled() }}\n", aggregate)
        self.assertNotIn("if: always()", aggregate)
        self.assertIn("needs: [workflow-checks, python-checks, backup-checks, emulator-checks, validation, full-browser-checks]", aggregate)
        for name in ("validation", "full-browser-checks"):
            job = self.workflow_job(name)
            # Neither long-running job waits for the other. Default success()
            # also stops both jobs when their workflow is canceled.
            self.assertIn("    needs: workflow-checks\n", job)
            header = job.split("    steps:\n", 1)[0]
            self.assertNotIn("    if: always()", header)
            self.assertNotIn("    if: ${{ always()", header)
        self.assertIn("    if: needs.workflow-checks.outputs.full == 'true' && inputs.validation == 'full'\n",
                      self.workflow_job("full-browser-checks"))

    def test_browser_gate_builds_fresh_selected_sources_with_workflow_owned_pins(self):
        browser = self.workflow_job("full-browser-checks")
        pins = browser.index("cp pyproject.toml uv.lock .python-version")
        selected = browser.index("ref: ${{ inputs.source_ref || github.sha }}")
        self.assertLess(pins, selected)
        self.assertIn('uv sync --locked --only-group build --project "$RUNNER_TEMP/felucca-python-project"', browser)
        self.assertIn('build.generate()', browser)
        self.assertIn("build.VERSION = build.resolve(['--release', release] if release else [])['version']", browser)
        self.assertIn('FELUCCA_VERIFIED_PR: ${{ inputs.verified_pr }}', browser)
        self.assertIn('FELUCCA_VERIFIED_COMMIT: ${{ inputs.source_ref }}', browser)
        self.assertIn('sh web/emu/build.sh', browser)
        self.assertNotIn('tools/ci.py emulator-tests', browser)
        self.assertIn('npm test --prefix web/emu', browser)
        for path in ('build/ci/', 'build/browser/', 'build/emu/', 'build/gen/resolved-profile.json'):
            self.assertIn(path, browser)
        self.assertIn('browser-provenance.txt', browser)
        self.assertIn('git submodule status --recursive', browser)
        # Keep the existing complete host/parity coverage in the other runner.
        host = self.workflow_job("validation")
        self.assertIn('sh tests/run_tests.sh', host)
        self.assertIn('python3 tools/ci.py verify-tests', host)
        self.assertNotIn('npm test --prefix web/emu', host)
        self.assertIn('Reproduce package from a clean checkout', host)

    def test_validated_artifacts_are_promoted_only_after_required_results_pass(self):
        aggregate = self.workflow_job("build")
        host = self.workflow_job("validation")
        for kind in ('firmware', 'release'):
            self.assertIn('name: candidate-' + kind + '-${{', host)
            self.assertNotIn('name: ' + kind + '-${{', host)
            download = aggregate.index('Download candidate ' + kind)
            promote = aggregate.index('Upload validated ' + kind)
            self.assertLess(aggregate.index('Check selected validation results'), download)
            self.assertLess(download, promote)
            self.assertIn('name: candidate-' + kind + '-${{', aggregate)
            self.assertIn('name: ' + kind + '-${{', aggregate)
        self.assertNotIn('always()', aggregate)

    def test_host_cpu_provenance_records_usable_clang_and_gcc_flags(self):
        compilers = [path for name in ("clang", "gcc") if (path := shutil.which(name))]
        if not compilers:
            self.skipTest("needs a host Clang or GCC")
        for compiler in compilers:
            with self.subTest(compiler=compiler), patch.dict(os.environ, CC=compiler):
                metadata = ci.host_cpu_provenance()
                self.assertEqual(metadata["compiler_command"], [compiler])
                self.assertEqual(set(metadata["harnesses"]), {"regress", "regress_os"})
                for name, harness in metadata["harnesses"].items():
                    self.assertIn("-O2" if name == "regress" else "-Os", harness["flags"])
                    self.assertEqual(harness["baseline_present"], (ci.build.SRC / harness["baseline"]).is_file())
                    subprocess.run([compiler, *harness["flags"], "-x", "c", "-c", "-o", str(self.root / "probe.o"), "-"],
                                   input="int x;", text=True, capture_output=True, check=True)

    def test_actions_summary_keeps_actual_cpu_and_pending_dependency_outcomes(self):
        workflow = (ci.build.SRC / ".github/workflows/build.yml").read_text()
        script = workflow.split("      - name: Summarize validation and limits\n", 1)[1].split("        run: |\n", 1)[1].split("\n  build:\n", 1)[0]
        script = "\n".join(line[10:] for line in script.splitlines())
        script = script.replace("${{ job.status }}", "success").replace("${{ needs.workflow-checks.outputs.full }}", "true")
        log = self.root / "build/ci/tests.log"
        log.parent.mkdir(parents=True)
        evidence = (
            "== CPU baselines: tests/cpu_baseline_linux_x86_64_clang_x.txt / tests/cpu_baseline_linux_x86_64_clang_x_os.txt",
            "regress: CPU: 78 of 78 counts unavailable (perf_event_open failed: Operation not permitted); the budget is not checked",
            "regress: CPU: no baseline for this host (BUDGET_UPDATE=1 sh tests/run_tests.sh writes it); the budget is not checked",
            "official V15 restore: skipped (needs FM-1_v15.fwsc in the repo root)",
            "FX rest: SKIP (#153 depends on unmerged #41; no silent-bus paths in selected fx.c)",
        )
        log.write_text("\n".join(evidence) + "\n")
        summary = self.root / "summary.md"
        subprocess.run(["bash", "-e", "-c", script], cwd=self.root,
                       env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary)), check=True)
        for line in evidence:
            self.assertIn(line, summary.read_text())
        # Setup diagnostics and a partial O2 result cannot establish completion;
        # the real harness can fail before its Os comparison finishes.
        for fx, pending in (
                ("", True),
                ("FX rest: source=fx.c sha256=123", True),
                ("FX rest O2: 63 audio/state matches; skips chorus/delay/HALL/SPRING=[1, 1, 1, 0]", True),
                ("FX rest: source=fx.c sha256=123\nFX rest: FAIL: compile failed", False),
                ("FX rest O2: 63 audio/state matches; skips chorus/delay/HALL/SPRING=[1, 1, 1, 0]\n"
                 "FX rest Os: 63 audio/state matches; skips chorus/delay/HALL/SPRING=[1, 1, 1, 0]", False)):
            with self.subTest(fx=fx):
                log.write_text("\n".join(evidence[:-1]) + "\n" + fx + "\n")
                summary.unlink()
                subprocess.run(["bash", "-e", "-c", script], cwd=self.root,
                               env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary)), check=True)
                text = summary.read_text()
                self.assertEqual("FX rest: pending coverage" in text, pending)
                self.assertNotIn("FX rest: SKIP", text)
                for line in fx.splitlines():
                    self.assertIn(line, text)

    def test_structured_source_summary_keeps_cpu_and_fx_evidence(self):
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'test_coverage.py').write_text("print('structured fixture')\n")
        self.test_actions_summary_keeps_actual_cpu_and_pending_dependency_outcomes()
        self.assertIn('Structured host coverage', (self.root / 'summary.md').read_text())

    def test_vendor_skip_words_alone_cannot_grant_exception(self):
        log = self.root / "tests.log"
        log.write_text("official V15 restore: skipped (needs FM-1_v15.fwsc in the repo root)\nALL HOST TESTS PASSED\n")
        with patch.dict(os.environ, FELUCCA_COVERAGE_REPORT='', FELUCCA_COVERAGE_ID=''), self.assertRaisesRegex(ValueError, 'explicit report'):
            ci.verify_tests(log)

    def test_complete_tests_require_outputs(self):
        log = self.root / "tests.log"
        log.write_text("ALL HOST TESTS PASSED\n")
        with patch.object(ci.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "incomplete test coverage"):
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
        (root / "BUILD-PROVENANCE.json").write_text(json.dumps({"revision": revision, "version": "1.6", "engines": self.engine,
            "source_distribution": {"archive": "felucca-1.6-source.tar.gz", "sha256": "0" * 64,
                                    "manifest_sha256": "0" * 64, "firmware_revision": revision,
                                    "engines": self.engine}}))
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
        self.finalize(output)
        return output, root

    def finalize(self, output):
        # Release fixtures isolate packaging from a mutable developer checkout;
        # source_archive_test exercises exact blobs in real clean Git repositories.
        with patch.object(ci.build, "OUT", output), patch.object(
                ci.source_archive, "source_files", return_value=(self.engine, self.source_files)):
            ci.finalize("1.6")

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

    def test_wrong_source_pin_fails_even_with_consistent_source_metadata_and_checksums(self):
        self.release()
        path = self.root / "BUILD-PROVENANCE.json"
        metadata = json.loads(path.read_text())
        metadata["engines"]["revision"] = "b" * 40
        metadata["source_distribution"]["engines"]["revision"] = "b" * 40
        path.write_text(json.dumps(metadata))
        self.checksums()
        with self.assertRaisesRegex(ValueError, "committed gitlink"):
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
        self.finalize(output)
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
        self.assertIn("felucca-1.6-source.tar.gz", (assets / "SHA256SUMS").read_text())
        metadata = json.loads((root / "BUILD-PROVENANCE.json").read_text())
        ci.source_archive.verify_archive(assets / "felucca-1.6-source.tar.gz", metadata["source_distribution"])
        with tarfile.open(assets / "felucca-1.6-release.tar.gz") as archive:
            manifest = archive.extractfile("felucca-1.6/SHA256SUMS").read().decode()
            self.assertIn("LICENSES/Apache-2.0.txt", manifest)

    def test_release_page_staging_rejects_corrupt_archive(self):
        output, root = self.bundle()
        (output / "felucca-1.6-release.tar.gz").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "invalid release archive checksum"):
            ci.stage_release(root, output, self.root / "assets", "1.6")

    def test_release_page_staging_requires_intact_matching_source_archive(self):
        output, root = self.bundle()
        archive = output / "felucca-1.6-source.tar.gz"
        original = archive.read_bytes()
        archive.unlink()
        with self.assertRaisesRegex(ValueError, "invalid source archive"):
            ci.stage_release(root, output, self.root / "assets", "1.6")
        archive.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "invalid source archive"):
            ci.stage_release(root, output, self.root / "assets", "1.6")
        archive.write_bytes(original)
        sidecar = archive.with_suffix(".gz.sha256")
        sidecar.unlink()
        with self.assertRaisesRegex(ValueError, "invalid source archive checksum"):
            ci.stage_release(root, output, self.root / "assets", "1.6")
        sidecar.write_text("invalid checksum")
        with self.assertRaisesRegex(ValueError, "invalid source archive checksum"):
            ci.stage_release(root, output, self.root / "assets", "1.6")
        metadata = json.loads((root / "BUILD-PROVENANCE.json").read_text())
        metadata["source_distribution"]["sha256"] = "1" * 64
        (root / "BUILD-PROVENANCE.json").write_text(json.dumps(metadata))
        self.checksums(root)
        with self.assertRaisesRegex(ValueError, "source archive does not match build provenance"):
            ci.stage_release(root, output, self.root / "assets", "1.6")

    def test_release_page_staging_rejects_colliding_asset_names(self):
        output, root = self.bundle()
        for name in ("LICENSE", "SHA256SUMS"):
            path = root / "LICENSES" / name
            path.write_text("collision")
            self.finalize(output)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "filenames collide"):
                ci.stage_release(root, output, self.root / "assets", "1.6")
            path.unlink()

    def test_publisher_cli_preserves_existing_repository_assets(self):
        output, root = self.bundle()
        shutil.copytree(root, self.root / "release")
        downloaded = self.root / "downloaded"
        downloaded.mkdir()
        for kind in ("release", "source"):
            for suffix in (".tar.gz", ".tar.gz.sha256"):
                shutil.copyfile(output / f"felucca-1.6-{kind}{suffix}", downloaded / f"felucca-1.6-{kind}{suffix}")
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
