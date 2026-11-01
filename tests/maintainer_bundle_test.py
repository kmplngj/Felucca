#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real isolated Git/archive fixtures; compiler/seal processes are simulated.

These exercise orchestration and refusal, not real compiler/runtime acceptance.
The existing manifest/source/report/runtime suites own payload correspondence.
"""
import copy
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import maintainer_bundle as B
import source_archive
import source_archive_test


class MaintainerBundles(unittest.TestCase):
    def setUp(self):
        self.fixture = source_archive_test.Archives()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.repo.resolve()
        self.fixture.git(self.root, 'remote', 'add', 'origin', 'https://github.com/kmplngj/Felucca.git')
        self.fixture.write(self.root, 'firmware/src/felucca.c', '#define FELUCCA_VERSION "v1.6.1"\n')
        for name in ('catalog.json', 'engine-identities.json', 'standard.json', 'reduced-lofi.json', 'macro.json', 'adpcm.json'):
            shutil.copyfile(ROOT / 'profiles' / name, self.root / 'profiles' / name)
        self.fixture.commit(self.root)
        self.revision = B.git(self.root, 'rev-parse', 'HEAD')
        self.output = self.root / 'build/run'
        self.env = dict(os.environ, GITHUB_ACTIONS='false', GH_TOKEN='secret-gh',
                        GITHUB_TOKEN='secret-github', ACTIONS_RUNTIME_TOKEN='secret-actions',
                        HTTPS_PROXY='http://proxy.invalid', SSL_CERT_FILE='/trusted/ca.pem',
                        JIELI_TOOLCHAIN='/target/tools', AC79_SDK='/target/sdk',
                        NODE_OPTIONS='', NODE_PATH='', EMU_CFLAGS='', EMU_OPT='', EMU_PREVIEW='',
                        FELUCCA_CPU2='0', FELUCCA_CHIP_PROBES='1')
        self.manifest = {'configuration_key': 'b' * 64,
                         'identity': {'source': {'repository': B.REPOSITORY, 'revision': self.revision},
                                      'profile': {'name': 'standard'}, 'runtime': {'requested': True}},
                         'runtime': {'state': 'available'}}
        self.calls = []

    def request(self, **overrides):
        args = dict(root=self.root, revision=self.revision, selected='standard', mode='local',
                    output=self.output, environment=self.env)
        args.update(overrides)
        return B.plan(**args)

    def fake_process(self, name, argv, cwd, environment, log):
        self.calls.append((name, argv, cwd, environment.copy()))
        # Local Git clone/pinning and complete-source verification are real.
        if argv[0] == 'git':
            B.run_command(name, argv, cwd, environment, log)
        else:
            log.write_text('simulated compiler/seal process: ' + name + '\n')
        if name == 'source-export':
            source_archive.export(cwd, Path(argv[-1]), argv[-3])
        elif name == 'seal':
            candidate = Path(argv[-1]); candidate.mkdir()
            (candidate / 'manifest.json').write_text(json.dumps(self.manifest))

    def execute(self, runner=None):
        # The offline verifier is the explicit seam; its real contract has its
        # own causal fixtures in build_manifest_test.py, run alongside this file.
        with patch.object(B.build_manifest, 'verify', return_value=self.manifest) as verifier:
            result = B.execute(self.request(), self.env, runner or self.fake_process)
        verifier.assert_called_once_with(self.output / 'candidate-bundle')
        return result

    def test_canonical_profiles_and_exact_current_revision(self):
        self.assertEqual(B.PROFILES, B.profile.SUPPORTED_PROFILES)
        for selected in B.PROFILES:
            self.assertEqual(self.request(selected=selected)['profile'], selected)
        for revision in ('main', 'HEAD', self.revision[:12], self.revision.upper(), 'a' * 40,
                         self.revision + '; touch /tmp/unsafe'):
            with self.assertRaises(ValueError): self.request(revision=revision)
        with self.assertRaises(ValueError): self.request(selected='custom')
        self.assertFalse(self.output.exists())

    def test_workflow_admission_does_not_accept_pr_fork_or_ref_input(self):
        env = dict(self.env, GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='workflow_dispatch',
                   GITHUB_REPOSITORY=B.REPOSITORY, GITHUB_REF='refs/heads/main',
                   GITHUB_SHA=self.revision, GITHUB_WORKFLOW_SHA=self.revision)
        self.assertEqual(self.request(mode='workflow', environment=env)['admission']['mode'], 'workflow')
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_EVENT_NAME', 'pull_request_target'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REPOSITORY', 'someone/Felucca'),
                           ('GITHUB_REF', 'refs/heads/topic'), ('GITHUB_SHA', 'a' * 40),
                           ('GITHUB_WORKFLOW_SHA', 'a' * 40)]:
            with self.assertRaisesRegex(ValueError, 'exact main dispatch'):
                self.request(mode='workflow', environment=dict(env, **{key: value}))
        with self.assertRaisesRegex(ValueError, 'local mode'):
            self.request(environment=env)

    def test_dirty_source_wrong_engine_and_missing_engine_fail_before_work(self):
        source = self.root / 'firmware/src/felucca.c'
        old = source.read_bytes(); source.write_bytes(old + b'changed')
        with self.assertRaisesRegex(ValueError, 'dirty'): self.request()
        source.write_bytes(old)
        engine = self.root / 'firmware/engines'
        (engine / 'extra').write_text('untracked')
        with self.assertRaisesRegex(ValueError, 'dirty'): self.request()
        (engine / 'extra').unlink()
        self.fixture.git(engine, '-c', 'user.name=Source fixture',
                         '-c', 'user.email=fixture@example.invalid',
                         'commit', '--allow-empty', '-qm', 'different pin')
        with self.assertRaises(ValueError): self.request()

    def test_new_output_and_no_output_alias(self):
        with self.assertRaisesRegex(ValueError, 'below'): self.request(output=self.root.parent / 'outside')
        self.output.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'already exists'): self.request()
        self.output.rmdir()
        self.output.symlink_to(self.root.parent / 'elsewhere', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'): self.request()

    def test_hooks_refused_and_transport_trust_selectors_preserved(self):
        for name in B.HOOKS:
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                self.request(environment=dict(self.env, **{name: 'unreviewed'}))
        result = B.build_environment(self.env, 'macro')
        for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'FELUCCA_CPU2', 'FELUCCA_CHIP_PROBES'):
            self.assertNotIn(name, result)
        for name in ('HTTPS_PROXY', 'SSL_CERT_FILE', 'JIELI_TOOLCHAIN', 'AC79_SDK'):
            self.assertEqual(result[name], self.env[name])
        self.assertEqual(result['FELUCCA_PROFILE'], 'macro')
        self.assertEqual(result['GITHUB_ACTIONS'], 'false')

    def test_archive_cli_refuses_before_importing_unverified_cached_helper(self):
        archive = self.fixture.base / 'unverified-archive'
        tools = archive / 'tools'; tools.mkdir(parents=True)
        (archive / 'SOURCE-PINS.json').write_text('{}')
        entry = tools / 'maintainer_bundle.py'
        source = Path(B.__file__).read_text(); entry.write_text(source)
        marker = self.fixture.base / 'unverified-helper-executed'
        helper = tools / 'build_manifest.py'
        helper.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("executed")\n')
        # A sourceless cached module can execute without an untracked .py file.
        py_compile.compile(str(helper), cfile=str(tools / 'build_manifest.pyc'), doraise=True)
        helper.unlink()
        env = dict(self.env, PYTHONPATH=str(ROOT / 'tools'))
        def cli():
            return subprocess.run([sys.executable, str(entry), '--help'], cwd=archive, env=env,
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        refused = cli()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('requires a clean committed Git checkout', refused.stderr)
        self.assertFalse(marker.exists())
        # Causal control: bypass only the startup refusal. The same cached helper
        # now executes before argument processing, proving the fixture sees it.
        start = source.index('import os as _source_os')
        end = source.index('\nimport argparse', start)
        entry.write_text(source[:start] + source[end:])
        cli()
        self.assertTrue(marker.exists())

    def test_complete_sequence_and_promotion_only_after_offline_verification(self):
        result = self.execute()
        self.assertEqual(result['status'], 'verified')
        names = [row[0] for row in self.calls]
        self.assertEqual(names[-6:], ['native-build', 'source-export', 'git-free-build',
                                     'runtime-prepare', 'paired-runtime', 'seal'])
        self.assertTrue((self.output / 'verified-bundle/manifest.json').is_file())
        self.assertFalse((self.output / 'candidate-bundle').exists())
        self.assertFalse((self.output / 'extracted/felucca-1.6.1-bundle-source/.git').exists())
        source_archive.verify_tree(self.output / 'extracted/felucca-1.6.1-bundle-source')
        for _, argv, _, environment in self.calls:
            self.assertIsInstance(argv, list)
            self.assertNotIn('GH_TOKEN', environment)
            self.assertNotIn('GITHUB_TOKEN', environment)
            self.assertNotIn('ACTIONS_RUNTIME_TOKEN', environment)
        self.assertEqual(result['admission']['mode'], 'local')
        self.assertIn('no review', result['admission']['scope'])

    def test_each_required_stage_failure_leaves_no_uploadable_bundle(self):
        for failed in ('native-build', 'source-export', 'git-free-build', 'runtime-prepare', 'paired-runtime', 'seal'):
            with self.subTest(failed=failed):
                self.output = self.root / 'build' / failed
                self.calls = []
                def run(name, argv, cwd, environment, log):
                    if name == failed:
                        log.write_text('simulated failure\n')
                        raise ValueError('causal ' + name)
                    self.fake_process(name, argv, cwd, environment, log)
                with self.assertRaisesRegex(ValueError, 'causal ' + failed): self.execute(run)
                self.assertFalse((self.output / 'verified-bundle').exists())
                saved = json.loads((self.output / 'RESULT.json').read_text())
                self.assertEqual(saved['status'], 'failed')
                self.assertEqual(saved['commands'][-1]['state'], 'failed')

    def test_unavailable_wrong_source_or_wrong_profile_never_promotes(self):
        for kind in ('unavailable', 'wrong-source', 'wrong-profile'):
            with self.subTest(kind=kind):
                self.output = self.root / 'build' / kind
                original = copy.deepcopy(self.manifest)
                if kind == 'unavailable': self.manifest['runtime']['state'] = 'unavailable'
                elif kind == 'wrong-source': self.manifest['identity']['source']['revision'] = 'a' * 40
                else: self.manifest['identity']['profile']['name'] = 'macro'
                with self.assertRaises(ValueError): self.execute()
                self.assertFalse((self.output / 'verified-bundle').exists())
                self.manifest = original

    def test_offline_verifier_failure_cannot_be_replaced_by_successful_commands(self):
        with patch.object(B.build_manifest, 'verify', side_effect=ValueError('corrupt manifest')):
            with self.assertRaisesRegex(ValueError, 'corrupt manifest'):
                B.execute(self.request(), self.env, self.fake_process)
        self.assertFalse((self.output / 'verified-bundle').exists())

    def test_interruption_and_source_mutation_leave_no_verified_destination(self):
        def interrupted(name, argv, cwd, environment, log):
            if name == 'paired-runtime': raise KeyboardInterrupt()
            self.fake_process(name, argv, cwd, environment, log)
        with self.assertRaises(KeyboardInterrupt): self.execute(interrupted)
        self.assertFalse((self.output / 'verified-bundle').exists())
        self.output = self.root / 'build/mutated'
        def mutated(name, argv, cwd, environment, log):
            self.fake_process(name, argv, cwd, environment, log)
            if name == 'seal': (self.root / 'firmware/src/felucca.c').write_text('changed during build')
        with self.assertRaisesRegex(ValueError, 'dirty'): self.execute(mutated)
        self.assertFalse((self.output / 'verified-bundle').exists())

    def test_workflow_has_manual_trusted_recipe_and_success_only_payload_upload(self):
        text = (ROOT / '.github/workflows/maintainer-bundle.yml').read_text()
        self.assertIn('on:\n  workflow_dispatch:', text)
        self.assertNotIn('pull_request:', text)
        self.assertNotIn('pull_request_target:', text)
        self.assertIn('permissions:\n  contents: read', text)
        self.assertNotRegex(text, r'permissions:[\s\S]*?\bwrite\b')
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertNotIn('ref: ${{ inputs.', text)
        self.assertIn('persist-credentials: false', text)
        actions = re.findall(r'uses: ([^\s]+)', text)
        self.assertTrue(actions and all(re.fullmatch(r'[\w/-]+@[0-9a-f]{40}', a) for a in actions))
        payload = text.split('- name: Retain only the verified bundle', 1)[1].split('- name:', 1)[0]
        self.assertNotIn('always()', payload)
        self.assertIn('path: build/maintainer-bundle/verified-bundle/', payload)
        self.assertNotIn('path: build/maintainer-bundle/\n', text)
        for line in text.splitlines():
            if '${{ inputs.' in line:
                self.assertFalse(line.lstrip().startswith(('run:', 'python', 'sh ', 'git ')))


if __name__ == '__main__':
    unittest.main()
