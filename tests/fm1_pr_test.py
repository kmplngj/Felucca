#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PR firmware orchestration, corruption guards and installer handoff; no hardware."""
import contextlib
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
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
MERGE = "c" * 40
REPO = "kmplngj/Felucca"
TITLE = "Sequencer: Wiedergabe & Übergänge"
PYTHON_INSTALLER = [sys.executable, str(Path(P.__file__).with_name("fm1_install.py"))]


def run(state="completed", conclusion="success", number=42):
    return {"id": number, "status": state, "conclusion": conclusion,
            "html_url": f"https://github.com/{REPO}/actions/runs/{number}",
            "display_title": P.run_title(333, SHA), "head_branch": "main"}


class InstallerPreflight(unittest.TestCase):
    def test_preflight_uses_the_same_interpreter_and_trusted_python_installer(self):
        with patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as check:
            self.assertEqual(P.prepare_installer(),
                             PYTHON_INSTALLER)
        check.assert_called_once_with([sys.executable, "-c", "import mido, rtmidi"],
                                      capture_output=True, text=True)

    def test_missing_dependencies_stop_before_github_build_or_install(self):
        for flags in ([], ["--automatic"]):
            error = io.StringIO()
            arguments = ["333", "--port", "FM-1 user's port", *flags]
            with patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
                    patch.object(P, "resolve_pr") as resolve, patch.object(P, "ensure_run") as build, \
                    patch.object(P, "resolve_automatic_pr") as automatic, patch.object(P, "api") as api, \
                    patch.object(P, "install") as install, contextlib.redirect_stderr(error):
                self.assertEqual(P.main(arguments), 2)
            for call in (resolve, automatic, api, build, install):
                call.assert_not_called()
            self.assertEqual(shlex.split(error.getvalue().split("Run:\n  ", 1)[1]),
                             ["uv", "run", "--project", str(P.SOURCE), "--locked", "--group", "midi",
                              "python", str(Path(P.__file__).resolve()), *arguments])

    def test_dependency_retry_quotes_trusted_source_and_arguments_from_other_directories(self):
        script = Path("/trusted source/Felucca/tools/fm1_pr.py")
        arguments = ["333", "--out", "relative output", "--port", "FM-1 $(echo unsafe)"]
        with patch.object(P, "__file__", str(script)), \
                patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
                self.assertRaises(ValueError) as error:
            P.prepare_installer(arguments)
        self.assertEqual(shlex.split(str(error.exception).split("Run:\n  ", 1)[1]),
                         ["uv", "run", "--project", str(script.parents[1]), "--locked", "--group", "midi",
                          "python", str(script), *arguments])

    def test_windows_dependency_retry_uses_literal_powershell_arguments(self):
        script = Path("/trusted source/user's Felucca/tools/fm1_pr.py")
        arguments = ["333", "--out", "relative output", "--port", "FM-1's ‘$(echo unsafe)’‚‛; & %PATH%"]
        with patch.object(P, "__file__", str(script)), patch.object(sys, "platform", "win32"), \
                patch.object(P.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
                self.assertRaises(ValueError) as error:
            P.prepare_installer(arguments)
        self.assertEqual(str(error.exception),
                         "Python MIDI installer needs mido and python-rtmidi. Run in PowerShell:\n  "
                         "& 'uv' 'run' '--project' '/trusted source/user''s Felucca' "
                         "'--locked' '--group' 'midi' 'python' "
                         "'/trusted source/user''s Felucca/tools/fm1_pr.py' "
                         "'333' '--out' 'relative output' '--port' 'FM-1''s ‘‘$(echo unsafe)’’‚‚‛‛; & %PATH%'")

    def test_removed_native_options_fail_before_preflight_or_github(self):
        for flags in (["--installer", "native"], ["--m-flasher", "/unused/binary"]):
            with patch.object(P, "prepare_installer") as prepare, \
                    patch.object(P, "resolve_pr") as resolve, self.assertRaises(SystemExit) as result:
                P.main(["333", *flags])
            self.assertEqual(result.exception.code, 2)
            prepare.assert_not_called()
            resolve.assert_not_called()

    def test_download_and_source_only_modes_skip_midi_dependencies(self):
        with patch.object(P, "prepare_installer") as prepare, \
                patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
                patch.object(P, "prepare_worktree"), patch.object(P, "remove_worktree"), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()), \
                patch.object(P, "download", return_value=Path("inert.fwsc")):
            for flags in (["--download-only"], ["--prepare-only"], ["--resolve-only"],
                          ["--remove-worktree", "unused"]):
                self.assertEqual(P.main(["333", *flags]), 0)
        prepare.assert_not_called()

    def test_default_and_explicit_python_selection_use_the_same_handoff(self):
        package = Path("a path/firmware.fwsc")
        command = PYTHON_INSTALLER
        for flags in ([], ["--installer", "python"]):
            with patch.object(P, "prepare_installer", return_value=command) as prepare, \
                    patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
                    patch.object(P, "api", return_value={"default_branch": "main"}), \
                    patch.object(P, "ensure_run", return_value=run()), \
                    patch.object(P, "download", return_value=package), \
                    patch.object(P, "install", return_value=5) as install:
                self.assertEqual(P.main(["333", "--port", "FM-1", "--yes", *flags]), 5)
            prepare.assert_called_once_with(["333", "--port", "FM-1", "--yes", *flags])
            install.assert_called_once_with(package, "FM-1", True, command=command)


