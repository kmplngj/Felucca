#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable audio-window admission/refusal contracts; no native emulator runs."""
import copy
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
import native_audio_window as A
import native_emulator_replay_test as F

PC = 0x0203aa8a
START = 168441255
WINDOW = (START, START + A.WIDTH)


def entries(slot=START, pc=PC, irq='3', frames=32):
    regs = ', '.join(format(n, 'x') for n in (0, 0, 0, frames, *([0] * 8)))
    return (f'break c0 pc={pc:#010x} [{slot}] sp=0x1c7b000 rets=0x2005800 '
            f'irq_levels=[{irq}] r0-11=[{regs}]\n').encode()


def trace(window=WINDOW, irq='3', first=PC, rest=PC+2):
    return ''.join(f'T {slot} c0 {first if i == 0 else rest:#010x} nop irq=[{irq}] '
                   'ie=true r0=0x0 r1=0x0\n' for i, slot in enumerate(range(*window))).encode()


def inventory():
    symbols = (f'{PC:08x} g F .text 00000002 analog_render\n'
               f'{PC+2:08x} g F .text 00000002 analog_render_1\n')
    listing = ''.join(f'{pc:08x}: 00 00 \tnop\n' for pc in (PC, PC+2))
    return A.H.ranges(symbols, listing)


