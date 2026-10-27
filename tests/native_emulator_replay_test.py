#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable replay refusal contracts; real native acceptance is explicitly opt-in."""
import json
import os
from pathlib import Path
import py_compile
import subprocess
import signal
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import native_emulator_replay as R

WINDOW = (100, 103)
PC = 0x02005230
STEPS = 264000000


def transcript(rows=True, notes=()):
    result = ''
    for ch, note, velocity in notes:
        regs = ', '.join(format(v, 'x') for v in (ch, note, velocity, *([0] * 9)))
        result += f'break c0 pc={PC:#010x} [180000001] sp=0x1c7b000 rets=0x2005800 irq_levels=[1] r0-11=[{regs}]\n'
    if rows:
        for slot in range(*WINDOW):
            result += f'T {slot} c0 0x02000120 goto_i irq=[] ie=false r0=0x1c7fc00 r1=0x0\n'
    result += (f'stopped after {STEPS} instructions (step limit, hist top-12 of 300 classes):\n'
               'time 1100 ms, 9215 interrupts, 318 audio halves (40704 samples)\n'
               'interrupts by source: c0 irq 63 x8907, c0 irq 11 x308\n'
               'wav: /ignored/audio.wav (0.92 s)\n'
               'lcd frames=37 inverted=true display_on=true\n')
    return result.encode()


def parse(data, **kw):
    return R.parse_log(data, traced=kw.pop('traced', True), window=WINDOW, steps=STEPS,
                       break_pc=PC, **kw)


