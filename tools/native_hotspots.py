#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Attribute bounded, revalidated PR733 native replay windows; never run firmware."""
import os as _source_os
if _source_os.path.isfile(_source_os.path.join(_source_os.path.dirname(
        _source_os.path.dirname(_source_os.path.realpath(__file__))), 'SOURCE-PINS.json')):
    raise SystemExit('native hotspot reporting requires a Git checkout')

import argparse
from collections import Counter
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path
import sys

import build
import build_report
import emulator_trace
import native_emulator_replay as replay
import target_frames

ROOT = Path(__file__).resolve().parents[1]
REPLAY_REVISION = '4ffca0afc71c0f347475370a5adb2c52441e47a2'
MAX_JSON = 512 * 1024
MAX_LISTING = 16 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def checked_file(root, name, limit, bindings):
    from build_manifest import file_at
    path = file_at(root, name)
    require(0 < path.stat().st_size <= limit, 'missing/empty/oversized input: ' + name)
    data = path.read_bytes()
    require(len(data) <= limit, 'input grew beyond bound: ' + name)
    bindings[str(path)] = hashlib.sha256(data).hexdigest()
    return data


def read_json(root, name, bindings, limit=MAX_JSON):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(checked_file(root, name, limit, bindings), object_pairs_hook=unique)


def source_context(root):
    require(not (root / 'SOURCE-PINS.json').exists(), 'replay verifier context must be Git')
    require(emulator_trace.git(root, 'rev-parse', '--show-toplevel') == str(root), 'invalid replay checkout root')
    require(emulator_trace.git(root, 'rev-parse', 'HEAD') == REPLAY_REVISION, 'unsupported replay verifier revision')
    require(not emulator_trace.git(root, 'status', '--porcelain=v1', '--untracked-files=all'), 'dirty replay verifier context')
    # Do not load code selected by a saved report. The caller supplies this trusted
    # context; its exact reviewed revision and relevant bytes must match our base.
    for name in ('native_emulator_replay.py', 'emulator_trace.py', 'build_report.py'):
        require(replay.digest(root / 'tools' / name) == replay.digest(ROOT / 'tools' / name),
                'replay verifier helper bytes differ: ' + name)


