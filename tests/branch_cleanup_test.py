#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Branch cleanup safety, API pagination and real Git lease regressions."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import branch_cleanup as cleanup

REPO = "owner/project"
BASE, HEAD, MERGE, NEW = (char * 40 for char in "abcd")
META = {"full_name": REPO, "default_branch": "main"}


def branch(name="topic", sha=HEAD, protected=False):
    return {"name": name, "commit": {"sha": sha}, "protected": protected}


def pull(state="closed", merged=True, head="topic", base="main", sha=HEAD,
         head_repo=REPO, base_repo=REPO):
    return {"number": 12, "state": state, "merged_at": "2026-10-13" if merged else None,
            "merge_commit_sha": MERGE,
            "head": {"ref": head, "sha": sha, "repo": {"full_name": head_repo}},
            "base": {"ref": base, "repo": {"full_name": base_repo}}}


class EligibilityTests(unittest.TestCase):
    def eligible(self, b=None, pulls=(), ancestors=(), metadata=META, keep=()):
        return cleanup.eligibility(b or branch(), metadata, pulls, set(ancestors).__contains__, keep)[0]

    def test_reachable_tip_without_pr_is_safe(self):
        self.assertTrue(self.eligible(ancestors=[HEAD]))

    def test_unmerged_branch_is_preserved(self):
        self.assertFalse(self.eligible())

    def test_squash_or_rebase_head_requires_reachable_merge_commit(self):
        self.assertTrue(self.eligible(pulls=[pull()], ancestors=[MERGE]))
        self.assertFalse(self.eligible(pulls=[pull()]))

    def test_new_commit_after_squash_merge_is_preserved(self):
        self.assertFalse(self.eligible(b=branch(sha=NEW), pulls=[pull()], ancestors=[MERGE]))

    def test_closed_unmerged_pr_is_preserved(self):
        self.assertFalse(self.eligible(pulls=[pull(merged=False)], ancestors=[MERGE]))

    def test_reused_branch_name_with_different_sha_is_preserved(self):
        self.assertFalse(self.eligible(pulls=[pull(sha=NEW)], ancestors=[MERGE]))

    def test_nondefault_merge_does_not_qualify(self):
        self.assertFalse(self.eligible(pulls=[pull(base="other")], ancestors=[MERGE]))

    def test_foreign_head_or_base_cannot_prove_a_merge(self):
        for changes in ({"head_repo": "fork/project"}, {"base_repo": "fork/project"},
                        {"head_repo": None}, {"base_repo": None}):
            with self.subTest(changes=changes):
                self.assertFalse(self.eligible(pulls=[pull(**changes)], ancestors=[MERGE]))

    def test_different_head_name_cannot_prove_merge(self):
        self.assertFalse(self.eligible(pulls=[pull(head="other")], ancestors=[MERGE]))

    def test_missing_merge_commit_cannot_prove_merge(self):
        pr = pull()
        pr["merge_commit_sha"] = None
        self.assertFalse(self.eligible(pulls=[pr], ancestors=[MERGE]))

    def test_open_head_and_base_are_preserved_even_if_merged(self):
        for pr in (pull(state="open", merged=False),
                   pull(state="open", merged=False, head="dependent", base="topic"),
                   pull(state="open", merged=False, head_repo="fork/project", base="topic")):
            with self.subTest(pr=pr):
                self.assertFalse(self.eligible(pulls=[pr, pull()], ancestors=[HEAD, MERGE]))

    def test_foreign_open_head_does_not_reserve_local_branch_name(self):
        pr = pull(state="open", merged=False, head_repo="fork/project")
        self.assertTrue(self.eligible(pulls=[pr], ancestors=[HEAD]))

    def test_protected_branch_is_preserved(self):
        self.assertFalse(self.eligible(b=branch(protected=True), ancestors=[HEAD]))

    def test_nonstandard_default_branch_is_preserved(self):
        self.assertFalse(self.eligible(metadata=META | {"default_branch": "topic"}, ancestors=[HEAD]))

    def test_permanent_branch_names_and_custom_patterns_are_preserved(self):
        for name in ("main", "master", "dev", "develop", "development", "stable", "staging",
                     "production", "gh-pages", "release", "releases", "maintenance", "support",
                     "release/1.6", "releases/1.6", "maintenance/1.6", "support/1.6", "stable/1.6", "v1.6"):
            with self.subTest(name=name):
                self.assertFalse(self.eligible(b=branch(name=name), ancestors=[HEAD]))
        self.assertFalse(self.eligible(ancestors=[HEAD], keep=["top*"]))

    def test_invalid_sha_and_api_errors_fail_closed(self):
        with self.assertRaises(ValueError):
            self.eligible(b=branch(sha="bad"))
        with self.assertRaises(OSError):
            cleanup.eligibility(branch(), META, [], lambda sha: (_ for _ in ()).throw(OSError("offline")))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.current = branch()
        self.live_open = []
        self.compare = {"status": "behind"}
        self.meta_calls = 0
        self.default_calls = 0
        self.change_default_name = False
        self.change_default_sha = False

    def api(self, endpoint):
        root = f"repos/{REPO}"
        if endpoint == root:
            self.meta_calls += 1
            return META | ({"default_branch": "new-main"}
                           if self.change_default_name and self.meta_calls > 1 else {})
        if endpoint == root + "/branches/main":
            self.default_calls += 1
            return branch("main", NEW if self.change_default_sha and self.default_calls > 1 else BASE)
        if endpoint == root + "/branches/topic":
            return self.current
        if endpoint == root + f"/compare/{BASE}...{HEAD}":
            return self.compare
        raise AssertionError(endpoint)

    def items(self, endpoint):
        if endpoint.endswith("/branches"):
            return [branch()]
        if endpoint.endswith("/pulls?state=closed"):
            return []
        if endpoint.endswith("/pulls"):
            return self.live_open
        raise AssertionError(endpoint)

    def run_audit(self, apply=False, report=None):
        with patch.object(cleanup, "api", side_effect=self.api), \
                patch.object(cleanup, "items", side_effect=self.items), \
                contextlib.redirect_stdout(io.StringIO()):
            return cleanup.audit(REPO, apply=apply, report=report)

    def test_dry_run_never_deletes(self):
        with patch.object(cleanup, "delete_branch") as delete:
            result = self.run_audit()
        delete.assert_not_called()
        self.assertTrue(result["completed"])
        self.assertEqual(result["branches"][0]["result"], "candidate")

    def test_apply_passes_exact_audited_sha(self):
        with patch.object(cleanup, "delete_branch") as delete:
            result = self.run_audit(apply=True)
        delete.assert_called_once_with(REPO, "topic", HEAD)
        self.assertEqual(result["branches"][0]["result"], "deleted")

    def test_concurrent_push_or_new_protection_prevents_deletion(self):
        for current in (branch(sha=NEW), branch(protected=True)):
            with self.subTest(current=current), patch.object(cleanup, "delete_branch") as delete:
                self.current = current
                result = self.run_audit(apply=True)
                delete.assert_not_called()
                self.assertEqual(result["branches"][0]["result"], "keep")

    def test_new_open_base_after_audit_prevents_deletion(self):
        calls = 0
        original = self.items

        def items(endpoint):
            nonlocal calls
            if endpoint.endswith("/pulls"):
                calls += 1
                return [] if calls == 1 else [pull(state="open", base="topic", head="dependent")]
            return original(endpoint)

        with patch.object(cleanup, "api", side_effect=self.api), \
                patch.object(cleanup, "items", side_effect=items), \
                patch.object(cleanup, "delete_branch") as delete, \
                contextlib.redirect_stdout(io.StringIO()):
            result = cleanup.audit(REPO, apply=True)
        delete.assert_not_called()
        self.assertEqual(result["branches"][0]["result"], "keep")

    def test_default_branch_change_aborts(self):
        for change in ("change_default_name", "change_default_sha"):
            with self.subTest(change=change), patch.object(cleanup, "delete_branch") as delete:
                self.setUp()
                setattr(self, change, True)
                with self.assertRaisesRegex(ValueError, "default branch changed"):
                    self.run_audit(apply=True)
                delete.assert_not_called()

    def test_lease_failure_is_reported_and_not_silently_ignored(self):
        failure = subprocess.CalledProcessError(1, ["git", "push"], stderr="stale info")
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(cleanup, "delete_branch", side_effect=failure):
            report = Path(temp) / "audit.json"
            with self.assertRaisesRegex(RuntimeError, "deletion refused"):
                self.run_audit(apply=True, report=report)
            result = json.loads(report.read_text())
            self.assertFalse(result["completed"])
            self.assertEqual(result["branches"][0]["result"], "failed")

    def test_diverged_or_ahead_comparison_is_not_merged(self):
        for status in ("diverged", "ahead"):
            with self.subTest(status=status):
                self.compare = {"status": status}
                self.assertEqual(self.run_audit()["branches"][0]["result"], "keep")
        self.compare = {"status": "identical"}
        self.assertEqual(self.run_audit()["branches"][0]["result"], "candidate")

    def test_invalid_repository_rejected_before_api_access(self):
        with patch.object(cleanup, "api") as api:
            for repo in ("-bad", "https://github.com/owner/project", "owner/project/extra"):
                with self.subTest(repo=repo), self.assertRaises(ValueError):
                    cleanup.audit(repo)
            api.assert_not_called()

    def test_paginated_api_objects_and_existing_query(self):
        data = "\n".join(json.dumps(branch(name=f"topic/{i}")) for i in range(205))
        result = subprocess.CompletedProcess([], 0, stdout=data)
        with patch.object(cleanup.subprocess, "run", return_value=result) as run:
            self.assertEqual(len(cleanup.items("repos/owner/project/pulls?state=closed")), 205)
        self.assertEqual(run.call_args.args[0], ["gh", "api", "--paginate",
                                                "repos/owner/project/pulls?state=closed&per_page=100",
                                                "--jq", ".[]"])