class ReplayContracts(unittest.TestCase):
    def setUp(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='native-replay-contract-', dir=ROOT / 'build')
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def test_archive_entry_refuses_before_sourceless_cached_helper_executes(self):
        archive = self.out / 'unverified-archive'
        tools = archive / 'tools'
        tools.mkdir(parents=True)
        (archive / 'SOURCE-PINS.json').write_text('{}')
        entry = tools / 'native_emulator_replay.py'
        source = Path(R.__file__).read_text()
        entry.write_text(source)
        marker = self.out / 'unverified-helper-executed'
        helper = tools / 'build_manifest.py'
        helper.write_text('from pathlib import Path\nPath(' + repr(str(marker)) +
                          ').write_text("executed")\n'
                          'raise SystemExit("cached helper executed before CLI admission")\n')
        py_compile.compile(str(helper), cfile=str(tools / 'build_manifest.pyc'), doraise=True)
        helper.unlink()
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        def cli():
            return subprocess.run([sys.executable, str(entry), '--help'], cwd=archive,
                                  env=env, capture_output=True, text=True, timeout=10)
        refused = cli()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('native replay orchestration requires a clean committed Git checkout',
                      refused.stderr)
        self.assertFalse(marker.exists())
        # Bypass only the new startup refusal: this reconstructs the previous
        # entry, and the same sourceless cache must now execute its marker.
        start = source.index('import os as _source_os')
        end = source.index('import argparse', start)
        entry.write_text(source[:start] + source[end:])
        previous = cli()
        self.assertNotEqual(previous.returncode, 0)
        self.assertIn('cached helper executed before CLI admission', previous.stderr)
        self.assertTrue(marker.exists())

    def test_complete_trace_and_plain_terminal_are_distinct(self):
        result, rows = parse(transcript())
        self.assertEqual(result['trace_rows'], 3)
        self.assertEqual(result['retired_instructions'], STEPS)
        self.assertEqual(len(rows.splitlines()), 3)
        plain, data = parse(transcript(False), traced=False)
        self.assertEqual(plain['trace_rows'], 0)
        self.assertEqual(data, b'')
        with self.assertRaisesRegex(ValueError, 'empty, partial'):
            parse(transcript(False))
        with self.assertRaisesRegex(ValueError, 'empty, partial'):
            parse(transcript(), traced=False)

    def test_c1_output_path_tokens_are_not_execution_records(self):
        original, trace = parse(transcript())
        path = b'/home/c1/build/native-replay-c1/audio.wav'
        changed = transcript().replace(b'/ignored/audio.wav', path)
        changed = b'XIP window -> /home/c1/build/native-replay-c1/xip.bin\n' + changed
        actual, actual_trace = parse(changed)
        self.assertEqual(actual, original)
        self.assertEqual(actual_trace, trace)

    def test_empty_or_partial_transcript_is_refused(self):
        for data in (b'', transcript()[:-1], b'T 100 c0 0x02000120', transcript().split(b'stopped')[0]):
            with self.subTest(data=data[:25]), self.assertRaises(ValueError):
                parse(data)

    def test_missing_duplicate_reordered_outside_rows_are_refused(self):
        data = transcript()
        rows = data.splitlines(keepends=True)
        variants = (b''.join(rows[1:]), rows[0] + data, rows[1] + rows[0] + b''.join(rows[2:]),
                    data.replace(b'T 100 ', b'T 99 '), data.replace(b'T 102 ', b'T 103 '))
        for changed in variants:
            with self.subTest(data=changed[:80]), self.assertRaises(ValueError):
                parse(changed)

    def test_unknown_class_pc_malformed_and_multicore_are_refused(self):
        for old, new in ((b'goto_i', b'?'), (b'goto_i', b'invalid,class'),
                         (b'0x02000120', b'0x00000000'), (b' c0 ', b' c1 '),
                         (b'irq=[]', b'irq=[99]'), (b'r1=0x0', b'r1=garbage')):
            with self.subTest(new=new), self.assertRaises(ValueError):
                parse(transcript().replace(old, new))
        for prefix in (b'cpu1 released at step 5\n', b'c1 irq 63 prio 1 -> 0x02000120\n',
                       b'break c1 pc=0x02000120 [100]\n', b'halt: bad opcode\n'):
            with self.assertRaises(ValueError):
                parse(prefix + transcript())
        with self.assertRaises(ValueError):
            parse(transcript().replace(b'c0 irq 11 x308', b'c1 irq 11 x308'))

    def test_failed_empty_duplicate_and_inconsistent_terminal_are_refused(self):
        for old, new in ((b'step limit', b'halt'), (b'264000000 instructions', b'0 instructions'),
                         (b'1100 ms', b'900 ms'), (b'318 audio', b'0 audio'),
                         (b'40704 samples', b'40703 samples'), (b'display_on=true', b'display_on=false')):
            with self.subTest(new=new), self.assertRaises(ValueError):
                parse(transcript().replace(old, new))
        with self.assertRaises(ValueError):
            parse(transcript() + transcript(False))

    def test_malformed_or_extra_reserved_terminal_prefixes_are_refused(self):
        for extra in (b'stopped after 1 instructions (halt, hist top-1 of 1 classes):\n',
                      b'time CORRUPTED ms, 0 interrupts, 0 audio halves (0 samples)\n',
                      b'wav: cannot write ignored\n', b'lcd frames=garbage\n',
                      b'interrupts by source: broken\n'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse(transcript() + extra)
        with self.assertRaisesRegex(ValueError, 'IRQ source counts'):
            parse(transcript().replace(b'irq 11 x308', b'irq 11 x307'))

    def test_exact_four_channel_admission_uses_hex_registers(self):
        notes = R.expected_midi('mixed-uart', False)
        data, _ = parse(transcript(notes=notes), expected_notes=notes)
        self.assertEqual(data['admitted_midi_notes'], notes)
        for wrong in (notes[:-1], notes[::-1], [(0, 30, 64)] + notes[1:], notes + [notes[0]]):
            with self.subTest(notes=wrong), self.assertRaisesRegex(ValueError, 'admission mismatch'):
                parse(transcript(notes=wrong), expected_notes=notes)
        with self.assertRaisesRegex(ValueError, 'admission mismatch'):
            parse(transcript(notes=notes))

    def test_partial_or_wrong_admission_breakpoint_is_refused(self):
        notes = R.expected_midi('mixed-uart', False)
        for data in (transcript(notes=notes).replace(b'0x02005230', b'0x02005232'),
                     transcript(notes=notes).replace(b'0, 30, 64, 0, 0', b'0, 30, 64')):
            with self.assertRaises(ValueError):
                parse(data, expected_notes=notes)

    def test_invalid_window_is_refused(self):
        for window in ((0, 0), (200, 100), (STEPS, STEPS + 2), (1, 100000)):
            with self.subTest(window=window), self.assertRaises(ValueError):
                R.parse_log(transcript(), traced=True, window=window, steps=STEPS, break_pc=PC)

    def test_decoded_image_mismatch_or_empty_is_refused(self):
        app = self.out / 'app.bin'
        xip = self.out / 'xip.bin'
        app.write_bytes(b'app exact bytes')
        xip.write_bytes(b'\0' * 0x120 + app.read_bytes())
        self.assertTrue(R.check_image(xip, app)['app_matches_verified_bin'])
        xip.write_bytes(xip.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'differs'):
            R.check_image(xip, app)
        xip.write_bytes(b'')
        with self.assertRaises(ValueError):
            R.check_image(xip, app)

    def test_native_report_artifact_mismatch_is_refused(self):
        (self.out / 'build').mkdir()
        file = self.out / 'build/felucca.bin'
        file.write_bytes(b'native')
        (self.out / 'build/resource-report.json').write_text(json.dumps({'artifact_sha256': {'build/felucca.bin': R.digest(file)}}))
        original = R.native_binding(self.out)
        self.assertIn('build/felucca.bin', original['artifacts'])
        file.write_bytes(b'altered')
        with self.assertRaisesRegex(ValueError, 'image/artifact mismatch'):
            R.native_binding(self.out)

    def test_clean_producer_switch_or_input_change_is_refused(self):
        native = {'binding': {'artifacts': 'fixed'}, 'report': {
            'build_identity': {'revision': 'a' * 40}, 'input_sha256': {'source.c': 'old'}}}
        def original_git(root, *args):
            return 'a' * 40 if args[0] == 'rev-parse' else ''
        with patch.object(R, 'native_binding', return_value=native['binding']), \
             patch.object(R.emulator_trace, 'git', side_effect=original_git), \
             patch.object(R.build_report, 'input_hashes', return_value={'source.c': 'old'}):
            R.check_native_unchanged(self.out, native)
            with patch.object(R.emulator_trace, 'git', return_value='b' * 40):
                with self.assertRaisesRegex(ValueError, 'revision changed'):
                    R.check_native_unchanged(self.out, native)
            with patch.object(R.build_report, 'input_hashes', return_value={'source.c': 'changed'}):
                with self.assertRaisesRegex(ValueError, 'source inputs changed'):
                    R.check_native_unchanged(self.out, native)
            with patch.object(R.emulator_trace, 'git', side_effect=lambda root, *args:
                              'a' * 40 if args[0] == 'rev-parse' else ' M native.c'):
                with self.assertRaisesRegex(ValueError, 'producer changed'):
                    R.check_native_unchanged(self.out, native)

    def test_pcm_format_length_and_terminal_must_agree(self):
        path = self.out / 'audio.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((2, 2, 44100, 2, 'NONE', 'not compressed'))
            wav.writeframes(struct.pack('<hhhh', 0, 1, -5, 0))
        result = R.read_pcm(path, 2)
        self.assertEqual(result['peak_pcm16'], 5)
        self.assertEqual(result['nonzero_samples'], 2)
        with self.assertRaisesRegex(ValueError, 'frame count'):
            R.read_pcm(path, 3)
        raw = path.read_bytes()
        for changed in (raw[:-1], raw + b'junk', b''):
            path.write_bytes(changed)
            with self.assertRaises(ValueError):
                R.read_pcm(path, 2)

    def test_repeat_or_trace_changes_are_refused(self):
        execution, _ = parse(transcript())
        first = {'audio': {'pcm': 'same'}, 'image': {'xip': 'same'}, 'execution': execution}
        R.compare_runs(first, first, same_trace=True)
        for key in ('audio', 'image'):
            changed = dict(first, **{key: {'changed': True}})
            with self.assertRaises(ValueError):
                R.compare_runs(first, changed, same_trace=True)
        changed = dict(first, execution=dict(execution, trace_sha256='altered'))
        with self.assertRaisesRegex(ValueError, 'trace differs'):
            R.compare_runs(first, changed, same_trace=True)
        R.compare_runs(first, changed, same_trace=False)

    def child(self, script, **kwargs):
        return R.capture([sys.executable, '-c', script], self.out, os.environ.copy(),
                         self.out / 'child', **kwargs)

    def test_actual_failing_child_preserves_status(self):
        with self.assertRaisesRegex(ValueError, 'child failure'):
            self.child('import sys; print("partial"); sys.exit(7)')
        record = json.loads((self.out / 'child.process.json').read_text())
        self.assertEqual(record['returncode'], 7)
        self.assertEqual(record['status'], 'incomplete')

    def assert_descendant_terminated(self, pidfile):
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            # Linux and macOS ps both expose STAT. A zombie has stopped executing
            # even if the host's init has not reaped the orphan yet.
            status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                    capture_output=True, text=True, timeout=0.5)
            self.assertIn(status.returncode, (0, 1), status.stderr)
            self.assertFalse(status.stderr.strip(), status.stderr)
            state = status.stdout.strip()
            if not state or state.startswith('Z'):
                return
            time.sleep(0.02)
        self.fail(f'descendant {pid} still executing after capture cleanup')

    def cleanup_test_descendant(self, pidfile):
        # Keep cleanup independent of the capture implementation under test.
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_actual_timeout_kills_inherited_pipe_descendant(self):
        pidfile = self.out / 'descendant.pid'
        script = ('import subprocess,sys; from pathlib import Path; '
                  'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                  f'Path({str(pidfile)!r}).write_text(str(p.pid))')
        try:
            with self.assertRaisesRegex(ValueError, 'timeout'):
                self.child(script, timeout=1)
            self.assertLess(json.loads((self.out / 'child.process.json').read_text())['wall_seconds'], 3)
            self.assert_descendant_terminated(pidfile)
        finally:
            self.cleanup_test_descendant(pidfile)

    def test_exit_zero_leader_cannot_hide_a_devnull_descendant(self):
        pidfile = self.out / 'descendant.pid'
        script = ('import subprocess,sys; from pathlib import Path; '
                  'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],'
                  'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                  f'Path({str(pidfile)!r}).write_text(str(p.pid))')
        try:
            with self.assertRaisesRegex(ValueError, 'surviving process group'):
                self.child(script)
            record = json.loads((self.out / 'child.process.json').read_text())
            self.assertEqual(record['status'], 'incomplete')
            self.assertEqual(record['returncode'], 0)
            self.assert_descendant_terminated(pidfile)
        finally:
            self.cleanup_test_descendant(pidfile)

    def test_actual_stdout_or_stderr_overflow_is_bounded(self):
        for fd in (1, 2):
            with self.subTest(fd=fd), self.assertRaisesRegex(ValueError, 'log output exceeds'):
                self.child(f'import os; os.write({fd}, b"x"*8192)', limit=1024)
            self.assertLessEqual((self.out / ('child.stdout' if fd == 1 else 'child.stderr')).stat().st_size, 1024)

    def test_actual_output_file_overflow_is_refused(self):
        path = self.out / 'large.bin'
        with self.assertRaisesRegex(ValueError, 'output'):
            self.child(f'from pathlib import Path; Path({str(path)!r}).write_bytes(b"x"*256)', watched=((path, 128),))

    def test_closed_pipes_do_not_disable_live_output_bound(self):
        path = self.out / 'growing.bin'
        script = ('import os,time; from pathlib import Path; os.close(1); os.close(2); '
                  f'Path({str(path)!r}).write_bytes(b"x"*256); time.sleep(30)')
        with self.assertRaisesRegex(ValueError, 'output file exceeds bound'):
            self.child(script, timeout=1, watched=((path, 128),))
        self.assertLess(json.loads((self.out / 'child.process.json').read_text())['wall_seconds'], 0.5)

    def test_changed_emulator_receipt_is_refused_before_launch(self):
        receipt = self.out / 'receipt.json'
        receipt.write_text('{"schema_version":1,"status":"complete","kind":"altered"}')
        destination = self.out / 'new-output'
        with self.assertRaisesRegex(ValueError, 'build receipt'):
            R.replay(self.out / 'native-producer', receipt, destination)
        self.assertFalse(destination.exists())

    def test_successful_empty_child_does_not_establish_replay(self):
        process = self.child('pass')
        self.assertEqual(process['returncode'], 0)
        with self.assertRaisesRegex(ValueError, 'empty or partial'):
            parse((self.out / 'child.stdout').read_bytes())


if __name__ == '__main__':
    unittest.main()
