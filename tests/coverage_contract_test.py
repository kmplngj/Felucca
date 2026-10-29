#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Causal contract fixtures plus real compiler/producer subprocess boundaries."""
import copy
import contextlib
import hashlib
import json
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_coverage as C


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.logs = self.root / 'logs'
        self.logs.mkdir()
        (self.root / 'tests').mkdir()
        metadata = dict(needs=[], capabilities=['case'])
        self.plan = 'unit_a\t\techo test\t@coverage=' + json.dumps(metadata) + '\n'
        (self.root / 'tests/run_tests.sh').write_text("#!/bin/sh\ncat <<'PLAN'\n" + self.plan + 'PLAN\n')
        (self.logs / 'plan.stdout.log').write_text(self.plan)
        (self.logs / 'unit.log').write_text('actual fixture output\n')
        self.source = dict(revision='a' * 40, configuration={}, inputs={'fixture': 'source'})
        self.events = self.logs / 'events'
        env = dict(os.environ, FELUCCA_COVERAGE_UNIT=str(self.events), FELUCCA_COVERAGE_ID='fresh')
        for args in (['command', 'sh', '-c', 'true'], ['outcome', 'case', 'passed']):
            subprocess.run([sys.executable, str(ROOT / 'tools/test_coverage.py'), *args], env=env, check=True)
        events = [json.loads(p.read_text()) for p in self.events.glob('*.json')]
        self.data = dict(schema=1, run_id='fresh', status='complete', before=self.source, after=self.source,
                         compiler={'fixture': True}, compiler_hashes={sys.executable: C.digest(sys.executable)},
                         baselines=['fixture-o2', 'fixture-os'], engine_ids=[0],
                         logs_root=str(self.logs), plan_sha256=C.digest(self.logs / 'plan.stdout.log'), outputs={},
                         summary=dict(status='passed', signal=None, preflight=dict(status='passed', returncode=0),
                                      plan=dict(status='passed', returncode=0), units=[dict(name='unit_a', dependencies=[],
                                      command=['echo test'], status='passed', returncode=0, **metadata)]),
                         units=[dict(name='unit_a', log='unit.log', log_sha256=C.digest(self.logs / 'unit.log'), events=events)])
        self.data['summary']['units'][0]['log'] = 'unit.log'
        for name in ('build/felucca.dis', 'build/emu/felucca.wasm', 'build/host/asan/fuzz_ed',
                     'build/host/phys_ref', 'build/host/regress', 'build/host/regress_os'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'bounded nonempty fixture')
            self.data['outputs'][name] = dict(bytes=p.stat().st_size, sha256=C.digest(p))

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, data=None, **changes):
        data = copy.deepcopy(self.data if data is None else data)
        data.update(changes)
        path = self.root / 'coverage.json'
        C.atomic(path, data)
        with patch.object(C, 'snapshot', return_value=self.source), \
             patch.object(C, 'host_config', return_value={'fixture': True}), \
             patch.object(C, 'baseline_config', return_value=['fixture-o2', 'fixture-os']), \
             patch.object(C, 'selected_engines', return_value=[0]):
            return C.verify(path, 'fresh', self.root)

    def shard_receipts(self):
        metadata = dict(needs=[], capabilities=['case'])
        plan = ''.join(name + '\t\techo test\t@coverage=' + json.dumps(metadata) + '\n'
                       for name in ('unit_a', 'unit_b'))
        (self.root / 'tests/run_tests.sh').write_text("#!/bin/sh\ncat <<'PLAN'\n" + plan + 'PLAN\n')
        paths = []
        for index, name in enumerate(('unit_a', 'unit_b'), 1):
            directory = self.root / ('receipt-' + str(index))
            directory.mkdir()
            d = copy.deepcopy(self.data)
            d.update(run_id='fresh-' + str(index), checkout_root=str(self.root), logs_root='/other/runner/logs',
                     scope=dict(kind='shard', index=index, count=2, cohort='cohort'),
                     compiler_map={'cc': [sys.executable]})
            for stage, contents in (('plan.stdout.log', plan), ('plan.stderr.log', ''), ('preflight.log', 'ok')):
                (directory / stage).write_text(contents)
            d['stage_logs'] = {p.name: C.digest(p) for p in directory.iterdir()}
            d['plan_sha256'] = C.digest(directory / 'plan.stdout.log')
            d['summary']['scope'] = d['scope']
            d['summary']['units'][0]['name'] = name
            d['units'][0]['name'] = name
            for event in d['units'][0]['events']:
                event['run_id'] = d['run_id']
            (directory / 'unit.log').write_bytes((self.logs / 'unit.log').read_bytes())
            d['outputs'] = {p: value for p, value in d['outputs'].items() if C.REQUIRED_OUTPUTS[p] is None}
            for output in d['outputs']:
                destination = directory / 'outputs' / output
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((self.root / output).read_bytes())
            C.atomic(directory / 'coverage.json', d)
            paths.append(directory)
        return paths

    def verify_shards(self, paths, cohort='cohort'):
        with patch.object(C, 'snapshot', return_value=self.source), \
             patch.object(C, 'host_config', return_value={'fixture': True}), \
             patch.object(C, 'baseline_config', return_value=['fixture-o2', 'fixture-os']), \
             patch.object(C, 'selected_engines', return_value=[0]), \
             patch.object(C, 'compiler_environment', return_value=({}, {'cc': [sys.executable]})):
            return C.verify_shards(paths, cohort, self.root)

    def test_aggregate_requires_all_shards_fresh_cohort_and_unmodified_evidence(self):
        paths = self.shard_receipts()
        self.assertEqual(self.verify_shards(paths)['status'], 'complete')
        for receipts, cohort in ((paths[:1], 'cohort'), (paths + paths[:1], 'cohort'),
                                 ([paths[0], paths[0]], 'cohort'), (paths, 'old-cohort')):
            with self.subTest(receipts=receipts, cohort=cohort), self.assertRaises(ValueError):
                self.verify_shards(receipts, cohort)
        report = paths[1] / 'coverage.json'
        original = C.read_json(report)
        for mutation in ('duplicate_unit', 'missing_unit', 'stale_run', 'failed', 'skip', 'compiler', 'source'):
            d = copy.deepcopy(original)
            if mutation == 'duplicate_unit':
                d['units'][0]['name'] = d['summary']['units'][0]['name'] = 'unit_a'
            elif mutation == 'missing_unit':
                d['units'] = d['summary']['units'] = []
            elif mutation == 'stale_run': d['run_id'] = 'fresh-1'
            elif mutation == 'failed': d['summary']['status'] = 'failed'
            elif mutation == 'skip': d['summary']['units'][0]['status'] = 'skipped'
            elif mutation == 'compiler': d['compiler_hashes'][sys.executable] = 'wrong'
            else: d['before'] = d['after'] = dict(self.source, revision='b' * 40)
            C.atomic(report, d)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.verify_shards(paths)
        C.atomic(report, original)
        for name in ('unit.log', 'preflight.log', 'plan.stderr.log', 'outputs/build/felucca.dis'):
            file = paths[1] / name
            before = file.read_bytes()
            file.write_bytes(before + b'changed')
            with self.subTest(log=name), self.assertRaises(ValueError):
                self.verify_shards(paths)
            file.write_bytes(before)

    def test_aggregate_accepts_relocated_checkout_without_weakening_input_or_flag_checks(self):
        paths = self.shard_receipts()
        self.source['configuration'] = {'CC': str(self.root / 'tools/cc') + ' -DVALUE=1'}
        for directory in paths:
            d = C.read_json(directory / 'coverage.json')
            d['checkout_root'] = '/separate/runner/source'
            d['before'] = d['after'] = dict(self.source, configuration={
                'CC': '/separate/runner/source/tools/cc -DVALUE=1'})
            C.atomic(directory / 'coverage.json', d)
        self.assertEqual(self.verify_shards(paths)['status'], 'complete')
        d = C.read_json(paths[1] / 'coverage.json')
        d['before']['configuration']['CC'] += ' -DOTHER=1'
        C.atomic(paths[1] / 'coverage.json', d)
        with self.assertRaisesRegex(ValueError, 'source/configuration'):
            self.verify_shards(paths)

    def test_partial_receipts_never_satisfy_full_verifier(self):
        for kind in ('shard', 'focused'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'partial scope'):
                self.verify(scope=dict(kind=kind))

    def test_complete_fixture_requires_real_child_and_capability_completion(self):
        self.verify()
        for changed in ('no_events', 'no_capability', 'fake_skip', 'changed_declaration'):
            d = copy.deepcopy(self.data)
            if changed == 'no_events': d['units'][0]['events'] = []
            elif changed == 'no_capability':
                d['units'][0]['events'] = [e for e in d['units'][0]['events'] if e['kind'] != 'outcome']
            elif changed == 'fake_skip':
                d['units'][0]['events'][-1] = dict(schema=1, run_id='fresh', kind='outcome', name='case',
                                                 status='skipped', reason='SKIP: required unavailable')
            else: d['summary']['units'][0]['capabilities'] = []
            with self.subTest(changed=changed), self.assertRaises(ValueError): self.verify(d)

    def test_missing_unit_stale_identity_configuration_and_preflight_fail(self):
        for key, value in (('run_id', 'old'), ('schema', 999), ('status', 'incomplete'), ('after', {})):
            with self.subTest(key=key), self.assertRaises(ValueError): self.verify(**{key: value})
        for status in ('failed', 'blocked', 'cancelled', 'skipped', 'not_applicable'):
            d = copy.deepcopy(self.data)
            d['summary']['units'][0]['status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError): self.verify(d)
        for stage in ('preflight', 'plan'):
            d = copy.deepcopy(self.data)
            d['summary'][stage]['status'] = 'failed'
            with self.subTest(stage=stage), self.assertRaises(ValueError): self.verify(d)
        d = copy.deepcopy(self.data)
        d['summary']['units'] = []
        d['units'] = []
        with self.assertRaises(ValueError): self.verify(d)

    def test_empty_stale_outputs_and_changed_logs_fail(self):
        (self.logs / 'unit.log').write_text('replaced\n')
        with self.assertRaisesRegex(ValueError, 'log changed'): self.verify()
        (self.logs / 'unit.log').write_text('actual fixture output\n')
        (self.root / 'build/host/regress').write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'empty, stale'): self.verify()

    def test_required_producer_and_python_completion_cannot_be_omitted(self):
        for argv in (['build/host/regress', 'tests/golden.txt', '-'], ['python3', 'tests/target_budget.py']):
            d = copy.deepcopy(self.data)
            command = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
            command['argv'] = argv
            outcomes, python, _ = C.command_policy(argv)
            command.update(required_producer=bool(outcomes), required_python=python, expected_outcomes=outcomes)
            with self.subTest(argv=argv), self.assertRaisesRegex(ValueError, 'completion absent'): self.verify(d)
            command.update(required_producer=False, required_python=False, expected_outcomes=[])
            with self.assertRaisesRegex(ValueError, 'contract changed'): self.verify(d)

    def test_entire_required_producer_event_cannot_be_removed(self):
        d = copy.deepcopy(self.data)
        producer = 'tests/target_budget.py'
        metadata = dict(needs=[], capabilities=['case'], producers=[producer])
        plan = 'unit_a\t\techo test\t@coverage=' + json.dumps(metadata) + '\n'
        (self.root / 'tests/run_tests.sh').write_text("#!/bin/sh\ncat <<'PLAN'\n" + plan + 'PLAN\n')
        (self.logs / 'plan.stdout.log').write_text(plan)
        d['plan_sha256'] = C.digest(self.logs / 'plan.stdout.log')
        d['summary']['units'][0]['producers'] = [producer]
        command = dict(schema=1, run_id='fresh', kind='command',
                       argv=['python3', producer], returncode=0, required_producer=True,
                       required_python=True, expected_outcomes=['target-budget'],
                       python=dict(schema=1, unittest=[]),
                       producer=dict(schema=1, outcomes=[dict(name='target-budget', status='passed',
                                                            reason=None, details={})]))
        d['units'][0]['events'].append(command)
        self.verify(d)
        d['units'][0]['events'].append(copy.deepcopy(command))
        with self.assertRaisesRegex(ValueError, 'required child producer absent or duplicated'):
            self.verify(d)
        d['units'][0]['events'].pop()
        d['units'][0]['events'].remove(command)
        with self.assertRaisesRegex(ValueError, 'required child producer absent'):
            self.verify(d)

    def semantic(self, name, details=None, status='passed', reason=None, binary='regress'):
        d = copy.deepcopy(self.data)
        command = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
        command.update(argv=['build/host/' + binary, 'tests/golden.txt', '-'] if name == 'regression' else
                       ['python3', 'tests/install_test.py'], required_producer=True,
                       required_python=name != 'regression', python=dict(schema=1, unittest=[]))
        outcomes, _, _ = C.command_policy(command['argv'])
        command['expected_outcomes'] = outcomes
        command['producer'] = dict(schema=1, outcomes=[dict(name=n, status='passed', reason=None, details={}) for n in outcomes])
        row = next(r for r in command['producer']['outcomes'] if r['name'] == name)
        row.update(details=details or {}, status=status, reason=reason)
        if name == 'regression': command['argv'][2] = details['baseline']
        return d

    def test_whole_cpu_policy_positives_and_neighbouring_negatives(self):
        cpu = dict(total=8, available=8, missing_entries=0, baseline='tests/budget', cpu_status='passed', cpu_reason='')
        self.verify(self.semantic('regression', cpu))
        for status, reason, available, baseline, binary in (
                ('skipped', 'counter-unavailable', 7, 'tests/budget', 'regress'),
                ('skipped', 'baseline-unavailable', 8, '-', 'regress_os'),
                ('not_applicable', 'c1-host-unqualified', 8, '-', 'regress_c1')):
            c = dict(cpu, cpu_status=status, cpu_reason=reason, available=available, baseline=baseline)
            self.verify(self.semantic('regression', c, binary=binary))
            for change in ({'cpu_reason': 'unexpected'}, {'missing_entries': 1}, {'available': 9}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.verify(self.semantic('regression', dict(c, **change), binary=binary))
        with self.assertRaises(ValueError):
            self.verify(self.semantic('regression', dict(cpu, cpu_status='skipped', cpu_reason='counter-unavailable')))

    def test_source_resolved_applicability_not_missing_installation(self):
        for name, reason, engines, configuration in (
                ('tsan', 'not-requested', [0], {'TSAN': ''}),
                ('macro', 'profile-excluded', [0], {'TSAN': ''}),
                ('asan_macro', 'profile-excluded', [0], {'TSAN': ''})):
            d = copy.deepcopy(self.data)
            d['summary']['units'][0].update(name=name, status='not_applicable', reason=reason, returncode=None)
            d['units'][0].update(name=name, events=[])
            plan = self.plan.replace('unit_a', name)
            (self.root / 'tests/run_tests.sh').write_text("#!/bin/sh\ncat <<'PLAN'\n" + plan + 'PLAN\n')
            (self.logs / 'plan.stdout.log').write_text(plan)
            d['plan_sha256'] = C.digest(self.logs / 'plan.stdout.log')
            with patch.dict(os.environ, configuration), patch.object(C, 'selected_engines', return_value=engines):
                self.verify(d)
            if name == 'tsan':
                with patch.dict(os.environ, {'TSAN': '1'}), self.assertRaisesRegex(ValueError, 'applicability'):
                    self.verify(d)
            else:
                # The same missing generated assets cannot exclude a selected engine.
                d['engine_ids'] = [0, 14]
                path = self.root / 'selected.json'
                C.atomic(path, d)
                with patch.object(C, 'snapshot', return_value=self.source), \
                     patch.object(C, 'host_config', return_value={'fixture': True}), \
                     patch.object(C, 'baseline_config', return_value=['fixture-o2', 'fixture-os']), \
                     patch.object(C, 'selected_engines', return_value=[0, 14]), \
                     self.assertRaisesRegex(ValueError, 'applicability'):
                    C.verify(path, 'fresh', self.root)

    def test_only_absent_official_fixtures_are_allowed(self):
        self.verify(self.semantic('official-v15', status='skipped', reason='proprietary-fixture-absent'))
        self.verify(self.semantic('official-v16', status='skipped', reason='proprietary-fixture-absent'))
        for name, status, reason in (('official-v15', 'skipped', 'foreign-file'),
                                     ('official-v15', 'failed', None), ('official-v16', 'failed', None),
                                     ('built-package-parity', 'skipped', 'package-missing'),
                                     ('js-synthetic', 'skipped', 'node-unavailable')):
            with self.subTest(name=name, status=status), self.assertRaises(ValueError):
                self.verify(self.semantic(name, status=status, reason=reason))

    def test_native_only_partitions_cannot_qualify_required_wasm(self):
        d = self.semantic('official-v15')
        command = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
        command['argv'] = ['sh', 'web/emu/partition_test.sh']
        outcomes, python, _ = C.command_policy(command['argv'])
        command.update(required_producer=bool(outcomes), required_python=python, expected_outcomes=outcomes)
        command.pop('python', None)
        command['producer']['outcomes'] = [dict(name=name, status='passed', reason=None, details={}) for name in outcomes]
        self.verify(d)
        wasm = next(row for row in command['producer']['outcomes'] if row['name'] == 'wasm-partitions')
        wasm.update(status='skipped', reason='emcc-unavailable')
        with self.assertRaisesRegex(ValueError, 'unapproved semantic skip'):
            self.verify(d)

    def test_optional_macro_client_parser_requires_actual_opt_in(self):
        d = self.semantic('official-v15')
        event = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
        event['argv'] = ['python3', 'tests/macro_device_pack_test.py']
        event['expected_outcomes'] = C.command_policy(event['argv'])[0]
        event['producer']['outcomes'] = [dict(name='macro-pack', status='passed', reason=None, details={}),
                                         dict(name='macro-webapp-parser', status='not_applicable',
                                              reason='not-requested', details={})]
        self.verify(d)
        for args in (['--webapp', '/client'], ['--webapp=/client']):
            rejected = copy.deepcopy(d)
            next(e for e in rejected['units'][0]['events'] if e['kind'] == 'command')['argv'] += args
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'unapproved semantic skip'):
                self.verify(rejected)

    def test_unknown_duplicate_and_unittest_skips_fail(self):
        d = self.semantic('official-v15')
        command = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
        command['producer']['outcomes'].append(copy.deepcopy(command['producer']['outcomes'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.verify(d)
        d = self.semantic('official-v15')
        command = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
        command['python']['unittest'] = [dict(successful=True, tests=1, skipped=[dict(test='required', reason='anything')])]
        with self.assertRaisesRegex(ValueError, 'unittest empty/skipped'): self.verify(d)

    def test_recorded_empty_or_malformed_unittest_run_is_not_coverage(self):
        for count in (0, -1, True, '1'):
            d = self.semantic('official-v15')
            command = next(e for e in d['units'][0]['events'] if e['kind'] == 'command')
            command['python']['unittest'] = [dict(successful=True, tests=count, skipped=[])]
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'unittest empty'):
                self.verify(d)

    def test_compiler_identity_and_duplicate_json_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'compiler executable'): self.verify(compiler_hashes={})
        with self.assertRaisesRegex(ValueError, 'compiler executable'):
            self.verify(compiler_hashes={sys.executable: 'wrong'})
        path = self.root / 'duplicate.json'
        path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate coverage key'): C.read_json(path)

    def test_update_mode_presence_cannot_claim_comparison_coverage(self):
        for key in ('GOLDEN_UPDATE', 'BUDGET_UPDATE'):
            for value in ('', '0', '1'):
                with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}), \
                     self.assertRaisesRegex(ValueError, 'update mode'):
                    self.verify()


