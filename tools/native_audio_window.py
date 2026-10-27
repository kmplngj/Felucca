#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Capture one source-qualified analog/audio window without changing PR733/738."""
import os as _source_os
if _source_os.path.isfile(_source_os.path.join(_source_os.path.dirname(
        _source_os.path.dirname(_source_os.path.realpath(__file__))), 'SOURCE-PINS.json')):
    raise SystemExit('native audio-window capture requires a Git checkout')

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import build_report
import emulator_trace
import native_emulator_replay as R
import native_hotspots as H

ROOT = Path(__file__).resolve().parents[1]
NATIVE_REVISION = 'ce5f4f5f83abee570bdf9141e8f8ec16aaacdd88'
WIDTH = 8192
FIRST_INPUT_SLOT = 700 * 240000  # Supported pinned one-core model; not physical cycles.
MAX_HITS = 16
IRQ_STACK = '[3]'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def select_anchor(functions, name):
    matches = [f for f in functions if name in f['names']]
    require(len(matches) == 1, 'missing/ambiguous supported DSP symbol: ' + name)
    require(matches[0]['section'] == '.text' and matches[0]['size_bytes'] > 0,
            'unsupported DSP symbol boundary')
    return matches[0]


def discovery_observation(data, native, anchor):
    require(data and data.endswith(b'\n'), 'empty/partial discovery transcript')
    lines = data.decode('ascii').splitlines()
    hits = []
    for line in lines:
        if not line.startswith('break '):
            continue
        match = R.BREAK.fullmatch(line)
        require(match is not None and int(match[1], 16) == anchor['address'],
                'unexpected discovery entry record')
        registers = [int(n, 16) for n in match[3].split(', ')]
        irq = re.search(r'irq_levels=(\[[0-7, ]*\]) ', line)[1]
        slot = int(match[2])
        require(len(registers) == 12 and registers[3] == 32 and irq == IRQ_STACK,
                'unsupported render entry arguments/IRQ stack')
        require(0 < slot <= R.STEPS and (not hits or slot > hits[-1]['slot']),
                'duplicate/reordered/out-of-run discovery slot')
        hits.append({'slot': slot, 'pc': int(match[1], 16), 'irq_stack_pre_dispatch': irq,
                     'registers': registers})
    require(0 < len(hits) <= MAX_HITS, 'missing or excessive discovery entries')
    candidates = [h for h in hits if h['slot'] >= FIRST_INPUT_SLOT]
    require(candidates, 'no supported render entry after held-key input')
    start = candidates[0]['slot']
    require(start + WIDTH <= R.STEPS + 1, 'discovered window exceeds finite run')
    # These are separately validated render-entry observations, not MIDI records.
    # Preserve the original bytes; normalize only those known records for the
    # existing complete terminal/audio validator, without duplicating its grammar.
    terminal_data = ('\n'.join(l for l in lines if not l.startswith('break ')) + '\n').encode()
    execution, _ = R.parse_log(terminal_data, traced=False, break_pc=native['break_pc'])
    return {'candidate': candidates[0], 'entries': hits, 'window': [start, start + WIDTH],
            'execution': execution, 'limit': 'pre-dispatch candidate; actual trace must independently qualify'}


def qualify_trace(trace, window, anchor, functions, unsized, instructions, *, control):
    require(isinstance(window, (tuple, list)) and len(window) == 2 and
            all(type(n) is int for n in window) and 0 < window[0] < window[1] <= R.STEPS + 1 and
            window[1] - window[0] == WIDTH, 'invalid bounded audio window')
    rows = trace.decode('ascii').splitlines()
    require(len(rows) == WIDTH and trace.endswith(b'\n'), 'incomplete audio trace window')
    matches = [R.TRACE.fullmatch(row) for row in rows]
    require(all(matches), 'malformed audio trace')
    require([int(m[1]) for m in matches] == list(range(*window)), 'audio window slot mismatch')
    if not control:
        require(int(matches[0][3], 16) == anchor['address'],
                'actual post-dispatch first PC differs from discovery candidate')
        require(all(m[5] == '3' for m in matches), 'unsupported actual audio IRQ stack')
    attribution = H.attribute(trace, functions, unsized, instructions)
    require(attribution['status'] == 'complete' and attribution['attributed_instructions'] == WIDTH,
            'audio window has unknown/ambiguous attribution')
    if not control:
        require(any('analog_render_1' in s['names'] and s['guest_instructions'] > 0
                    for s in attribution['symbols']), 'window contains no decoded analog_render_1 work')
    return attribution


