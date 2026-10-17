#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the actual workflow guards before a job can reach the home runner."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def script(path, name):
    block = (ROOT / path).read_text().split(f"      - name: {name}\n", 1)[1]
    body = block.split("        run: |\n", 1)[1].split("\n      - ", 1)[0]
    return "\n".join(line[10:] for line in body.splitlines())


class RunnerGuard(unittest.TestCase):
    def test_home_guard_rejects_automatic_foreign_pr_release_and_malformed_sources(self):
        guard = script('.github/workflows/build.yml', 'Validate runner trust boundary')
        env = dict(os.environ, FELUCCA_CI_RUNNER='home', GITHUB_EVENT_NAME='workflow_dispatch',
                   GITHUB_ACTOR='owner', GITHUB_REPOSITORY_OWNER='owner', SOURCE_REF='a' * 40,
                   VERIFIED_PR='', VERSION='')
        self.assertEqual(subprocess.run(['bash', '-e', '-c', guard], env=env, capture_output=True).returncode, 0)
        for change in ({'GITHUB_EVENT_NAME': 'pull_request'}, {'GITHUB_EVENT_NAME': 'push'},
                       {'GITHUB_ACTOR': 'outsider'}, {'VERIFIED_PR': '12'}, {'VERSION': '1.6'},
                       {'SOURCE_REF': ''}, {'SOURCE_REF': 'A' * 40}, {'FELUCCA_CI_RUNNER': 'unknown'}):
            with self.subTest(change=change):
                self.assertNotEqual(subprocess.run(['bash', '-e', '-c', guard], env=env | change,
                                                   capture_output=True).returncode, 0)
        for event in ('pull_request', 'push', 'workflow_dispatch'):
            with self.subTest(event=event):
                self.assertEqual(subprocess.run(['bash', '-e', '-c', guard], env=env | {
                    'FELUCCA_CI_RUNNER': 'github', 'GITHUB_EVENT_NAME': event, 'SOURCE_REF': '',
                    'VERSION': '1.6'}, capture_output=True).returncode, 0)

    def test_benchmark_accepts_only_main_ancestors_without_pr_or_target_inputs(self):
        guard = script('.github/workflows/ci.yml', 'Verify requested source history')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()
            git('init', '-b', 'main')
            (root / 'file').write_text('trusted')
            git('add', 'file')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '--no-gpg-sign', '-m', 'trusted main')
            trusted = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/remotes/origin/main', trusted)
            git('checkout', '-b', 'untrusted')
            (root / 'file').write_text('not on main')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-am', 'untrusted', '--no-gpg-sign')
            foreign = git('rev-parse', 'HEAD')
            env = dict(os.environ, BENCHMARK_COMMIT=trusted, GITHUB_ACTOR='owner',
                       GITHUB_REPOSITORY_OWNER='owner', PR_NUMBER='', PR_COMMIT='',
                       VALIDATION='full', GITHUB_OUTPUT=str(root / 'output'))
            result = subprocess.run(['bash', '-e', '-c', guard], cwd=root, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'output').read_text(), f'sha={trusted}\n')
            for change in ({'BENCHMARK_COMMIT': foreign}, {'BENCHMARK_COMMIT': 'a' * 40},
                           {'BENCHMARK_COMMIT': 'main'}, {'GITHUB_ACTOR': 'outsider'},
                           {'PR_NUMBER': '12'}, {'PR_COMMIT': trusted}, {'VALIDATION': 'target'}):
                with self.subTest(change=change):
                    result = subprocess.run(['bash', '-e', '-c', guard], cwd=root,
                                            env=env | change, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
