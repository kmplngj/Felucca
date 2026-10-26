#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Meter oracles and actual native capture proof. No target compiler/SDK required.

Reference: independently installed pyloudnorm==0.2.0, MIT, Christian Steinmetz
(2018), Meter(filter_class='DeMan'). No reference source is copied here.
The 48k constants below are BS.1770-3 Tables 1/2, not candidate-generated values.
"""
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
import pyloudnorm

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("loudness_audit", ROOT/"tools/loudness_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class MeterProof(unittest.TestCase):
    def test_published_48k_coefficients_and_rate_response(self):
        expected = [([1.53512485958697, -2.69169618940638, 1.19839281085285],
                     [1, -1.69065929318241, .73248077421585]),
                    ([1, -2, 1], [1, -1.99004745483398, .99007225036621])]
        for actual, reference in zip(audit.k_coefficients(48000), expected):
            np.testing.assert_allclose(actual, reference, rtol=0, atol=2e-14)
        # Independent DeMan reference coefficients at 44.1k. Bilinear frequency
        # warping means the response need not be identical across sample rates.
        expected_44100 = [
            ([1.5308412300498355, -2.6509799951536985, 1.1690790799210682],
             [1, -1.6636551132560204, .7125954280732254]),
            ([1, -2, 1], [1, -1.9891696736297957, .9891990357870394]),
        ]
        for actual, reference in zip(audit.k_coefficients(44100), expected_44100):
            np.testing.assert_allclose(actual, reference, rtol=0, atol=2e-14)
        self.assertFalse(np.array_equal(audit.k_coefficients(44100)[0][0], expected[0][0]))

    def test_independent_reference_aligned_complete_windows(self):
        self.assertEqual(__import__('importlib.metadata', fromlist=['version']).version('pyloudnorm'), '0.2.0')
        for rate in (44100, 48000):
            t = np.arange(rate*2)/rate
            fixtures = [np.column_stack((.07*np.sin(2*np.pi*997*t), .11*np.sin(2*np.pi*211*t))),
                        np.column_stack((.05*np.sin(2*np.pi*1000*t), np.zeros(len(t))))]
            # Fixed seed, stepped amplitude: exercises the relative gate as well.
            noise = np.random.default_rng(679).normal(0, .025, (rate*4, 2))
            noise[rate:3*rate] *= .003
            fixtures.append(noise)
            reference = pyloudnorm.Meter(rate, filter_class='DeMan')
            for pcm in fixtures:
                with self.subTest(rate=rate, frames=len(pcm)):
                    self.assertAlmostEqual(audit.meter(pcm, rate)['integrated_lufs'],
                                           reference.integrated_loudness(pcm), delta=1e-7)

    def test_stereo_energy_and_mono_cancellation(self):
        x = .05*np.sin(2*np.pi*1000*np.arange(44100)/44100)
        one = audit.meter(np.column_stack((x, np.zeros(len(x)))))
        both = audit.meter(np.column_stack((x, x)))
        anti = audit.meter(np.column_stack((x, -x)))
        self.assertAlmostEqual(both['integrated_lufs']-one['integrated_lufs'], 10*math.log10(2), places=10)
        self.assertEqual(both['integrated_lufs'], anti['integrated_lufs'])
        swapped = audit.meter(np.column_stack((np.zeros(len(x)), x)))
        self.assertEqual(swapped['integrated_lufs'], one['integrated_lufs'])
        self.assertEqual(audit.meter(np.column_stack((x, -x)).mean(axis=1))['status'], 'silence')

    def test_boundary_counts_and_strict_gates(self):
        self.assertEqual(audit.meter(np.empty((0, 2)))['status'], 'empty')
        for n in (1, 17639):
            self.assertEqual(audit.meter(np.full(n, .1))['status'], 'short')
        for n, count in ((17640, 1), (19846, 1), (22049, 1), (22050, 2), (26460, 3)):
            self.assertEqual(audit.meter(np.full(n, .1))['gate_blocks'], count)
        for n, count in ((0, 0), (1, 0), (17639, 0), (17640, 1), (44100, 7)):
            silent = audit.meter(np.zeros(n))
            self.assertEqual(silent['status'], 'empty' if not n else 'silence')
            self.assertEqual(silent['gate_blocks'], count)
            self.assertEqual(silent['absolute_gate_blocks'], 0)
            self.assertEqual(silent['relative_gate_blocks'], 0)
            self.assertIsNone(silent['integrated_lufs'])
        self.assertEqual(audit.meter(np.full(44100, 1e-12))['status'], 'all_gated')
        threshold = 10**((-70+.691)/10)
        self.assertEqual(audit.gate_energy([threshold])['absolute_gate_blocks'], 0)
        self.assertEqual(audit.gate_energy([threshold*.999])['status'], 'all_gated')
        self.assertEqual(audit.gate_energy([threshold*1.001])['status'], 'ok')
        # Mean power .55 -> relative gate .055; .1 survives, .01 does not.
        result = audit.gate_energy([1, .1, .01])
        self.assertEqual(result['relative_gate_blocks'], 2)
        self.assertAlmostEqual(result['integrated_lufs'], -.691+10*math.log10(.55))
        # Mean power 10 -> relative threshold exactly 1; equality is excluded.
        boundary = audit.gate_energy([19., 1.])
        self.assertEqual(boundary['relative_gate_blocks'], 1)
        self.assertAlmostEqual(boundary['integrated_lufs'], -.691+10*math.log10(19))

    def test_nonfinite_shape_overrange_and_strict_json(self):
        for value in (np.nan, np.inf, -np.inf):
            with self.assertRaises(ValueError): audit.meter([value])
        for bad in (np.zeros((4, 3)), np.zeros((1, 2, 2))):
            with self.assertRaises(ValueError): audit.meter(bad)
        for pcm in (np.empty((0, 2)), np.zeros(44100), np.ones(1), np.full(44100, 2.0)):
            report = audit.meter(pcm)
            json.dumps(report, allow_nan=False)
        self.assertEqual(audit.meter(np.full(1, 2.0))['overrange_samples'], 1)


class ContractProof(unittest.TestCase):
    def setUp(self):
        self.phrases = audit.read_json(audit.PHRASES)

    def test_donor_phrases_and_native_duration(self):
        self.assertEqual(self.phrases['source_commit'], audit.DONOR)
        self.assertEqual(set(self.phrases['roles']), {'bass', 'held', 'comp', 'melody', 'one-key-chord'})
        case = audit.make_case(dict(id='lead', engine_id=3, preset=0, role='melody', reverb='hall'), self.phrases)
        self.assertEqual(case['body_frames'], 32*(44100*60//100//4))
        self.assertTrue(any(n == 72 and v and f >= 30*6615//32*32 for f, n, v in case['events']))
        self.assertGreater(case['frames'], max(e[0] for e in case['events']))
        self.assertEqual(self.phrases['drum_notes'], [36, 38, 39, 42, 46, 45, 37, 56])
        self.assertEqual(self.phrases['canonical_drum_kits'], [0, 4, 5, 6, 7, 8, 9, 10, 11])

    def test_invalid_selection_and_duplicate_json(self):
        valid = dict(id='synth', engine_id=0, preset=0, role='bass', reverb='room')
        for delta in ({'engine_id': True}, {'role': 'guessed'}, {'reverb': 'default'}, {'preset': -1}, {'id': '../source'}, {'lane': 1}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                audit.make_case(dict(valid, **delta), self.phrases)
        for kit in (1, 2, 3, 12, True):
            with self.assertRaises(ValueError):
                audit.make_case(dict(id='d', engine_id=10, preset=0, role='drum-hit', reverb='hall', kit=kit, lane=0), self.phrases)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.json'
            path.write_text('{"id":1,"id":2}')
            with self.assertRaises(ValueError): audit.read_json(path)
            path.write_text('{"value":NaN}')
            with self.assertRaises(ValueError): audit.read_json(path)

    def test_output_and_count_budgets_before_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'cases.json'
            case = dict(id='s', engine_id=0, preset=0, role='bass', reverb='room')
            for cases in ([], [case]*9, [case, case]):
                audit.write_json(path, {'schema': 1, 'cases': cases})
                with mock.patch.object(audit, 'compile_probe') as compiler:
                    with self.assertRaises(ValueError):
                        audit.run_audit(path, ROOT/'build/audit-run-fixture-invalid')
                    compiler.assert_not_called()
            audit.write_json(path, {'schema': 1, 'cases': [case]})
            for output in (ROOT/'firmware', ROOT/'build/gen', ROOT/'build/audit-run-sub/nested'):
                with self.assertRaises(ValueError): audit.run_audit(path, output)

    def test_capture_child_failure_and_truncated_metadata(self):
        case = audit.make_case(dict(id='s', engine_id=0, preset=0, role='bass', reverb='hall'), self.phrases)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(audit, 'command', side_effect=ValueError('child failure')):
                with self.assertRaisesRegex(ValueError, 'child failure'):
                    audit.capture(Path('/unused'), case, Path(tmp)/'failed')
            def truncated(argv, directory, *args, **kwargs):
                (directory/'render.stdout').write_text('{"schema":1}')
            with mock.patch.object(audit, 'command', side_effect=truncated):
                with self.assertRaisesRegex(ValueError, 'metadata'):
                    audit.capture(Path('/unused'), case, Path(tmp)/'truncated')


class NativeProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'build').mkdir(exist_ok=True)
        cls.before = audit.inventory()
        cls.directory = Path(tempfile.mkdtemp(prefix='audit-run-proof-', dir=ROOT/'build'))
        # Earlier caller flags must not disable the mandatory native overflow guard.
        cls.probe = audit.compile_probe(cls.directory, ['-fno-sanitize=all', '-fsanitize-recover=all'])
        cls.phrases = audit.read_json(audit.PHRASES)

    @classmethod
    def tearDownClass(cls):
        # Logs and actual raw evidence remain in the ignored CI artifact directory.
        if cls.before != audit.inventory():
            raise AssertionError('source changed during native proof')

    def test_real_master_non_equivalent_control(self):
        output = audit.command([str(self.probe), '--self-test'], self.directory, 'master-proof')
        self.assertEqual(json.loads(output), {'tap_boundaries': True, 'master_replay': True, 'attenuate_rescale_is_not_equivalent': True})

    def test_real_native_overflow_cannot_produce_success(self):
        with self.assertRaisesRegex(ValueError, 'child exited'):
            audit.command([str(self.probe), '--overflow-self-test'], self.directory, 'native-overflow')
        self.assertIn('signed integer overflow', (self.directory/'native-overflow.stderr').read_text())

    def test_actual_compiled_omission_rejects_profile_claim(self):
        directory = Path(tempfile.mkdtemp(prefix='audit-run-omitted-', dir=ROOT/'build'))
        probe = audit.compile_probe(directory, ['-DFELUCCA_ENG_OMIT=11'])
        case = dict(id='selected-analog', engine_id=0, preset=0, reverb='hall',
                    frames=audit.CTL, events=[[0, 36, 100]])
        with self.assertRaisesRegex(ValueError, 'compiled engine selection'):
            audit.capture(probe, case, directory/'capture')

    def test_real_repeat_order_subset_and_block_lifetime(self):
        a = audit.make_case(dict(id='a', engine_id=0, preset=0, role='bass', reverb='hall'), self.phrases)
        b = audit.make_case(dict(id='b', engine_id=10, preset=0, role='drum-hit', reverb='room', kit=0, lane=0), self.phrases)
        captures = {}
        # Full selection, reverse selection, then a standalone subset. Every call
        # is a new actual process; no fake/generated PCM supplies native evidence.
        for index, case in enumerate((a, b, b, a, a)):
            meta, arrays = audit.capture(self.probe, case, self.directory/f'capture-{index}')
            self.assertEqual(meta['tap_replay_blocks'], case['frames']//audit.CTL)
            self.assertEqual(meta['reverb'], 2 if case['reverb'] == 'hall' else 0)
            if case['id'] in captures:
                for tap in ('pre', 'post'):
                    np.testing.assert_array_equal(arrays[tap], captures[case['id']][tap])
            else:
                captures[case['id']] = arrays
            self.assertTrue(np.any(arrays['pre']))
            blocks = arrays['pre'].reshape(-1, audit.CTL, 2)
            self.assertGreater(len(np.unique(blocks.reshape(len(blocks), -1), axis=0)), 2)
            self.assertFalse(np.array_equal(blocks[0], blocks[-1]))
            self.assertFalse(np.array_equal(arrays['pre'], arrays['post']))

    def test_native_rejects_partial_events_and_missing_engine(self):
        events = self.directory/'partial-events.txt'
        events.write_text('0 36 100\n32 36\n')
        argv = [str(self.probe), '0', '0', '255', '0', '64', str(events), str(self.directory/'bad-pre'), str(self.directory/'bad-post')]
        result = subprocess.run(argv, capture_output=True)
        self.assertEqual(result.returncode, 2)
        events.write_text('0 36 100\n')
        argv[1] = '63'
        self.assertEqual(subprocess.run(argv, capture_output=True).returncode, 2)

    def test_real_selected_report_and_artifact_hashes(self):
        selection = self.directory/'selected.json'
        audit.write_json(selection, {'schema': 1, 'cases': [dict(id='kick', engine_id=10, preset=0, role='drum-hit', reverb='hall', kit=0, lane=0)]})
        output = ROOT/'build'/('audit-run-report-'+self.directory.name.removeprefix('audit-run-proof-'))
        report_path = audit.run_audit(selection, output)
        report = audit.read_json(report_path)
        case = report['cases'][0]
        self.assertEqual(case['engine_key'], 'felucca.engine.drum')
        self.assertEqual(case['probe']['reverb'], 2)
        self.assertEqual(case['listening'], 'not_performed')
        self.assertEqual(report['physical_dac_usb'], 'not_measured')
        self.assertEqual(audit.read_json(output/'source-before.json'), audit.read_json(output/'source-after.json'))
        manifest = audit.read_json(output/'manifest.json')
        for name, digest in manifest.items():
            self.assertEqual(audit.sha(output/name), digest)
        for tap in ('pre', 'post'):
            self.assertEqual((output/'kick'/f'{tap}.i32le').stat().st_size, case['case']['frames']*8)
        self.assertEqual((output/'kick/post-master.wav').stat().st_size, 44+case['case']['frames']*4)


if __name__ == '__main__':
    unittest.main()
