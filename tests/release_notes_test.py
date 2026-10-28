#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Release trust boundaries and complete changelog regression checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import release_notes as release
import ci


class ReleaseTest(unittest.TestCase):
    def test_dev_requires_merged_pr_for_exact_main_tip_in_this_repo(self):
        sha = 'a' * 40
        pr = dict(number=42, merged_at='2026-10-28', merge_commit_sha=sha,
                  base={'ref': 'main', 'repo': {'full_name': 'owner/repo'}})
        identity = release.dev_identity([pr], 'owner/repo', sha)
        self.assertEqual(identity['tag'], 'dev-pr42-' + sha[:12])
        ci.version(identity['version'])  # Real package version validator.
        for wrong in (dict(pr, merged_at=None), dict(pr, merge_commit_sha='b' * 40),
                      dict(pr, base={'ref': 'other', 'repo': {'full_name': 'owner/repo'}})):
            self.assertIsNone(release.dev_identity([wrong], 'owner/repo', sha))
        self.assertIsNone(release.dev_identity([pr], 'another/repo', sha))
        self.assertIsNone(release.dev_identity([pr, pr], 'owner/repo', sha))
        self.assertIsNone(release.dev_identity([], 'owner/repo', sha))

    def test_publication_requires_exact_tag_commit_attestation_and_report(self):
        valid = ['1.6.2', 'a' * 40, 'tag', 'v1.6.2', 'a' * 40, 'true', 'https://example.org/report']
        release.check_approval(*valid)
        for index, wrong in ((2, 'branch'), (3, 'v1.6.1'), (4, 'b' * 40), (4, 'aaaa'),
                             (5, 'false'), (6, ''), (6, 'http://example.org'), (6, 'https://x\ntext')):
            args = valid.copy()
            args[index] = wrong
            with self.subTest(index=index, wrong=wrong), self.assertRaises(ValueError):
                release.check_approval(*args)

    def test_notes_include_direct_and_pr_commits_but_exclude_previous_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.org')
            for message in ('previous stable', 'direct maintenance', 'PR change (#42)'):
                git('commit', '--allow-empty', '-qm', message)
                if message == 'previous stable':
                    base = git('rev-parse', 'HEAD')
            sha = git('rev-parse', 'HEAD')
            with patch.object(release, 'git', side_effect=git), patch.dict(os.environ, GITHUB_RUN_ID='123'):
                dev = release.notes('dev', 'owner/repo', sha, '0.0-devPR42gabcdef', '42', base=base)
                stable = release.notes('stable', 'owner/repo', sha, '1.6.2', evidence='https://example.org/test', base=base)
            for text in (dev, stable):
                self.assertIn('direct maintenance', text)
                self.assertIn('PR change (#42)', text)
                self.assertNotIn('- ' + base[:7] + ' previous stable', text)
                self.assertIn('/blob/' + sha + '/docs/usb-rescue.md', text)
            self.assertIn('not hardware-qualified', dev)
            self.assertNotIn('author attests', dev)
            self.assertIn('https://example.org/test', stable)

    def test_publication_refuses_rebuilt_bytes_different_from_tested_package(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / 'test.fwsc'
            package.write_bytes(b'hardware tested bytes')
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            release.verify_tested_package(package, digest)
            package.write_bytes(b'different rebuild')
            with self.assertRaises(ValueError):
                release.verify_tested_package(package, digest)
            for invalid in ('', 'abc', 'z' * 64):
                with self.assertRaises(ValueError):
                    release.validate_package_digest(invalid)

    def test_previous_stable_ignores_dev_drafts_and_nonancestor(self):
        releases = [[dict(tag_name=tag, draft=draft, prerelease=pre, published_at=date)
                     for tag, draft, pre, date in (
                         ('v1.0', False, False, '2026-01-01'),
                         ('dev-pr1-abc', False, True, '2026-10-28'),
                         ('v1.1', True, False, '2026-10-27'),
                         ('v2.0', False, False, '2026-10-26'))]]
        import json
        with patch.object(release.subprocess, 'check_output', return_value=json.dumps(releases)), \
             patch.object(release, 'git', side_effect=lambda *args: {'v1.0^{commit}': 'a' * 40, 'v2.0^{commit}': 'b' * 40}[args[-1]]), \
             patch.object(release.subprocess, 'run', side_effect=lambda args: subprocess.CompletedProcess(args, 0 if args[-2] == 'a' * 40 else 1)):
            self.assertEqual(release.previous_stable('owner/repo', 'c' * 40), 'a' * 40)
            # A new version on the same commit has an empty range from that stable.
            self.assertEqual(release.previous_stable('owner/repo', 'a' * 40), 'a' * 40)


if __name__ == '__main__':
    unittest.main()
