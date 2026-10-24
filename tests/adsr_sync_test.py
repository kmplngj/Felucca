#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real-handler ADSR trace with a forced current-renderer pixel oracle.

The private adapter reuses ui_test's unchanged HAL/init/input helpers, substitutes
an independent delayed-DMA model under real lcd.c, and compiles real UI/editor
sources. No curve formula or candidate snapshot drives the pixel oracle. Conservative redraw counts remain required.
A caller doing CPU/render measurements must hold the shared validation flock.
--source-root permits an immutable pre-change source export; --force-graph makes
that source's ordinary ADSR/LFO renderer unconditional for the external oracle.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

if sys.flags.optimize != 0:
    raise SystemExit('adsr-sync: Python optimization disables required validation assertions; run without -O/PYTHONOPTIMIZE')

ROOT = Path(__file__).resolve().parents[1]


def prepare(source, out, force_graph=False, mutation=None):
    out.mkdir(parents=True, exist_ok=True)
    original = (source / 'tests/ui_test.c').read_text()
    prefix = original[:original.index('static int check(')]
    start = prefix.index('static void lcd_fill(')
    end = prefix.index('#define FELUCCA_FLASH 0', start)
    backend = (ROOT / 'tests/adsr_sync_lcd_observer.h').read_text().replace('@ROOT@', str(source))
    if mutation == 'dma-source':
        assert backend.count('memcpy(wire_copy,p,n);') == 1
        backend = backend.replace('memcpy(wire_copy,p,n);', 'memcpy(wire_copy,p,n);wire_copy[0]^=1;')
    prefix = prefix[:start] + backend + prefix[end:]
    init = original[original.index('static void ui_power_on('):original.index('/* card slot drawn with MOTION')]
    helpers = original[original.index('static void frame(void)'):original.index('static int16_t stored_param(')]
    assert helpers.count('    ui_input();') == 1
    helpers = helpers.replace('    ui_input();', '    felucca_dbg.stage = 0;\n    ui_input();')
    # Stage is an execution tag, reset as in main.c; an overlay must not inherit
    # the preceding frame's stage=5 and be counted as a graph submission.
    text = '#define UI_TEST_NO_MAIN 1\n#define FELUCCA_OTA 1\n' + prefix + init + helpers
    text = text.replace('"../firmware/', '"' + str(source) + '/firmware/')
    graph = source / 'firmware/src/ui_graph.c'
    if mutation:
        s = graph.read_text()
        replacements = {
            'old-signature': ('sig = graph_signature_of(adsr_values);', '(void)adsr_values;'),
            'live-posthash': ('if (adsr) ui.graph_sig = sig;', 'if (adsr) ui.graph_sig = graph_signature();'),
            'live-render': ('graph_adsr(t, c, adsr ? adsr_values : 0);', 'graph_adsr(t, c, 0);'),
        }
        if mutation in replacements:
            a, b = replacements[mutation]
            expected = 1
            assert s.count(a) == expected, (mutation, s.count(a))
            s = s.replace(a, b)
            graph = out / 'mutant_ui_graph.c'
            graph.write_text(s)
    text = text.replace('"' + str(source / 'firmware/src/ui_graph.c') + '"', '"' + str(graph) + '"')
    if force_graph:
        a = '#include "' + str(graph) + '"'
        b = ('#define draw_graph oracle_draw_graph\n' + a + '\n#undef draw_graph\n'
             'static void draw_graph(void) { uint8_t f=ui.force; '
             'if(!ui.home && !ui.layer && !page_over && '
             '(cur_page()->graph==GR_ADSR || cur_page()->graph==GR_LFO))ui.force=1; '
             'oracle_draw_graph();ui.force=f; }')
        assert text.count(a) == 1
        text = text.replace(a, b)
    (out / 'adapter.h').write_text(text)
    (out / 'trace.c').write_text((ROOT / 'tests/adsr_sync_test.c').read_text().replace('@ROOT@', str(source)))


