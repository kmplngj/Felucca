#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline watch regressions: legacy evidence, real Git DAGs and crash safety."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import firmware_watch as W

REPO = "fixture/donor"
NATIVE = "f" * 40


def git(path, *args):
    env = os.environ | {"GIT_AUTHOR_NAME": "Watch fixture", "GIT_AUTHOR_EMAIL": "watch@example.invalid",
                       "GIT_COMMITTER_NAME": "Watch fixture", "GIT_COMMITTER_EMAIL": "watch@example.invalid"}
    return subprocess.check_output(["git", "-C", str(path), *args], env=env,
                                   stderr=subprocess.PIPE, text=True).strip()


def source(repo, base, tip=None, branches=("main",), identity=123):
    return {"repository": repo, "repository_id": identity,
            "historical_targets": dict.fromkeys(branches, base),
            "recent_frontiers": dict.fromkeys(branches, base),
            "pinned_recent_targets": dict.fromkeys(branches, tip or base),
            "historical_total_at_setup": 1, "recent_total_at_setup": 0,
            "historical_reviewed": 0, "recent_reviewed": 0, "last_reviewed_sha": None}


def review(sha, disposition="not_applicable", repo=REPO, queue="recent"):
    return {"repository": repo, "source_sha": sha, "parents": [], "branches": ["main"],
            "queue": queue, "commit_title": "Fixture commit", "changed_paths": [],
            "felucca_comparison_sha": NATIVE, "disposition": disposition,
            "rationale": "Compared fixture source to native implementation; no applicable change.",
            "source_evidence": [f"https://github.com/{repo}/commit/{sha}"],
            "native_evidence": [f"https://github.com/kmplngj/Felucca/blob/{NATIVE}/README.md"],
            "issue_urls": [], "run_id": "fixture-run"}


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.cache = self.root / "cache"
        self.watch = W.Watch(self.data, self.cache)
        # Any accidental external process is a test failure; local Git still runs.
        self.original_run = W.run
        self.command_log = []
        self.network = patch.object(W, "run", side_effect=self.offline_run)
        self.network.start()
        self.addCleanup(self.network.stop)

    def offline_run(self, args, *a, **kw):
        self.command_log.append(list(args))
        if args[0] == "gh":
            raise AssertionError(f"Unexpected GitHub access: {args}")
        if args[0] == "git" and any(x in args for x in ("fetch", "clone", "push")):
            raise AssertionError(f"Unexpected remote Git access: {args}")
        return self.original_run(args, *a, **kw)

    def snapshot(self, sources, records=(), extra=None):
        state = {"schema_version": 1, "destination_repo": "kmplngj/Felucca",
                 "repositories": sources, "pending_source_additions": [],
                 "latest_felucca_comparison_sha": NATIVE, "round_robin_next_repository_index": 0}
        state.update(extra or {})
        body = "<!-- felucca-firmware-watch-state:start -->\n```json\n" + json.dumps(state) + "\n```\n<!-- felucca-firmware-watch-state:end -->"
        comments = []
        for i, r in enumerate(records):
            comments.append({"id": i + 1, "url": f"https://github.com/kmplngj/Felucca/issues/152#issuecomment-{i+1}",
                             "body": "<!-- felucca-firmware-watch-journal:v1 -->\n```json\n" +
                             json.dumps({"schema_version": 1, "records": [r]}) + "\n```"})
        path = self.root / "snapshot.json"
        path.write_text(json.dumps({"issue_url": "https://github.com/kmplngj/Felucca/issues/152",
                                    "body": body, "comments": comments}))
        return path

    def migrate(self, sources, records=(), extra=None):
        self.watch.migrate(self.snapshot(sources, records, extra))

    def contents(self):
        return {str(p.relative_to(self.data)): p.read_bytes() for p in self.data.rglob("*") if p.is_file()}

    def state(self):
        return json.loads((self.data / "state.json").read_text())

    def runtime(self, repo=REPO):
        return next(s for s in self.state()["repositories"] if s["repository"] == repo)

    def record(self, *records):
        path = self.root / "record.json"
        path.write_text(json.dumps({"records": list(records)}))
        return self.watch.record(path)

    def repository(self):
        path = self.root / "donor"
        path.mkdir()
        git(path, "init", "-b", "main")
        return path

    def commit(self, path, title):
        git(path, "commit", "--allow-empty", "-m", title)
        return git(path, "rev-parse", "HEAD")

    def seed_cache(self, path, repo=REPO):
        target = self.watch.cache(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(["git", "clone", "--bare", str(path), str(target)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return target

    def tasks(self, limit=100):
        result = self.watch.queue(limit)
        self.assertEqual(result["blockers"], [], result)
        return result["tasks"]

    def test_migration_is_lossless_deterministic_and_idempotent(self):
        entry = source(REPO, "a" * 40)
        entry["future_source_metadata"] = {"unicode": "WAVE — λ"}
        pending = source("fixture/pending", "c" * 40, identity=124) | {"status": "pending_initialization", "authorization": "User request"}
        path = self.snapshot([entry], [review("b" * 40)], {"pending_source_additions": [pending], "future_state": [1, 2]})
        self.watch.migrate(path)
        before = self.contents()
        self.watch.migrate(path)
        self.assertEqual(before, self.contents())
        other = W.Watch(self.root / "other", self.root / "other-cache")
        other.migrate(path)
        self.assertEqual(before, {str(p.relative_to((self.root / "other"))): p.read_bytes() for p in (self.root / "other").rglob("*") if p.is_file()})
        self.assertEqual(json.loads((self.data / "sources.json").read_text())["pending_source_additions"], [pending])
        self.assertEqual(self.state()["future_state"], [1, 2])
        self.assertIn("WAVE", (self.data / "sources.json").read_text())
        self.watch.validate()

    def test_malformed_marked_comment_prevents_partial_migration(self):
        path = self.snapshot([source(REPO, "a" * 40)])
        value = json.loads(path.read_text())
        value["comments"].append({"id": 99, "url": "https://example.invalid/99", "body": "<!-- felucca-firmware-watch-journal:v1 -->\n```json\n{broken\n```"})
        path.write_text(json.dumps(value))
        with self.assertRaises((W.WatchError, json.JSONDecodeError)):
            self.watch.migrate(path)
        self.assertFalse((self.data / "state.json").exists())

    def test_conflicting_legacy_terminal_evidence_rejected(self):
        one = review("a" * 40)
        two = one | {"disposition": "existing_issue", "issue_urls": ["https://github.com/kmplngj/Felucca/issues/1"]}
        with self.assertRaises((W.WatchError, json.JSONDecodeError)):
            self.migrate([source(REPO, "a" * 40)], [one, two])
        self.assertFalse((self.data / "state.json").exists())

    def test_complete_merge_dag_includes_side_history_roots_and_deduplicates_branches(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        git(repo, "checkout", "-b", "side")
        side = self.commit(repo, "side history")
        git(repo, "checkout", "main")
        main = self.commit(repo, "main history")
        git(repo, "merge", "--no-ff", "side", "-m", "merge side")
        merge = git(repo, "rev-parse", "HEAD")
        git(repo, "branch", "next")
        self.migrate([source(REPO, merge, branches=("main", "next"))])
        self.seed_cache(repo)
        tasks = self.tasks()
        self.assertEqual({t["source_sha"] for t in tasks}, {root, side, main, merge})
        self.assertEqual(len(tasks), 4)
        self.assertTrue(all(set(t["branches"]) == {"main", "next"} for t in tasks))
        self.assertTrue(all(t["queue"] == "history" for t in tasks))
        self.assertEqual(next(t["parents"] for t in tasks if t["source_sha"] == root), [])
        order = {t["source_sha"]: i for i, t in enumerate(tasks)}
        self.assertLess(order[root], order[side])
        self.assertLess(order[side], order[merge])

    def test_pending_and_out_of_order_completion_do_not_skip_recent_holes(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        first = self.commit(repo, "first recent")
        tip = self.commit(repo, "tip")
        self.migrate([source(REPO, root, tip)], [review(first, "pending"), review(tip)])
        self.seed_cache(repo)
        self.watch.checkpoint()
        self.assertEqual(self.runtime()["recent_frontiers"]["main"], root)
        self.assertIn(first, {t["source_sha"] for t in self.tasks()})
        self.assertNotIn(tip, {t["source_sha"] for t in self.tasks()})
        self.record(review(first) | {"parents": [root], "commit_title": "first recent"})
        self.watch.checkpoint()
        self.assertEqual(self.runtime()["recent_frontiers"]["main"], tip)
        self.assertIn(root, {t["source_sha"] for t in self.tasks()})

    def test_incorrect_frontier_cannot_hide_unreviewed_hole_or_block_other_sources(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        first = self.commit(repo, "unreviewed recent")
        tip = self.commit(repo, "out of order completed")
        other = "fixture/unblocked"
        completed = review(tip) | {"parents": [first], "commit_title": "out of order completed"}
        self.migrate([source(REPO, root, tip), source(other, root, identity=124)], [completed])
        self.seed_cache(repo)
        self.seed_cache(repo, other)
        state = self.state()
        next(r for r in state["repositories"] if r["repository"] == REPO)["recent_frontiers"]["main"] = tip
        (self.data / "state.json").write_text(json.dumps(state))
        journal = (self.data / "reviews.jsonl").read_bytes()
        queued = self.watch.queue(10)
        self.assertEqual([(t["repository"], t["source_sha"]) for t in queued["tasks"]], [(other, root)])
        self.assertEqual({b["repository"] for b in queued["blockers"]}, {REPO})
        summary = self.watch.summary()
        self.assertFalse(summary["complete_inventory"])
        self.assertIsNone(summary["remaining_recent"])
        self.assertIsNone(summary["remaining_history"])
        self.assertEqual(summary["known_remaining_history"], 1)
        self.assertEqual(summary["terminal_pairs"], 1)
        checkpoint = self.watch.checkpoint()
        self.assertEqual({b["repository"] for b in checkpoint["blockers"]}, {REPO})
        self.assertEqual((self.data / "reviews.jsonl").read_bytes(), journal)
        self.assertEqual(self.runtime()["recent_frontiers"]["main"], tip)
        # Correcting the bad cached frontier restores the hole without any review credit.
        state = self.state()
        next(r for r in state["repositories"] if r["repository"] == REPO)["recent_frontiers"]["main"] = root
        (self.data / "state.json").write_text(json.dumps(state))
        restored = self.tasks()
        self.assertIn((REPO, first), {(t["repository"], t["source_sha"]) for t in restored})
        self.assertNotIn((REPO, tip), {(t["repository"], t["source_sha"]) for t in restored})

    def test_same_sha_in_different_repositories_remains_two_assessments(self):
        repo = self.repository()
        root = self.commit(repo, "shared root")
        self.migrate([source(REPO, root), source("fixture/other", root, identity=124)])
        self.seed_cache(repo)
        self.seed_cache(repo, "fixture/other")
        tasks = self.tasks()
        self.assertEqual({(t["repository"], t["source_sha"]) for t in tasks},
                         {(REPO, root), ("fixture/other", root)})
        self.record(review(root, queue="history") | {"commit_title": "shared root"})
        self.assertEqual([(t["repository"], t["source_sha"]) for t in self.tasks()], [("fixture/other", root)])

    def test_round_robin_recent_history_share_and_repository_fairness(self):
        repo = self.repository()
        history = [self.commit(repo, f"history {n}") for n in range(15)]
        recent = [self.commit(repo, f"recent {n}") for n in range(15)]
        names = ["fixture/one", "fixture/two", "fixture/three"]
        self.migrate([source(name, history[-1], recent[-1], identity=200 + n)
                      for n, name in enumerate(names)])
        for name in names:
            self.seed_cache(repo, name)
        tasks = self.tasks(50)
        self.assertEqual(len(tasks), 50)
        self.assertEqual(sum(t["queue"] == "recent" for t in tasks), 30)
        self.assertEqual(sum(t["queue"] == "history" for t in tasks), 20)
        for lane in ("recent", "history"):
            counts = [sum(t["queue"] == lane and t["repository"] == name for t in tasks) for name in names]
            self.assertLessEqual(max(counts) - min(counts), 1)
        self.assertEqual(len({(t["repository"], t["source_sha"]) for t in tasks}), 50)

    def test_small_batches_rotate_repository_cursor_only_after_accepted_record(self):
        repo = self.repository()
        self.commit(repo, "root")
        tip = self.commit(repo, "tip")
        names = ["fixture/one", "fixture/two", "fixture/three"]
        self.migrate([source(name, tip, identity=300 + n) for n, name in enumerate(names)])
        for name in names:
            self.seed_cache(repo, name)
        first = self.tasks(1)[0]
        self.assertEqual(first["repository"], names[0])
        item = review(first["source_sha"], repo=names[0], queue="history") | {
            key: first[key] for key in ("parents", "branches", "commit_title", "changed_paths")}
        original_atomic_json = W.atomic_json
        def interrupt_state(path, document):
            if Path(path).name == "state.json":
                raise OSError("crash after journal fsync before cursor checkpoint")
            return original_atomic_json(path, document)
        with patch.object(W, "atomic_json", side_effect=interrupt_state):
            with self.assertRaises(OSError):
                self.record(item)
        self.record(item)
        self.assertEqual(self.tasks(1)[0]["repository"], names[1])
        cursor = self.state()["round_robin_next_repository_index"]
        self.record(item)
        self.assertEqual(self.state()["round_robin_next_repository_index"], cursor)
        self.assertEqual(self.tasks(1)[0]["repository"], names[1])

    def test_shallow_graph_is_blocked_instead_of_crediting_partial_history(self):
        repo = self.repository()
        self.commit(repo, "root")
        tip = self.commit(repo, "tip")
        self.migrate([source(REPO, tip)])
        target = self.watch.cache(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(["git", "clone", "--bare", "--depth=1", repo.as_uri(), str(target)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = self.watch.queue(10)
        self.assertEqual(result["tasks"], [])
        self.assertTrue(result["blockers"])
        self.assertIn("shallow", json.dumps(result["blockers"]).lower())
        summary = self.watch.summary()
        self.assertFalse(summary["complete_inventory"])
        self.assertIsNone(summary["remaining_history"])
        self.assertIsNone(summary["remaining_recent"])
        self.assertEqual(summary["known_remaining_history"], 0)

    def sync_with_remote(self, tips, identities=None):
        """Mock only remote responses; object traversal and ref validation use Git."""
        def remote(args, *a, **kw):
            self.command_log.append(list(args))
            if args[0] == "gh":
                self.assertEqual(args[1], "api")
                name = args[2].removeprefix("repos/")
                return json.dumps({"id": (identities or {}).get(name, 123), "full_name": name})
            if args[0] == "git" and "fetch" in args:
                cache = next(v.split("=", 1)[1] for v in args if v.startswith("--git-dir="))
                for refspec in (v for v in args if v.startswith("+refs/heads/")):
                    branch = refspec.split(":", 1)[0].removeprefix("+refs/heads/")
                    if branch not in tips:
                        raise W.WatchError("missing tracked branch " + branch)
                    self.original_run(["git", "--git-dir=" + cache, "update-ref", "refs/watch/" + branch, tips[branch]])
                return ""
            return self.offline_run(args, *a, **kw)
        with patch.object(W, "run", side_effect=remote):
            return self.watch.sync()

    def test_sync_freezes_recent_target_until_older_interval_is_complete(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        frozen = self.commit(repo, "first recent")
        live = self.commit(repo, "newer recent")
        self.migrate([source(REPO, root, frozen)])
        self.seed_cache(repo)
        self.assertEqual(self.sync_with_remote({"main": live})["blockers"], [])
        self.watch.checkpoint()
        self.assertEqual(self.runtime()["pinned_recent_targets"]["main"], frozen)
        self.assertNotIn(live, {t["source_sha"] for t in self.tasks()})
        self.record(review(frozen) | {"parents": [root], "commit_title": "first recent"})
        self.assertEqual(self.runtime()["recent_frontiers"]["main"], frozen)
        self.assertEqual(self.runtime()["pinned_recent_targets"]["main"], live)
        self.assertIn(live, {t["source_sha"] for t in self.tasks()})
        gh_calls = [c for c in self.command_log if c[0] == "gh"]
        self.assertEqual(gh_calls, [["gh", "api", "repos/" + REPO]])

    def test_rewrite_missing_branch_and_identity_mismatch_block_without_coverage(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        frozen = self.commit(repo, "frozen target")
        self.migrate([source(REPO, root, frozen)])
        self.seed_cache(repo)
        for tips, ids, reason in (({"main": root}, None, "rewrite"),
                                  ({}, None, "missing tracked branch"),
                                  ({"main": frozen}, {REPO: 999}, "stable ID")):
            with self.subTest(reason=reason):
                result = self.sync_with_remote(tips, ids)
                self.assertIn(reason, json.dumps(result["blockers"]))
                self.assertEqual(self.runtime()["recent_frontiers"]["main"], root)
                self.assertEqual(self.runtime()["pinned_recent_targets"]["main"], frozen)
                self.assertEqual((self.data / "reviews.jsonl").read_bytes(), b"")
                self.assertEqual(self.watch.queue(10)["tasks"], [])

    def test_failed_pending_initialization_preserves_authorization_and_full_metadata(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        pending = source("fixture/new", root, identity=124) | {
            "status": "pending_initialization", "authorization": "User explicitly requested WAVE", "unknown_metadata": [1, 2]}
        self.migrate([source(REPO, root)], extra={"pending_source_additions": [pending]})
        self.seed_cache(repo)
        self.seed_cache(repo, "fixture/new")
        result = self.sync_with_remote({"main": root}, {"fixture/new": 999})
        self.assertTrue(result["blockers"])
        sources = json.loads((self.data / "sources.json").read_text())
        self.assertEqual(sources["pending_source_additions"], [pending])
        self.assertEqual([r["repository"] for r in self.state()["repositories"]], [REPO])
        self.assertEqual((self.data / "reviews.jsonl").read_bytes(), b"")
        result = self.sync_with_remote({"main": root}, {"fixture/new": 124})
        self.assertEqual(result["blockers"], [])
        sources = json.loads((self.data / "sources.json").read_text())
        self.assertEqual(sources["pending_source_additions"], [])
        admitted = next(r for r in sources["repositories"] if r["repository"] == "fixture/new")
        self.assertEqual(admitted["authorization"], pending["authorization"])
        self.assertEqual(admitted["unknown_metadata"], [1, 2])
        self.assertEqual((self.data / "reviews.jsonl").read_bytes(), b"")

    def test_writer_lock_rejects_second_process_before_mutation(self):
        self.migrate([source(REPO, "a" * 40)])
        before = self.contents()
        with W.writer_lock(self.data):
            result = subprocess.run([sys.executable, str(ROOT / "tools/firmware_watch.py"),
                                     "--data-dir", str(self.data), "--cache-dir", str(self.cache), "checkpoint"],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lock", result.stderr.lower())
        self.assertEqual(before, self.contents())

    def test_retry_after_durable_record_append_rebuilds_checkpoint_without_duplicates(self):
        repo = self.repository()
        root = self.commit(repo, "root")
        tip = self.commit(repo, "Fixture commit")
        self.migrate([source(REPO, root, tip)])
        self.seed_cache(repo)
        item = review(tip) | {"parents": [root]}
        with patch.object(self.watch, "checkpoint", side_effect=OSError("simulated crash after fsync")):
            with self.assertRaisesRegex(OSError, "simulated crash"):
                self.record(item)
        appended = (self.data / "reviews.jsonl").read_bytes()
        self.assertEqual(len(appended.splitlines()), 1)
        self.assertEqual(self.runtime()["recent_frontiers"]["main"], root)
        self.record(item)
        self.assertEqual((self.data / "reviews.jsonl").read_bytes(), appended)
        self.assertEqual(self.runtime()["recent_frontiers"]["main"], tip)

    def test_run_lease_has_explicit_ownership_and_outlives_command_lock(self):
        self.migrate([source(REPO, "a" * 40)])
        self.watch.lease("acquire", "run-one")
        with self.assertRaises(W.WatchError):
            self.watch.lease("acquire", "run-two")
        with self.assertRaises(W.WatchError):
            self.watch.lease("release", "run-two")
        with W.writer_lock(self.data):
            self.watch.validate()
        with self.assertRaises(W.WatchError):
            self.watch.lease("acquire", "run-two")
        self.watch.lease("release", "run-one")
        self.watch.lease("acquire", "run-two")
        self.watch.lease("release", "run-two")

    def test_shared_run_lease_coordinates_isolated_worktree_caches(self):
        shared = self.root / "common-git-dir" / "firmware-watch-lease"
        first = W.Watch(self.root / "worktree-one" / "data", self.root / "worktree-one" / "cache", lease_dir=shared)
        second = W.Watch(self.root / "worktree-two" / "data", self.root / "worktree-two" / "cache", lease_dir=shared)
        first.lease("acquire", "first-run")
        with self.assertRaises(W.WatchError):
            second.lease("acquire", "second-run")
        with self.assertRaises(W.WatchError):
            second.lease("release", "second-run")
        first.lease("release", "first-run")
        second.lease("acquire", "second-run")
        second.lease("release", "second-run")

    def test_missing_journal_evidence_and_migration_digest_count_corruption_fail_closed(self):
        self.migrate([source(REPO, "a" * 40)], [review("b" * 40)])
        baseline = self.contents()
        cases = (("reviews.jsonl", "rationale", None),
                 ("reviews.jsonl", "native_evidence", None),
                 ("migration-report.json", "snapshot_sha256", "0" * 64),
                 ("migration-report.json", "journal_records", 999))
        for filename, field, value in cases:
            with self.subTest(filename=filename, field=field):
                path = self.data / filename
                document = json.loads(baseline[filename])
                if value is None:
                    del document[field]
                else:
                    document[field] = value
                corrupted = (json.dumps(document) + "\n").encode()
                path.write_bytes(corrupted)
                try:
                    with self.assertRaises((W.WatchError, json.JSONDecodeError)):
                        self.watch.validate()
                    self.assertEqual(path.read_bytes(), corrupted)
                finally:
                    path.write_bytes(baseline[filename])
        self.watch.validate()

    def test_record_idempotency_terminal_conflict_and_torn_journal(self):
        repo = self.repository()
        root = self.commit(repo, "Fixture commit")
        self.migrate([source(REPO, root)])
        self.seed_cache(repo)
        item = review(root, queue="history")
        self.record(item)
        before = self.contents()
        self.record(item)
        self.assertEqual(before, self.contents())
        with self.assertRaises((W.WatchError, json.JSONDecodeError)):
            self.record(item | {"disposition": "existing_issue", "issue_urls": ["https://github.com/kmplngj/Felucca/issues/1"]})
        self.assertEqual(before, self.contents())
        journal = self.data / "reviews.jsonl"
        with journal.open("ab") as stream:
            stream.write(b'{"repository":')
        broken = journal.read_bytes()
        with self.assertRaises((W.WatchError, json.JSONDecodeError)):
            self.watch.validate()
        with self.assertRaises(W.WatchError):
            self.record(item)
        with self.assertRaises(W.WatchError):
            self.watch.checkpoint()
        self.assertEqual(broken, journal.read_bytes())


class MigratedDataTests(unittest.TestCase):
    def test_committed_ledger_validates_and_retains_all_legacy_assessments(self):
        data = ROOT / "data" / "firmware-watch"
        self.assertTrue((data / "sources.json").is_file(), "Migration must be committed with the helper")
        with tempfile.TemporaryDirectory() as tmp:
            W.Watch(data, Path(tmp)).validate()
        records = [json.loads(line) for line in (data / "reviews.jsonl").read_text().splitlines()]
        legacy = [r for r in records if r.get("provenance")]
        self.assertEqual(len(legacy), 109)
        self.assertEqual(sum(r["disposition"] != "pending" for r in legacy), 108)
        self.assertEqual(len({(r["repository"], r["source_sha"]) for r in legacy}), 109)
        snapshot = data / "legacy-issue-152.json"
        self.assertTrue(snapshot.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            migrated = Path(tmp) / "migrated"
            watch = W.Watch(migrated, Path(tmp) / "cache")
            watch.migrate(snapshot)
            first = {p.name: p.read_bytes() for p in migrated.iterdir() if p.is_file()}
            watch.migrate(snapshot)
            self.assertEqual(first, {p.name: p.read_bytes() for p in migrated.iterdir() if p.is_file()})
            watch.validate()
            imported = [json.loads(line) for line in (migrated / "reviews.jsonl").read_text().splitlines()]
            self.assertEqual(imported, legacy)


if __name__ == "__main__":
    unittest.main()