class GitLeaseTests(unittest.TestCase):
    def test_real_git_delete_lease_accepts_exact_head_and_refuses_concurrent_push(self):
        real_run = subprocess.run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local, remote = root / "local", root / "remote.git"

            def git(*args):
                return real_run(["git", *args], cwd=local, check=True, capture_output=True, text=True).stdout.strip()

            local.mkdir()
            real_run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            git("init", "-b", "main")
            git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "base")
            old = git("rev-parse", "HEAD")
            git("push", str(remote), "HEAD:refs/heads/topic")
            git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "new work")
            new = git("rev-parse", "HEAD")
            git("push", str(remote), "HEAD:refs/heads/topic")

            def push(command, **kwargs):
                self.assertIn(f"--force-with-lease=refs/heads/topic:{old if reject else new}", command)
                self.assertEqual(command[-2], f"https://github.com/{REPO}.git")
                return real_run([*command[:-2], str(remote), command[-1]], cwd=local, **kwargs)

            reject = True
            with patch.object(cleanup.subprocess, "run", side_effect=push), self.assertRaises(subprocess.CalledProcessError):
                cleanup.delete_branch(REPO, "topic", old)
            self.assertEqual(git("ls-remote", str(remote), "refs/heads/topic").split()[0], new)
            reject = False
            with patch.object(cleanup.subprocess, "run", side_effect=push):
                cleanup.delete_branch(REPO, "topic", new)
            self.assertEqual(git("ls-remote", str(remote), "refs/heads/topic"), "")


if __name__ == "__main__":
    unittest.main()