def execute(native, receipt, directory, *, control, traced=False, window=None,
            discovery_anchor=None, functions=None, unsized=None, instructions=None, basis_audio=None, basis_image=None):
    directory.mkdir()
    wav, xip = directory / 'audio.wav', directory / 'xip.bin'
    env = {k: v for k, v in os.environ.items() if not k.startswith('FM1_')}
    require(not any(env.get(k) for k in build_report.HOST_INJECTION_ENV), 'host loader injection is unsupported')
    env.update(FM1_FWSC_XIP=str(xip), FM1_BREAK_MAX=str(MAX_HITS if discovery_anchor else 9))
    if traced:
        env['FM1_TRACE_RANGE'] = ':'.join(map(str, window))
    break_pc = discovery_anchor['address'] if discovery_anchor else native['break_pc']
    argv = [receipt['binary'], '--fwsc', native['package'], '--steps', str(R.STEPS),
            '--break-pc', hex(break_pc), '--wav', str(wav)]
    if not control:
        argv += ['--keys', R.CASES['held-key']]
    process = R.capture(argv, directory, env, directory / 'child',
                        watched=((wav, R.MAX_WAV), (xip, R.MAX_XIP)))
    require(not (directory / 'child.stderr').read_bytes(), 'unexpected emulator stderr')
    stdout = (directory / 'child.stdout').read_bytes()
    observation = discovery_observation(stdout, native, discovery_anchor) if discovery_anchor else None
    if observation:
        execution, trace = observation['execution'], b''
    else:
        execution, trace = R.parse_log(stdout, traced=traced, window=tuple(window), break_pc=break_pc)
    image = R.check_image(xip, Path(native['root']) / 'build/felucca.bin')
    require(image == basis_image, 'decoded image differs from the verified original basis')
    audio = R.read_pcm(wav, execution['audio_frames'])
    require(audio == basis_audio, 'whole PCM differs from the verified original basis')
    require(audio['peak_pcm16'] == 0 if control else audio['peak_pcm16'] > 0,
            'silent-control/nonzero-workload mismatch')
    (directory / 'trace.txt').write_bytes(trace)
    result = {'control': control, 'traced': traced, 'process': process,
              'execution': execution, 'audio': audio, 'image': image}
    if observation:
        result['discovery'] = observation
    elif traced:
        result['attribution'] = qualify_trace(trace, window, select_anchor(functions, 'analog_render'),
                                             functions, unsized, instructions, control=control)
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def validate_output(directory, row, native, window, functions, unsized, instructions):
    """Re-read the fixed owned output set; reuse the original evidence parsers."""
    bindings = {}
    require(H.read_json(directory, 'result.json', bindings) == row, 'saved audio result changed')
    process = H.read_json(directory, 'child.process.json', bindings, 16 * 1024)
    require(process == row['process'], 'saved audio process changed')
    stdout = H.checked_file(directory, 'child.stdout', R.MAX_LOG, bindings)
    stderr = R.build_manifest.file_at(directory, 'child.stderr')
    require(stderr.stat().st_size == 0, 'unexpected saved audio stderr')
    bindings[str(stderr)] = R.digest(stderr)
    require(bindings[str(directory / 'child.stdout')] == process['stdout_sha256'] and
            bindings[str(stderr)] == process['stderr_sha256'], 'saved audio child log digest mismatch')
    if 'discovery' in row:
        observed = discovery_observation(stdout, native, select_anchor(functions, 'analog_render'))
        require(observed == row['discovery'], 'saved render discovery changed')
        execution, trace = observed['execution'], b''
    else:
        execution, trace = R.parse_log(stdout, traced=row['traced'], window=tuple(window), break_pc=native['break_pc'])
    saved_trace = R.build_manifest.file_at(directory, 'trace.txt')
    require(saved_trace.stat().st_size <= R.MAX_LOG and saved_trace.read_bytes() == trace,
            'saved audio trace changed')
    bindings[str(saved_trace)] = R.digest(saved_trace)
    for name, limit in (('audio.wav', R.MAX_WAV), ('xip.bin', R.MAX_XIP)):
        H.checked_file(directory, name, limit, bindings)
    require(build_report.canonical(execution) == build_report.canonical(row['execution']) and
            R.read_pcm(directory / 'audio.wav', execution['audio_frames']) == row['audio'] and
            R.check_image(directory / 'xip.bin', Path(native['root']) / 'build/felucca.bin') == row['image'],
            'saved audio evidence changed')
    if row['traced']:
        require(qualify_trace(trace, window, select_anchor(functions, 'analog_render'),
                              functions, unsized, instructions, control=row['control']) == row['attribution'],
                'saved audio attribution changed')
    return bindings


