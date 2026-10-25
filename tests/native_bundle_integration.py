#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build and seal a real native bundle from isolated Git and Git-free sources."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_manifest as M
import source_archive as S


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


class NativeBundle(unittest.TestCase):
    def test_real_key_metadata_and_git_free_reproduction(self):
        output = ROOT / 'build/ci/native-bundle'
        output.mkdir(parents=True, exist_ok=True)
        evidence = Path(tempfile.mkdtemp(prefix='run-', dir=output))
        report_path = ROOT / 'build/resource-report.json'
        original_bytes = report_path.read_bytes()
        original = json.loads(original_bytes)
        original_profile = json.loads((ROOT / 'build/gen/resolved-profile.json').read_text())
        (evidence / 'original-ci-report.json').write_bytes(original_bytes)
        context = {k: os.environ.get(k) for k in ('GITHUB_ACTIONS', 'GITHUB_EVENT_NAME',
                   'GITHUB_REPOSITORY', 'GITHUB_REF', 'GITHUB_SHA', 'FELUCCA_VERIFIED_PR', 'FELUCCA_VERIFIED_COMMIT')}
        (evidence / 'original-ci-context.json').write_text(json.dumps(context, indent=2) + '\n')
        revision = git(ROOT, 'rev-parse', 'HEAD')
        self.assertEqual(original['build_identity']['revision'], revision, 'stale native report revision')
        self.assertFalse(git(ROOT, 'status', '--porcelain', '--untracked-files=all'), 'dirty source checkout')
        self.assertFalse(original['build_identity']['dirty'], 'dirty native producer')
        self.assertEqual(original['build_identity']['repository'], 'kmplngj/Felucca')
        protected = set(original['artifact_sha256']) | {'build/resource-report.json'}

        def snapshot():
            return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(protected)}

        before = snapshot()
        expected_context = dict(context)
        commands = []

        def run(argv, cwd, name):
            row = dict(argv=list(map(str, argv)), cwd=str(cwd), started=time.time(), exit_code=None, log=name + '.log')
            try:
                with (evidence / row['log']).open('wb') as log:
                    result = subprocess.run(row['argv'], cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
                row['exit_code'] = result.returncode
                self.assertEqual(result.returncode, 0, name + ': see ' + str(evidence / row['log']))
            finally:
                row['ended'] = time.time()
                commands.append(row)
                (evidence / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')

        try:
            run([sys.executable, 'tools/build_report.py', '--verify', 'build/resource-report.json'], ROOT, 'original-report')
            # PR parentage requires Git. This controlled pair keeps commit identity, without a PR label.
            os.environ['GITHUB_ACTIONS'] = 'false'
            expected_context['GITHUB_ACTIONS'] = 'false'
            os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
            work = Path(tempfile.mkdtemp(prefix='native-bundle-', dir=ROOT / 'build'))
            self.addCleanup(shutil.rmtree, work)
            control, engine = work / 'control', work / 'control/firmware/engines'
            run(['git', 'clone', '--no-local', '--no-checkout', ROOT, control], ROOT, 'clone')
            run(['git', 'checkout', '--detach', revision], control, 'checkout')
            run(['git', 'remote', 'set-url', 'origin', git(ROOT, 'remote', 'get-url', 'origin')], control, 'origin')
            run(['git', 'submodule', 'init', '--', 'firmware/engines'], control, 'engine-registration')
            run(['git', 'clone', '--no-local', ROOT / 'firmware/engines', engine], ROOT, 'engines')
            pin = git(ROOT, 'rev-parse', revision + ':firmware/engines')
            run(['git', 'checkout', '--detach', pin], engine, 'engine-pin')
            run(['git', 'remote', 'set-url', 'origin', git(ROOT / 'firmware/engines', 'remote', 'get-url', 'origin')], engine, 'engine-origin')
            self.assertIn('firmware/engines/src/felucca_engine.h',
                          git(control, 'ls-files', '--recurse-submodules').splitlines())
            cfg = original['configuration']
            args = ['--release', cfg['version_override'][1:]] if cfg['version_override'] else []
            args += ['--product', cfg['product']]
            run(['sh', 'build.sh', *args], control, 'control-build')
            control_report = json.loads((control / 'build/resource-report.json').read_text())
            (evidence / 'control-report.json').write_bytes((control / 'build/resource-report.json').read_bytes())
            label = control_report['build_identity']['version'].removeprefix('v')
            archive = work / ('felucca-' + label + '-source.tar.gz')
            S.export(control, archive, label)
            S.verify_archive(archive)
            with tarfile.open(archive, 'r:gz') as source:
                source.extractall(work / 'extracted', filter='data')
            reproduced = work / 'extracted' / ('felucca-' + label + '-source')
            self.assertFalse((reproduced / '.git').exists())
            S.verify_tree(reproduced)
            run(['sh', 'build.sh', *args], reproduced, 'git-free-build')
            (evidence / 'git-free-report.json').write_bytes((reproduced / 'build/resource-report.json').read_bytes())
            resolved = json.loads((control / 'build/gen/resolved-profile.json').read_text())
            self.assertEqual(resolved['engine_ids'], original_profile['engine_ids'])
            self.assertEqual(json.loads((reproduced / 'build/gen/resolved-profile.json').read_text())['engine_ids'],
                             original_profile['engine_ids'])
            for root in (control, reproduced):
                self.assertNotIn(b'felucca.engine.', (root / 'build/felucca.bin').read_bytes())
            manifest = M.create(control, archive, reproduced, evidence / 'bundle', allowed_revision=revision,
                                profile_name=resolved['profile'], runtime_unavailable='not_requested')
            self.assertEqual(M.verify(evidence / 'bundle'), manifest)
            authority = json.loads((control / 'profiles/engine-identities.json').read_text())
            catalog = json.loads((control / 'profiles/catalog.json').read_text())
            slots = {s['id']: s for s in authority['slots']}
            self.assertEqual(set(slots), set(range(64)))
            self.assertEqual(len(authority['slots']), 64)
            self.assertEqual(slots[1], dict(id=1, key='felucca.engine.digital', status='retired'))
            self.assertEqual(slots[14], dict(id=14, key='felucca.engine.macro', status='active'))
            self.assertTrue(all(slots[i] == dict(id=i, key=None, status='reserved') for i in range(15, 64)))
            self.assertEqual({e['id']: e['key'] for e in catalog['engines']},
                             {i: s['key'] for i, s in slots.items() if s['status'] != 'reserved'})
            selected = [dict(id=e['id'], key=e['key'], status=slots[e['id']]['status'], owner=e['owner'], source=e['source'])
                        for e in sorted(catalog['engines'], key=lambda e: e['id']) if e['id'] in resolved['engine_ids']]
            expected = dict(state='available', reference=dict(path='profiles/engine-identities.json',
                            sha256=hashlib.sha256((control / 'profiles/engine-identities.json').read_bytes()).hexdigest()), selected=selected)
            self.assertEqual(manifest['identity']['profile']['engine_key_metadata'], expected)
            self.assertEqual(expected['reference']['sha256'], original['input_sha256']['profiles/engine-identities.json'])
            result = dict(status='passed', revision=revision, engine=pin, key_metadata=expected,
                          engine_ids=resolved['engine_ids'], linked_keys=False,
                          configuration_key=manifest['configuration_key'], original_sha256=before)
        finally:
            self.assertEqual(snapshot(), before, 'original CI native/report outputs changed')
            self.assertEqual(git(ROOT, 'rev-parse', 'HEAD'), revision, 'source revision changed during integration check')
            self.assertFalse(git(ROOT, 'status', '--porcelain', '--untracked-files=all'), 'source checkout changed')
            self.assertEqual({k: os.environ.get(k) for k in context}, expected_context, 'CI context changed')
        (evidence / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
