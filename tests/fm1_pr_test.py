#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PR firmware orchestration, corruption guards and installer handoff; no hardware."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build
import fm1_install
import fm1_pr as P
import fm1pkg_make as M

SHA = "a" * 40
OLD = "b" * 40
REPO = "kmplngj/Felucca"


def run(state="completed", conclusion="success", number=42):
    return {"id": number, "status": state, "conclusion": conclusion,
            "html_url": f"https://github.com/{REPO}/actions/runs/{number}",
            "display_title": P.run_title(333, SHA), "head_branch": "main"}


class Selection(unittest.TestCase):
    def test_current_head_and_reachable_old_commit(self):
        with patch.object(P, "api", return_value={"head": {"sha": SHA}}) as api:
            self.assertEqual(P.resolve_revision(REPO, "333"), SHA)
            api.assert_called_once()
        for state in ("ahead", "identical"):
            with patch.object(P, "api", side_effect=[{"head": {"sha": SHA}}, {"status": state}]):
                self.assertEqual(P.resolve_revision(REPO, "333", OLD), OLD)

    def test_bad_inputs_fail_before_api(self):
        for repo, number, sha in (("../repo", "333", SHA), (REPO, "--help", SHA),
                                  (REPO, "0", SHA), (REPO, "333", "abc"),
                                  (REPO, "333", "a" * 40 + "\n")):
            with patch.object(P, "api") as api, self.assertRaises(ValueError):
                P.resolve_revision(repo, number, sha)
            api.assert_not_called()

    def test_unrelated_or_newer_commit_rejected(self):
        for state in ("behind", "diverged"):
            with patch.object(P, "api", side_effect=[{"head": {"sha": SHA}}, {"status": state}]), \
                    self.assertRaisesRegex(ValueError, "not reachable"):
                P.resolve_revision(REPO, 333, OLD)

    def test_paginated_selection_ignores_other_pr_commit_and_branch(self):
        wrong_pr = run(number=100) | {"display_title": P.run_title(334, SHA)}
        wrong_sha = run(number=99) | {"display_title": P.run_title(333, OLD)}
        wrong_branch = run(number=98) | {"head_branch": "other"}
        with patch.object(P, "api", side_effect=[
                {"workflow_runs": [wrong_pr, wrong_sha, wrong_branch] + [wrong_pr] * 97},
                {"workflow_runs": [run()]}]) as api:
            self.assertEqual(P.matching_runs(REPO, 333, SHA, "main"), [run()])
            self.assertIn("page=2", api.call_args.args[0])

    def test_expired_missing_duplicate_and_wrong_artifacts(self):
        good = {"name": "firmware-42", "expired": False}
        for artifacts in ([], [good | {"expired": True}], [good | {"name": "diagnostics-42"}],
                          [good, good]):
            with patch.object(P, "pages", return_value=artifacts):
                self.assertIsNone(P.firmware_artifact(REPO, run()))
        with patch.object(P, "pages", return_value=[good]):
            self.assertEqual(P.firmware_artifact(REPO, run()), good)

    def test_reuse_success_without_dispatch(self):
        with patch.object(P, "matching_runs", return_value=[run()]), \
                patch.object(P, "firmware_artifact", return_value={"name": "firmware-42"}), \
                patch.object(P, "api", return_value=run()), patch.object(P, "gh") as gh:
            self.assertEqual(P.ensure_run(REPO, 333, SHA, "main", 30), run())
            gh.assert_not_called()

    def test_dispatch_wait_and_resume_active_run(self):
        active = run("in_progress", None)
        with patch.object(P, "matching_runs", side_effect=[[], [active]]), \
                patch.object(P, "api", return_value=run()), \
                patch.object(P, "firmware_artifact", return_value={"name": "firmware-42"}), \
                patch.object(P.time, "sleep"), patch.object(P, "gh") as gh:
            self.assertEqual(P.ensure_run(REPO, 333, SHA, "main", 30), run())
            self.assertEqual(gh.call_args.kwargs["payload"],
                             {"ref": "main", "inputs": {"pr": "333", "commit": SHA}})
        with patch.object(P, "matching_runs", return_value=[active]), \
                patch.object(P, "api", return_value=run()), \
                patch.object(P, "firmware_artifact", return_value={"name": "firmware-42"}), \
                patch.object(P, "gh") as gh:
            self.assertEqual(P.ensure_run(REPO, 333, SHA, "main", 30, True), run())
            gh.assert_not_called()

    def test_no_build_fails_without_writing(self):
        with patch.object(P, "matching_runs", return_value=[run(conclusion="failure")]), \
                patch.object(P, "gh") as gh, self.assertRaisesRegex(ValueError, "maintainer"):
            P.ensure_run(REPO, 333, SHA, "main", 30, True)
        gh.assert_not_called()

    def test_failed_canceled_and_artifactless_builds_do_not_install(self):
        for outcome in ("failure", "cancelled", "timed_out"):
            with patch.object(P, "matching_runs", side_effect=[[], [run(conclusion=outcome)]]), \
                    patch.object(P, "gh"), self.assertRaisesRegex(ValueError, "no firmware installed"):
                P.ensure_run(REPO, 333, SHA, "main", 30)
        with patch.object(P, "matching_runs", return_value=[run("in_progress", None)]), \
                patch.object(P, "api", return_value=run()), \
                patch.object(P, "firmware_artifact", return_value=None), \
                self.assertRaisesRegex(ValueError, "no live firmware"):
            P.ensure_run(REPO, 333, SHA, "main", 30)

    def test_timeout_preserves_remote_build(self):
        with patch.object(P, "matching_runs", return_value=[]), patch.object(P, "gh") as gh, \
                patch.object(P.time, "monotonic", side_effect=[0, 30]), \
                self.assertRaisesRegex(ValueError, "not canceled"):
            P.ensure_run(REPO, 333, SHA, "main", 1)
        self.assertEqual(gh.call_count, 1)

    def test_dispatch_permission_failure_is_reported(self):
        with patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "HTTP 403: Resource not accessible")), self.assertRaisesRegex(ValueError, "403"):
            P.gh("api", "endpoint")