def rows(log):
    result = []
    for line in log.splitlines():
        parts = line.split()
        if len(parts) == 9 and parts[0].isdigit():
            result.append(dict(index=int(parts[0]), tag=parts[1], image_hash=int(parts[2]),
                               wire_bytes=int(parts[3]), windows=int(parts[4]),
                               graph_bytes=int(parts[5]), graph_windows=int(parts[6]),
                               canvas_begins=int(parts[7]), graph_begins=int(parts[8])))
    return result


def check_counts(records):
    zero = {'inactive-lock', 'sleep'}
    full = {'direct-relevant', 'cc-attack', 'editor-relevant', 'editor-irrelevant-force',
            'forced-same', 'focus-only-hot', 'focus-only-cool', 'palette', 'wake',
            'direct-level', 'direct-esync', 'cc-level', 'mod-negative', 'all-adsr-relevant'}
    assert len(records) >= 62, 'trace ended early'
    for row in records:
        if row['tag'] in zero:
            assert row['graph_bytes'] == row['graph_windows'] == row['graph_begins'] == 0, row
        if row['tag'] in full:
            assert row['graph_bytes'] >= 48011 and row['graph_windows'] and row['graph_begins'], row
        if row['tag'] == 'direct-esync':
            assert row['wire_bytes'] > 0, 'unrelated card unit must still update'
        if row['tag'] == 'lfo-irrelevant-conservative':
            assert row['graph_bytes'] == 48011, 'other graphs keep conservative signatures'


def run(source, out, *, fm4=False, force_graph=False, mutation=None):
    prepare(source, out, force_graph, mutation)
    cmd = shlex.split(os.environ.get('CC', 'cc')) + ['-O1', '-w', '-DFELUCCA_FM4=' + str(int(fm4)),
        '-I' + os.environ.get('ADSR_TEST_GEN', str(source / 'build/gen')), '-I' + str(source / 'firmware/src'),
        '-I' + str(source / 'tests'), str(out / 'trace.c'), '-o', str(out / 'trace'), '-lm']
    if not force_graph:
        cmd.insert(len(shlex.split(os.environ.get('CC', 'cc'))), '-DADSR_SYNC_TEST=1')
    subprocess.run(cmd, check=True)
    process = subprocess.run([str(out / 'trace'), str(out / 'screens.rgb565')], capture_output=True, text=True)
    (out / 'trace.log').write_text(process.stdout + process.stderr)
    record = dict(command=cmd, returncode=process.returncode, rows=rows(process.stdout), mutation=mutation)
    if not mutation:
        assert process.returncode == 0, process.stderr
        if not force_graph:
            check_counts(record['rows'])
    else:
        failed = process.returncode != 0
        if not failed:
            try:
                check_counts(record['rows'])
            except AssertionError:
                failed = True
        assert failed, 'negative control escaped: ' + mutation
        record['detected'] = True
    record['sha256'] = {q.name: hashlib.sha256(q.read_bytes()).hexdigest()
                        for q in out.iterdir() if q.is_file()}
    (out / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/adsr-sync')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--fm4', action='store_true')
    parser.add_argument('--force-graph', action='store_true')
    parser.add_argument('--negative-controls', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve(); source = args.source_root.resolve()
    result = [run(source, out / 'positive', fm4=args.fm4, force_graph=args.force_graph)]
    if args.negative_controls:
        assert not args.force_graph, 'controls target the candidate'
        for mutation in ['old-signature', 'live-posthash', 'live-render', 'dma-source']:
            result.append(run(source, out / mutation, fm4=args.fm4, mutation=mutation))
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('adsr-sync:', len(result[0]['rows']), 'checkpoints, forced full-render oracle, real LCD bytes/DMA;',
          len(result) - 1, 'negative controls detected')


if __name__ == '__main__':
    main()