def validate_saved(proof, replay_root, native_root, out):
    source_context(replay_root)
    require(proof.is_relative_to(replay_root / 'build') and proof != replay_root / 'build',
            'proof must be inside explicit replay checkout build/')
    bindings = {}
    summary = read_json(proof, 'summary.json', bindings)
    require(isinstance(summary, dict) and type(summary.get('schema_version')) is int, 'invalid replay summary object/schema')
    require((summary.get('schema_version'), summary.get('kind'), summary.get('status')) ==
            (1, 'felucca-native-replay-evidence', 'passed'), 'unsupported/incomplete replay summary')
    require(summary['driver_sha256'] == replay.digest(ROOT / 'tools/native_emulator_replay.py') and
            summary['steps'] == replay.STEPS and summary['trace_window'] == list(replay.WINDOW),
            'unsupported replay driver/window')
    require(summary['native']['root'] == str(native_root), 'explicit native root differs from saved producer')
    receipt_path = Path(summary['emulator_receipt'])
    require(receipt_path.is_relative_to(replay_root / 'build'), 'emulator receipt outside explicit verifier context')
    receipt = read_json(replay_root, str(receipt_path.relative_to(replay_root)), bindings)
    require(bindings[str(receipt_path)] == summary['emulator_receipt_sha256'], 'emulator receipt digest mismatch')
    # Preserve the original helper's ignored-path contract in its original clean
    # checkout. Do not relocate/rewrite receipt paths to fit this consumer tree.
    process = replay.capture([sys.executable, replay_root / 'tools/emulator_trace.py', 'verify', receipt_path],
                             replay_root, os.environ.copy(), out / 'emulator-verification')
    require((out / 'emulator-verification.stdout').read_text().startswith(
            'verified ' + summary['emulator_binary_sha256'] + ' '), 'emulator receipt verification missing')
    require(receipt['binary_sha256'] == summary['emulator_binary_sha256'], 'emulator binary differs from replay')
    native = replay.native_inputs(native_root, out)
    require(native['binding'] == summary['native']['binding'] and native['report'] == summary['native']['report'] and
            native['break_pc'] == summary['native']['break_pc'], 'native evidence differs from saved replay')
    require(read_json(proof, 'native-resource-report.json', bindings) == native['report'], 'saved native report mismatch')
    expected = [(case, control, label, traced) for case in replay.CASES for control in (True, False)
                for label, traced in (('trace-1', True), ('plain', False), ('trace-2', True))]
    runs = summary.get('runs')
    require(isinstance(runs, list) and len(runs) == len(expected), 'incomplete replay run plan')
    traces, groups, timings = {}, {}, []
    for row, (case, control, label, traced) in zip(runs, expected):
        directory = case + ('-control-' if control else '-workload-') + label
        require((row['directory'], row['case']) == (directory, case) and
                row['control'] is control and row['traced'] is traced, 'unexpected/reordered replay run')
        saved = read_json(proof, directory + '/result.json', bindings, 64 * 1024)
        require(saved == {k: v for k, v in row.items() if k != 'directory'}, 'saved run result mismatch')
        proc = read_json(proof, directory + '/child.process.json', bindings, 16 * 1024)
        require(proc == row['process'] and proc['status'] == 'complete' and proc['returncode'] == 0 and
                proc['timeout_seconds'] == replay.TIMEOUT and proc['log_limit_bytes'] == replay.MAX_LOG,
                'failed/incomplete child receipt')
        require(type(proc['wall_seconds']) in (int, float) and math.isfinite(proc['wall_seconds']) and
                0 < proc['wall_seconds'] <= replay.TIMEOUT + 1, 'invalid child wall observation')
        base = proof / directory
        argv = [receipt['binary'], '--fwsc', native['package'], '--steps', str(replay.STEPS),
                '--break-pc', hex(native['break_pc']), '--wav', str(base / 'audio.wav')]
        if not control:
            argv += ['--keys', replay.CASES[case]]
        require(proc['argv'] == argv, 'saved child invocation differs from fixed recipe')
        stdout = checked_file(proof, directory + '/child.stdout', replay.MAX_LOG, bindings)
        # Successful pinned CLI stderr is empty; permit only that exact empty file.
        from build_manifest import file_at
        stderr = file_at(proof, directory + '/child.stderr')
        require(stderr.stat().st_size == 0, 'unexpected child stderr')
        bindings[str(stderr)] = replay.digest(stderr)
        require(len(stdout) <= replay.MAX_LOG and hashlib.sha256(stdout).hexdigest() == proc['stdout_sha256'] and
                bindings[str(stderr)] == proc['stderr_sha256'], 'saved child log digest mismatch')
        execution, trace = replay.parse_log(stdout, traced=traced, window=tuple(summary['trace_window']), break_pc=native['break_pc'],
                                          expected_notes=replay.expected_midi(case, control))
        trace_path = file_at(proof, directory + '/trace.txt')
        require(trace_path.stat().st_size <= replay.MAX_LOG and trace_path.read_bytes() == trace,
                'persisted trace differs from complete child transcript')
        bindings[str(trace_path)] = replay.digest(trace_path)
        checked_file(proof, directory + '/xip.bin', replay.MAX_XIP, bindings)
        checked_file(proof, directory + '/audio.wav', replay.MAX_WAV, bindings)
        image = replay.check_image(base / 'xip.bin', native_root / 'build/felucca.bin')
        audio = replay.read_pcm(base / 'audio.wav', execution['audio_frames'])
        require(build_report.canonical(execution) == build_report.canonical(row['execution']) and
                image == row['image'] and audio == row['audio'], 'recomputed native run evidence differs')
        require(audio['peak_pcm16'] == 0 if control else audio['peak_pcm16'] > 0, 'audio control/workload mismatch')
        group = case + ('-control' if control else '-workload')
        groups.setdefault(group, []).append(row)
        if traced:
            traces.setdefault(group, []).append(trace)
    for group, rows in groups.items():
        replay.compare_runs(rows[0], rows[2], same_trace=True)
        replay.compare_runs(rows[0], rows[1], same_trace=False)
        durations = [r['process']['wall_seconds'] for r in rows]
        timings.append({'group': group, 'trace_wall_seconds': [durations[0], durations[2]],
                        'plain_wall_seconds': durations[1],
                        'mean_trace_wall_ratio': (durations[0] + durations[2]) / (2 * durations[1])})
    return native, traces, bindings, timings, process