class Download(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            for name in ("uboot.boot", "cfg_tool.bin", "cfg/eq_cfg_hw.bin"):
                file = sdk / "cpu/wl82/tools" / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"SDK fixture")
            with patch.object(M, "SDK", sdk):
                cls.raw = M.ufw(M.flash_image(b"APP fixture", M.KEY),
                                build.ldr_wrap(fm1_install.LOADER_MARK + bytes(
                                    (i * 101 + (i >> 7) * 29 + 101) & 255 for i in range(3000))),
                                "FM-1_900")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact(self.root)

    def artifact(self, root):
        root.mkdir(parents=True, exist_ok=True)
        (root / "felucca.fwsc").write_bytes(self.raw)
        (root / "provenance.json").write_text(json.dumps({"revision": SHA}))
        (root / "package.sha256").write_text(f"{hashlib.sha256(self.raw).hexdigest()}  build/felucca.fwsc\n")

    def test_real_package_validation_and_wrong_revision(self):
        self.assertEqual(P.verify_download(self.root, SHA), self.root / "felucca.fwsc")
        with self.assertRaisesRegex(ValueError, "provenance"):
            P.verify_download(self.root, OLD)

    def test_corruption_wrong_manifest_and_duplicate_packages(self):
        package = self.root / "felucca.fwsc"
        package.write_bytes(self.raw[:-1])
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            P.verify_download(self.root, SHA)
        self.artifact(self.root)
        (self.root / "package.sha256").write_text(f"{'0' * 64} build/wrong.fwsc")
        with self.assertRaisesRegex(ValueError, "manifest"):
            P.verify_download(self.root, SHA)
        self.artifact(self.root)
        (self.root / "another.fwsc").write_bytes(self.raw)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            P.verify_download(self.root, SHA)

    def test_matching_hash_does_not_bypass_package_structure(self):
        raw = b"invalid but correctly checksummed package"
        (self.root / "felucca.fwsc").write_bytes(raw)
        (self.root / "package.sha256").write_text(f"{hashlib.sha256(raw).hexdigest()} build/felucca.fwsc")
        with self.assertRaises(fm1_install.InstallError):
            P.verify_download(self.root, SHA)

    def test_failed_download_cleans_partial_files(self):
        output = self.root / "out"
        with patch.object(P, "gh", side_effect=ValueError("download failed")), self.assertRaises(ValueError):
            P.download(REPO, run(), SHA, output)
        self.assertEqual(list(output.iterdir()), [])

    def test_cli_download_only_never_opens_installer(self):
        def download(*args, **kwargs):
            self.artifact(Path(args[args.index("--dir") + 1]))
            return ""
        with patch.object(P, "resolve_revision", return_value=SHA), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()), \
                patch.object(P, "gh", side_effect=download), patch.object(P, "install") as install:
            self.assertEqual(P.main(["333", "--download-only", "--out", str(self.root / "out")]), 0)
        install.assert_not_called()
        self.assertEqual(len(list((self.root / "out").rglob("*.fwsc"))), 1)

    def test_verification_error_blocks_installer(self):
        with patch.object(P, "resolve_revision", return_value=SHA), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()), \
                patch.object(P, "download", side_effect=ValueError("SHA-256 mismatch")), \
                patch.object(P, "install") as install:
            self.assertEqual(P.main(["333"]), 2)
        install.assert_not_called()

    def test_installer_confirmation_port_and_return_code(self):
        package = self.root / "felucca.fwsc"
        with patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess([], 5)) as call:
            self.assertEqual(P.install(package), 5)
            self.assertNotIn("--yes", call.call_args.args[0])
            P.install(package, "Felucca", True)
            self.assertEqual(call.call_args.args[0][-3:], ["--port", "Felucca", "--yes"])

    def test_successful_install_reports_pending_hardware_scenarios(self):
        output = io.StringIO()
        with patch.object(P, "resolve_revision", return_value=SHA), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()), \
                patch.object(P, "download", return_value=self.root / "felucca.fwsc"), \
                patch.object(P, "install", return_value=0) as install, \
                contextlib.redirect_stdout(output):
            self.assertEqual(P.main(["333", "--port", "Felucca"]), 0)
        install.assert_called_once_with(self.root / "felucca.fwsc", "Felucca", False)
        self.assertIn("still require hardware validation", output.getvalue())


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
