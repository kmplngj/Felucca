#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PR firmware orchestration, corruption guards and installer handoff; no hardware."""
import contextlib
import hashlib
import io
import json
import os
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

    def test_download_errors_do_not_expose_signed_url_queries(self):
        with patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "GET https://example.invalid/artifact.zip?sig=secret&se=time: Forbidden")):
            with self.assertRaises(ValueError) as error:
                P.gh("run", "download")
        self.assertIn("Forbidden", str(error.exception))
        self.assertNotIn("sig=secret", str(error.exception))

    def test_target_and_full_runs_and_artifacts_never_overlap(self):
        full = run()
        target = run(number=43) | {"display_title": P.run_title(333, SHA, "target")}
        with patch.object(P, "pages", return_value=[full, target]):
            self.assertEqual(P.matching_runs(REPO, 333, SHA, "main"), [full])
            self.assertEqual(P.matching_runs(REPO, 333, SHA, "main", "target"), [target])
        with patch.object(P, "pages", return_value=[{"name": "firmware-target-42", "expired": False}]):
            self.assertIsNone(P.firmware_artifact(REPO, full))
            self.assertIsNotNone(P.firmware_artifact(REPO, full, "target"))

    def test_target_dispatch_resume_and_reuse_keep_scope(self):
        target = run() | {"display_title": P.run_title(333, SHA, "target")}
        with patch.object(P, "matching_runs", side_effect=[[], [target]]) as matching, \
                patch.object(P, "firmware_artifact", return_value={"name": "firmware-target-42"}) as artifact, \
                patch.object(P, "gh") as gh:
            self.assertEqual(P.ensure_run(REPO, 333, SHA, "main", 30, False, "target"), target)
        self.assertEqual(gh.call_args.kwargs["payload"]["inputs"]["validation"], "target")
        for call in matching.call_args_list:
            self.assertEqual(call.args[-1], "target")
        self.assertEqual(artifact.call_args.args[-1], "target")


