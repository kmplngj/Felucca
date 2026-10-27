#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded native replay evidence for #662; no hotspot or device timing report."""
import os as _source_os

# Like maintainer_bundle, this consumer requires Git. Refuse extracted sources
# before importing repository helpers, including unverified sourceless bytecode.
if _source_os.path.isfile(_source_os.path.join(_source_os.path.dirname(
        _source_os.path.dirname(_source_os.path.realpath(__file__))), 'SOURCE-PINS.json')):
    raise SystemExit('native replay orchestration requires a clean committed Git checkout')

import argparse
import array
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import struct
import subprocess
import sys
import time
import wave

import build_manifest
import build_report
import emulator_trace
import fm1_install

ROOT = Path(__file__).resolve().parents[1]
STEPS = 264_000_000
WINDOW = (200_000_000, 200_004_096)
MAX_LOG = 2 * 1024 * 1024
MAX_WAV = 256 * 1024
MAX_XIP = 1024 * 1024
TIMEOUT = 60
MIXED_NOTES = (48, 55, 60, 67)
MIXED = ('700:midi:903064913764923c64934364,'
         '1000:midi:803000813700823c00834300')
CASES = {'held-key': '700-1000:n7', 'mixed-uart': MIXED}
TRACE = re.compile(r'T ([1-9][0-9]*) c([0-9]+) (0x[0-9a-f]{8}) (\S+) irq=\[((?:[0-7](?:, [0-7])*)?)\] ie=(?:true|false) r0=0x[0-9a-f]{1,8} r1=0x[0-9a-f]{1,8}')
BREAK = re.compile(r'break c0 pc=(0x[0-9a-f]{8}) \[([0-9]+)\] sp=0x[0-9a-f]+ rets=0x[0-9a-f]+ irq_levels=\[[0-7, ]*\] r0-11=\[([0-9a-f, ]+)\]')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(argv, cwd, env, prefix, *, timeout=TIMEOUT, limit=MAX_LOG,
            watched=()):
    """Bound stdout/stderr in pipes; terminate the entire owned process group on failure."""
    require(os.name == 'posix', 'bounded process-group capture requires Linux or macOS')
    require(0 < timeout <= 120 and 0 < limit <= MAX_LOG, 'invalid process bound')
    started = time.monotonic()
    record = {'argv': list(map(str, argv)), 'timeout_seconds': timeout,
              'log_limit_bytes': limit, 'returncode': None, 'status': 'incomplete'}
    selector = selectors.DefaultSelector()
    child = None
    logs = {}
    consumed = 0
    failure = None
    try:
        for stream in ('stdout', 'stderr'):
            logs[stream] = prefix.with_suffix('.' + stream).open('wb')
        child = subprocess.Popen(record['argv'], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        selector.register(child.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(child.stderr, selectors.EVENT_READ, 'stderr')
        while selector.get_map() or child.poll() is None:
            if time.monotonic() - started > timeout:
                raise ValueError('child timeout')
            for path, bound in watched:
                if path.exists() and path.stat().st_size > bound:
                    raise ValueError('child output file exceeds bound: ' + path.name)
            if not selector.get_map():
                time.sleep(0.02)
                continue
            for key, _ in selector.select(0.02):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                allowed = max(0, limit - consumed)
                logs[key.data].write(data[:allowed])
                consumed += len(data)
                if consumed > limit:
                    raise ValueError('child log output exceeds bound')
        remaining = timeout - (time.monotonic() - started)
        require(remaining > 0, 'child timeout')
        record['returncode'] = child.wait(timeout=remaining)
        require(record['returncode'] == 0, 'child failure: exit ' + str(record['returncode']))
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError('child left a surviving process group')
        for path, bound in watched:
            require(path.is_file() and not path.is_symlink() and path.stat().st_size <= bound,
                    'missing or oversized child output: ' + path.name)
        record['status'] = 'complete'
    except BaseException as error:
        failure = error
        record['error'] = str(error)
    finally:
        selector.close()
        if child is not None:
            # EOF and an exited leader do not establish descendant completion.
            # Clean the entire owned group on success, failure and interruption.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            record['returncode'] = child.returncode
            for stream in (child.stdout, child.stderr):
                if not stream.closed:
                    stream.close()
        for log in logs.values():
            log.close()
        record['wall_seconds'] = time.monotonic() - started
        for stream in logs:
            record[stream + '_sha256'] = digest(prefix.with_suffix('.' + stream))
        prefix.with_suffix('.process.json').write_text(json.dumps(record, indent=2) + '\n')
    if failure is not None:
        raise failure
    return record


def native_binding(root):
    """Hash only existing report-declared paths; the existing verifier is admission authority."""
    path = build_manifest.file_at(root, 'build/resource-report.json')
    report = json.loads(path.read_text())
    # Safe path resolution and complete source/config checks are delegated, not redefined.
    hashes = {name: digest(build_manifest.file_at(root, name))
              for name in report['artifact_sha256']}
    require(hashes == report['artifact_sha256'], 'native image/artifact mismatch')
    return {'resource_report_sha256': digest(path), 'artifacts': hashes}


def native_inputs(root, out):
    root = root.resolve()
    report_path = build_manifest.file_at(root, 'build/resource-report.json')
    report = json.loads(report_path.read_text())
    identity = report['build_identity']
    require(identity['dirty'] is False and identity['source'] == 'git', 'clean native Git producer required')
    require(emulator_trace.git(root, 'rev-parse', 'HEAD') == identity['revision'], 'native producer revision mismatch')
    require(not emulator_trace.git(root, 'status', '--porcelain=v1', '--untracked-files=all'), 'native producer is dirty')
    # Use its checked-in existing resource verifier, including actual toolchain, source,
    # profile, package hash and ELF/disassembly/resource checks. This never builds.
    verifier = build_manifest.file_at(root, 'tools/build_report.py')
    process = capture([sys.executable, verifier, '--verify', report_path], root, os.environ.copy(),
                      out / 'native-verification', timeout=120)
    require(b'resource report: artifacts, inputs and configuration match\n' in
            (out / 'native-verification.stdout').read_bytes(), 'native verifier did not establish validity')
    cfg = report['configuration']
    profile = json.loads(build_manifest.file_at(root, 'build/gen/resolved-profile.json').read_text())
    require(profile['profile'] == 'standard' and profile['asset_variant'] == 'm8stealth', 'only standard/M8Stealth native factory workload is supported')
    require(cfg['effective_defines']['FELUCCA_UART'] == '1', 'native UART input is unavailable')
    require(cfg['logical_constants']['HALF_FRAMES'] == '128' and cfg['logical_constants']['FS'] == '44100', 'unsupported native audio configuration')
    package = build_manifest.file_at(root, 'build/' + report['package'])
    product, _ = fm1_install.load_package(package, False)  # pure validation; no MIDI API instantiated
    require(product == cfg['product'], 'native package product mismatch')
    listing = build_manifest.file_at(root, 'build/felucca.dis').read_text()
    entries = re.findall(r'^midi_note_event:\n\s*([0-9a-f]+):', listing, re.M)
    require(len(entries) == 1, 'missing or ambiguous MIDI admission breakpoint')
    source = build_manifest.file_at(root, 'firmware/src/midi_control.c').read_text()
    require('static void midi_note_event(uint32_t ch, uint32_t note, uint32_t vel)' in source,
            'unsupported MIDI admission function signature')
    # An exact named entry observation is used only to establish workload delivery.
    # There is no range lookup, symbol aggregation, function-call or cost report.
    return {'root': str(root), 'report': report, 'binding': native_binding(root),
            'package': str(package), 'break_pc': int(entries[0], 16),
            'resource_verification': process}


def check_native_unchanged(root, native):
    require(native_binding(root) == native['binding'], 'native evidence changed during replay')
    require(emulator_trace.git(root, 'rev-parse', 'HEAD') == native['report']['build_identity']['revision'],
            'native producer revision changed during replay')
    require(build_report.input_hashes(root) == native['report']['input_sha256'],
            'native source inputs changed during replay')
    require(not emulator_trace.git(root, 'status', '--porcelain=v1', '--untracked-files=all'),
            'native producer changed during replay')


def check_image(xip_path, app_path):
    xip, app = xip_path.read_bytes(), app_path.read_bytes()
    require(0 < len(xip) <= MAX_XIP and 0 < len(app) <= 0x8dfbc,
            'empty or oversized native image')
    require(xip[0x120:0x120 + len(app)] == app, 'decoded native package app differs from verified BIN')
    return {'xip_sha256': hashlib.sha256(xip).hexdigest(), 'app_offset': 0x120,
            'app_bytes': len(app), 'app_matches_verified_bin': True}


def parse_log(data, *, traced, window=WINDOW, steps=STEPS, break_pc, expected_notes=()):
    require(data and data.endswith(b'\n'), 'empty or partial child transcript')
    text = data.decode('ascii')
    lines = text.splitlines()
    require(not any(l.startswith(('halt', 'cpu1', 'break c1')) for l in lines), 'halt or second-core execution is unsupported')
    require(not re.search(r'\bc1\b', text), 'second-core execution is unsupported')
    rows, notes = [], []
    for line in lines:
        if line.startswith('T'):
            match = TRACE.fullmatch(line)
            require(match is not None, 'malformed or unknown-class trace row')
            slot, core, pc, name, _ = match.groups()
            require(core == '0' and name != '?' and re.fullmatch(r'[a-zA-Z0-9_]+', name), 'unsupported trace core/class')
            slot, pc = int(slot), int(pc, 16)
            require(window[0] <= slot < window[1], 'trace row outside requested window')
            require((0x02000120 <= pc < 0x0208e0dc) or (0x01c00000 <= pc < 0x01c06000), 'trace PC outside supported native code windows')
            rows.append((slot, line))
        if line.startswith('break '):
            match = BREAK.fullmatch(line)
            require(match is not None and int(match[1], 16) == break_pc, 'unexpected or malformed admission breakpoint')
            registers = [int(x, 16) for x in match[3].split(', ')]
            require(len(registers) == 12 and 0 < int(match[2]) <= steps, 'partial admission registers or slot')
            notes.append(tuple(registers[:3]))
    require(notes == list(expected_notes), 'native MIDI channel/note/velocity admission mismatch')
    require((window[0] < window[1] <= steps + 1) and window[1] - window[0] <= 65536, 'invalid trace window')
    expected_slots = list(range(*window)) if traced else []
    require([slot for slot, _ in rows] == expected_slots, 'empty, partial, duplicate or reordered trace window')
    def terminal(prefix, grammar):
        entries = [line for line in lines if line.startswith(prefix)]
        require(len(entries) == 1, 'missing or duplicate terminal field: ' + prefix)
        match = re.fullmatch(grammar, entries[0])
        require(match is not None, 'malformed terminal field: ' + prefix)
        return match

    stopped = terminal('stopped after', r'stopped after ([0-9]+) instructions \(step limit, hist top-[0-9]+ of [0-9]+ classes\):')
    require(stopped[1] == str(steps), 'inconsistent successful terminal count')
    ending = terminal('time ', r'time ([0-9]+) ms, ([0-9]+) interrupts, ([0-9]+) audio halves \(([0-9]+) samples\)')
    ms, irqs, halves, frames = map(int, ending.groups())
    require(ms == steps // 240000 and irqs > 0 and halves > 0 and frames == halves * 128,
            'inconsistent or empty terminal audio window')
    sources = terminal('interrupts by source:', r'interrupts by source: (c0 irq [0-9]+ x[1-9][0-9]*(?:, c0 irq [0-9]+ x[1-9][0-9]*)*)')
    irq_sources = [(int(irq), int(n)) for irq, n in re.findall(r'c0 irq ([0-9]+) x([0-9]+)', sources[1])]
    require(len({irq for irq, _ in irq_sources}) == len(irq_sources) and
            sum(n for _, n in irq_sources) == irqs, 'inconsistent or truncated IRQ source counts')
    terminal('wav:', r'wav: .+ \([0-9.]+ s\)')
    terminal('lcd frames=', r'lcd frames=[1-9][0-9]* inverted=(?:true|false) display_on=true')
    trace_data = ('\n'.join(row for _, row in rows) + ('\n' if rows else '')).encode()
    return {'retired_instructions': steps, 'emulated_ms': ms, 'interrupts': irqs,
            'audio_halves': halves, 'audio_frames': frames, 'trace_rows': len(rows),
            'trace_sha256': hashlib.sha256(trace_data).hexdigest(), 'observed_core': 0,
            'admitted_midi_notes': notes}, trace_data


def read_pcm(path, expected_frames):
    raw = path.read_bytes()
    require(44 <= len(raw) <= MAX_WAV and raw[:4] == b'RIFF' and
            struct.unpack('<I', raw[4:8])[0] + 8 == len(raw), 'partial or oversized WAV')
    with wave.open(str(path)) as wav:
        require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) ==
                (2, 2, 44100, 'NONE'), 'unsupported PCM format')
        require(wav.getnframes() == expected_frames, 'PCM/terminal frame count mismatch')
        pcm = wav.readframes(expected_frames + 1)
    require(len(pcm) == expected_frames * 4 and pcm, 'empty or partial PCM')
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    return {'frames': expected_frames, 'pcm_sha256': hashlib.sha256(pcm).hexdigest(),
            'wav_sha256': hashlib.sha256(raw).hexdigest(), 'peak_pcm16': max(map(abs, samples)),
            'nonzero_samples': sum(x != 0 for x in samples)}


