#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build identity sources, CI trust boundary, bounds and stale-output regression."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_identity as identity


class IdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run_git('init', '-q')
        self.run_git('config', 'user.email', 'test@example.com')
        self.run_git('config', 'user.name', 'Test')
        (self.root / 'firmware/src').mkdir(parents=True)
        (self.root / 'firmware/src/felucca.c').write_text('#define FELUCCA_VERSION "v1.6.1"\n')
        (self.root / '.gitignore').write_text('build/\n')
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'first')
        self.sha = self.run_git('rev-parse', 'HEAD')

    def run_git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def test_clean_dirty_release_and_second_revision(self):
        first = identity.resolve(self.root, env={})
        self.assertEqual(first['build'], self.sha[:8])
        self.assertIsNone(first['pr'])
        self.assertEqual(identity.resolve(self.root, 'v2.0', {})['version'], 'v2.0')
        p = self.root / 'untracked.c'
        p.write_text('changed')
        self.assertEqual(identity.resolve(self.root, env={})['build'], self.sha[:8] + '-dirty')
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'second')
        second = identity.resolve(self.root, env={})
        self.assertEqual(second['version'], first['version'])
        self.assertNotEqual(second['build'], first['build'])

    def test_archive_and_unknown(self):
        import shutil
        shutil.rmtree(self.root / '.git')
        self.assertEqual(identity.resolve(self.root, env={})['build'], 'unknown')
        (self.root / 'SOURCE-PINS.json').write_text('{}')
        with patch('source_archive.verify_tree', return_value={'firmware_revision': self.sha}) as verify:
            got = identity.resolve(self.root, env={})
            verify.assert_called_once_with(self.root)
            self.assertEqual(got['build'], self.sha[:8])
            self.assertEqual(got['source'], 'verified archive')
        with patch('source_archive.verify_tree', side_effect=ValueError('tampered')):
            with self.assertRaisesRegex(ValueError, 'tampered'):
                identity.resolve(self.root, env={})

    def event_env(self, event, kind):
        path = self.root / 'build/event.json'
        path.parent.mkdir(exist_ok=True)
        event['repository'] = {'full_name': 'test/repo'}
        path.write_text(json.dumps(event))
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': kind,
                'GITHUB_EVENT_PATH': str(path), 'GITHUB_REPOSITORY': 'test/repo'}

    def test_exact_pr(self):
        env = self.event_env({'inputs': {'pr': '1234567', 'commit': self.sha}}, 'workflow_dispatch')
        with self.assertRaisesRegex(ValueError, 'verified'):
            identity.resolve(self.root, env=env)
        env.update(FELUCCA_VERIFIED_PR='1234567', FELUCCA_VERIFIED_COMMIT=self.sha)
        got = identity.resolve(self.root, env=env)
        self.assertEqual(got['pr_label'], 'PR #1234567 head')
        self.assertEqual(got['revision'], self.sha)
        for pr in ['0', '-1', '12345678', '1"', '1\n']:
            bad = self.event_env({'inputs': {'pr': pr, 'commit': self.sha}}, 'workflow_dispatch')
            bad.update(FELUCCA_VERIFIED_PR=pr, FELUCCA_VERIFIED_COMMIT=self.sha)
            with self.assertRaises(ValueError):
                identity.resolve(self.root, env=bad)
        self.event_env({'inputs': {'pr': '1234567', 'commit': self.sha}}, 'workflow_dispatch')
        (self.root / 'changed.c').write_text('dirty')
        with self.assertRaisesRegex(ValueError, 'modified'):
            identity.resolve(self.root, env=env)

    def test_merge_pr_compiles_merge_revision(self):
        self.run_git('checkout', '-qb', 'head')
        (self.root / 'head.c').write_text('head')
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'PR head')
        head = self.run_git('rev-parse', 'HEAD')
        self.run_git('checkout', '-q', '-')
        self.run_git('merge', '--no-ff', '-qm', 'test merge', 'head')
        merge = self.run_git('rev-parse', 'HEAD')
        env = self.event_env({'number': 123, 'pull_request': {'head': {'sha': head}}}, 'pull_request')
        env.update(GITHUB_SHA=merge, GITHUB_REF='refs/pull/123/merge')
        got = identity.resolve(self.root, env=env)
        self.assertEqual(got['revision'], merge)
        self.assertEqual(got['pr_head'], head)
        self.assertEqual(got['pr_label'], 'PR #123 merge')
        shallow = self.root / 'build/shallow'
        subprocess.run(['git', 'clone', '-q', '--depth', '1', self.root.as_uri(), str(shallow)], check=True)
        # Focused emulator CI uses a depth-1 checkout. Git's %P is empty there,
        # but the compiled merge object still carries its authenticated parents.
        self.assertEqual(identity.resolve(shallow, env=env)['revision'], merge)
        self.assertEqual(identity.resolve(shallow, env=env)['pr_label'], 'PR #123 merge')
        env['GITHUB_SHA'] = head
        with self.assertRaisesRegex(ValueError, 'checkout'):
            identity.resolve(self.root, env=env)

    def test_no_branch_inference_and_stale_rebuild(self):
        self.run_git('checkout', '-qb', 'PR-123')
        with patch.dict(os.environ, {}, clear=True):
            directory = self.root / 'build/gen'
            identity.write(self.root, directory)
            identity.check(self.root, directory)
            (self.root / 'changed.c').write_text('dirty')
            with self.assertRaisesRegex(ValueError, 'stale'):
                identity.check(self.root, directory)
            identity.write(self.root, directory)
            identity.check(self.root, directory)
            self.assertEqual(json.loads((directory / 'build-identity.json').read_text())['pr_label'], '')
            self.assertIn('-dirty', (directory / 'build_identity.h').read_text())

    def test_archive_pr_context(self):
        import shutil
        env = self.event_env({'inputs': {'pr': '123', 'commit': self.sha}}, 'workflow_dispatch')
        env.update(FELUCCA_VERIFIED_PR='123', FELUCCA_VERIFIED_COMMIT=self.sha)
        shutil.rmtree(self.root / '.git')
        (self.root / 'SOURCE-PINS.json').write_text('{}')
        with patch('source_archive.verify_tree', return_value={'firmware_revision': self.sha}):
            self.assertEqual(identity.resolve(self.root, env=env)['pr_label'], 'PR #123 head')
            env = self.event_env({'number': 123, 'pull_request': {'head': {'sha': self.sha}}}, 'pull_request')
            with self.assertRaisesRegex(ValueError, 'parentage'):
                identity.resolve(self.root, env=env)

    def test_version_freshness_and_explicit_override(self):
        import shutil
        with patch.dict(os.environ, {}, clear=True):
            directory = self.root / 'build/gen'
            source = self.root / 'firmware/src/felucca.c'
            # Already dirty: a second source edit must not hide behind -dirty.
            (self.root / 'changed.c').write_text('dirty')
            for no_git in (False, True):
                if no_git:
                    shutil.rmtree(self.root / '.git')
                source.write_text('#define FELUCCA_VERSION "v1.6.1"\n')
                identity.write(self.root, directory)
                identity.check(self.root, directory)
                source.write_text('#define FELUCCA_VERSION "v1.6.2"\n')
                with self.assertRaisesRegex(ValueError, 'stale'):
                    identity.check(self.root, directory)
                identity.write(self.root, directory)
                identity.check(self.root, directory)
                # An explicit release remains authoritative over source defaults.
                identity.write(self.root, directory, 'v2.0-rc1')
                source.write_text('#define FELUCCA_VERSION "v1.6.3"\n')
                identity.check(self.root, directory)
                self.assertEqual(json.loads((directory / 'build-identity.json').read_text())['version'],
                                 'v2.0-rc1')

    def test_bounds_and_injection(self):
        for version in ['', 'v' + 'a' * 31, 'v1"', 'v1\n', 'v日本']:
            with self.assertRaises(ValueError):
                identity.resolve(self.root, version, {})
        self.assertEqual(identity.outputs(identity.resolve(self.root, env={})),
                         identity.outputs(identity.resolve(self.root, env={})))


if __name__ == '__main__':
    unittest.main()