class Worktrees(unittest.TestCase):
    """Exercise real indexes, linked worktrees and nested gitlinks, without GitHub."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="PR worktrees ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "file"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        leaf = self.repo("leaf")
        module = self.repo("module")
        self.git(module, "submodule", "add", str(leaf), "nested")
        self.commit(module)
        self.pin = self.git(module, "rev-parse", "HEAD")
        self.source = self.repo("source")
        (self.source / ".gitignore").write_text("generated/\n")
        self.git(self.source, "submodule", "add", str(module), "engine")
        self.commit(self.source)
        self.original = self.git(self.source, "rev-parse", "HEAD")
        (self.source / "tracked").write_text("PR version\n")
        self.commit(self.source)
        self.revision = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "update-ref", "refs/pull/333/head", self.revision)
        self.git(self.source, "checkout", "--detach", self.original)
        # Rewrite only this fixture's GitHub URL; production never enables file transport.
        self.git(self.source, "config", f"url.file://{self.source}.insteadOf",
                 f"https://github.com/{REPO}.git")
        self.path = self.base / "PR source"

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.rstrip("\n")

    def commit(self, root):
        self.git(root, "add", "-A")
        self.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--no-gpg-sign", "-m", "fixture")

    def repo(self, name):
        root = self.base / name
        root.mkdir()
        self.git(root, "init")
        (root / "tracked").write_text("original\n")
        self.commit(root)
        return root

    def prepare(self):
        return P.prepare_worktree(REPO, 333, self.revision, self.path, self.source)

    def remove(self):
        P.remove_worktree(REPO, 333, self.path, self.source)

    def test_dirty_source_unchanged_exact_detached_head_and_recursive_pins(self):
        (self.source / "tracked").write_text("staged\n")
        self.git(self.source, "add", "tracked")
        (self.source / "tracked").write_text("unstaged\n")
        (self.source / "untracked").write_text("keep\n")
        (self.source / "generated").mkdir()
        (self.source / "generated/output").write_text("keep ignored\n")
        (self.source / "engine/tracked").write_text("local engine edits\n")
        self.git(self.source, "update-ref", "refs/heads/keep", self.original)
        before = {command: self.git(self.source, *command.split()) for command in
                  ("status --porcelain --ignored", "diff", "diff --cached", "show-ref", "rev-parse HEAD")}
        index = (self.source / ".git/index").read_bytes()
        self.assertEqual(self.prepare(), self.path)
        self.assertEqual(self.git(self.path, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(self.git(self.path, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")
        self.assertEqual(self.git(self.path / "engine", "rev-parse", "HEAD"), self.pin)
        self.assertTrue((self.path / "engine/nested/tracked").is_file())
        self.assertEqual((self.path / "tracked").read_text(), "PR version\n")
        for command, output in before.items():
            self.assertEqual(self.git(self.source, *command.split()), output)
        self.assertEqual((self.source / ".git/index").read_bytes(), index)
        self.assertEqual((self.source / "untracked").read_text(), "keep\n")
        self.assertEqual((self.source / "generated/output").read_text(), "keep ignored\n")
        self.assertEqual(self.git(self.source, "for-each-ref", "refs/felucca-pr"), "")
        self.assertEqual(self.prepare(), self.path)
        self.remove()
        self.assertFalse(self.path.exists())
        self.assertEqual((self.source / "tracked").read_text(), "unstaged\n")

    def test_reuse_refuses_modified_or_switched_head(self):
        self.prepare()
        (self.path / "tracked").write_text("keep edits\n")
        with self.assertRaisesRegex(ValueError, "local changes"):
            self.prepare()
        self.git(self.path, "restore", "tracked")
        self.git(self.path, "checkout", "--detach", self.original)
        with self.assertRaisesRegex(ValueError, "HEAD changed"):
            self.prepare()
        with self.assertRaisesRegex(ValueError, "HEAD changed"):
            self.remove()

    def test_cleanup_refuses_extra_files_including_ignored_nested_files(self):
        self.prepare()
        for name in ("tracked", "untracked", "generated/output", "engine/nested/extra"):
            file = self.path / name
            original = file.read_bytes() if file.exists() else None
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("keep this file\n")
            with self.assertRaisesRegex(ValueError, "local changes"):
                self.remove()
            self.assertEqual(file.read_text(), "keep this file\n")
            if original is None:
                file.unlink()
                if name == "generated/output":
                    file.parent.rmdir()
            else:
                file.write_bytes(original)
        # An ignored file inside a submodule must also prevent deletion.
        self.git(self.path / "engine/nested", "config", "core.excludesFile", str(self.base / "ignores"))
        (self.base / "ignores").write_text("ignored\n")
        extra = self.path / "engine/nested/ignored"
        extra.write_text("keep ignored nested output\n")
        with self.assertRaisesRegex(ValueError, "local changes"):
            self.remove()
        extra.unlink()
        self.remove()

    def test_existing_directory_foreign_worktree_and_source_are_preserved(self):
        self.path.mkdir()
        (self.path / "keep").write_text("keep\n")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual((self.path / "keep").read_text(), "keep\n")
        self.path.joinpath("keep").unlink()
        self.path.rmdir()
        self.git(self.source, "worktree", "add", "--detach", str(self.path), self.revision)
        with self.assertRaisesRegex(ValueError, "not created"):
            self.prepare()
        with self.assertRaisesRegex(ValueError, "not created"):
            self.remove()
        with self.assertRaises(ValueError):
            P.remove_worktree(REPO, 333, self.source, self.source)
        with self.assertRaisesRegex(ValueError, "outside"):
            P.prepare_worktree(REPO, 333, self.revision, self.source / "inside", self.source)

    def test_cleanup_preserves_hidden_edits_and_submodule_local_branches(self):
        self.prepare()
        self.git(self.path, "update-index", "--assume-unchanged", "tracked")
        (self.path / "tracked").write_text("hidden edit\n")
        with self.assertRaisesRegex(ValueError, "hidden index"):
            self.remove()
        self.git(self.path, "update-index", "--no-assume-unchanged", "tracked")
        self.git(self.path, "restore", "tracked")
        nested = self.path / "engine/nested"
        pinned = self.git(nested, "rev-parse", "HEAD")
        self.git(nested, "checkout", "-b", "my-work")
        (nested / "tracked").write_text("local commit\n")
        self.commit(nested)
        self.git(nested, "checkout", "--detach", pinned)
        with self.assertRaisesRegex(ValueError, "local submodule commits"):
            self.remove()
        self.assertTrue(self.path.exists())
        self.git(nested, "branch", "-D", "my-work")
        self.remove()

    def test_wrong_pr_and_force_push_do_not_reuse_unrelated_sources(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "another"):
            P.prepare_worktree(REPO, 334, self.revision, self.path, self.source)
        self.remove()
        # Simulate a force-push between API resolution and fetching.
        self.git(self.source, "update-ref", "refs/pull/333/head", self.original)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.git(self.source, "for-each-ref", "refs/felucca-pr"), "")

    def test_cli_prepare_and_cleanup_skip_ci_download_and_installer(self):
        with patch.object(P, "resolve_revision", return_value=self.revision), \
                patch.object(P, "prepare_worktree") as prepare, \
                patch.object(P, "remove_worktree") as remove, \
                patch.object(P, "ensure_run") as build, patch.object(P, "download") as download, \
                patch.object(P, "install") as install, patch.object(P, "api") as api:
            self.assertEqual(P.main(["333", "--prepare-only", "--worktree-dir", str(self.path)]), 0)
            prepare.assert_called_once_with(REPO, "333", self.revision, self.path)
            self.assertEqual(P.main(["333", "--remove-worktree", str(self.path)]), 0)
            remove.assert_called_once_with(REPO, "333", self.path)
            for call in (build, download, install, api):
                call.assert_not_called()

    def test_cli_preparation_failure_blocks_build_and_install(self):
        with patch.object(P, "resolve_revision", return_value=self.revision), \
                patch.object(P, "prepare_worktree", side_effect=ValueError("submodule failed")), \
                patch.object(P, "ensure_run") as build, patch.object(P, "install") as install:
            self.assertEqual(P.main(["333", "--worktree"]), 2)
        build.assert_not_called()
        install.assert_not_called()

    def test_cli_resolve_only_has_no_git_mutations(self):
        with patch.object(P, "resolve_revision", return_value=self.revision), \
                patch.object(P, "prepare_worktree") as prepare, \
                patch.object(P, "remove_worktree") as remove, patch.object(P, "ensure_run") as build:
            self.assertEqual(P.main(["333", "--resolve-only", "--worktree"]), 0)
        for call in (prepare, remove, build):
            call.assert_not_called()

    def test_cli_worktree_keeps_pinned_ci_download_and_installer_flow(self):
        package = self.base / "firmware.fwsc"
        with patch.object(P, "resolve_revision", return_value=self.revision), \
                patch.object(P, "prepare_worktree") as prepare, \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()) as build, \
                patch.object(P, "download", return_value=package) as download, \
                patch.object(P, "install", return_value=0) as install:
            self.assertEqual(P.main(["333", "--worktree"]), 0)
        prepare.assert_called_once_with(REPO, "333", self.revision, None)
        build.assert_called_once_with(REPO, "333", self.revision, "main", 3600, False, "full")
        self.assertEqual(download.call_args.args[2], self.revision)
        install.assert_called_once_with(package, None, False)


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

    def test_target_scope_is_required_and_cannot_satisfy_full_validation(self):
        with self.assertRaisesRegex(ValueError, "validation scope"):
            P.verify_download(self.root, SHA, "target")
        record = self.root / "provenance.json"
        record.write_text(json.dumps({"revision": SHA, "validation": {"scope": "target"}}))
        self.assertEqual(P.verify_download(self.root, SHA, "target"), self.root / "felucca.fwsc")
        with self.assertRaisesRegex(ValueError, "validation scope"):
            P.verify_download(self.root, SHA, "full")
        for validation in ({"scope": "unknown"}, "target", None):
            record.write_text(json.dumps({"revision": SHA, "validation": validation}))
            with self.assertRaisesRegex(ValueError, "validation scope"):
                P.verify_download(self.root, SHA, "target")

    def test_target_cli_warns_and_downloads_without_installing(self):
        output = io.StringIO()
        with patch.object(P, "resolve_revision", return_value=SHA), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()) as build, \
                patch.object(P, "download", return_value=self.root / "felucca.fwsc") as download, \
                patch.object(P, "install") as install, contextlib.redirect_stdout(output):
            self.assertEqual(P.main(["333", "--validation", "target", "--download-only"]), 0)
        build.assert_called_once_with(REPO, "333", SHA, "main", 3600, False, "target")
        self.assertEqual(download.call_args.args[-1], "target")
        install.assert_not_called()
        self.assertIn("does not replace full PR validation", output.getvalue())

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
