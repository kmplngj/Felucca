#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Backup receipts reject stale, incomplete, fork and mismatched CI evidence."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ci_reuse as reuse


class ReuseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.root / '.gitignore').write_text('build/\n')
        for name in (reuse.WORKFLOW, '.github/workflows/build.yml', 'tools/ci_reuse.py',
                     'web/test_backup.mjs', 'web/fm1backup.js'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture\n')
        self.commit()
        self.event = self.base / 'event.json'
        self.event.write_text(json.dumps({'repository': {'full_name': 'owner/repo'}}))
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'push',
                    'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_PATH': str(self.event),
                    'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1',
                    'GITHUB_SHA': self.revision()}
        self.runtime = patch.object(reuse, 'runtime', side_effect=lambda env: {'node': 'pinned', 'profile': env.get('FELUCCA_PROFILE')})
        self.runtime.start()
        self.addCleanup(self.runtime.stop)
        self.log = self.root / 'build/backup-tests.log'
        self.log.parent.mkdir()
        self.log.write_text('Backup fixture completed successfully\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture', '--allow-empty')

    def revision(self):
        return self.git('rev-parse', 'HEAD')

    def snapshot(self):
        return reuse.snapshot(self.root, reuse.JOB, self.env)

    def receipt(self):
        before = self.snapshot()
        return before, reuse.record(self.root, before, self.log, self.env)

    def run_metadata(self, receipt):
        source = receipt['snapshot']['origin']
        return {'status': 'completed', 'conclusion': 'success', 'id': source['run_id'],
                'run_attempt': source['run_attempt'], 'head_sha': source['head_sha'],
                'event': source['event'], 'path': reuse.WORKFLOW,
                'repository': {'full_name': 'owner/repo'}, 'head_repository': {'full_name': 'owner/repo'}}

    def verify(self, expected, receipt, run=None):
        return reuse.verify(expected, receipt, run or self.run_metadata(receipt), self.log.parent)

    def test_identical_source_after_merge_reuses_only_backup_with_original_identity(self):
        previous, receipt = self.receipt()
        self.git('commit', '-qm', 'same tree different identity', '--allow-empty')
        self.env.update(GITHUB_SHA=self.revision(), GITHUB_RUN_ID='101')
        current = self.snapshot()
        self.assertNotEqual(previous['origin']['revision'], current['origin']['revision'])
        result = self.verify(current, receipt)
        self.assertTrue(result['reused'])
        self.assertEqual(result['revision'], previous['origin']['revision'])
        self.assertEqual(result['run_id'], 100)
        self.assertEqual(result['job'], 'backup-checks')

    def test_metadata_sensitive_jobs_are_never_reused(self):
        for job in ('host', 'host-0', 'host-1', 'browser', 'target', 'python-checks', 'unknown'):
            with self.subTest(job=job), self.assertRaisesRegex(ValueError, 'only standalone'):
                reuse.snapshot(self.root, job, self.env)

    def test_same_repo_pr_uses_api_head_and_retains_compiled_merge_revision(self):
        base = self.revision()
        self.git('checkout', '-qb', 'topic')
        (self.root / 'web/fm1backup.js').write_text('topic input\n')
        self.commit()
        head = self.revision()
        self.git('checkout', '-q', '--detach', base)
        self.git('merge', '--no-ff', '-qm', 'synthetic PR merge', head)
        merge = self.revision()
        self.event.write_text(json.dumps({'repository': {'full_name': 'owner/repo'},
            'pull_request': {'head': {'sha': head, 'repo': {'full_name': 'owner/repo'}},
                             'base': {'repo': {'full_name': 'owner/repo'}}}}))
        self.env.update(GITHUB_EVENT_NAME='pull_request', GITHUB_SHA=merge)
        _, receipt = self.receipt()
        self.assertEqual(receipt['snapshot']['origin']['head_sha'], head)
        self.assertEqual(receipt['snapshot']['origin']['revision'], merge)
        self.git('commit', '-qm', 'actual merged main identity', '--allow-empty')
        self.env.update(GITHUB_EVENT_NAME='push', GITHUB_SHA=self.revision(), GITHUB_RUN_ID='101')
        result = self.verify(self.snapshot(), receipt)
        self.assertEqual(result['revision'], merge)
        self.assertEqual(result['head_sha'], head)

    def test_any_changed_tracked_input_blocks_reuse(self):
        for path in ('asset.bin', 'LICENSE', '.github/workflows/ci.yml', 'tools/helper.py'):
            with self.subTest(path=path):
                _, receipt = self.receipt()
                item = self.root / path
                item.parent.mkdir(parents=True, exist_ok=True)
                item.write_text('changed\n')
                self.commit()
                self.env['GITHUB_SHA'] = self.revision()
                with self.assertRaisesRegex(ValueError, 'inputs do not match'):
                    self.verify(self.snapshot(), receipt)

    def test_modified_and_untracked_sources_refuse_snapshot(self):
        for path in ('web/fm1backup.js', 'extra.js'):
            original = self.root / path
            content = original.read_bytes() if original.exists() else None
            original.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'clean sources'):
                self.snapshot()
            if content is None:
                original.unlink()
            else:
                original.write_bytes(content)

    def test_record_requires_unchanged_inputs_run_and_nonempty_log(self):
        before = self.snapshot()
        self.env['FELUCCA_PROFILE'] = 'macro'
        with self.assertRaisesRegex(ValueError, 'changed after test start'):
            reuse.record(self.root, before, self.log, self.env)
        self.env.pop('FELUCCA_PROFILE')
        self.log.write_text('')
        with self.assertRaisesRegex(ValueError, 'empty backup'):
            reuse.record(self.root, before, self.log, self.env)

    def test_failure_cancellation_fork_other_workflow_and_mismatched_run_refuse_reuse(self):
        expected, receipt = self.receipt()
        mutations = [('status', 'in_progress'), ('conclusion', 'failure'),
                     ('conclusion', 'cancelled'), ('id', 99), ('run_attempt', 2),
                     ('head_sha', 'b' * 40), ('event', 'workflow_dispatch'),
                     ('path', '.github/workflows/other.yml'),
                     ('repository', {'full_name': 'different/repo'}),
                     ('head_repository', {'full_name': 'fork/repo'})]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                run = self.run_metadata(receipt)
                run[key] = value
                with self.assertRaisesRegex(ValueError, 'trusted same-repository'):
                    self.verify(expected, receipt, run)

    def test_altered_receipt_inputs_and_log_are_rejected(self):
        expected, receipt = self.receipt()
        altered = copy.deepcopy(receipt)
        altered['snapshot']['inputs']['runtime']['node'] = 'different'
        with self.assertRaisesRegex(ValueError, 'invalid backup input'):
            self.verify(expected, altered)
        self.log.write_text('altered successful looking log\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.verify(expected, receipt)

    def test_missing_log_and_path_traversal_are_rejected(self):
        expected, receipt = self.receipt()
        self.log.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or empty'):
            self.verify(expected, receipt)
        for name in ('../event.json', '/etc/passwd', '..', '.'):
            receipt['evidence']['name'] = name
            with self.assertRaisesRegex(ValueError, 'invalid evidence filename'):
                self.verify(expected, receipt)

    def test_release_manual_and_fork_origins_cannot_record_reusable_evidence(self):
        for key, value in [('VERSION', '1.6'), ('RELEASE_VALIDATION', 'true'),
                           ('GITHUB_REF_TYPE', 'tag'), ('GITHUB_EVENT_NAME', 'workflow_dispatch')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                reuse.snapshot(self.root, reuse.JOB, self.env | {key: value})
        self.event.write_text(json.dumps({'repository': {'full_name': 'owner/repo'},
            'pull_request': {'head': {'sha': self.revision(), 'repo': {'full_name': 'fork/repo'}},
                             'base': {'repo': {'full_name': 'owner/repo'}}}}))
        with self.assertRaisesRegex(ValueError, 'fork evidence'):
            reuse.snapshot(self.root, reuse.JOB, self.env | {'GITHUB_EVENT_NAME': 'pull_request'})

    def test_actual_submodule_bytes_and_pin_are_inputs(self):
        dependency = self.base / 'dependency'
        dependency.mkdir()
        subprocess.run(['git', 'init', '-q', str(dependency)], check=True)
        subprocess.run(['git', '-C', str(dependency), 'config', 'user.email', 'fixture@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(dependency), 'config', 'user.name', 'Fixture'], check=True)
        (dependency / 'engine.c').write_text('engine\n')
        subprocess.run(['git', '-C', str(dependency), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(dependency), 'commit', '-qm', 'engine'], check=True)
        self.git('-c', 'protocol.file.allow=always', 'submodule', 'add', str(dependency), 'engine')
        self.commit()
        self.env['GITHUB_SHA'] = self.revision()
        before = self.snapshot()
        self.assertTrue(any(row[0] == 'engine' and row[1] == '160000' for row in before['inputs']['sources']))
        (self.root / 'engine/engine.c').write_text('modified dependency\n')
        with self.assertRaisesRegex(ValueError, 'clean sources'):
            self.snapshot()

    def archive(self, receipt, members=None):
        output = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)  # Deliberately duplicate ZIP fixture.
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, content in (members or [('receipt.json', json.dumps(receipt)),
                                                   ('backup-tests.log', self.log.read_text())]):
                    archive.writestr(name, content)
        return output.getvalue()

    def restore_fixture(self):
        _, receipt = self.receipt()
        run = self.run_metadata(receipt)
        self.env['GITHUB_RUN_ID'] = '101'
        expected = self.snapshot()
        artifact = {'id': 33, 'name': f"backup-receipt-{expected['fingerprint']}",
                    'expired': False, 'size_in_bytes': 1000, 'workflow_run': {'id': 100}}
        return expected, receipt, run, artifact

    def mock_api(self, run, artifact, payload):
        def respond(endpoint, **kwargs):
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 3)
            prefix = 'repos/owner/repo/actions'
            if endpoint.startswith(f'{prefix}/artifacts?name=backup-receipt-'):
                self.assertTrue(endpoint.endswith('&per_page=3&page=1'))
                return json.dumps({'artifacts': [artifact]}).encode()
            if endpoint.startswith(f'{prefix}/runs/') and endpoint.rsplit('/', 1)[1].isdigit():
                return json.dumps(run).encode()
            if endpoint == f'{prefix}/artifacts/33/zip':
                return payload
            self.fail(f'unexpected API endpoint: {endpoint}')
        return patch.object(reuse, 'gh_api', side_effect=respond)

    def test_restore_downloads_exact_small_receipt_and_retains_origin(self):
        expected, receipt, run, artifact = self.restore_fixture()
        destination = self.root / 'build/restored'
        with self.mock_api(run, artifact, self.archive(receipt)) as api:
            result = reuse.restore(self.root, expected, destination, self.env)
        self.assertTrue(result['reused'])
        self.assertEqual(result['run_id'], 100)
        self.assertEqual(json.loads((destination / 'receipt.json').read_text()), receipt)
        self.assertEqual(json.loads((destination / 'run.json').read_text()), run)
        self.assertEqual(len(api.call_args_list), 3)
        self.assertEqual(api.call_args_list[-1].args[0], 'repos/owner/repo/actions/artifacts/33/zip')

    def test_restore_never_follows_artifact_urls_or_downloads_oversized_expired_artifact(self):
        expected, receipt, run, artifact = self.restore_fixture()
        for updates in ({'size_in_bytes': reuse.MAX_BYTES + 1}, {'expired': True},
                        {'name': 'other-artifact'}, {'id': 'https://untrusted.invalid/secret'}):
            with self.subTest(updates=updates), self.mock_api(run, artifact | updates, b'unused') as api:
                result = reuse.restore(self.root, expected, self.root / 'build/restored', self.env)
                self.assertFalse(result['reused'])
                self.assertEqual(len(api.call_args_list), 1)

    def test_restore_rejects_inherited_receipt_and_fork_metadata(self):
        expected, receipt, run, artifact = self.restore_fixture()
        receipt['snapshot']['origin']['run_id'] = 99
        with self.mock_api(run, artifact, self.archive(receipt)):
            self.assertFalse(reuse.restore(self.root, expected, self.root / 'build/restored', self.env)['reused'])
        fork = copy.deepcopy(run)
        fork['head_repository']['full_name'] = 'fork/repo'
        with self.mock_api(fork, artifact, b'unused') as api:
            self.assertFalse(reuse.restore(self.root, expected, self.root / 'build/restored', self.env)['reused'])
            self.assertEqual(len(api.call_args_list), 2)

    def test_restore_inspects_at_most_three_artifacts_without_pagination(self):
        expected, receipt, run, artifact = self.restore_fixture()
        foreign = artifact | {'name': 'unrelated-artifact'}
        # A valid candidate at position four must not cause another request.
        payload = json.dumps({'artifacts': [foreign] * 3 + [artifact]}).encode()
        with patch.object(reuse, 'gh_api', return_value=payload) as api:
            result = reuse.restore(self.root, expected, self.root / 'build/restored', self.env)
        self.assertFalse(result['reused'])
        self.assertEqual(len(api.call_args_list), 1)
        self.assertEqual(api.call_args.args[0],
                         f"repos/owner/repo/actions/artifacts?name=backup-receipt-{expected['fingerprint']}&per_page=3&page=1")

    def test_restore_artifact_must_bind_numeric_prior_origin_run(self):
        expected, receipt, run, artifact = self.restore_fixture()
        for origin in ({'id': 101}, {'id': '100'}, {'id': 0}, {'id': 99}):
            with self.subTest(origin=origin), self.mock_api(run, artifact | {'workflow_run': origin}, self.archive(receipt)) as api:
                self.assertFalse(reuse.restore(self.root, expected, self.root / 'build/restored', self.env)['reused'])
                # Invalid/prior mismatches never reach a ZIP endpoint.
                self.assertFalse(any(call.args[0].endswith('/zip') for call in api.call_args_list))

    def test_restore_empty_exact_fingerprint_result_and_expired_lookup_budget_stop_early(self):
        expected, receipt, run, artifact = self.restore_fixture()
        with patch.object(reuse, 'gh_api', return_value=b'{"artifacts": []}') as api:
            self.assertFalse(reuse.restore(self.root, expected, self.root / 'build/restored', self.env)['reused'])
            self.assertEqual(api.call_count, 1)
        with self.mock_api(run, artifact, self.archive(receipt)) as api, \
                patch.object(reuse.time, 'monotonic', side_effect=[0, 0, 11]):
            self.assertFalse(reuse.restore(self.root, expected, self.root / 'build/restored', self.env)['reused'])
            self.assertEqual(api.call_count, 1)

    def test_restore_rejects_changed_current_inputs_and_unsafe_directory_before_network(self):
        expected, _, _, _ = self.restore_fixture()
        with patch.object(reuse, 'gh_api') as api:
            with self.assertRaisesRegex(ValueError, 'ignored build'):
                reuse.restore(self.root, expected, self.base / 'outside', self.env)
            (self.root / 'web/fm1backup.js').write_text('modified')
            with self.assertRaisesRegex(ValueError, 'clean sources'):
                reuse.restore(self.root, expected, self.root / 'build/restored', self.env)
            api.assert_not_called()

    def test_zip_refuses_traversal_symlinks_extra_duplicate_and_expanded_size(self):
        _, receipt = self.receipt()
        destination = self.root / 'build/unpack'
        destination.mkdir()
        symlink = zipfile.ZipInfo('backup-tests.log')
        symlink.create_system = 3
        symlink.external_attr = (0o120777 << 16)
        samples = [
            [('receipt.json', '{}'), ('../outside', 'bad')],
            [('receipt.json', '{}'), ('/outside', 'bad')],
            [('receipt.json', '{}'), (symlink, 'bad')],
            [('receipt.json', '{}'), ('backup-tests.log', 'ok'), ('extra.txt', 'bad')],
            [('receipt.json', '{}'), ('receipt.json', '{}')],
            [('receipt.json', '{}'), ('backup-tests.log', 'x' * reuse.MAX_BYTES)],
        ]
        for members in samples:
            with self.subTest(names=[getattr(name, 'filename', name) for name, _ in members]):
                with self.assertRaises(ValueError):
                    reuse.unpack_receipt(self.archive(receipt, members), destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_restore_candidate_malformed_archive_and_mismatched_fingerprint_fall_back(self):
        expected, receipt, run, artifact = self.restore_fixture()
        wrong = copy.deepcopy(receipt)
        wrong['snapshot']['inputs']['runtime']['node'] = 'unmatched'
        for payload in (b'invalid zip', self.archive(wrong), b'x' * (reuse.MAX_BYTES + 1)):
            with self.subTest(size=len(payload)), self.mock_api(run, artifact, payload):
                self.assertFalse(reuse.restore(self.root, expected, self.root / 'build/restored', self.env)['reused'])
                self.assertEqual(list((self.root / 'build/restored').iterdir()), [])


class RuntimeTest(unittest.TestCase):
    def test_node_preload_and_loader_overrides_are_not_reusable(self):
        for name in ('NODE_OPTIONS', 'NODE_PATH', 'NODE_ICU_DATA', 'LD_PRELOAD', 'DYLD_LIBRARY_PATH'):
            with self.subTest(name=name), patch.object(reuse.shutil, 'which', return_value='/fake/node'):
                with self.assertRaisesRegex(ValueError, 'not permitted'):
                    reuse.runtime({name: 'external-input'})

    def test_cli_malformed_receipt_fails_closed_with_fresh_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / 'missing.json')
            errors = io.StringIO()
            with patch.object(sys, 'argv', ['ci_reuse.py', 'verify', '--snapshot', missing]), contextlib.redirect_stderr(errors):
                self.assertEqual(reuse.main(), 1)
            self.assertIn('run selected checks fresh', errors.getvalue())

    def test_restore_cli_api_auth_errors_are_sanitized_and_emit_fresh_output(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'expected.json'
            snapshot.write_text('{}')
            output = Path(directory) / 'output'
            stdout = io.StringIO()
            argv = ['ci_reuse.py', 'restore', '--snapshot', str(snapshot), '--directory', directory]
            error = subprocess.CalledProcessError(1, ['gh'], stderr='RAW_SECRET_TOKEN')
            with patch.object(reuse, 'restore', side_effect=error), patch.object(sys, 'argv', argv), \
                    patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}), contextlib.redirect_stdout(stdout):
                self.assertEqual(reuse.main(), 0)
            self.assertEqual(output.read_text(), 'reused=false\n')
            self.assertIn('run fresh', stdout.getvalue())
            self.assertNotIn('RAW_SECRET_TOKEN', stdout.getvalue())

    def test_gh_api_fixes_hostname_suppresses_stderr_and_enforces_byte_limit(self):
        def start(command, **kwargs):
            self.assertEqual(command[:6], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET'])
            self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
            kwargs['stdout'].write(b'x' * (reuse.MAX_BYTES + 1))
            kwargs['stdout'].flush()
            process = Mock()
            process.poll.return_value = 0
            process.returncode = 0
            return process
        with patch.object(reuse.subprocess, 'Popen', side_effect=start):
            with self.assertRaisesRegex(ValueError, 'oversized'):
                reuse.gh_api('repos/owner/repo/actions/artifacts/33/zip')


if __name__ == '__main__':
    unittest.main()