def expected_midi(case, control):
    if case != 'mixed-uart' or control:
        return []
    return [(ch, note, vel) for vel in (100, 0) for ch, note in enumerate(MIXED_NOTES)]


def run_case(native, receipt, directory, case, *, control, traced):
    directory.mkdir()
    wav, xip = directory / 'audio.wav', directory / 'xip.bin'
    env = {k: v for k, v in os.environ.items() if not k.startswith('FM1_')}
    require(not any(env.get(k) for k in build_report.HOST_INJECTION_ENV), 'host loader injection is unsupported')
    env.update(FM1_FWSC_XIP=str(xip), FM1_BREAK_MAX='9')
    if traced:
        env['FM1_TRACE_RANGE'] = ':'.join(map(str, WINDOW))
    argv = [receipt['binary'], '--fwsc', native['package'], '--steps', str(STEPS),
            '--break-pc', hex(native['break_pc']), '--wav', str(wav)]
    if not control:
        argv += ['--keys', CASES[case]]
    process = capture(argv, directory, env, directory / 'child',
                      watched=((wav, MAX_WAV), (xip, MAX_XIP)))
    image = check_image(xip, Path(native['root']) / 'build/felucca.bin')
    parsed, trace_data = parse_log((directory / 'child.stdout').read_bytes(), traced=traced,
                                   break_pc=native['break_pc'], expected_notes=expected_midi(case, control))
    require(not (directory / 'child.stderr').read_bytes(), 'unexpected emulator stderr')
    (directory / 'trace.txt').write_bytes(trace_data)
    pcm = read_pcm(wav, parsed['audio_frames'])
    require((pcm['peak_pcm16'] == 0) if control else (pcm['peak_pcm16'] > 0),
            'no-input control is not silent or workload produced no audio')
    result = {'case': case, 'control': control, 'traced': traced, 'process': process,
              'execution': parsed, 'audio': pcm, 'image': image}
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def compare_runs(first, second, *, same_trace):
    require(first['audio'] == second['audio'], 'repeated/traced/untraced PCM differs')
    fields = ('retired_instructions', 'emulated_ms', 'interrupts', 'audio_halves',
              'audio_frames', 'observed_core', 'admitted_midi_notes')
    require(all(first['execution'][k] == second['execution'][k] for k in fields), 'terminal or admission counts differ')
    require(first['image'] == second['image'], 'decoded native images differ')
    if same_trace:
        require(first['execution'] == second['execution'], 'repeated trace differs')