def ranges(symbols, listing):
    require(len(symbols.encode()) <= replay.MAX_LOG and len(listing.encode()) <= MAX_LISTING,
            'symbol/disassembly input exceeds bound')
    require(len(symbols.splitlines()) <= 10000 and len(listing.splitlines()) <= 300000,
            'symbol/disassembly row limit exceeded')
    require(sum('F' in line.split()[1:-3] for line in symbols.splitlines()) <= 4096,
            'function range limit exceeded')
    inventory = target_frames.inventory(symbols, listing)
    rows, errors = build.disassembly_rows(listing, 'app')
    require(not errors, 'malformed disassembly')
    # Same undecoded/data categories as the existing frame inventory; never infer
    # a decoded instruction from an address/byte row alone.
    instructions = {int(row[1], 16): {'text': row[3].strip(), 'bytes': len(bytes.fromhex(row[2]))}
                    for row in rows if not build.objdump_data_row(row[0]) and not
                    re.match(r'^(?:\.\w+|\(bad\)|unknown(?:\b|_)|<)', row[3].strip(), re.I)}
    # Frame-analysis status is intentionally not a hotspot metric. Only the shared
    # parser's actual sized ranges/alias groups and explicit unsized labels are used.
    return inventory['functions'], inventory['unscored_code_symbols'], instructions


def attribute(trace, functions, unsized, instructions):
    lines = trace.decode('ascii').splitlines()
    require(0 < len(lines) <= 65536 and trace.endswith(b'\n'), 'empty/partial/oversized trace')
    counts, classes, entries, unknown = Counter(), Counter(), Counter(), Counter()
    per_class = {}
    for line in lines:
        match = replay.TRACE.fullmatch(line)
        require(match is not None and match[2] == '0' and
                match[4] != '?' and match[4].replace('_', '').isalnum(), 'malformed/unsupported trace row')
        pc, name = int(match[3], 16), match[4]
        classes[name] += 1
        hits = [i for i, f in enumerate(functions) if f['address'] <= pc < f['address'] + f['size_bytes']]
        if pc not in instructions:
            unknown[(pc, 'not a decoded instruction start')] += 1
        elif len(hits) > 1:
            unknown[(pc, 'ambiguous overlapping ranges')] += 1
        elif not hits:
            zero = any(f['address'] == pc and f['size_bytes'] == 0 for f in unsized)
            unknown[(pc, 'zero-sized label without range' if zero else 'no sized function range')] += 1
        elif pc + instructions[pc]['bytes'] > functions[hits[0]]['address'] + functions[hits[0]]['size_bytes']:
            unknown[(pc, 'instruction crosses function boundary')] += 1
        else:
            index = hits[0]
            counts[index] += 1
            entries[index] += pc == functions[index]['address']
            per_class.setdefault(index, Counter())[name] += 1
    symbols = []
    for index, count in sorted(counts.items(), key=lambda item: (-item[1], functions[item[0]]['address'])):
        f = functions[index]
        symbols.append({'names': f['names'], 'section': f['section'], 'start': f['address'],
                        'end_exclusive': f['address'] + f['size_bytes'], 'guest_instructions': count,
                        'entry_pc_hits_not_calls': entries[index], 'instruction_classes': dict(sorted(per_class[index].items())),
                        'zero_sized_entry_labels': sorted(s['name'] for s in unsized if s['size_bytes'] == 0 and
                            s['address'] == f['address'] and s['section'] == f['section'])})
    unresolved = [{'pc': pc, 'reason': reason, 'guest_instructions': count}
                  for (pc, reason), count in sorted(unknown.items())]
    total = len(lines)
    require(sum(counts.values()) + sum(unknown.values()) == total and sum(classes.values()) == total,
            'instruction accounting mismatch')
    return {'status': 'unavailable' if unknown else 'complete', 'guest_instructions': total,
            'attributed_instructions': sum(counts.values()), 'unresolved_instructions': sum(unknown.values()),
            'symbols': symbols, 'instruction_classes': dict(sorted(classes.items())), 'unresolved': unresolved}


