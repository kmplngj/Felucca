#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exact original-scan/actual-source motion mask comparison; adapters stay ignored.

The frozen reference is independent of the candidate. Production has no test hooks.
DSP PCM runs normally; strict sanitizers exercise the changed walks without rendering
unrelated fixed-point DSP. The unchanged full-DSP strict failure is recorded separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_coverage import Producer

PIN = 'f101979be19de475a6733e917bccc07733c87a65'
ORIGINAL = '493c044d62abf0f98f0688611b55f3da162a4ddc54336da489b3996befffaa8a'
REFERENCE = '36342533be817781ee6f7c392684eb767742dcf0c2ff6e81ad7bc815c3d4a831'
SEEDS = (0x615, 0x10040)


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'adapter needs exactly one {old!r}; review changed source')
    return source.replace(old, new)


def function(source, name):
    match = re.search(r'^static[^\n]*\b' + name + r'\([^\n]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('function not found: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 2]


def change(source, name, old, new):
    body = function(source, name)
    return once(source, body, once(body, old, new))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_files(a, b):
    offset = 0
    with a.open('rb') as left, b.open('rb') as right:
        while True:
            x, y = left.read(1 << 20), right.read(1 << 20)
            if x != y:
                at = next((i for i, (u, v) in enumerate(zip(x, y)) if u != v), min(len(x), len(y)))
                return offset + at
            if not x:
                return None
            offset += len(x)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/host/motion_sparse')
    parser.add_argument('--reference-baseline', action='store_true', help='prove fixture against unchanged pinned scan before production editing')
    args = parser.parse_args()
    coverage = Producer()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'firmware/src/motion.c').read_text(encoding='utf-8')
    reference = (ROOT / 'tests/motion_sparse_reference.h').read_text(encoding='utf-8')
    bodies = [function(reference, name) for name in ('motion_restore', 'motion_unlock')]
    if hashlib.sha256(('\n\n'.join(bodies) + '\n').encode()).hexdigest() != REFERENCE:
        raise ValueError('frozen f101 original-scan reference changed')
    if args.reference_baseline and hashlib.sha256(source.encode()).hexdigest() != ORIGINAL:
        raise ValueError('reference baseline requires unchanged f101 motion.c')
    original = source
    for name, body in zip(('motion_restore', 'motion_unlock'), bodies):
        original = once(original, function(original, name), body)
    cc = shlex.split(os.environ.get('CC', 'cc'))
    report = dict(pin=PIN, reference_body_sha256=REFERENCE, source_sha256=digest(ROOT / 'firmware/src/motion.c'),
                  driver_sha256=digest(ROOT / 'tests/motion_sparse_test.c'), commands=[], rows=[], controls=[],
                  reference_baseline=args.reference_baseline, skips=[])
    env = os.environ.copy()
    env.update(ASAN_OPTIONS='detect_leaks=0:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')

    def run(name, command):
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=180)
        (out / (name + '.stdout.log')).write_bytes(result.stdout)
        (out / (name + '.stderr.log')).write_bytes(result.stderr)
        report['commands'].append(dict(name=name, command=command, exit=result.returncode))
        return result

    version = run('compiler', cc + ['--version'])
    if version.returncode:
        raise ValueError('compiler version probe failed')
    report['compiler'] = version.stdout.decode().splitlines()[0]

    def build(raw, label, flags, cpu2):
        directory = out / label; directory.mkdir(exist_ok=True)
        motion = raw
        motion = once(motion, 't->p[id] = motion_base[k][id];', 't->p[id] = sparse_write(1, t, id, motion_base[k][id]);')
        motion = once(motion, 't->p[id] = v;', 't->p[id] = sparse_write(2, t, id, v);')
        motion = once(motion, 't->p[id] = (int16_t)param_fit(d, e->value);', 't->p[id] = sparse_write(3, t, id, (int16_t)param_fit(d, e->value));')
        motion = 'static int16_t sparse_write(uint32_t, track_t *, uint32_t, int16_t);\n' + motion
        (directory / 'motion.c').write_text(motion, encoding='utf-8')
        seq = once((ROOT / 'firmware/src/seq.c').read_text(), '#include "motion.c"', f'#include "{directory / "motion.c"}"')
        (directory / 'seq.c').write_text(seq, encoding='utf-8')
        voice = (ROOT / 'firmware/src/voice.c').read_text()
        for name, kind, args_text in [('trk_note_on', 4, 'note, vel'), ('trk_note_off', 5, 'note, 0')]:
            body = function(voice, name)
            voice = once(voice, body, once(body, '\n{', f'\n{{\n    sparse_note({kind}, t, {args_text});'))
        voice = 'static void sparse_note(uint32_t, track_t *, uint32_t, uint32_t);\n' + voice
        (directory / 'voice.c').write_text(voice, encoding='utf-8')
        host = (ROOT / 'tests/hostsim.c').read_text()
        for name in ('seq', 'voice'):
            host = once(host, f'#include "../firmware/src/{name}.c"', f'#include "{directory / (name + ".c")}"')
        host = host.replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
        (directory / 'hostsim.c').write_text(host, encoding='utf-8')
        ui = once((ROOT / 'tests/ui_test.c').read_text(), '#include "hostsim.c"', f'#include "{directory / "hostsim.c"}"')
        ui = ui.replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
        (directory / 'ui_test.c').write_text(ui, encoding='utf-8')
        binary = directory / 'test'
        command = cc + flags + ['-w', '-I' + str(ROOT / 'build/gen'), '-I' + str(ROOT / 'firmware/src'),
                               '-I' + str(ROOT / 'tests'), f'-DFELUCCA_CPU2={cpu2}',
                               f'-DMOTION_TEST_UI="{directory / "ui_test.c"}"', str(ROOT / 'tests/motion_sparse_test.c'), '-lm', '-o', str(binary)]
        result = run(label + '-compile', command)
        if result.returncode:
            raise ValueError(f'{label} compile failed; see {out / (label + "-compile.stderr.log")}')
        return binary

    def execute(binary, label, seed, walks=False):
        prefix = out / label
        command = [str(binary), str(prefix), str(seed)] + (['--walks-only'] if walks else [])
        result = run(label, command)
        return result, prefix

    def compare(left, right):
        for suffix in ('events', 'state', 'pcm'):
            at = compare_files(left.with_suffix('.' + suffix), right.with_suffix('.' + suffix))
            if at is not None:
                return dict(stream=suffix, byte=at, word=at // 4)
        return None

    try:
        novec = ['-fno-vectorize', '-fno-slp-vectorize']
        probe = run('novec-probe', cc + novec + ['-x', 'c', '-c', '-o', os.devnull, os.devnull])
        if probe.returncode:
            novec = ['-fno-tree-vectorize', '-fno-tree-slp-vectorize']
        builds = [('O2-cpu2-on', ['-O2'], 1, False), ('Os-cpu2-off', ['-Os'] + novec, 0, False)]
        if os.environ.get('SANITIZE', '1') == '0':
            report['skips'].append('sanitizer-disabled')
            coverage.outcome('motion-sparse-sanitizer', 'skipped', 'sanitizer-disabled')
            print('strict changed-walk sanitizers: SKIP (SANITIZE=0)', flush=True)
        else:
            builds.append(('strict-walks', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all'], 1, True))
        for label, flags, cpu2, walks in builds:
            ref = build(original, label + '-reference', flags, cpu2)
            candidate = build(source, label + '-candidate', flags, cpu2)
            for seed in SEEDS:
                a, pa = execute(ref, f'{label}-reference-{seed}', seed, walks)
                b, pb = execute(candidate, f'{label}-candidate-{seed}', seed, walks)
                if a.returncode or b.returncode:
                    raise ValueError(label + ' fixture failed; inspect its stderr log')
                meta = json.loads(a.stdout); other = json.loads(b.stdout)
                if meta != other or compare(pa, pb):
                    raise ValueError(f'{label}: exact PCM/event/state mismatch: {compare(pa, pb)}')
                row = dict(build=label, cpu2=cpu2, seed=seed, walks_only=walks, **meta,
                           hashes={s: digest(pa.with_suffix('.' + s)) for s in ('pcm', 'events', 'state')})
                report['rows'].append(row)
                scope = 'changed-walk events/explicit-state (no DSP/PCM)' if walks else 'PCM/events/explicit-state'
                print(f'{label} seed={seed}: exact {scope} PASS ({meta})', flush=True)
            if walks:
                coverage.outcome('motion-sparse-sanitizer', seeds=len(SEEDS), scope='changed-walks-only', exclusions=[])
        if not args.reference_baseline:
            restore = function(source, 'motion_restore')
            low = once(restore, 't->p[id] = motion_base[k][id];', 'if (id != P_ATK) t->p[id] = motion_base[k][id];')
            high = once(restore, 't->p[id] = motion_base[k][id];', 'if (id / 32u != 3u) t->p[id] = motion_base[k][id];')
            tail = re.sub(r'        if \(w == P_COUNT / 32u\)\n            bits &= \(1u << \(P_COUNT & 31u\)\) - 1u;\n', '', restore)
            if tail == restore: raise ValueError('tail-mask control requires the reviewed candidate guard')
            clear = once(restore, 'memset(motion_active[k], 0, sizeof motion_active[k]);', '/* deliberate missing clear */')
            order = source.replace('__builtin_ctz(bits)', '(31u - __builtin_clz(bits))').replace('bits &= bits - 1u;', 'bits &= ~(1u << (id % 32u));')
            if order == source: raise ValueError('order control requires the reviewed bit walker')
            lock = change(source, 'motion_unlock', 'memset(motion_locked[k], 0, sizeof motion_locked[k]);', '/* deliberate missing clear */')
            mutants = [('low-bit', once(source, restore, low), 'events'), ('high-word', once(source, restore, high), 'events'),
                       ('tail', once(source, restore, tail), 'tail'), ('active-clear', once(source, restore, clear), 'state'),
                       ('order', order, 'events'), ('locked-clear', lock, 'state')]
            # Compare controls to a matching normal original scan, not sanitizer output with different code addresses.
            ref = build(original, 'controls-reference', ['-O1'], 1)
            a, pa = execute(ref, 'controls-reference-run', SEEDS[0], True)
            if a.returncode: raise ValueError('control reference failed')
            for label, raw, expected in mutants:
                binary = build(raw, 'control-' + label, ['-O1'], 1)
                result, pb = execute(binary, 'control-' + label + '-run', SEEDS[0], True)
                mismatches = {}
                if not result.returncode:
                    for stream in ('events', 'state', 'pcm'):
                        at = compare_files(pa.with_suffix('.' + stream), pb.with_suffix('.' + stream))
                        if at is not None:
                            mismatches[stream] = dict(byte=at, word=at // 4)
                if expected == 'tail':
                    detected = result.returncode == 1 and b'unused tail bit reached parameter write' in result.stderr
                else:
                    detected = result.returncode == 0 and expected in mismatches
                if not detected: raise ValueError(f'{label}: intended {expected} control not detected: exit={result.returncode}, mismatches={mismatches}')
                report['controls'].append(dict(name=label, expected=expected, exit=result.returncode, mismatches=mismatches))
                print(f'negative {label}: intended {expected} mismatch detected', flush=True)
        coverage.outcome('motion-sparse', rows=len(report['rows']), controls=len(report['controls']), reference_pin=PIN)
        report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print('motion sparse: FAIL: ' + str(error), file=sys.stderr)
        sys.exit(1)