def replay(native_root, emulator_receipt, out):
    out = emulator_trace.ignored_path(out)
    require(out != ROOT / 'build' and not out.exists(), 'output must be a new ignored build subdirectory')
    require(not out.is_relative_to(native_root.resolve()) and
            not native_root.resolve().is_relative_to(out), 'output overlaps native producer')
    receipt = emulator_trace.verify(emulator_receipt)
    out.mkdir(parents=True)
    summary = {'schema_version': 1, 'kind': 'felucca-native-replay-evidence', 'status': 'incomplete',
               'scope': 'one-core synthetic native replay; no hotspots, cycle/deadline or device qualification',
               'driver_sha256': digest(Path(__file__)), 'steps': STEPS, 'trace_window': list(WINDOW),
               'emulator_receipt': str(emulator_receipt.resolve()),
               'emulator_receipt_sha256': digest(emulator_receipt), 'emulator_binary_sha256': receipt['binary_sha256'],
               'initialization': 'fresh --fwsc each child; pinned loader seeds stock USR voices EE000..F1FFF and settings FA000..FBD7F; native settings FC000/FD000 and autosave E5000/E6000 remain outside seed',
               'uart': '12 bytes/event queued at 700/1000 ms; modeled UART1 31250 baud, 10 bits/byte = 320 us/byte, not simultaneous USB/sample events',
               'admission_limit': 'MIDI entry argument tuples are delivery observations before possible IRQ dispatch; they do not count completed voice allocation or per-part renders; duplicates/preemption re-hits fail rather than being relabelled as calls',
               'unsupported': ['host direct parameter/engine setters', 'host RNG/master initialization', 'host sample-aligned timeline parity', 'multi-core execution', 'symbol hotspot attribution'],
               'runs': [], 'comparisons': []}
    path = out / 'summary.json'
    try:
        native = native_inputs(native_root, out)
        summary['native'] = native
        # Preserve the producer's complete existing report; no second report authority.
        (out / 'native-resource-report.json').write_bytes((native_root / 'build/resource-report.json').read_bytes())
        for case in CASES:
            for control in (True, False):
                group = []
                for label, traced in (('trace-1', True), ('plain', False), ('trace-2', True)):
                    name = case + ('-control-' if control else '-workload-') + label
                    print('native replay: ' + name, flush=True)
                    result = run_case(native, receipt, out / name, case, control=control, traced=traced)
                    group.append(result)
                    summary['runs'].append({'directory': name, **result})
                    path.write_text(json.dumps(summary, indent=2) + '\n')
                compare_runs(group[0], group[2], same_trace=True)
                compare_runs(group[0], group[1], same_trace=False)
                timings = [r['process']['wall_seconds'] for r in group]
                summary['comparisons'].append({'case': case, 'control': control,
                    'trace_and_pcm_repeat': True, 'traced_plain_pcm_and_terminal_match': True,
                    'trace_wall_seconds': [timings[0], timings[2]], 'plain_wall_seconds': timings[1],
                    'mean_trace_wall_ratio': ((timings[0] + timings[2]) / 2) / timings[1],
                    'timing_limit': 'single interleaved plain observation, two traced observations; host scheduling/IO noise included; not physical cycles or a speedup'})
        check_native_unchanged(native_root, native)
        require(emulator_trace.verify(emulator_receipt) == receipt and
                digest(emulator_receipt) == summary['emulator_receipt_sha256'], 'emulator receipt changed during replay')
        summary['status'] = 'passed'
    except BaseException as error:
        summary['error'] = str(error)
        raise
    finally:
        path.write_text(json.dumps(summary, indent=2) + '\n')
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-root', type=Path, required=True, help='trusted clean producer with matching verified build/')
    p.add_argument('--emulator-receipt', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    try:
        print(replay(args.native_root.resolve(), args.emulator_receipt.resolve(), args.out))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, subprocess.SubprocessError,
            fm1_install.InstallError, wave.Error) as error:
        print('native replay: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