class ProducerTests(unittest.TestCase):
    def test_actual_target_missing_listing_and_python_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = dict(os.environ, FELUCCA_COVERAGE_UNIT=str(root / 'events'), FELUCCA_COVERAGE_ID='producer')
            r = subprocess.run([sys.executable, str(ROOT / 'tools/test_coverage.py'), 'command',
                                sys.executable, 'tests/target_budget.py', str(root / 'missing.dis')],
                               env=env, cwd=ROOT, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            event = json.loads(next((root / 'events').glob('*.json')).read_text())
            self.assertEqual(event['producer']['outcomes'][0]['reason'], 'disassembly-missing')
            self.assertEqual(event['python'], dict(schema=1, unittest=[]))

    def test_actual_unittest_adapter_records_top_level_skips_not_nested_fixture_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'test.py'
            source.write_text('import unittest\nclass T(unittest.TestCase):\n'
                              ' @unittest.skip("missing required dependency")\n def test_required(self): pass\n'
                              'unittest.main()\n')
            env = dict(os.environ, FELUCCA_COVERAGE_UNIT=str(root / 'events'), FELUCCA_COVERAGE_ID='producer')
            subprocess.run([sys.executable, str(ROOT / 'tools/test_coverage.py'), 'command', sys.executable, str(source)],
                           env=env, capture_output=True, check=True)
            event = json.loads(next((root / 'events').glob('*.json')).read_text())
            self.assertEqual(event['python']['unittest'][0]['skipped'][0]['reason'], 'missing required dependency')
            source.write_text('import unittest\nunittest.TextTestRunner().run(unittest.TestSuite())\n')
            for p in (root / 'events').iterdir(): p.unlink()
            subprocess.run([sys.executable, str(ROOT / 'tools/test_coverage.py'), 'command', sys.executable, str(source)],
                           env=env, capture_output=True, check=True)
            event = json.loads(next((root / 'events').glob('*.json')).read_text())
            self.assertEqual(event['python']['unittest'], [dict(tests=0, successful=True, skipped=[])])

    def test_real_install_absence_and_present_foreign_file_are_distinct(self):
        # Load the actual simulation definitions, without its full test sequence.
        # No proprietary file or device is used; a foreign existing file must raise.
        source = (ROOT / 'tests/install_test.py').read_text().split('\nwire()\n')[0]
        namespace = dict(__file__=str(ROOT / 'tests/install_test.py'), __name__='coverage_install_fixture')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('FELUCCA_COVERAGE_CHILD', None)
            exec(compile(source, namespace['__file__'], 'exec'), namespace)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                namespace['ROOT'] = Path(temporary)
                with contextlib.redirect_stdout(io.StringIO()): namespace['official']()
                self.assertEqual(namespace['coverage'].rows[-1]['reason'], 'proprietary-fixture-absent')
                namespace['coverage'].rows.clear()
                (Path(temporary) / 'FM-1_v15.fwsc').write_bytes(b'foreign file')
                with self.assertRaises(namespace['I'].InstallError), contextlib.redirect_stdout(io.StringIO()):
                    namespace['official']()
                self.assertEqual(namespace['coverage'].rows, [])
        finally:
            import shutil
            shutil.rmtree(namespace['TMP'], ignore_errors=True)


class LifecycleTests(unittest.TestCase):
    def test_nested_lifecycle_fixtures_do_not_pollute_outer_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / 'outer-events'
            env = dict(os.environ, FELUCCA_COVERAGE_UNIT=str(events), FELUCCA_COVERAGE_ID='outer')
            env, mapping = C.compiler_environment(env, root / 'outer-shims')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/test_coverage.py'),
                                     'command', sys.executable, 'tests/coverage_contract_test.py',
                                     'LifecycleTests.test_fresh_identity_invalidation_and_changed_input_failure',
                                     'LifecycleTests.test_real_shell_scheduler_contract_normal_compact_serial_parallel',
                                     'CompilerTests.test_implicit_missing_cxx_keeps_c_runner_available',
                                     '-q'], cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = [C.read_json(p) for p in events.glob('*.json')]
            self.assertTrue(any(e['kind'] == 'command' for e in rows))
            self.assertEqual({e['run_id'] for e in rows}, {'outer'})
            bound = {argv[0] for argv in mapping.values()}
            self.assertTrue(all(e['executable'] in bound for e in rows if e['kind'] in ('compiler', 'probe')))

    def test_nested_lifecycle_with_production_compiler_layer(self):
        # The portable host unit already runs under a production compiler shim.
        # Add that layer here too, so the fast helper gate exercises the same
        # nested lifecycle boundary before the complete host suite starts.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('FELUCCA_COVERAGE_')}
            env.update(FELUCCA_COVERAGE_UNIT=str(root / 'production-events'),
                       FELUCCA_COVERAGE_ID='production')
            env, mapping = C.compiler_environment(env, root / 'production-shims')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/test_coverage.py'),
                                     'command', sys.executable, 'tests/coverage_contract_test.py',
                                     'LifecycleTests.test_nested_lifecycle_fixtures_do_not_pollute_outer_invocation',
                                     '-q'], cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = [C.read_json(p) for p in (root / 'production-events').glob('*.json')]
            self.assertTrue(any(e['kind'] == 'command' for e in rows))
            self.assertEqual({e['run_id'] for e in rows}, {'production'})
            bound = {argv[0] for argv in mapping.values()}
            self.assertTrue(all(e['executable'] in bound for e in rows if e['kind'] in ('compiler', 'probe')))

    def test_verified_archive_identity_requires_real_manifest_content_and_modes(self):
        import source_archive
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'fixture.c'
            source.write_text('int fixture;\n')
            source.chmod(0o644)
            metadata = dict(schema_version=1, firmware_revision='a' * 40, source_date_epoch=1,
                            engines=dict(path='firmware/engines', revision='b' * 40),
                            files={'fixture.c': dict(mode=0o644, sha256=C.digest(source))})
            (root / source_archive.MANIFEST).write_bytes(source_archive.manifest_bytes(metadata))
            identity = C.snapshot(root, {})
            self.assertEqual((identity['source_kind'], identity['revision'], identity['engines']),
                             ('verified-archive', 'a' * 40, 'b' * 40))
            extra = root / 'unmanifested.c'
            extra.write_text('unexpected')
            with self.assertRaisesRegex(ValueError, 'unmanifested'): C.snapshot(root, {})
            extra.unlink()
            source.chmod(0o755)
            with self.assertRaisesRegex(ValueError, 'executable mode'): C.snapshot(root, {})
            source.chmod(0o644)
            source.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'missing or changed'): C.snapshot(root, {})
            (root / source_archive.MANIFEST).unlink()
            with self.assertRaisesRegex(ValueError, 'cannot verify'): C.snapshot(root, {})

    def test_missing_installations_are_availability_not_applicability(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(C, 'ROOT', Path(temporary)):
            self.assertEqual(C.requirements(['assets', 'macro-assets', 'node', 'emcc', 'sanitizer'],
                                            dict(PATH='', SANITIZE='0')),
                             ['generated-assets-missing', 'macro-assets-missing', 'node-unavailable',
                              'emcc-unavailable', 'sanitizer-disabled'])
            with self.assertRaisesRegex(ValueError, 'unknown coverage prerequisite'):
                C.requirements(['invented'], {})

    def test_native_partitions_run_without_optional_wasm_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'tests').mkdir()
            (root / 'tools').symlink_to(ROOT / 'tools', target_is_directory=True)
            (root / 'firmware').symlink_to(ROOT / 'firmware', target_is_directory=True)
            (root / 'tests/run_tests.sh').write_text((ROOT / 'tests/run_tests.sh').read_text())
            plan = subprocess.check_output(['sh', 'tests/run_tests.sh', '--plan'], cwd=root, text=True)
            self.assertFalse((root / 'build/felucca.fwsc').exists())
            worker = subprocess.run(['sh', 'tests/run_tests.sh', '--unit', 'emulator_partitions'],
                                    cwd=root, text=True, capture_output=True)
            self.assertNotEqual(worker.returncode, 0)
            self.assertIn('run ./build.sh first', worker.stdout)
        row = next(line for line in plan.splitlines() if line.startswith('emulator_partitions\t'))
        metadata = json.loads(row.split('@coverage=', 1)[1])
        self.assertIn('assets', metadata['needs'])
        self.assertIn('node', metadata['needs'])
        self.assertNotIn('emcc', metadata['needs'])
        self.assertEqual(metadata['producers'], ['web/emu/partition_test.sh'])
        self.assertEqual(C.PRODUCERS['web/emu/partition_test.sh'], {'native-partitions', 'wasm-partitions'})

    def test_fresh_identity_invalidation_and_changed_input_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'report.json'
            path.write_text('malformed previous success')
            env = dict(os.environ, FELUCCA_COVERAGE_REPORT=str(path), FELUCCA_COVERAGE_ID='unique')
            env.pop('FELUCCA_COVERAGE_UNIT', None)  # fixture probes cannot publish into the enclosing unit
            source = dict(revision='a' * 40)
            with patch.object(C, 'snapshot', side_effect=[source, dict(revision='b' * 40)]), \
                 patch.object(C, 'selected_engines', return_value=[0]), \
                 patch.object(C, 'baseline_config', return_value=['fixture-o2', 'fixture-os']):
                contract = C.Coverage(root, env)
                self.assertEqual(json.loads(path.read_text())['status'], 'incomplete')
                logs = root / 'logs'
                logs.mkdir()
                summary = dict(status='passed', units=[])
                self.assertFalse(contract.finish(summary, logs))
                self.assertEqual(summary['status'], 'failed')
                self.assertEqual(json.loads(path.read_text())['status'], 'incomplete')
                with self.assertRaisesRegex(ValueError, 'must be fresh'):
                    C.Coverage(root, env)
                self.assertEqual(json.loads(path.read_text())['status'], 'incomplete')

    def test_real_shell_scheduler_contract_normal_compact_serial_parallel(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        import test_jobs as J
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.git').touch()
            (root / 'tests').mkdir()
            script = root / 'tests/run_tests.sh'
            helper = shlex.quote(str(ROOT / 'tools/test_coverage.py'))
            metadata = json.dumps(dict(needs=[], capabilities=['case']))
            plan = ''.join(f'{name}\t{dependency}\techo\t{name}\t@coverage={metadata}\n'
                           for name, dependency in (('a', ''), ('b', ''), ('c', 'a b'), ('d', ''), ('e', '')))
            script.write_text("#!/bin/sh\ncase \"$1\" in\n--preflight) echo preflight;;\n--plan) cat <<'PLAN'\n" +
                              plan + 'PLAN\n;;\n--unit)\n' +
                              f'python3 {helper} command sh -c "echo actual-$2" || exit $?\n' +
                              f'python3 {helper} outcome case passed\n;;\nesac\n')
            source = dict(revision='a' * 40, inputs={'fixture': C.digest(script)}, configuration={})
            semantic, receipts = [], []
            for output in ('build/felucca.dis', 'build/emu/felucca.wasm'):
                destination = root / output
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b'shared prerequisite')
            cases = [(jobs, compact, dict(kind='full')) for jobs in (1, 2) for compact in (False, True)]
            cases += [(2, True, dict(kind='shard', index=i, count=2, cohort='integration')) for i in (1, 2)]
            for jobs, compact, scope in cases:
                env = dict(os.environ, TEST_JOBS=str(jobs), FELUCCA_COVERAGE_REPORT=str(root / 'coverage.json'),
                           FELUCCA_COVERAGE_ID=f'run-{jobs}-{compact}-{scope.get("index", 0)}')
                env.pop('FELUCCA_COVERAGE_UNIT', None)
                # This intentionally small source/engine fixture still runs the real
                # shell, scheduler, private shims, child adapter and report writer.
                with patch.object(J, '__file__', str(root / 'tests/test_jobs.py')), \
                     patch.object(C, 'snapshot', return_value=source), \
                     patch.object(C, 'selected_engines', return_value=[0]), \
                     patch.object(C, 'baseline_config', return_value=['fixture-o2', 'fixture-os']):
                    # Redirect fd1 too: report_log copies raw bytes to stdout.buffer.
                    with tempfile.TemporaryFile() as output:
                        old = os.dup(1)
                        try:
                            sys.stdout.flush()
                            os.dup2(output.fileno(), 1)
                            self.assertEqual(J.execute(script, root / 'host', env, compact, True, scope), 0)
                        finally:
                            sys.stdout.flush()
                            os.dup2(old, 1)
                            os.close(old)
                report = json.loads((root / 'coverage.json').read_text())
                self.assertEqual(report['status'], 'complete')
                self.assertEqual(report['summary']['preflight']['status'], 'passed')
                if scope['kind'] == 'shard':
                    receipts.append(Path(report['logs_root']))
                else:
                    semantic.append([(u['name'], [(e['kind'], e.get('name'), e.get('returncode')) for e in
                                            sorted(u['events'], key=lambda e: e['kind'])]) for u in report['units']])
            self.assertTrue(all(s == semantic[0] for s in semantic))
            with patch.object(C, 'snapshot', return_value=source), \
                 patch.object(C, 'selected_engines', return_value=[0]), \
                 patch.object(C, 'baseline_config', return_value=['fixture-o2', 'fixture-os']):
                result = C.verify_shards(receipts, 'integration', root)
                self.assertEqual(set(result['units']), {'a', 'b', 'c', 'd', 'e'})