class Selection(unittest.TestCase):
    def test_current_head_and_reachable_old_commit(self):
        with patch.object(P, "api", return_value={"head": {"sha": SHA}, "title": TITLE}) as api:
            self.assertEqual(P.resolve_pr(REPO, "333"), (SHA, TITLE))
            api.assert_called_once()
        for state in ("ahead", "identical"):
            with patch.object(P, "api", side_effect=[{"head": {"sha": SHA}, "title": TITLE}, {"status": state}]):
                self.assertEqual(P.resolve_pr(REPO, "333", OLD), (OLD, TITLE))

    def test_bad_inputs_fail_before_api(self):
        for repo, number, sha in (("../repo", "333", SHA), (REPO, "--help", SHA),
                                  (REPO, "0", SHA), (REPO, "333", "abc"),
                                  (REPO, "333", "a" * 40 + "\n")):
            with patch.object(P, "api") as api, self.assertRaises(ValueError):
                P.resolve_pr(repo, number, sha)
            api.assert_not_called()

    def test_unrelated_or_newer_commit_rejected(self):
        for state in ("behind", "diverged"):
            with patch.object(P, "api", side_effect=[{"head": {"sha": SHA}, "title": TITLE}, {"status": state}]), \
                    self.assertRaisesRegex(ValueError, "not reachable"):
                P.resolve_pr(REPO, 333, OLD)

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
            self.assertEqual(call.args[-2:], ("target", "standard"))
        self.assertEqual(artifact.call_args.args[-2:], ("target", "standard"))


class Profiles(unittest.TestCase):
    def test_profile_names_are_literal_and_checked_before_network_or_installer(self):
        for name in ("../macro", "Macro", "macro/standard", "--macro", "macro\n", "macro--test", ""):
            with patch.object(P, "api") as api, patch.object(P, "prepare_installer") as install:
                self.assertEqual(P.main(["333", "--profile=" + name]), 2)
            api.assert_not_called()
            install.assert_not_called()
        with patch.object(P, "api") as api:
            P.validate_profile_source(REPO, SHA, "standard")
        api.assert_not_called()

    def test_opt_in_profile_is_read_from_pinned_source_and_filename_must_match(self):
        item = {"type": "file", "path": "profiles/macro.json", "encoding": "base64",
                "content": base64.b64encode(b'{"name":"macro"}').decode()}
        with patch.object(P, "api", return_value=item) as api:
            P.validate_profile_source(REPO, SHA, "macro")
        api.assert_called_once_with(f"repos/{REPO}/contents/profiles/macro.json?ref={SHA}")
        for changes in ({"type": "symlink"}, {"path": "profiles/standard.json"},
                        {"content": base64.b64encode(b'{"name":"standard"}').decode()},
                        {"content": "not JSON"}):
            with patch.object(P, "api", return_value=item | changes), self.assertRaises(ValueError):
                P.validate_profile_source(REPO, SHA, "macro")

    def test_profile_run_selection_artifact_and_dispatch_are_separate(self):
        standard = run()
        macro = run(number=43) | {"display_title": P.run_title(333, SHA, "full", "macro")}
        with patch.object(P, "pages", return_value=[standard, macro]):
            self.assertEqual(P.matching_runs(REPO, 333, SHA, "main", "full", "macro"), [macro])
            self.assertEqual(P.matching_runs(REPO, 333, SHA, "main"), [standard])
        self.assertEqual(P.artifact_name(macro, "full", "macro"), "firmware-macro-43")
        self.assertEqual(P.artifact_name(macro, "target", "macro"), "firmware-target-macro-43")
        with patch.object(P, "matching_runs", side_effect=[[], [macro]]) as matching, \
                patch.object(P, "firmware_artifact", return_value={"name": "firmware-macro-43"}), \
                patch.object(P, "gh") as gh:
            self.assertEqual(P.ensure_run(REPO, 333, SHA, "main", 30, False, "full", "macro"), macro)
        self.assertEqual(gh.call_args.kwargs["payload"]["inputs"],
                         {"pr": "333", "commit": SHA, "profile": "macro"})
        self.assertTrue(all(call.args[-1] == "macro" for call in matching.call_args_list))

    def test_automatic_profile_request_is_rejected_before_api(self):
        with patch.object(P, "api") as api:
            self.assertEqual(P.main(["333", "--automatic", "--profile", "macro"]), 2)
        api.assert_not_called()