def report(proof, replay_root, native_root, out):
    out = emulator_trace.ignored_path(out)
    require(not out.exists() and out != ROOT / 'build', 'output must be a new ignored build subdirectory')
    require(not any(out.is_relative_to(root) or root.is_relative_to(out)
                    for root in (proof, replay_root, native_root)), 'output overlaps an input context')
    out.mkdir(parents=True)
    result = {'schema_version': 1, 'kind': 'felucca-native-guest-hotspots', 'status': 'incomplete',
              'driver_sha256': replay.digest(Path(__file__)), 'groups': {},
              'limits': ['Unsigned trusted local saved artifacts; consistency checks are not a signature or independent child-execution attestation',
                         'Guest execution counts and entry-PC hits, not calls, physical cycles or deadline margin',
                         'Zero-sized labels get no inferred extent; inlined work stays in its containing range',
                         'One-core PR733 recipes/window only; no new firmware execution or hardware qualification']}
    path = out / 'hotspots.json'
    try:
        native, traces, bindings, timings, process = validate_saved(proof, replay_root, native_root, out)
        command = ("import sys;sys.path.insert(0,sys.argv[1]+'/tools');import build;"
                   "sys.stdout.write(build.tc('common/bin/objdump','-t',build.OUT/'felucca.elf'))")
        objdump = build.toolchain() / 'common/bin/objdump'
        expected_objdump = native['report']['configuration']['toolchain_sha256']['common/bin/objdump']
        require(replay.digest(objdump) == expected_objdump, 'target symbol tool differs from verified compiler closure')
        result['symbol_process'] = replay.capture([sys.executable, '-c', command, native_root], native_root,
                                                 os.environ.copy(), out / 'symbols', timeout=120)
        require(replay.digest(objdump) == expected_objdump, 'target symbol tool changed during capture')
        require(not (out / 'symbols.stderr').read_bytes(), 'unexpected target-tool stderr')
        symbols = (out / 'symbols.stdout').read_text()
        listing = checked_file(native_root, 'build/felucca.dis', MAX_LISTING, bindings).decode()
        functions, unsized, instructions = ranges(symbols, listing)
        for group, pair in traces.items():
            first, second = (attribute(trace, functions, unsized, instructions) for trace in pair)
            require(first == second, 'repeated hotspot attribution differs')
            result['groups'][group] = first
        result.update(proof_directory=str(proof), native_identity=native['report']['build_identity'],
                      configuration_sha256=native['report']['configuration_sha256'], objdump_sha256=expected_objdump,
                      replay_summary_sha256=bindings[str(proof / 'summary.json')],
                      replay_root=str(replay_root), replay_revision=REPLAY_REVISION,
                      native_root=str(native_root), native_binding=native['binding'],
                      symbol_table_sha256=replay.digest(out / 'symbols.stdout'),
                      sized_range_groups=len(functions), unsized_code_labels=unsized,
                      trace_window=list(replay.WINDOW), wall_time_observations=timings,
                      wall_time_limit='Recomputed saved host wall observations, not a calibrated speedup or hardware timing',
                      input_sha256=bindings, emulator_verification=process)
        replay.check_native_unchanged(native_root, native)
        source_context(replay_root)
        require(all(replay.digest(Path(name)) == value for name, value in bindings.items()),
                'saved input changed during reporting')
        result['status'] = 'unavailable' if any(g['status'] != 'complete' for g in result['groups'].values()) else 'complete'
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        encoded = json.dumps(result, indent=2) + '\n'
        if len(encoded.encode()) > replay.MAX_LOG:
            result.update(status='incomplete', error='hotspot report exceeds output bound', groups={})
            encoded = json.dumps(result, indent=2) + '\n'
            if len(encoded.encode()) > replay.MAX_LOG:
                encoded = json.dumps({'status': 'incomplete', 'error': 'hotspot report exceeds output bound'}) + '\n'
        path.write_text(encoded)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--replay-root', type=Path, required=True, help='trusted clean PR733 verifier checkout; never inferred from JSON')
    parser.add_argument('--native-root', type=Path, required=True, help='trusted clean native artifact producer')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        path = report(args.proof.resolve(), args.replay_root.resolve(), args.native_root.resolve(), args.out)
        print(path)
        return 0 if json.loads(path.read_text())['status'] == 'complete' else 1
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, subprocess.SubprocessError) as error:
        print('native hotspots: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