class CompilerTests(unittest.TestCase):
    def test_multiword_wrapper_space_arguments_real_identity_exit_and_signal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / 'compiler wrapper'
            compiler = subprocess.check_output(['which', 'cc'], text=True).strip()
            wrapper.write_text('#!/bin/sh\nexec "$@"\n')
            wrapper.chmod(0o755)
            define = '-DMESSAGE="a b"'
            env = dict(os.environ, CC=shlex.join([str(wrapper), 'cc', define]),
                       FELUCCA_COVERAGE_UNIT=str(root / 'events'), FELUCCA_COVERAGE_ID='compile')
            e, mapping = C.compiler_environment(env, root / 'shims')
            source, output = root / 'source with spaces.c', root / 'output with spaces'
            source.write_text('#include <string.h>\nint main(void){return strcmp(MESSAGE,"a b") ? 4 : 7;}\n')
            r = subprocess.run([e['CC'], str(source), '-o', str(output)], env=e)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(subprocess.run([str(output)]).returncode, 7)
            self.assertEqual(mapping['requested-cc'], [str(wrapper), 'cc', define])
            events = [json.loads(p.read_text()) for p in (root / 'events').glob('*.json')]
            self.assertTrue(any(e['argv'] == [str(wrapper), 'cc', define, str(source), '-o', str(output)] for e in events))
            self.assertTrue(any(e['executable'] == compiler for e in events))
            source.write_text('not valid C\n')
            direct = subprocess.run([str(wrapper), compiler, str(source), '-o', str(output)], capture_output=True)
            shim = subprocess.run([e['CC'], str(source), '-o', str(output)], env=e, capture_output=True)
            self.assertEqual(shim.returncode, direct.returncode)
            wrapper.write_text('#!/bin/sh\nkill -TERM $$\n')
            self.assertEqual(subprocess.run([e['CC']], env=e).returncode, -15)

    def test_implicit_missing_cxx_keeps_c_runner_available(self):
        import shutil
        which = shutil.which
        env = dict(os.environ)
        env.pop('CXX', None)
        env.pop('FELUCCA_COVERAGE_UNIT', None)  # Nested shim fixtures must not publish into their caller.
        def c_only(name, **kwargs):
            return None if name in ('c++', 'clang++', 'g++') else which(name, **kwargs)
        with tempfile.TemporaryDirectory() as temporary, patch.object(C.shutil, 'which', side_effect=c_only):
            result, mapping = C.compiler_environment(env, Path(temporary) / 'shims')
            self.assertNotIn('CXX', result)
            self.assertNotIn('requested-cxx', mapping)
            self.assertEqual(subprocess.run([result['CC'], '--version'], env=result,
                                            stdout=subprocess.DEVNULL).returncode, 0)
        env['CXX'] = 'felucca-missing-explicit-cxx'
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, 'CXX'):
            C.compiler_environment(env, Path(temporary) / 'shims')

    def test_metadata_failure_cannot_run_unrecorded_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / 'not-a-directory'
            events.write_text('do not replace')
            env = dict(os.environ, FELUCCA_COVERAGE_UNIT=str(events), FELUCCA_COVERAGE_ID='compile')
            e, _ = C.compiler_environment(env, root / 'shims')
            output = root / 'compiled.o'
            result = subprocess.run([e['CC'], '-x', 'c', '-c', '-o', str(output), '-'], env=e,
                                    input='int x;', text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_concurrent_compiler_records_are_complete_and_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = dict(os.environ, FELUCCA_COVERAGE_UNIT=str(root / 'events'), FELUCCA_COVERAGE_ID='compile')
            e, mapping = C.compiler_environment(env, root / 'shims')
            processes = [subprocess.Popen([e['CC'], '--version'], env=e, stdout=subprocess.DEVNULL) for _ in range(8)]
            self.assertTrue(all(p.wait() == 0 for p in processes))
            events = [json.loads(p.read_text()) for p in (root / 'events').iterdir()]
            # An outer runner can itself be instrumented. Each exec layer must
            # record once per process, while eight requested invocations remain eight.
            selected = [event for event in events if event['executable'] == mapping['requested-cc'][0]]
            self.assertEqual(len(selected), 8)
            self.assertEqual(len({event['pid'] for event in selected}), 8)
            self.assertEqual(len({(event['executable'], event['pid']) for event in events}), len(events))
            self.assertTrue(all(e['kind'] == 'probe' and e['run_id'] == 'compile' for e in events))


if __name__ == '__main__':
    unittest.main()