class Automatic(unittest.TestCase):
    def pull(self):
        return {"state": "open", "title": TITLE, "merge_commit_sha": MERGE,
                "head": {"sha": SHA}, "base": {"sha": OLD}}

    def commit(self):
        return {"sha": MERGE, "parents": [{"sha": OLD}, {"sha": SHA}]}

    def automatic(self, **changes):
        return run() | {"event": "pull_request", "head_sha": SHA,
                        "pull_requests": [{"number": 333,
                                           "url": f"https://api.github.com/repos/{REPO}/pulls/333",
                                           "head": {"sha": SHA}, "base": {"sha": OLD}}]} | changes

    def test_resolution_pins_current_head_base_and_merge(self):
        for selected in (None, SHA):
            with patch.object(P, "api", side_effect=[self.pull(), self.commit()]):
                self.assertEqual(P.resolve_automatic_pr(REPO, 333, selected), (SHA, OLD, MERGE, TITLE))

    def test_resolution_rejects_stale_merge_closed_pr_and_historical_commit(self):
        for pull in (self.pull() | {"state": "closed"},
                     self.pull() | {"merge_commit_sha": None},
                     self.pull() | {"merge_commit_sha": "bad"},
                     self.pull() | {"head": {"sha": "bad"}},
                     self.pull() | {"base": {"sha": "bad"}}):
            with patch.object(P, "api", return_value=pull), self.assertRaises(ValueError):
                P.resolve_automatic_pr(REPO, 333)
        with patch.object(P, "api", return_value=self.pull()), self.assertRaisesRegex(ValueError, "current PR head"):
            P.resolve_automatic_pr(REPO, 333, OLD)
        for commit in (self.commit() | {"sha": SHA},
                       self.commit() | {"parents": [{"sha": SHA}, {"sha": OLD}]},
                       self.commit() | {"parents": [{"sha": "d" * 40}, {"sha": SHA}]}):
            with patch.object(P, "api", side_effect=[self.pull(), commit]), \
                    self.assertRaisesRegex(ValueError, "base/head"):
                P.resolve_automatic_pr(REPO, 333)

    def test_selection_requires_successful_current_pr_head_and_base(self):
        good = self.automatic()
        association = good["pull_requests"][0]
        rejected = [self.automatic(event="push"), self.automatic(head_sha=OLD),
                    self.automatic(status="in_progress", conclusion=None),
                    self.automatic(pull_requests=[])]
        rejected += [self.automatic(conclusion=value) for value in ("failure", "cancelled", "timed_out")]
        rejected += [self.automatic(pull_requests=[association | changes]) for changes in (
            {"number": 334}, {"url": "https://api.github.com/repos/other/fork/pulls/333"},
            {"head": {"sha": OLD}}, {"base": {"sha": "d" * 40}})]
        for candidate in rejected:
            with self.subTest(candidate=candidate), \
                    patch.object(P, "pages", return_value=[candidate]), \
                    patch.object(P, "firmware_artifact") as artifact, \
                    patch.object(P, "gh") as gh, self.assertRaisesRegex(ValueError, "no build was requested"):
                P.automatic_run(REPO, "333", SHA, OLD)
            artifact.assert_not_called()
            gh.assert_not_called()
        with patch.object(P, "pages", return_value=[good]) as pages, \
                patch.object(P, "firmware_artifact", return_value={"name": "firmware-42"}), \
                patch.object(P, "gh") as gh:
            self.assertEqual(P.automatic_run(REPO, "333", SHA, OLD), good)
        self.assertIn(f"event=pull_request&head_sha={SHA}", pages.call_args.args[0])
        gh.assert_not_called()

    def test_selection_uses_newest_live_artifact_and_fails_if_all_expired(self):
        runs = [self.automatic(id=value) for value in (41, 43, 42)]
        for available in (42, None):
            with patch.object(P, "pages", return_value=runs), \
                    patch.object(P, "firmware_artifact", side_effect=lambda repo, run:
                                 {"name": f"firmware-{run['id']}"} if run["id"] == available else None):
                if available:
                    self.assertEqual(P.automatic_run(REPO, 333, SHA, OLD)["id"], available)
                else:
                    with self.assertRaisesRegex(ValueError, "live firmware artifact"):
                        P.automatic_run(REPO, 333, SHA, OLD)

    def test_incompatible_cli_options_fail_before_network_or_installer_setup(self):
        for options in (["--validation", "target"], ["--workflow-ref", "main"],
                        ["--worktree"], ["--worktree-dir", "somewhere"],
                        ["--prepare-only"], ["--remove-worktree", "somewhere"], ["--resolve-only"]):
            with patch.object(P, "api") as api, patch.object(P, "prepare_installer") as installer:
                self.assertEqual(P.main(["333", "--automatic", *options]), 2)
            api.assert_not_called()
            installer.assert_not_called()


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

    def preserve_commit(self, root, revision):
        backup = self.base / "preserved.git"
        self.git(self.base, "init", "--bare", str(backup))
        self.git(root, "remote", "add", "preserved", str(backup))
        self.git(root, "push", "preserved", f"{revision}:refs/heads/kept")
        return backup

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
        self.assertEqual(self.prepare(), self.path.resolve())
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
        self.assertEqual(self.prepare(), self.path.resolve())
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
        local = self.git(nested, "rev-parse", "HEAD")
        self.git(nested, "checkout", "--detach", pinned)
        with self.assertRaisesRegex(ValueError, "local submodule commits"):
            self.remove()
        self.assertTrue(self.path.exists())
        self.git(nested, "branch", "-D", "my-work")
        with self.assertRaisesRegex(ValueError, "local submodule commits"):
            self.remove()
        backup = self.preserve_commit(nested, local)
        self.remove()
        self.assertEqual(self.git(backup, "show", "refs/heads/kept:tracked"), "local commit")

    def test_cleanup_preserves_reflog_only_nested_submodule_commits_until_backed_up(self):
        self.prepare()
        nested = self.path / "engine/nested"
        pinned = self.git(nested, "rev-parse", "HEAD")
        (nested / "tracked").write_text("detached local work\n")
        self.commit(nested)
        local = self.git(nested, "rev-parse", "HEAD")
        self.git(nested, "checkout", "--detach", pinned)
        private = Path(self.git(nested, "rev-parse", "--absolute-git-dir"))
        self.assertEqual(self.git(nested, "rev-list", "--all", "--not", "--remotes", "HEAD"), "")
        self.assertEqual(self.git(nested, "rev-list", "--reflog", "--all", "--not", "--remotes", "HEAD"), local)
        retained = {file: file.read_bytes() for file in
                    (nested / "tracked", private / "HEAD", private / "logs/HEAD")}
        with self.assertRaisesRegex(ValueError, "local submodule commits"):
            self.remove()
        self.assertTrue(self.path.is_dir())
        self.assertTrue(private.is_dir())
        for file, content in retained.items():
            self.assertEqual(file.read_bytes(), content)
        self.assertEqual(self.git(nested, "show", f"{local}:tracked"), "detached local work")

        # A branch in the private Git directory would still be deleted. Preserve
        # the commit in an independent repository before retrying removal.
        backup = self.preserve_commit(nested, local)
        self.assertEqual(self.git(backup, "show", "refs/heads/kept:tracked"), "detached local work")
        self.remove()
        self.assertFalse(self.path.exists())
        self.assertFalse(private.exists())
        self.assertEqual(self.git(backup, "show", "refs/heads/kept:tracked"), "detached local work")

    def test_cleanup_preserves_reflog_only_parent_commits_until_pushed(self):
        self.prepare()
        (self.path / "tracked").write_text("detached parent work\n")
        self.commit(self.path)
        local = self.git(self.path, "rev-parse", "HEAD")
        self.git(self.path, "checkout", "--detach", self.revision)
        private = Path(self.git(self.path, "rev-parse", "--absolute-git-dir"))
        self.assertEqual(self.git(self.path, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(self.git(self.path, "status", "--porcelain"), "")
        retained = {file: file.read_bytes() for file in (private / "HEAD", private / "logs/HEAD")}
        with self.assertRaisesRegex(ValueError, "parent commits"):
            self.remove()
        self.assertTrue(self.path.is_dir())
        self.assertTrue(private.is_dir())
        for file, content in retained.items():
            self.assertEqual(file.read_bytes(), content)
        self.assertEqual(self.git(self.path, "show", f"{local}:tracked"), "detached parent work")

        backup = self.preserve_commit(self.path, local)
        self.remove()
        self.assertFalse(self.path.exists())
        self.assertFalse(private.exists())
        self.assertEqual(self.git(backup, "show", "refs/heads/kept:tracked"), "detached parent work")

    def check_deinitialized_submodule_cleanup(self, target):
        self.prepare()
        nested = self.path / "engine/nested"
        self.assertEqual(self.git(nested, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")
        (nested / "tracked").write_text("deinitialized detached work\n")
        self.commit(nested)
        local = self.git(nested, "rev-parse", "HEAD")
        private = Path(self.git(nested, "rev-parse", "--absolute-git-dir"))
        target = Path(target)
        self.git(self.path / target.parent, "submodule", "deinit", "--force", "--", target.name)
        # Deinitialization hides this repository from recursive foreach/status,
        # including when an ancestor submodule is the one deinitialized.
        retained = {file: file.read_bytes() for file in
                    (private / "HEAD", private / "logs/HEAD", self.path / "tracked")}
        with self.assertRaisesRegex(ValueError, "uninitialized submodules"):
            self.remove()
        self.assertTrue(self.path.is_dir())
        self.assertTrue(private.is_dir())
        for file, content in retained.items():
            self.assertEqual(file.read_bytes(), content)
        self.assertEqual(self.git(self.path, "--git-dir", str(private), "--work-tree", str(self.path),
                                  "show", f"{local}:tracked"),
                         "deinitialized detached work")

        # The helper never initializes on removal. Explicitly restore the fixture
        # and back up its detached commit outside the disposable worktree.
        self.git(self.path, "submodule", "update", "--init", "--recursive", "--checkout")
        with self.assertRaisesRegex(ValueError, "local submodule commits"):
            self.remove()
        backup = self.preserve_commit(nested, local)
        self.remove()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.git(backup, "show", "refs/heads/kept:tracked"), "deinitialized detached work")

    def test_cleanup_preserves_deinitialized_nested_submodule_work(self):
        self.check_deinitialized_submodule_cleanup("engine/nested")

    def test_cleanup_preserves_nested_work_under_deinitialized_ancestor(self):
        self.check_deinitialized_submodule_cleanup("engine")

    def test_cleanup_preserves_orphaned_submodule_repository(self):
        self.prepare()
        parent = self.path / "engine"
        self.git(parent, "submodule", "add", str(self.base / "leaf"), "temporary")
        orphan = parent / "temporary"
        self.git(orphan, "checkout", "--detach")
        (orphan / "tracked").write_text("orphan detached work\n")
        self.commit(orphan)
        local = self.git(orphan, "rev-parse", "HEAD")
        private = Path(self.git(orphan, "rev-parse", "--absolute-git-dir"))
        self.git(parent, "submodule", "deinit", "--force", "--", "temporary")
        self.git(parent, "rm", "--cached", "temporary")
        self.git(parent, "restore", "--source", "HEAD", "--staged", "--worktree", ".gitmodules")
        orphan.rmdir()
        self.assertFalse(any(line.startswith("-") for line in
                             self.git(self.path, "submodule", "status", "--recursive").splitlines()))
        self.assertEqual(self.git(self.path, "status", "--porcelain"), "")
        retained = {file: file.read_bytes() for file in (private / "HEAD", private / "logs/HEAD")}
        with self.assertRaisesRegex(ValueError, "orphaned submodule repositories"):
            self.remove()
        self.assertTrue(self.path.is_dir())
        for file, content in retained.items():
            self.assertEqual(file.read_bytes(), content)

        backup = self.base / "preserved.git"
        self.git(self.base, "init", "--bare", str(backup))
        self.git(backup, "fetch", str(private), f"{local}:refs/heads/kept")
        self.assertEqual(self.git(backup, "show", "refs/heads/kept:tracked"), "orphan detached work")
        # Cleanup cannot resolve an orphan automatically, even after a backup.
        with self.assertRaisesRegex(ValueError, "orphaned submodule repositories"):
            self.remove()
        self.assertTrue(private.is_dir())

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
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(self.revision, TITLE)), \
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
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(self.revision, TITLE)), \
                patch.object(P, "prepare_worktree", side_effect=ValueError("submodule failed")), \
                patch.object(P, "ensure_run") as build, patch.object(P, "install") as install:
            self.assertEqual(P.main(["333", "--worktree"]), 2)
        build.assert_not_called()
        install.assert_not_called()

    def test_cli_resolve_only_has_no_git_mutations(self):
        output = io.StringIO()
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(self.revision, TITLE)), \
                patch.object(P, "prepare_worktree") as prepare, \
                patch.object(P, "remove_worktree") as remove, patch.object(P, "ensure_run") as build, \
                contextlib.redirect_stdout(output):
            self.assertEqual(P.main(["333", "--resolve-only", "--worktree"]), 0)
        self.assertEqual(output.getvalue(), self.revision + "\n")
        for call in (prepare, remove, build):
            call.assert_not_called()

    def test_cli_worktree_keeps_pinned_ci_download_and_installer_flow(self):
        package = self.base / "firmware.fwsc"
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(self.revision, TITLE)), \
                patch.object(P, "prepare_worktree") as prepare, \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()) as build, \
                patch.object(P, "download", return_value=package) as download, \
                patch.object(P, "install", return_value=0) as install:
            self.assertEqual(P.main(["333", "--worktree"]), 0)
        prepare.assert_called_once_with(REPO, "333", self.revision, None)
        build.assert_called_once_with(REPO, "333", self.revision, "main", 3600, False, "full", "standard")
        self.assertEqual(download.call_args.args[2], self.revision)
        install.assert_called_once_with(package, None, False, command=PYTHON_INSTALLER)


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

    def test_automatic_cli_verifies_merge_before_install_or_download_only(self):
        for download_only, recorded in ((False, MERGE), (True, MERGE), (False, SHA)):
            output = io.StringIO()
            def downloaded(*args, **kwargs):
                root = Path(args[args.index("--dir") + 1])
                self.artifact(root)
                (root / "provenance.json").write_text(json.dumps({"revision": recorded}))
                return ""
            with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER) as prepare, \
                    patch.object(P, "resolve_automatic_pr", return_value=(SHA, OLD, MERGE, TITLE)), \
                    patch.object(P, "automatic_run", return_value=run()) as automatic, \
                    patch.object(P, "resolve_pr") as exact, patch.object(P, "ensure_run") as dispatch, \
                    patch.object(P, "gh", side_effect=downloaded), \
                    patch.object(P, "install", return_value=0) as install, contextlib.redirect_stdout(output):
                options = ["--download-only", "--no-build"] if download_only else []
                self.assertEqual(P.main(["333", "--automatic", "--out",
                                         str(self.root / "out"), *options]), 0 if recorded == MERGE else 2)
            automatic.assert_called_once_with(REPO, "333", SHA, OLD)
            exact.assert_not_called()
            dispatch.assert_not_called()
            if download_only:
                prepare.assert_not_called()
            if download_only or recorded != MERGE:
                install.assert_not_called()
            else:
                self.assertEqual(install.call_count, 1)
                self.assertEqual(install.call_args.kwargs["command"], PYTHON_INSTALLER)
            self.assertIn(f"Commit: {MERGE}", output.getvalue())
            self.assertIn(f"PR head: {SHA}", output.getvalue())
            self.assertIn(f"Base commit: {OLD}", output.getvalue())

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
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()) as build, \
                patch.object(P, "download", return_value=self.root / "felucca.fwsc") as download, \
                patch.object(P, "install") as install, contextlib.redirect_stdout(output):
            self.assertEqual(P.main(["333", "--validation", "target", "--download-only"]), 0)
        build.assert_called_once_with(REPO, "333", SHA, "main", 3600, False, "target", "standard")
        self.assertEqual(download.call_args.args[-2:], ("target", "standard"))
        install.assert_not_called()
        self.assertIn("does not replace full PR validation", output.getvalue())

    def test_profile_download_requires_matching_provenance_and_generated_selection(self):
        record = self.root / "provenance.json"
        with self.assertRaisesRegex(ValueError, "profile provenance"):
            P.verify_download(self.root, SHA, profile="macro")
        selection = {"profile": "macro", "selection_sha256": "f" * 64}
        record.write_text(json.dumps({"revision": SHA, "profile": selection}))
        with self.assertRaisesRegex(ValueError, "requested profile"):
            P.verify_download(self.root, SHA)
        with self.assertRaisesRegex(ValueError, "resolved-profile"):
            P.verify_download(self.root, SHA, profile="macro")
        generated = self.root / "resolved-profile.json"
        generated.write_text(json.dumps(selection | {"profile": "standard"}))
        with self.assertRaisesRegex(ValueError, "differs from provenance"):
            P.verify_download(self.root, SHA, profile="macro")
        generated.write_text(json.dumps(selection))
        self.assertEqual(P.verify_download(self.root, SHA, profile="macro"), self.root / "felucca.fwsc")

    def test_profile_cli_propagates_and_rejects_wrong_package_before_install(self):
        with patch.object(P, "prepare_installer", return_value=["flasher"]), \
                patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
                patch.object(P, "validate_profile_source") as source, \
                patch.object(P, "ensure_run", return_value=run()) as build, \
                patch.object(P, "download", side_effect=ValueError("Firmware profile mismatch")) as download, \
                patch.object(P, "install") as install:
            self.assertEqual(P.main(["333", "--profile", "macro", "--workflow-ref", "candidate"]), 2)
        source.assert_called_once_with(REPO, SHA, "macro")
        build.assert_called_once_with(REPO, "333", SHA, "candidate", 3600, False, "full", "macro")
        self.assertEqual(download.call_args.args[-1], "macro")
        install.assert_not_called()

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
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()), \
                patch.object(P, "gh", side_effect=download), patch.object(P, "install") as install:
            self.assertEqual(P.main(["333", "--download-only", "--out", str(self.root / "out")]), 0)
        install.assert_not_called()
        self.assertEqual(len(list((self.root / "out").rglob("*.fwsc"))), 1)

    def test_verification_error_blocks_installer(self):
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
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
        for repository in (REPO, "another/fork"):
            with self.subTest(repository=repository):
                output = io.StringIO()
                def installed(*args, **kwargs):
                    # GitHub may be unavailable once the device update finishes.
                    api.side_effect = ValueError("GitHub unavailable after installation")
                    return 0
                with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                        patch.object(P, "api", side_effect=[{"head": {"sha": SHA}, "title": TITLE},
                                                          {"default_branch": "main"}]) as api, \
                        patch.object(P, "ensure_run", return_value=run()), \
                        patch.object(P, "download", return_value=self.root / "felucca.fwsc"), \
                        patch.object(P, "install", side_effect=installed) as install, \
                        contextlib.redirect_stdout(output):
                    self.assertEqual(P.main(["333", "--repo", repository, "--port", "Felucca"]), 0)
                install.assert_called_once_with(self.root / "felucca.fwsc", "Felucca", False,
                                                command=PYTHON_INSTALLER)
                self.assertIn("still require hardware validation", output.getvalue())
                self.assertTrue(output.getvalue().endswith(
                    f"PR #333: {TITLE}\nhttps://github.com/{repository}/pull/333\n"))

    def test_failed_installer_has_no_success_summary(self):
        output = io.StringIO()
        with patch.object(P, "prepare_installer", return_value=PYTHON_INSTALLER), \
                patch.object(P, "resolve_pr", return_value=(SHA, TITLE)), \
                patch.object(P, "api", return_value={"default_branch": "main"}), \
                patch.object(P, "ensure_run", return_value=run()), \
                patch.object(P, "download", return_value=self.root / "felucca.fwsc"), \
                patch.object(P, "install", return_value=5), contextlib.redirect_stdout(output):
            self.assertEqual(P.main(["333"]), 5)
        self.assertNotIn("Installer finished", output.getvalue())
        self.assertNotIn(TITLE, output.getvalue())
        self.assertNotIn("/pull/333", output.getvalue())


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
