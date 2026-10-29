#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in real native acceptance; no firmware build or device access."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import native_emulator_replay as replay


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-root', type=Path, required=True)
    p.add_argument('--emulator-receipt', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    report = replay.replay(args.native_root.resolve(), args.emulator_receipt.resolve(), args.out)
    summary = json.loads(report.read_text())
    replay.require(summary['status'] == 'passed' and len(summary['runs']) == 12 and
                   len(summary['comparisons']) == 4, 'incomplete native acceptance plan')
    replay.require(all(row['execution']['trace_rows'] == (4096 if row['traced'] else 0)
                       for row in summary['runs']), 'incomplete trace window')
    mixed = [r for r in summary['runs'] if r['case'] == 'mixed-uart' and not r['control']]
    expected = [list(n) for n in replay.expected_midi('mixed-uart', False)]
    replay.require(len(mixed) == 3 and all(r['execution']['admitted_midi_notes'] == expected
                                         for r in mixed), 'mixed native MIDI admission missing')
    # Reuse real retained inputs for two admission negative controls. Native producer
    # and genuine emulator receipt remain immutable; only local copies are damaged.
    receipt = json.loads(args.emulator_receipt.read_text())
    receipt['binary_sha256'] = '0' * 64
    bad_receipt = report.parent / 'invalid-emulator-receipt.json'
    bad_receipt.write_text(json.dumps(receipt))
    try:
        replay.replay(args.native_root.resolve(), bad_receipt, report.parent / 'must-not-run')
    except ValueError:
        replay.require(not (report.parent / 'must-not-run').exists(), 'bad receipt launched native child')
    else:
        raise ValueError('modified real emulator receipt accepted')
    first = report.parent / summary['runs'][0]['directory'] / 'xip.bin'
    altered = bytearray(first.read_bytes())
    altered[0x120] ^= 1
    bad_image = report.parent / 'invalid-xip.bin'
    bad_image.write_bytes(altered)
    try:
        replay.check_image(bad_image, args.native_root / 'build/felucca.bin')
    except ValueError:
        pass
    else:
        raise ValueError('modified real native package image accepted')
    (report.parent / 'execution-checks.json').write_text(json.dumps({
        'status': 'passed', 'real_native_runs': 12, 'paired_groups': 4,
        'negative_controls': ['modified real emulator receipt refused before launch',
                              'modified real decoded native app refused'],
        'production_summary_sha256': replay.digest(report)}, indent=2) + '\n')
    print('PASS native replay execution: ' + str(report))


if __name__ == '__main__':
    main()
