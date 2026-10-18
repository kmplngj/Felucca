#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Focused native send-gain arithmetic/lifecycle checks; build copies stay ignored."""
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / 'build/host/send_gain'
out.mkdir(parents=True, exist_ok=True)
host = (ROOT / 'tests/hostsim.c').read_text().replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
(out / 'hostsim.c').write_text(host)
cc = shlex.split(os.environ.get('CC', 'cc'))
novec = ['-fno-vectorize', '-fno-slp-vectorize']
if subprocess.run(cc + novec + ['-x', 'c', '-c', '-o', os.devnull, '-'], input='', text=True, capture_output=True).returncode:
    novec = ['-fno-tree-vectorize', '-fno-tree-slp-vectorize']
for cpu2 in (0, 1):
    for name, flags in [('O2', ['-O2']), ('Os', ['-Os'] + novec)]:
        binary = out / f'{name}-cpu2-{cpu2}'
        subprocess.run(cc + flags + ['-w', f'-DFELUCCA_CPU2={cpu2}', '-I' + str(ROOT / 'build/gen'),
                       '-I' + str(ROOT / 'firmware/src'), f'-DFX_TEST_HOSTSIM="{out / "hostsim.c"}"',
                       str(ROOT / 'tests/send_gain_test.c'), '-lm', '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

# Existing fixed-point DSP shifts negative samples; follow the established shift exclusion.
if os.environ.get('SANITIZE', '1') != '0':
    binary = out / 'sanitize'
    sanitizers = ['-fsanitize=address,undefined', '-fno-sanitize=shift', '-fno-sanitize-recover=all']
    probe = subprocess.run(cc + sanitizers + ['-x', 'c', '-o', str(out / 'probe'), '-'],
                           input='int main(void){return 0;}', text=True, capture_output=True)
    if probe.returncode or subprocess.run([str(out / 'probe')], capture_output=True).returncode:
        print('send gain: sanitizer SKIP (compiler/runtime unavailable)')
    else:
        subprocess.run(cc + ['-O1', '-g'] + sanitizers + ['-w', '-I' + str(ROOT / 'build/gen'),
                       '-I' + str(ROOT / 'firmware/src'), f'-DFX_TEST_HOSTSIM="{out / "hostsim.c"}"',
                       str(ROOT / 'tests/send_gain_test.c'), '-lm', '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
else:
    print('send gain: sanitizer SKIP (SANITIZE=0)')

# Exercise actual load routes through the established UI fixture, without running the full UI suite.
load = out / 'loads'
subprocess.run(cc + ['-O2', '-w', '-I' + str(ROOT / 'build/gen'), '-I' + str(ROOT / 'firmware/src'),
               str(ROOT / 'tests/send_gain_load_test.c'), '-lm', '-o', str(load)], check=True)
subprocess.run([str(load)], check=True)