def capture(proof, replay_root, native_root, out):
    out = emulator_trace.ignored_path(out)
    require(out != ROOT / 'build' and not out.exists(), 'output must be a new ignored build subdirectory')
    require(not any(out.is_relative_to(p) or p.is_relative_to(out) for p in (proof, replay_root, native_root)),
            'output overlaps an input context')
    out.mkdir(parents=True)
    summary = {'schema_version': 1, 'kind': 'felucca-analog-first-window', 'status': 'incomplete',
               'driver_sha256': R.digest(Path(__file__)), 'recipe': 'held-n7-analog-first-v1',
               'steps': R.STEPS, 'runs': [], 'comparisons': [],
               'limits': ['Source-qualified ce5 baseline and pinned one-core emulator only',
                          'Partial audio/DSP window; not a whole ISR, function-call or physical-cycle measurement',
                          'Discovery breakpoints precede IRQ dispatch; actual traced PC/stack is authoritative',
                          'Trusted unsigned local artifacts; no independent execution attestation',
                          'No generic routing, mixed recipe, nested-IRQ accounting or device qualification']}
    path = out / 'summary.json'
    try:
        # Reuse the full original saved-basis admission/report, not another authority.
        basis_path = H.report(proof, replay_root, native_root, out / 'basis-validation')
        basis = json.loads(basis_path.read_text())
        require(basis['status'] == 'complete', 'original basis attribution is unavailable')
        bindings = dict(basis['input_sha256'])
        original = H.read_json(proof, 'summary.json', bindings)
        native = original['native']
        require(native['report']['build_identity']['revision'] == NATIVE_REVISION,
                'audio recipe is qualified only for the audited ce5 native baseline')
        receipt_path = Path(original['emulator_receipt'])
        receipt = H.read_json(replay_root, str(receipt_path.relative_to(replay_root)), bindings)
        symbols = (basis_path.parent / 'symbols.stdout').read_text()
        require(R.digest(basis_path.parent / 'symbols.stdout') == basis['symbol_table_sha256'],
                'basis symbol output changed')
        listing = (native_root / 'build/felucca.dis').read_text()
        functions, unsized, instructions = H.ranges(symbols, listing)
        anchor = select_anchor(functions, 'analog_render')
        select_anchor(functions, 'analog_render_1')
        basis_runs = {row['directory']: row for row in original['runs']}
        workload_audio = basis_runs['held-key-workload-trace-1']['audio']
        control_audio = basis_runs['held-key-control-trace-1']['audio']
        basis_image = basis_runs['held-key-workload-trace-1']['image']
        summary.update(native_identity=native['report']['build_identity'], native_binding=native['binding'],
                       original_proof=str(proof), original_summary_sha256=R.digest(proof / 'summary.json'),
                       original_verifier_root=str(replay_root), original_verifier_revision=H.REPLAY_REVISION,
                       emulator_binary_sha256=receipt['binary_sha256'],
                       helper_sha256={name: R.digest(ROOT / 'tools' / name) for name in
                                      ('native_emulator_replay.py', 'native_hotspots.py', 'emulator_trace.py')},
                       basis_report_sha256=R.digest(basis_path), input_sha256=bindings)
        print('audio window: discovery', flush=True)
        discovered = execute(native, receipt, out / 'discovery', control=False,
                             discovery_anchor=anchor, basis_audio=workload_audio, basis_image=basis_image)
        summary['discovery'] = discovered
        window = discovered['discovery']['window']
        summary['trace_window'] = window
        summary['anchor'] = {'names': anchor['names'], 'start': anchor['address'],
                             'end_exclusive': anchor['address'] + anchor['size_bytes'],
                             'required_model_irq_stack': IRQ_STACK}
        for control in (False, True):
            group = []
            for label, traced in (('trace-1', True), ('plain', False), ('trace-2', True)):
                name = ('control-' if control else 'workload-') + label
                print('audio window: ' + name, flush=True)
                row = execute(native, receipt, out / name, control=control, traced=traced, window=window,
                              functions=functions, unsized=unsized, instructions=instructions,
                              basis_audio=control_audio if control else workload_audio, basis_image=basis_image)
                summary['runs'].append({'directory': name, **row})
                group.append(row)
                path.write_text(json.dumps(summary, indent=2) + '\n')
            if not control:
                R.compare_runs(discovered, group[0], same_trace=False)
            R.compare_runs(group[0], group[2], same_trace=True)
            R.compare_runs(group[0], group[1], same_trace=False)
            require(group[0]['attribution'] == group[2]['attribution'], 'repeated audio attribution differs')
            times = [r['process']['wall_seconds'] for r in group]
            summary['comparisons'].append({'control': control, 'trace_pcm_terminal_repeat': True,
                'original_basis_whole_pcm_match': True, 'trace_wall_seconds': [times[0], times[2]],
                'plain_wall_seconds': times[1], 'mean_trace_wall_ratio': (times[0] + times[2]) / (2 * times[1]),
                'wall_limit': 'Small noisy host IO/scheduling observation; not physical timing or speedup'})
        captured_bindings = {}
        for name, row in [('discovery', discovered)] + [(r['directory'], {k:v for k,v in r.items() if k != 'directory'})
                                                        for r in summary['runs']]:
            captured_bindings.update(validate_output(out / name, row, native, window, functions, unsized, instructions))
        summary['capture_file_sha256'] = captured_bindings
        R.check_native_unchanged(native_root, native)
        H.source_context(replay_root)
        summary['final_emulator_verification'] = R.capture([sys.executable, replay_root / 'tools/emulator_trace.py', 'verify', receipt_path],
                  replay_root, os.environ.copy(), out / 'final-emulator-verification')
        require(all(R.digest(Path(name)) == sha for name, sha in bindings.items()), 'original basis changed during capture')
        require(R.digest(basis_path) == summary['basis_report_sha256'] and
                R.digest(basis_path.parent / 'symbols.stdout') == basis['symbol_table_sha256'],
                'basis report/symbol data changed during capture')
        require(all(R.digest(ROOT / 'tools' / name) == sha for name, sha in summary['helper_sha256'].items()),
                'helper source changed during capture')
        require(all(R.digest(Path(name)) == sha for name, sha in captured_bindings.items()),
                'captured output changed during final checks')
        require(R.digest(Path(__file__)) == summary['driver_sha256'], 'audio driver changed during capture')
        summary['status'] = 'passed'
    except BaseException as error:
        summary['error'] = str(error)
        raise
    finally:
        encoded = json.dumps(summary, indent=2) + '\n'
        if len(encoded.encode()) > R.MAX_LOG:
            encoded = json.dumps({'status': 'incomplete', 'error': 'audio report exceeds output bound'}) + '\n'
        path.write_text(encoded)
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proof', type=Path, required=True)
    p.add_argument('--replay-root', type=Path, required=True)
    p.add_argument('--native-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    try:
        path = capture(args.proof.resolve(), args.replay_root.resolve(), args.native_root.resolve(), args.out)
        print(path)
        return 0 if json.loads(path.read_text())['status'] == 'passed' else 1
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, subprocess.SubprocessError) as error:
        print('native audio window: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
