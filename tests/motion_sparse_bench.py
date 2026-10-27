#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in paired HOST costs, never target cycles or whole-device CPU.

Requires generated assets, as for motion_sparse_test.py. Not run by the default
suite; no timing thresholds or baseline updates. Fresh output directories only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import statistics
import subprocess
import sys

import motion_sparse_test as audit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_coverage import snapshot


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spread(values):
    median = statistics.median(values)
    return dict(median=median, min=min(values), max=max(values),
                mad=statistics.median(abs(x - median) for x in values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new ignored output directory; existing results are never overwritten')
    parser.add_argument('--smoke', action='store_true', help='two pairs and at most 1024 loops; functional replay only, not qualification')
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / 'build'):
        parser.error('--out must be under ignored build/')
    out.mkdir(parents=True, exist_ok=False)
    pairs, target_ns, pilot, minimum, maximum = (2, 500000, 64, 16, 1024) if args.smoke else (9, 15000000, 1024, 256, 1000000)
    report = dict(host=platform.platform(), machine=platform.machine(), smoke=args.smoke,
                  source_before=snapshot(ROOT, os.environ), commands=[], builds=[],
                  reference_pin=audit.PIN, reference_body_sha256=audit.REFERENCE,
                  configuration=dict(pairs=pairs, target_batch_ns=target_ns, pilot_loops=pilot, minimum_loops=minimum, maximum_loops=maximum),
                  method='Warmed alternating pairs, identical loops/inputs/observable sinks. Batch includes mask rearm, compiler memory barriers and indirect wrapper call. Separate copied restore guard boundaries use host clock bookends; no IRQ is disabled. Empty bookends reported without subtraction. Host instruction counter reused verbatim from tests/host_instructions.h, not target instructions. No target or FM-1 timing claim.')
    source = (ROOT / 'firmware/src/motion.c').read_text(encoding='utf-8')
    reference = (ROOT / 'tests/motion_sparse_reference.h').read_text(encoding='utf-8')
    bodies = [audit.function(reference, name) for name in ('motion_restore', 'motion_unlock')]
    if hashlib.sha256(('\n\n'.join(bodies) + '\n').encode()).hexdigest() != audit.REFERENCE:
        raise ValueError('frozen f101 original-scan reference changed')
    originals = []
    for name, body in zip(('restore', 'unlock'), bodies):
        originals.append(body.replace('motion_' + name + '(', 'bench_original_' + name + '_raw('))
    for variant, text in [('original', reference), ('candidate', source)]:
        body = audit.function(text, 'motion_restore').replace('motion_restore(', 'bench_' + variant + '_guard_raw(')
        body = audit.once(body, 'motion_guard()', 'bench_guard_begin()')
        body = audit.once(body, 'motion_unguard(f)', 'bench_guard_end(f)')
        originals.append(body)
    (out / 'reference.inc').write_text('\n\n'.join(originals) + '\n', encoding='utf-8')
    cc = shlex.split(os.environ.get('CC', 'cc'))

    def command(label, argv):
        with (out / (label + '.stdout.log')).open('wb') as stdout, (out / (label + '.stderr.log')).open('wb') as stderr:
            result = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=180)
        report['commands'].append(dict(command=argv, exit=result.returncode))
        if result.returncode:
            raise ValueError(label + ' failed; inspect retained logs')

    try:
        command('compiler', cc + ['--version'])
        report['compiler'] = (out / 'compiler.stdout.log').read_text().strip()
        # Compile both before any timed run; probe the actual compiler's no-vector flags.
        novec = ['-fno-vectorize', '-fno-slp-vectorize']
        probe = subprocess.run(cc + novec + ['-x', 'c', '-c', '-o', os.devnull, os.devnull], capture_output=True)
        (out / 'novec-probe.stderr.log').write_bytes(probe.stderr)
        if probe.returncode:
            novec = ['-fno-tree-vectorize', '-fno-tree-slp-vectorize']
        for label, flags in [('O2', ['-O2']), ('Os-novec', ['-Os'] + novec)]:
            binary = out / ('cost-' + label)
            argv = cc + flags + ['-w', '-DFELUCCA_CPU2=1', '-I' + str(ROOT / 'build/gen'),
                    '-I' + str(ROOT / 'firmware/src'), '-I' + str(ROOT / 'tests'),
                    '-DBENCH_UI="' + str(ROOT / 'tests/ui_test.c') + '"',
                    '-DBENCH_REFERENCE="' + str(out / 'reference.inc') + '"',
                    str(Path(__file__).with_suffix('.c')), '-lm', '-o', str(binary)]
            command(label + '-compile', argv)
        for label in ('O2', 'Os-novec'):
            binary = out / ('cost-' + label)
            command(label, [str(binary), *map(str, (pairs, target_ns, pilot, minimum, maximum))])
            rows = [json.loads(line) for line in (out / (label + '.stdout.log')).read_text().splitlines()]
            summaries = []
            for mode in range(3):
                for density in range(4):
                    for records in (0, 128):
                        samples = [r for r in rows if r['kind'] == 'sample' and (r['mode'], r['density'], r['records']) == (mode, density, records)]
                        if len(samples) != pairs * 2:
                            raise ValueError('incomplete case samples')
                        item = dict(mode=['restore-batch', 'unlock-batch', 'restore-host-guard-window'][mode],
                                    mask=['empty', 'one-high110', 'sparse8', 'dense111'][density], records=records)
                        for variant in (0, 1):
                            subset = [r for r in samples if r['variant'] == variant]
                            item[['original', 'candidate'][variant]] = dict(
                                batch_ns=spread([r['elapsed_ns'] / r['loops'] for r in subset]),
                                window_ns=spread([r['window_ns'] / r['loops'] for r in subset]),
                                host_instructions=spread([r['instructions'] / r['loops'] for r in subset]) if all(r['counter_available'] for r in subset) else None)
                        ratios = []
                        for pair in range(pairs):
                            a, b = [next(r for r in samples if r['pair'] == pair and r['variant'] == v) for v in (0, 1)]
                            if a['sink'] != b['sink'] or a['loops'] != b['loops']:
                                raise ValueError('unequal observable sink or paired inputs')
                            metric = 'window_ns' if mode == 2 else 'elapsed_ns'
                            ratios.append(100 * (b[metric] / a[metric] - 1))
                        item['paired_percent_change'] = spread(ratios)
                        summaries.append(item)
            report['builds'].append(dict(label=label, binary_sha256=sha(binary), environment=rows[0], summaries=summaries,
                empty_bookend_ns=spread([r['window_ns'] / r['loops'] for r in rows if r['kind'] == 'bookend-probe'])))
            print(label + (' SMOKE' if args.smoke else '') + f' PASS: 24 cases x {pairs} alternating pairs; identical sinks', flush=True)
        report['source_after'] = snapshot(ROOT, os.environ)
        if report['source_before'] != report['source_after']:
            raise ValueError('source or generated inputs changed during measurement')
        report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