class AudioWindow(unittest.TestCase):
    def setUp(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='audio-window-contract-', dir=ROOT / 'build')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.functions, self.unsized, self.instructions = inventory()
        self.anchor = A.select_anchor(self.functions, 'analog_render')
        self.native = {'root': str(self.root), 'break_pc': F.PC, 'package': str(self.root/'native.fwsc')}
        (self.root/'build').mkdir()
        (self.root/'build/felucca.bin').write_bytes(b'\0'*8)
        self.count = 0

    def discover(self, rows):
        return A.discovery_observation(rows + F.transcript(rows=False), self.native, self.anchor)

    def qualify(self, data=None, window=WINDOW, control=False, functions=None, instructions=None):
        return A.qualify_trace(trace() if data is None else data, window, self.anchor,
                               self.functions if functions is None else functions, self.unsized,
                               self.instructions if instructions is None else instructions, control=control)

    def test_discovery_selects_first_supported_post_input_candidate(self):
        found = self.discover(entries(A.FIRST_INPUT_SLOT-1) + entries() + entries(START+50))
        self.assertEqual(found['candidate']['slot'], START)
        self.assertEqual(found['window'], list(WINDOW))
        self.assertEqual(found['execution']['trace_rows'], 0)
        self.assertEqual(len(found['entries']), 3)

    def test_discovery_missing_duplicate_reordered_excessive_and_out_of_run(self):
        for data in (b'', entries()+entries(), entries()+entries(START-1),
                     b''.join(entries(START+i) for i in range(A.MAX_HITS+1)),
                     entries(0), entries(A.R.STEPS+1), entries(A.R.STEPS-A.WIDTH+2),
                     entries(A.FIRST_INPUT_SLOT-1)):
            with self.subTest(data=data[:90]), self.assertRaises(ValueError):
                self.discover(data)

    def test_discovery_argument_irq_pc_and_terminal_refusals(self):
        for data in (entries(pc=PC+2), entries(irq='1'), entries(irq='3, 7'), entries(frames=31),
                     entries().replace(b'r0-11=[', b'r0-11=[0, '), entries().replace(b'break c0', b'break c1')):
            with self.subTest(data=data[:90]), self.assertRaises(ValueError):
                self.discover(data)
        for data in (entries(), entries()+F.transcript(rows=False)[:-1],
                     entries()+F.transcript(rows=False)+b'time CORRUPT\n',
                     entries()+F.transcript(rows=False)+b'cpu1 running\n'):
            with self.subTest(data=data[-50:]), self.assertRaises(ValueError):
                A.discovery_observation(data, self.native, self.anchor)

    def test_actual_trace_requires_post_dispatch_anchor_irq_and_render_work(self):
        good = self.qualify()
        self.assertEqual(good['attributed_instructions'], A.WIDTH)
        self.assertEqual(good['status'], 'complete')
        for data in (trace(first=PC+2), trace(irq=''), trace(irq='3, 7'), trace(rest=PC),
                     trace().replace(b' c0 ', b' c1 ', 1)):
            with self.subTest(data=data[:100]), self.assertRaises(ValueError):
                self.qualify(data)

    def test_matched_control_does_not_require_render_entry_or_irq(self):
        result = self.qualify(trace(first=PC+2, rest=PC+2, irq=''), control=True)
        self.assertEqual(result['status'], 'complete')

    def test_trace_bounds_order_partial_and_unknown_are_refused(self):
        for window in ((0,A.WIDTH), (START,10**12), (START,START+A.WIDTH-1),
                       (True, A.WIDTH+1), (START,), None):
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.qualify(window=window)
        data = trace()
        for bad in (b'', data[:-1], data.split(b'\n',1)[1], data+data.splitlines(keepends=True)[0],
                    data.replace(str(START+1).encode(), str(START).encode(), 1),
                    trace(rest=PC+4), data.replace(b' nop ', b' ? ', 1)):
            with self.subTest(data=bad[:90]), self.assertRaises(ValueError):
                self.qualify(bad)
        with self.assertRaisesRegex(ValueError, 'unknown/ambiguous'):
            self.qualify(functions=self.functions+[dict(self.functions[0], names=['overlap'])])
        with self.assertRaisesRegex(ValueError, 'unknown/ambiguous'):
            self.qualify(instructions={PC:self.instructions[PC]})

    def test_missing_or_ambiguous_supported_symbols_refuse(self):
        for functions in ([], self.functions+[self.functions[0]],
                          [dict(self.functions[0], section='.data')],
                          [dict(self.functions[0], size_bytes=0)]):
            with self.subTest(functions=functions), self.assertRaises(ValueError):
                A.select_anchor(functions, 'analog_render')

    def execute_fixture(self, *, control=False, traced=True, discovery=False, change=None):
        self.count += 1
        directory = self.root/f'run-{self.count}'
        wav_basis = self.root/'basis.wav'
        pcm = (b'\0'*4 if control else b'\1\0\1\0')*40704
        with wave.open(str(wav_basis),'wb') as wav:
            wav.setparams((2,2,44100,40704,'NONE','not compressed')); wav.writeframes(pcm)
        basis_audio = A.R.read_pcm(wav_basis, 40704)
        xip_basis = self.root/'basis.bin'; xip_basis.write_bytes(b'\0'*0x120+b'\0'*8)
        basis_image = A.R.check_image(xip_basis, self.root/'build/felucca.bin')
        seen = {}
        def child(argv,cwd,env,prefix,**kw):
            seen.update(argv=list(argv),env=env,watched=kw['watched'])
            if change == 'child failure': raise ValueError('child failure')
            if change == 'child timeout': raise ValueError('child timeout')
            stdout = ((entries() if discovery else trace() if traced else b'') + F.transcript(rows=False))
            if change == 'empty': stdout=b''
            if change == 'partial': stdout=stdout[:-1]
            prefix.with_suffix('.stdout').write_bytes(stdout)
            prefix.with_suffix('.stderr').write_bytes(b'error' if change == 'stderr' else b'')
            (directory/'audio.wav').write_bytes(wav_basis.read_bytes() + (b'x' if change == 'PCM' else b''))
            (directory/'xip.bin').write_bytes(xip_basis.read_bytes())
            if change == 'image': (directory/'xip.bin').write_bytes(b'bad')
            process={'wall_seconds':1,'status':'complete','returncode':0,
                     'stdout_sha256':A.R.digest(prefix.with_suffix('.stdout')),
                     'stderr_sha256':A.R.digest(prefix.with_suffix('.stderr'))}
            prefix.with_suffix('.process.json').write_text(json.dumps(process))
            return process
        if change == 'basis PCM': basis_audio=dict(basis_audio,peak_pcm16=42)
        if change == 'basis image': basis_image=dict(basis_image,xip_sha256='a'*64)
        with patch.object(A.R,'capture',side_effect=child), patch.dict(os.environ,{'FM1_TRACE_RANGE':'bad'}):
            result=A.execute(self.native,{'binary':'/trusted/emulator'},directory,control=control,traced=traced,
                window=WINDOW,discovery_anchor=self.anchor if discovery else None,functions=self.functions,
                unsized=self.unsized,instructions=self.instructions,basis_audio=basis_audio,basis_image=basis_image)
        return result,dict(seen,directory=directory)

    def test_execute_preserves_recipe_clears_inherited_trace_and_checks_basis(self):
        result,seen=self.execute_fixture(traced=False)
        self.assertFalse(result['traced']); self.assertNotIn('FM1_TRACE_RANGE',seen['env'])
        self.assertEqual(seen['argv'][-2:],['--keys','700-1000:n7'])
        self.assertEqual(len(seen['watched']),2)
        _,seen=self.execute_fixture(control=True)
        self.assertNotIn('--keys',seen['argv'])
        self.assertEqual(seen['env']['FM1_TRACE_RANGE'],f'{START}:{START+A.WIDTH}')
        result,seen=self.execute_fixture(traced=False,discovery=True)
        self.assertEqual(seen['env']['FM1_BREAK_MAX'],'16'); self.assertIn('discovery',result)

    def test_execute_failure_empty_partial_pcm_image_and_basis_refusals(self):
        for change in ('child failure','child timeout','empty','partial','stderr','PCM','image','basis PCM','basis image'):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.execute_fixture(change=change)

    def capture_fixture(self, *, wrong_revision=False, change_at_end=None, change_before_reread=None):
        replay=self.root/'replay'; replay.mkdir()
        proof=replay/'build/proof'; proof.mkdir(parents=True)
        receipt_path=replay/'build/receipt.json'; receipt={'binary':'/trusted/emulator','binary_sha256':'a'*64}
        receipt_path.write_text(json.dumps(receipt))
        native_root=self.root/'producer'; (native_root/'build').mkdir(parents=True)
        native=dict(self.native,root=str(native_root),report={'build_identity':{'revision':'wrong' if wrong_revision else A.NATIVE_REVISION}},binding={})
        execution,_=A.R.parse_log(F.transcript(rows=False),traced=False,break_pc=F.PC)
        basis_row={'audio':{'peak_pcm16':1},'image':{'xip_sha256':'b'*64}}
        summary={'native':native,'emulator_receipt':str(receipt_path),'runs':[
            {'directory':'held-key-workload-trace-1',**basis_row},
            {'directory':'held-key-control-trace-1',**basis_row,'audio':{'peak_pcm16':0}}]}
        (proof/'summary.json').write_text(json.dumps(summary))
        (native_root/'build/felucca.dis').write_text('fixture listing')
        calls=[]; self.child_calls=calls; changed=[False]; actual_digest=A.R.digest
        def basis(*args):
            out=args[-1]; out.mkdir(); symbols=out/'symbols.stdout'; symbols.write_text('fixture symbols')
            path=out/'hotspots.json'; path.write_text(json.dumps({'status':'complete','input_sha256':{
                str(proof/'summary.json'):A.R.digest(proof/'summary.json'),str(receipt_path):A.R.digest(receipt_path)},
                'symbol_table_sha256':A.R.digest(symbols)}))
            if change_before_reread:
                target=proof/'summary.json' if change_before_reread == 'summary' else receipt_path
                target.write_bytes(target.read_bytes()+b' ')
            return path
        def execute(native,receipt,directory,**kw):
            calls.append((directory.name,kw))
            row={'control':kw['control'],'traced':kw.get('traced',False),'audio':kw['basis_audio'],
                 'image':kw['basis_image'],'execution':dict(execution),'process':{'wall_seconds':1}}
            if row['traced']:
                row['execution'].update(trace_rows=A.WIDTH,trace_sha256='c'*64)
                row['attribution']={'fixture':'complete attribution'}
            if 'discovery_anchor' in kw:
                row['discovery']={'window':list(WINDOW)}
            return row
        def final_check(*args):
            if change_at_end == 'basis': (proof/'summary.json').write_text('{}')
            if change_at_end == 'native': raise ValueError('native source inputs changed during replay')
            changed[0]=True
        def digest(path):
            target=ROOT/'tools'/('native_audio_window.py' if change_at_end == 'driver' else 'native_hotspots.py')
            return 'changed' if changed[0] and change_at_end in ('driver','helper') and path == target else actual_digest(path)
        out=self.root/'capture'
        with patch('builtins.print'), patch.object(A.H,'report',side_effect=basis), patch.object(A.H,'ranges',return_value=inventory()), \
             patch.object(A.H,'source_context'), patch.object(A.R,'check_native_unchanged',side_effect=final_check), \
             patch.object(A.R,'capture',return_value={}), patch.object(A,'execute',side_effect=execute), \
             patch.object(A,'validate_output',return_value={}), patch.object(A.R,'digest',side_effect=digest):
            path=A.capture(proof,replay,native_root,out)
        return json.loads(path.read_text()),calls

    def test_complete_seven_child_plan_and_reused_repeat_controls(self):
        result,calls=self.capture_fixture()
        self.assertEqual(result['status'],'passed'); self.assertEqual(len(calls),7)
        self.assertEqual([name for name,_ in calls],['discovery','workload-trace-1','workload-plain',
            'workload-trace-2','control-trace-1','control-plain','control-trace-2'])
        self.assertEqual(len(result['comparisons']),2)
        self.assertEqual(calls[1][1]['window'],list(WINDOW))
        self.assertEqual(calls[-1][1]['window'],list(WINDOW))

    def test_verified_basis_digest_cannot_be_refreshed_by_a_changed_reread(self):
        for name in ('summary','receipt'):
            with self.subTest(name=name):
                other=AudioWindow(); other.setUp()
                try:
                    with self.assertRaisesRegex(ValueError,'verified basis changed before capture'):
                        other.capture_fixture(change_before_reread=name)
                    self.assertEqual(other.child_calls,[])
                    self.assertEqual(json.loads((other.root/'capture/summary.json').read_text())['status'],'incomplete')
                finally: other.doCleanups()

    def test_unsupported_source_and_final_changed_inputs_leave_incomplete(self):
        with self.assertRaisesRegex(ValueError,'audited ce5'):
            self.capture_fixture(wrong_revision=True)
        self.assertEqual(json.loads((self.root/'capture/summary.json').read_text())['status'],'incomplete')
        # Separate fixture roots keep every attempted capture's output immutable.
        for change in ('basis','native','helper','driver'):
            with self.subTest(change=change):
                other=AudioWindow(); other.setUp()
                try:
                    with self.assertRaises(ValueError): other.capture_fixture(change_at_end=change)
                    self.assertEqual(json.loads((other.root/'capture/summary.json').read_text())['status'],'incomplete')
                finally: other.doCleanups()


    def test_saved_outputs_are_reparsed_and_each_changed_artifact_refuses(self):
        row,seen=self.execute_fixture()
        directory=seen['directory']
        def validate():
            return A.validate_output(directory,row,self.native,WINDOW,self.functions,self.unsized,self.instructions)
        self.assertEqual(len(validate()),7)
        for name in ('result.json','child.process.json','child.stdout','child.stderr','trace.txt','audio.wav','xip.bin'):
            path=directory/name; original=path.read_bytes(); path.write_bytes(original+b'changed')
            try:
                with self.subTest(name=name),self.assertRaises((ValueError,json.JSONDecodeError)):
                    validate()
            finally: path.write_bytes(original)
        for kwargs in ({'traced':False},{'traced':False,'discovery':True},{'control':True}):
            row,seen=self.execute_fixture(**kwargs)
            self.assertEqual(len(A.validate_output(seen['directory'],row,self.native,WINDOW,
                self.functions,self.unsized,self.instructions)),7)

    def test_basis_verifier_failure_stops_before_discovery(self):
        out=self.root/'refused'
        with patch.object(A.H,'report',side_effect=ValueError('receipt/source/basis refusal')), \
             patch.object(A,'execute') as child:
            with self.assertRaisesRegex(ValueError,'receipt/source/basis refusal'):
                A.capture(self.root/'proof',self.root/'replay',self.root/'native',out)
            child.assert_not_called()
        self.assertEqual(json.loads((out/'summary.json').read_text())['status'],'incomplete')

    def test_repeat_pcm_terminal_and_trace_mutations_use_original_authority(self):
        row={'audio':{},'image':{},'execution':dict(A.R.parse_log(F.transcript(rows=False),traced=False,break_pc=F.PC)[0])}
        for mutate in ('audio','image','interrupts','trace_sha256'):
            other=copy.deepcopy(row)
            if mutate in ('audio','image'): other[mutate]['changed']=True
            else: other['execution'][mutate]='changed'
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                A.R.compare_runs(row,other,same_trace=True)

    def test_archive_entry_refuses_cached_helper_before_help(self):
        tree=self.root/'archive'; tools=tree/'tools'; tools.mkdir(parents=True)
        (tree/'SOURCE-PINS.json').write_text('{}')
        entry=tools/'native_audio_window.py'; source=Path(A.__file__).read_text(); entry.write_text(source)
        marker=tree/'executed'; helper=tools/'build_report.py'
        helper.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\nraise SystemExit("cached marker")\n')
        py_compile.compile(str(helper),cfile=str(tools/'build_report.pyc'),doraise=True); helper.unlink()
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')}
        def run():
            return subprocess.run([sys.executable,entry,'--help'],cwd=tree,env=env,capture_output=True,timeout=5)
        refused=run(); self.assertNotEqual(refused.returncode,0)
        self.assertIn(b'requires a Git checkout',refused.stderr); self.assertFalse(marker.exists())
        # Causal bypass of only the early guard executes the identical cached helper.
        entry.write_text('import argparse'+source.split('import argparse',1)[1])
        old=run(); self.assertIn(b'cached marker',old.stderr); self.assertTrue(marker.exists())

    def test_cli_refuses_partial_or_oversized_report_status(self):
        path=self.root/'status.json'; path.write_text('{"status":"incomplete"}')
        with patch('builtins.print'), patch.object(A,'capture',return_value=path), patch.object(sys,'argv',[
                'native_audio_window','--proof',str(self.root),'--replay-root',str(self.root),
                '--native-root',str(self.root),'--out',str(self.root/'out')]):
            self.assertEqual(A.main(),1)


if __name__=='__main__':
    unittest.main()
