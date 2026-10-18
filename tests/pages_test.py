#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Reject untrusted or mismatched artifacts before a privileged Pages deployment."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pages


class PagesTests(unittest.TestCase):
    def setUp(self):
        self.repository = "kmplngj/Felucca"
        self.run = {"id": 123, "repository": {"full_name": self.repository},
                    "head_repository": {"full_name": self.repository},
                    "head_branch": "main", "head_sha": "a" * 40,
                    "path": ".github/workflows/ci.yml", "event": "push",
                    "status": "completed", "conclusion": "success"}
        self.artifact = {"name": "site-123", "expired": False, "id": 456}

    def test_only_successful_main_ci_is_accepted(self):
        for field, bad in (("event", "pull_request"), ("event", "pull_request_target"),
                           ("head_branch", "feature"), ("status", "in_progress"),
                           ("conclusion", "failure"), ("conclusion", "cancelled"),
                           ("path", ".github/workflows/release.yml"),
                           ("repository", {"full_name": "other/Felucca"}),
                           ("head_repository", {"full_name": "other/Felucca"})):
            with self.subTest(field=field, value=bad):
                run = self.run | {field: bad}
                with self.assertRaisesRegex(ValueError, "successful main CI"):
                    pages.select_run(run, {"artifacts": [self.artifact]}, self.repository)
        for event in ("push", "workflow_dispatch"):
            self.assertEqual(pages.select_run(self.run | {"event": event},
                             {"artifacts": [self.artifact]}, self.repository), self.artifact)

    def test_docs_or_expired_artifacts_do_not_deploy(self):
        for artifacts in ([], [self.artifact | {"expired": True}],
                          [self.artifact | {"name": "site-999"}]):
            self.assertIsNone(pages.select_run(self.run, {"artifacts": artifacts}, self.repository))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            pages.select_run(self.run, {"artifacts": [self.artifact, self.artifact]}, self.repository)

    def test_provenance_must_bind_artifact_to_repository_run_and_revision(self):
        data = {"firmware": {"repository": self.repository, "revision": self.run["head_sha"]},
                "run_id": "123"}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "provenance.json"
            path.write_text(json.dumps(data))
            pages.check_site(temp, self.run, self.repository)
            for section, field, value in (("firmware", "repository", "other/Felucca"),
                                           ("firmware", "revision", "b" * 40),
                                           (None, "run_id", "999")):
                with self.subTest(field=field):
                    bad = copy.deepcopy(data)
                    (bad[section] if section else bad)[field] = value
                    path.write_text(json.dumps(bad))
                    with self.assertRaisesRegex(ValueError, "provenance"):
                        pages.check_site(temp, self.run, self.repository)


if __name__ == "__main__":
    unittest.main()
