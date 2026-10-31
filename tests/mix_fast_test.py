#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""mix_part's specialised loops (fx.c, #185/#458) against FELUCCA_MIX_FAST=0: identical per-block traces."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_coverage import Producer
coverage = Producer()
out = ROOT / 'build/host/mix_fast'
out.mkdir(parents=True, exist_ok=True)
host = (ROOT / 'tests/hostsim.c').read_text().replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
(out / 'hostsim.c').write_text(host)
cc = shlex.split(os.environ.get('CC', 'cc'))
novec = ['-fno-vectorize', '-fno-slp-vectorize']
if subprocess.run(cc + novec + ['-x', 'c', '-c', '-o', os.devnull, '-'], input='', text=True, capture_output=True).returncode:
    novec = ['-fno-tree-vectorize', '-fno-tree-slp-vectorize']
SEEDS = [str(s) for s in range(1, 9)]
# (name, flags, FELUCCA_CPU2, scenario argument): the adversarial bound runs with -fwrapv, where the reference's
# x * 4096 wrap is defined behaviour (the target's 32-bit multiply wraps the same way)
CONFIGS = [('O2-cpu2-0', ['-O2'], 0, ''), ('O2-cpu2-1', ['-O2'], 1, ''),
           ('Os-cpu2-0', ['-Os'] + novec, 0, ''), ('Os-cpu2-1', ['-Os'] + novec, 1, ''),
           ('O2-c1', ['-O2', '-DC1_HOST', '-pthread'], 1, ''),
           ('adv-cpu2-0', ['-O2', '-fwrapv'], 0, 'adv'), ('adv-cpu2-1', ['-O2', '-fwrapv'], 1, 'adv')]


def build(name, flags, cpu2, fast):
    binary = out / f'{name}-fast{fast}'
    subprocess.run(cc + flags + ['-w', f'-DFELUCCA_CPU2={cpu2}', f'-DFELUCCA_MIX_FAST={fast}',
                   '-I' + str(ROOT / 'build/gen'), '-I' + str(ROOT / 'firmware/src'), '-I' + str(ROOT / 'tests'),
                   f'-DFX_TEST_HOSTSIM="{out / "hostsim.c"}"', str(ROOT / 'tests/mix_fast_test.c'), '-lm',
                   '-o', str(binary)], check=True)
    return binary


def run(binary, seed, arg):
    r = subprocess.run([str(binary), seed] + ([arg] if arg else []), text=True, capture_output=True, check=True)
    paths = [int(v) for v in r.stderr.split('paths', 1)[1].split()]
    return r.stdout, paths


failed = 0
for name, flags, cpu2, arg in CONFIGS:
    ref, cand = build(name, flags, cpu2, 0), build(name, flags, cpu2, 1)
    total = [0] * 5
    for seed in SEEDS:
        a, pa = run(ref, seed, arg)
        b, pb = run(cand, seed, arg)
        assert pa[0] == pa[2] == pa[3] == pa[4] == 0, f'{name}: the reference ran a specialised loop {pa}'
        if a != b:
            first = next(x for x, y in zip(a.splitlines(), b.splitlines()) if x != y)
            print(f'mix fast: {name} seed {seed}: FAILED, first differing checkpoint: {first.split()[1]}')
            failed += 1
        total = [t + v for t, v in zip(total, pb)]
    # every loop reached (fx.c mix_loop's f): dry (0), general (1), centred dry (2), centred with sends (3);
    # mix_unity_fix (4) under adv
    need = [0, 1, 2, 3] + ([4] if arg else [])
    missing = [k for k in need if not total[k]]
    if missing:
        print(f'mix fast: {name}: loops never ran: {missing} (counts {total})')
        failed += 1
    print(f'mix fast: {name}: {len(SEEDS)} seeds identical; loops dry/general/centred-dry/centred/fallback {total}')

if os.environ.get('SANITIZE', '1') != '0':
    sanitizers = ['-fsanitize=address,undefined', '-fno-sanitize=shift', '-fno-sanitize-recover=all']
    probe = subprocess.run(cc + sanitizers + ['-x', 'c', '-o', str(out / 'probe'), '-'],
                           input='int main(void){return 0;}', text=True, capture_output=True)
    if probe.returncode or subprocess.run([str(out / 'probe')], capture_output=True).returncode:
        print('mix fast: sanitizer SKIP (compiler/runtime unavailable)')
        coverage.outcome('mix-fast-sanitizer', 'skipped', 'sanitizer-unavailable')
    else:
        binary = build('sanitize', ['-O1', '-g'] + sanitizers, 1, 1)
        for seed in SEEDS[:3]:
            run(binary, seed, '')
        coverage.outcome('mix-fast-sanitizer')
else:
    print('mix fast: sanitizer SKIP (SANITIZE=0)')
    coverage.outcome('mix-fast-sanitizer', 'skipped', 'sanitizer-disabled')

if failed:
    sys.exit(1)
coverage.outcome('mix-fast-native', builds=['O2', 'Os', 'c1', 'wrapv'], cpu2=[0, 1])
