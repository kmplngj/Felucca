#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Native shared-chorus continuity checks; WAVs and instrumented copies stay in build/."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
from fx_rest_test import ROOT, replace_once
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_coverage import Producer
coverage = Producer()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fx-source', type=Path, default=ROOT / 'firmware/src/fx.c')
parser.add_argument('--out', type=Path, default=ROOT / 'build/host/chorus_depth')
parser.add_argument('--legacy', action='store_true', help='capture old discontinuities without accepting them')
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
source = args.fx_source.read_text()
source = replace_once(source, 'uint32_t ri = (uint32_t)r >> 8;',
                      'chorus_test_tap[i] = r; uint32_t ri = (uint32_t)r >> 8;')
fx = out / 'fx.c'
fx.write_text('static int32_t chorus_test_tap[32];\n' + source)
host = (ROOT / 'tests/hostsim.c').read_text()
host = replace_once(host, '#include "../firmware/src/fx.c"', f'#include "{fx}"')
host = host.replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
(out / 'hostsim.c').write_text(host)
cc = shlex.split(os.environ.get('CC', 'cc'))
novec = ['-fno-vectorize', '-fno-slp-vectorize']
if subprocess.run(cc + novec + ['-x', 'c', '-c', '-o', os.devnull, '-'],
                  input='', text=True, capture_output=True).returncode:
    novec = ['-fno-tree-vectorize', '-fno-tree-slp-vectorize']
builds = [('O2', ['-O2']), ('Os', ['-Os'] + novec)]
if os.environ.get('SANITIZE', '1') != '0':
    # Existing fixed-point DSP shifts signed negative samples; match run_tests.sh's
    # established shift exclusion while checking address/other undefined behavior.
    sanitizers = ['-fsanitize=address,undefined', '-fno-sanitize=shift']
    probe = subprocess.run(cc + sanitizers + ['-x', 'c', '-o', str(out / 'sanitizer_probe'), '-'],
                           input='int main(void) { return 0; }', text=True, capture_output=True)
    if probe.returncode or subprocess.run([str(out / 'sanitizer_probe')], capture_output=True).returncode:
        print('chorus depth: sanitizer SKIP (compiler/runtime unavailable)', flush=True)
        coverage.outcome('chorus-sanitizer', 'skipped', 'sanitizer-unavailable')
    else:
        builds.append(('sanitize', ['-O1', '-g'] + sanitizers))
else:
    print('chorus depth: sanitizer SKIP (SANITIZE=0)', flush=True)
    coverage.outcome('chorus-sanitizer', 'skipped', 'sanitizer-disabled')
for name, flags in builds:
    binary = out / name
    subprocess.run(cc + flags + (['-DCHORUS_DEPTH_TEST_SMOOTH=1'] if not args.legacy and 'cho_depth' in source else []) + ['-w', '-I' + str(ROOT / 'build/gen'),
                   '-I' + str(ROOT / 'firmware/src'), f'-DFX_TEST_HOSTSIM="{out / "hostsim.c"}"',
                   str(ROOT / 'tests/chorus_depth_test.c'), '-lm', '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(out), 'legacy' if args.legacy else 'smooth'], check=True)
    if name == 'sanitize': coverage.outcome('chorus-sanitizer')
coverage.outcome('chorus-native', builds=[name for name, _ in builds])
