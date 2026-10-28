#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable attribution and saved-evidence refusal fixtures; no emulator execution."""
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import native_hotspots as H
import native_emulator_replay_test as fixtures

A = 0x02000120


def sym(name='f', start=A, size=4, flags='g F'):
    return f'{start:08x} {flags} .text {size:08x} {name}\n'


def listing(start=A, count=8):
    return ''.join(f'{start + i*2:08x}: 00 00 \tnop\n' for i in range(count))


def trace(*pcs):
    return ''.join(f'T {100+i} c0 {pc:#010x} nop irq=[] ie=true r0=0x0 r1=0x0\n'
                   for i, pc in enumerate(pcs)).encode()


class Hotspots(unittest.TestCase):
    def setUp(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='hotspot-contract-', dir=ROOT / 'build')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def attribution(self, symbols, data, dis=None):
        return H.attribute(data, *H.ranges(symbols, listing() if dis is None else dis))

    def test_half_open_ranges_adjacent_function_and_entry_hits(self):
        result = self.attribution(sym() + sym('next', A+4, 2), trace(A, A+2, A+4))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([f['guest_instructions'] for f in result['symbols']], [2, 1])
        self.assertEqual(result['symbols'][1]['names'], ['next'])
        self.assertEqual(result['symbols'][0]['entry_pc_hits_not_calls'], 1)
        end = self.attribution(sym(), trace(A+4))
        self.assertEqual(end['status'], 'unavailable')
        self.assertEqual(end['attributed_instructions'], 0)

    def test_aliases_count_once_and_duplicate_names_at_different_ranges_survive(self):
        result = self.attribution(sym('alias') + sym('f') + sym('f', A+4, 2), trace(A, A+4))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['symbols']), 2)
        self.assertEqual(result['symbols'][0]['names'], ['alias', 'f'])
        self.assertEqual(sum(f['guest_instructions'] for f in result['symbols']), 2)
        self.assertEqual(result['instruction_classes'], {'nop': 2})

    def test_zero_sized_labels_get_no_inferred_extent(self):
        symbols = sym() + sym('entry_alias', size=0, flags='g') + sym('asm', A+8, 0, 'g')
        result = self.attribution(symbols, trace(A, A+8, A+10))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['symbols'][0]['zero_sized_entry_labels'], ['entry_alias'])
        self.assertEqual(result['unresolved_instructions'], 2)
        self.assertIn('zero-sized', result['unresolved'][0]['reason'])
        with self.assertRaisesRegex(ValueError, 'no sized functions'):
            H.ranges(sym('asm', size=0, flags='g'), listing())

    def test_overlap_never_selects_smallest_or_duplicates_counts(self):
        result = self.attribution(sym() + sym('inner', A+2, 2), trace(A, A+2))
        self.assertEqual(result['attributed_instructions'], 1)
        self.assertEqual(result['unresolved_instructions'], 1)
        self.assertIn('ambiguous', result['unresolved'][0]['reason'])

    def test_mid_instruction_unknown_decode_inline_data_and_crossing_end(self):
        for text in ('(bad)', 'unknown_op', '.long 0', '< 0 : 0x0 >'):
            with self.subTest(text=text):
                result = self.attribution(sym(size=2), trace(A), f'{A:08x}: 00 00 \t{text}\n')
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['attributed_instructions'], 0)
        dis = f'{A:08x}: 00 00 00 00 \tr0 = 0\n'
        self.assertIn('instruction start', self.attribution(sym(), trace(A+2), dis)['unresolved'][0]['reason'])
        result = self.attribution(sym(size=2), trace(A), dis)
        self.assertIn('crosses', result['unresolved'][0]['reason'])
        self.assertEqual(result['status'], 'unavailable')

    def test_unrelated_unsupported_frame_does_not_hide_valid_execution(self):
        result = self.attribution(sym(size=2), trace(A), f'{A:08x}: 00 00 \tsp = r0\n')
        self.assertEqual(result['status'], 'complete')

    def test_malformed_missing_duplicate_and_oversize_inputs_fail(self):
        for symbols, dis in (('bad F .text size f\n', listing()), (sym()+sym(), listing()),
                             (sym(), listing() + listing()), (sym(), f'{A:x}: invalid\n')):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                H.ranges(symbols, dis)
        with self.assertRaises(ValueError):
            H.ranges(sym() * 10001, listing())
        for data in (b'', trace(A)[:-1], trace(A).replace(b' c0 ', b' c1 '),
                     trace(A).replace(b' nop ', b' ? ')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.attribution(sym(), data)

    def test_saved_json_bounds_duplicates_paths_and_symlinks(self):
        bindings = {}
        (self.root / 'x.json').write_text('{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            H.read_json(self.root, 'x.json', bindings)
        with self.assertRaises(ValueError):
            H.checked_file(self.root, 'x.json', 1, bindings)
        with self.assertRaises(ValueError):
            H.checked_file(self.root, '../x.json', 99, bindings)
        (self.root / 'link').symlink_to(self.root / 'x.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            H.checked_file(self.root, 'link', 99, bindings)

    def test_untrusted_source_context_refuses_before_any_external_verifier(self):
        H.emulator_trace.run(['git', '-c', 'init.templateDir=', 'init', '--quiet', self.root])
        (self.root / 'file').write_text('fixture')
        H.emulator_trace.run(['git', '-C', self.root, 'add', 'file'])
        H.emulator_trace.run(['git', '-C', self.root, '-c', 'user.name=Test', '-c', 'user.email=t@example.invalid',
                             'commit', '--quiet', '-m', 'fixture'])
        with self.assertRaisesRegex(ValueError, 'unsupported replay verifier revision'):
            H.source_context(self.root)
        (self.root / 'SOURCE-PINS.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'must be Git'):
            H.source_context(self.root)

    def test_archive_entry_blocks_sourceless_helper_before_help(self):
        tree = self.root / 'archive'; tools = tree / 'tools'; tools.mkdir(parents=True)
        (tree / 'SOURCE-PINS.json').write_text('{}')
        entry = tools / 'native_hotspots.py'; entry.write_text(Path(H.__file__).read_text())
        marker = tree / 'executed'; helper = tools / 'build.py'
        helper.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        py_compile.compile(str(helper), cfile=str(tools / 'build.pyc'), doraise=True); helper.unlink()
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        p = subprocess.run([sys.executable, entry, '--help'], cwd=tree, env=env, capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0); self.assertIn(b'requires a Git checkout', p.stderr)
        self.assertFalse(marker.exists())

    def test_symbol_capture_uses_verified_toolchain_with_unset_empty_and_override(self):
        for setting in (None, '', 'explicit', 'relative'):
            with self.subTest(setting=setting):
                tree = self.root / ('unset' if setting is None else setting or 'empty')
                native_root = tree / 'native'
                tools = native_root / 'tools'; tools.mkdir(parents=True)
                # Exercise the producer's real build.tc/toolchain selection in
                # the actual symbol child, without invoking a target compiler.
                for name in ('build.py', 'fm1pkg_make.py', 'lz4blk.py'):
                    (tools / name).write_bytes((ROOT / 'tools' / name).read_bytes())
                (native_root / 'build').mkdir()
                (native_root / 'build/felucca.dis').write_text(listing())
                home = tree / 'home'
                toolchain = tree / 'selected-toolchain' if setting in ('explicit', 'relative') else home / '.jieli/toolchain'
                objdump = toolchain / 'common/bin/objdump'
                objdump.parent.mkdir(parents=True)
                clang = toolchain / 'pi32v2/bin/clang'; clang.parent.mkdir(parents=True); clang.touch()
                marker = tree / 'symbol-invocation.json'
                objdump.write_text('#!' + sys.executable + '\nimport json, os, sys\nfrom pathlib import Path\n'
                                   'Path(' + repr(str(marker)) + ').write_text(json.dumps({'
                                   '"argv":sys.argv,"toolchain":os.environ["JIELI_TOOLCHAIN"]}))\n'
                                   'sys.stdout.write(' + repr(sym()) + ')\n')
                objdump.chmod(0o755)
                expected_sha = H.replay.digest(objdump)
                native = {'report': {'configuration': {'toolchain_sha256': {'common/bin/objdump': expected_sha}},
                                     'build_identity': {}, 'configuration_sha256': 'fixture'}, 'binding': {}}
                proof = tree / 'replay/build/proof'; proof.mkdir(parents=True)
                summary = proof / 'summary.json'; summary.write_text('{}')
                admitted = (native, {'fixture': [trace(A), trace(A)]},
                            {str(summary): H.replay.digest(summary)}, [], {})
                with patch.object(H, 'validate_saved', return_value=admitted), \
                     patch.object(H.replay, 'check_native_unchanged'), patch.object(H, 'source_context'), \
                     patch.object(Path, 'home', return_value=home), \
                     patch.dict(os.environ, {'JIELI_DOCKER': '0'}):
                    if setting is None:
                        os.environ.pop('JIELI_TOOLCHAIN', None)
                    else:
                        os.environ['JIELI_TOOLCHAIN'] = ('../selected-toolchain' if setting == 'relative' else
                                                       str(toolchain) if setting else '')
                    path = H.report(proof, tree / 'replay', native_root, tree / 'report')
                result = json.loads(path.read_text())
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['objdump_sha256'], expected_sha)
                invocation = json.loads(marker.read_text())
                self.assertEqual(invocation['argv'], [str(objdump.resolve()), '-t', 'build/felucca.elf'])
                self.assertEqual(invocation['toolchain'], str(toolchain))

    def saved_fixture(self):
        r = H.replay
        context = self.root / 'replay'; proof = context / 'build/proof'; proof.mkdir(parents=True)
        native_root = self.root / 'native'; (native_root / 'build').mkdir(parents=True)
        app = native_root / 'build/felucca.bin'; app.write_bytes(b'\0' * 8)
        native = {'root':str(native_root), 'package':str(native_root / 'build/felucca.fwsc'),
                  'report':{}, 'binding':{'fixture':'native'}, 'break_pc':fixtures.PC}
        receipt = {'binary':'/verified/emulator', 'binary_sha256':'a'*64}
        receipt_path = context / 'build/receipt.json'; receipt_path.write_text(json.dumps(receipt))
        summary = {'schema_version':1, 'kind':'felucca-native-replay-evidence', 'status':'passed',
                   'driver_sha256':r.digest(ROOT / 'tools/native_emulator_replay.py'), 'steps':r.STEPS,
                   'trace_window':list(fixtures.WINDOW), 'native':native, 'emulator_receipt':str(receipt_path),
                   'emulator_receipt_sha256':r.digest(receipt_path), 'emulator_binary_sha256':'a'*64, 'runs':[]}
        for case in r.CASES:
            for control in (True, False):
                for label,traced in (('trace-1',True),('plain',False),('trace-2',True)):
                    name=case+('-control-' if control else '-workload-')+label; base=proof/name; base.mkdir()
                    notes=r.expected_midi(case,control)
                    stdout=fixtures.transcript(rows=traced,notes=notes).replace(b'/ignored/audio.wav',str(base/'audio.wav').encode())
                    (base/'child.stdout').write_bytes(stdout); (base/'child.stderr').write_bytes(b'')
                    execution, trace_data=r.parse_log(stdout,traced=traced,window=fixtures.WINDOW,
                                                      break_pc=native['break_pc'],expected_notes=notes)
                    (base/'trace.txt').write_bytes(trace_data); (base/'xip.bin').write_bytes(b'\0'*0x120+app.read_bytes())
                    with wave.open(str(base/'audio.wav'),'wb') as wav:
                        wav.setparams((2,2,44100,40704,'NONE','not compressed'))
                        wav.writeframes((b'\0'*4 if control else b'\1\0\1\0')*40704)
                    argv=[receipt['binary'],'--fwsc',native['package'],'--steps',str(r.STEPS),'--break-pc',hex(native['break_pc']),'--wav',str(base/'audio.wav')]
                    if not control: argv+=['--keys',r.CASES[case]]
                    proc={'argv':argv,'status':'complete','returncode':0,'timeout_seconds':r.TIMEOUT,
                          'log_limit_bytes':r.MAX_LOG,'wall_seconds':1,'stdout_sha256':r.digest(base/'child.stdout'),
                          'stderr_sha256':r.digest(base/'child.stderr')}
                    row={'case':case,'control':control,'traced':traced,'process':proc,'execution':execution,
                         'image':r.check_image(base/'xip.bin',app),'audio':r.read_pcm(base/'audio.wav',40704)}
                    (base/'child.process.json').write_text(json.dumps(proc)); (base/'result.json').write_text(json.dumps(row))
                    summary['runs'].append({'directory':name,**row})
        (proof/'summary.json').write_text(json.dumps(summary)); (proof/'native-resource-report.json').write_text('{}')
        out=self.root/'verification'; out.mkdir()
        return context,proof,native_root,native,out

    def validate_fixture(self, values):
        context,proof,native_root,native,out=values
        def capture(argv,cwd,env,prefix,**kw):
            prefix.with_suffix('.stdout').write_text('verified '+'a'*64+' /verified/emulator\n')
            return {'fixture':'original receipt authority'}
        with patch.object(H,'source_context'), patch.object(H.replay,'native_inputs',return_value=native), \
             patch.object(H.replay,'capture',side_effect=capture), patch.object(H.replay,'WINDOW',fixtures.WINDOW):
            return H.validate_saved(proof,context,native_root,out)

    def test_complete_saved_plan_recomputed_not_just_passed_label(self):
        values=self.saved_fixture(); native,traces,bindings,timings,_=self.validate_fixture(values)
        self.assertEqual(len(traces),4); self.assertEqual(len(timings),4)
        self.assertTrue(all(len(pair)==2 for pair in traces.values())); self.assertGreater(len(bindings),70)
        summary=values[1]/'summary.json'; data=json.loads(summary.read_text()); data['runs'].pop()
        summary.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'run plan'):
            self.validate_fixture(values)

    def test_saved_trace_image_log_and_recipe_mutations_are_refused(self):
        values=self.saved_fixture(); proof=values[1]; base=proof/'held-key-control-trace-1'
        for name in ('trace.txt','child.stdout','audio.wav','xip.bin','child.process.json'):
            path=base/name; old=path.read_bytes(); path.write_bytes(old+b'changed')
            try:
                with self.subTest(name=name),self.assertRaises((ValueError,json.JSONDecodeError)):
                    self.validate_fixture(values)
            finally: path.write_bytes(old)
        summary=proof/'summary.json'; data=json.loads(summary.read_text()); data['native']['root']='/report-chosen-code'
        summary.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'explicit native root'):
            self.validate_fixture(values)


if __name__ == '__main__':
    unittest.main()
