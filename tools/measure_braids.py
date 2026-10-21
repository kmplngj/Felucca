#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Measure each added model's isolated DSP code/data with the target compiler.

This is a standalone object probe, not a modular firmware build. Restrict only
the macro/digital dispatch cases in a copy of the generated header; the shared
analog dispatcher stays intact. Values include shared helpers/tables and probe
entry points, exclude Felucca's mixer/UI/presets, and must not be added together
or treated as the bytes saved by removing a model from the complete firmware.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import build

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, default=build.OUT / "braids-cost")
parser.add_argument("--model", type=int, help="Felucca model ID, 3..47 (default: all added models)")
args = parser.parse_args()
args.out = args.out.resolve()
args.out.relative_to(build.SRC)  # Docker can access only this checkout.
args.out.mkdir(parents=True, exist_ok=True)
models = json.loads((build.SRC / "assets/braids/models.json").read_text())
models = [m for m in models if m["id"] >= 3 and (args.model is None or m["id"] == args.model)]
if not models:
    parser.error("model must be in 3..47")
header = args.out / "full.h"
subprocess.run([sys.executable, build.SRC / "tools/gen_braids.py", header], check=True)
original = header.read_text()


def restrict(source, cls, selected):
    pattern = r"(static void braids_" + cls + r"_dispatch\([^{}]+\) \{\n switch\(s->shape_\) \{\n)(.*?)(default:.*?\n\}\n\}\n)"

    def replace(match):
        cases = [line for line in match[2].splitlines(True) if line.startswith("case " + str(selected) + ": ")]
        assert len(cases) == 1, (cls, selected)
        return match[1] + cases[0] + match[3]

    result, count = re.subn(pattern, replace, source, flags=re.S)
    assert count == 1, cls
    return result


rows = []
for model in models:
    upstream = model["upstream"]
    source = restrict(original, "MacroOscillator", upstream)
    if upstream >= 13:
        source = restrict(source, "DigitalOscillator", upstream - 13)
    folder = args.out / str(model["id"])
    folder.mkdir(exist_ok=True)
    (folder / "bank.h").write_text(source)
    cfile, obj = folder / "probe.c", folder / "probe.o"
    cfile.write_text('''/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
void *memset(void *, int, unsigned);
#include "bank.h"
typedef char probe_core_size[(sizeof(braids_MacroOscillator) == 17000) ? 1 : -1];
void probe_init(braids_MacroOscillator *s) {
    memset(s, 0, sizeof *s);
    braids_MacroOscillator_Init(s);
}
void probe_run(braids_MacroOscillator *s, const uint8_t *sync,
               int16_t *out, int16_t pitch, int16_t timbre, int16_t color) {
    s->shape_ = ''' + str(upstream) + ''';
    braids_MacroOscillator_set_pitch(s, pitch);
    braids_MacroOscillator_set_parameters(s, timbre, color);
    braids_MacroOscillator_Render(s, sync, out, 24);
}
void probe_strike(braids_MacroOscillator *s) { braids_MacroOscillator_Strike(s); }
''')
    build.tc("cc", *build.CFLAGS, "-c", cfile, "-o", obj)
    sections = build.tc("common/bin/objdump", "-h", obj)
    (folder / "sections.txt").write_text(sections)
    sizes = [(name, int(size, 16)) for name, size in re.findall(r"^\s*\d+\s+(\S+)\s+([0-9a-f]+)\s", sections, re.M)]
    code = sum(size for name, size in sizes if name == ".text" or name.startswith(".text."))
    data = sum(size for name, size in sizes if name.startswith((".rodata", ".data")))
    row = {"id": model["id"], "upstream": upstream, "name": model["name"],
           "isolated_code_bytes": code, "isolated_table_bytes": data,
           "isolated_flash_bytes": code + data, "core_state_bytes": 17000, "part_state_bytes": 17324}
    rows.append(row)
    print(f"{model['id']:2} {model['name']:12} code {code:5} tables {data:5} total {code + data:5}", flush=True)
with (args.out / "flash.csv").open("w") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
