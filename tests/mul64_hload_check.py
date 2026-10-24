#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Static inventory of 64-bit multiplies next to 16-bit loads in the target disassembly (issue #425).

felucca-bsp documents a pi32v2 failure in which code that inlines 32x32->64 multiplies among 16-bit
loads now and then leaves a register one bit off (github.com/hugelton/felucca-bsp, docs/CPU.md; an
idea source only, no text copied). This tool does not detect or reproduce that fault. It counts, per
function of build/felucca.dis, the pi32v2 instructions of these two kinds and the pairs that lie
within N instructions of each other, and marks each function by what reaches it:

  A  the audio ISR (fm1_alnk0_irq)       T  the TIMER5 scan (fm1_timer5_irq)
  C  the CPU1 job (c1_parts)             -  neither: main loop (or unreached / not in the IR)

Instruction forms, as printed by the JieLi objdump (verified against build/felucca.dis):
  64-bit multiply   rX_rY = rA * rB (s|u)      accumulate  rX_rY += rA * rB (s|u)   (-= is accepted)
  16-bit load       rD = h[...] (s|u)          (stores, h[...] = rS, are not loads)
The window is measured in instructions in address order inside one function; it does not follow
branches. Reachability uses tools/size_fns.py's isr_reach on the unoptimized IR (build/felucca.ll)
of the same build, so a function the optimizer inlined is counted in its caller only.

  tests/mul64_hload_check.py [DIS] [--ir LL] [--window N] [--json OUT] [--top K]
                             [--fail-on-new BASELINE.json]
Exit 0 unless --fail-on-new finds an ISR/CPU1-reachable function with more multiplies near a 16-bit
load than the baseline (a JSON file this tool wrote); 2 for unusable input."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

LABEL = re.compile(r"^([A-Za-z_][A-Za-z_0-9.]*):$")
INSN = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$")
MUL64 = re.compile(r"^\s*r\d+_r\d+\s*([+-]?=)\s*r\d+\s*\*\s*r\d+\s*\(([su])\)")
HLOAD = re.compile(r"^\s*r\d+\s*=\s*h\[[^\]]*\]\s*\(([su])\)")
WINDOWS = (4, 8, 16)
# What each root set reaches. The CPU1 job is the function C1_RUN hands to core 1 (fx.c).
ROOTS = {"A": ("fm1_alnk0_irq",), "T": ("fm1_timer5_irq",), "C": ("c1_parts",)}
SOURCES = ("firmware/src", "firmware/engines/src")


def parse(lines):
    """{name: [(addr, kind)]} with kind 'M' (64-bit multiply), 'L' (16-bit load) or '.' (other).
    A function runs to the next label not starting with '.' (jump-table labels are inside)."""
    out, cur = {}, None
    for line in lines:
        m = LABEL.match(line.strip())
        if m:
            if not m.group(1).startswith("."):
                cur = out.setdefault(m.group(1), [])
            continue
        m = INSN.match(line)
        if m is None or cur is None:
            continue
        text = m.group(3).strip()
        kind = "M" if MUL64.match(text) else "L" if HLOAD.match(text) else "."
        cur.append((int(m.group(1), 16), kind))
    return out


def near(insns, n):
    """(pairs, multiplies with a load within n): within n instructions, either side"""
    mul = [i for i, (_, k) in enumerate(insns) if k == "M"]
    load = [i for i, (_, k) in enumerate(insns) if k == "L"]
    pairs = sum(1 for a in mul for b in load if abs(a - b) <= n)
    muls = sum(1 for a in mul if any(abs(a - b) <= n for b in load))
    return pairs, muls


def analyse(funcs, windows):
    rows = []
    for name, insns in funcs.items():
        kinds = [k for _, k in insns]
        row = {"name": name, "insns": len(insns), "mul64": kinds.count("M"), "hload": kinds.count("L"),
               "near_pairs": {}, "near_mul": {}}
        for n in windows:
            row["near_pairs"][str(n)], row["near_mul"][str(n)] = near(insns, n)
        if row["mul64"]:
            rows.append(row)
    return rows


def reach(ir_text):
    """{root letter: set of function names}; a root absent from the IR (c1_parts with FELUCCA_CPU2=0) is empty"""
    import size_fns as S
    present = {m.strip('"') for m in re.findall(r"^define [^\n]*?@" + S.IR_NAME, ir_text, re.M)}
    sets = {}
    for tag, roots in ROOTS.items():
        roots = tuple(r for r in roots if r in present)
        sets[tag] = S.isr_reach(ir_text, roots=roots) if roots else set()
    return sets


def sources(names=()):
    """best-effort {function: file} from the C sources (size_fns's definition scanner; names it misses,
    e.g. a definition behind attributes, fall back to the first column-0 line that opens `name(`)"""
    import size_fns as S
    out, texts = {}, {}
    for d in SOURCES:
        for f in sorted((ROOT / d).glob("*.c")):
            texts[f"{d}/{f.name}"] = f.read_text(errors="replace")
            for name in S.definitions(texts[f"{d}/{f.name}"]):
                out.setdefault(name, f"{d}/{f.name}")
    for name in names:
        if name not in out:
            rx = re.compile(r"^[A-Za-z_][^;\n]*\b" + re.escape(name) + r"\s*\([^;\n]*$", re.M)
            out[name] = next((f for f, t in texts.items() if rx.search(t)), "")
    return out


def tag(name, sets):
    return "".join(t for t in "ATC" if name in sets.get(t, ())) or "-"


def table(rows, window, top):
    key = str(window)
    rows = sorted(rows, key=lambda r: (r["tags"] == "-", -r["near_mul"][key], -r["near_pairs"][key], -r["mul64"], r["name"]))
    head = f"{'function':28} {'reach':5} {'insns':>6} {'mul64':>5} {'hload':>5} {'near_mul':>8} {'pairs':>6}  source"
    out = [f"window N={window} instructions; reach: A=audio ISR T=TIMER5 C=CPU1 job -=none", head]
    for r in rows[:top] if top else rows:
        out.append(f"{r['name']:28} {r['tags']:5} {r['insns']:6} {r['mul64']:5} {r['hload']:5} "
                   f"{r['near_mul'][key]:8} {r['near_pairs'][key]:6}  {r.get('src', '')}")
    return "\n".join(out)


def totals(rows, windows):
    out = {}
    for label, pick in (("all", lambda r: True), ("isr_or_cpu1", lambda r: r["tags"] != "-"), ("main_only", lambda r: r["tags"] == "-")):
        sel = [r for r in rows if pick(r)]
        t = {"functions": len(sel), "mul64": sum(r["mul64"] for r in sel), "hload": sum(r["hload"] for r in sel),
             "functions_with_near": {}, "near_mul": {}, "near_pairs": {}}
        for n in map(str, windows):
            t["functions_with_near"][n] = sum(1 for r in sel if r["near_mul"][n])
            t["near_mul"][n] = sum(r["near_mul"][n] for r in sel)
            t["near_pairs"][n] = sum(r["near_pairs"][n] for r in sel)
        out[label] = t
    return out


def new_findings(rows, baseline, window):
    """ISR/CPU1-reachable functions whose multiplies near a load exceed the baseline (missing = 0)"""
    key = str(window)
    if not isinstance(baseline, dict) or baseline.get("schema") != 1:
        raise ValueError("expected a schema 1 inventory object")
    windows = baseline.get("windows")
    if not isinstance(windows, list) or any(type(n) is not int or n <= 0 for n in windows):
        raise ValueError("windows must be a list of positive integers")
    if window not in windows:
        raise ValueError(f"baseline has no window N={window} (has {windows})")
    functions = baseline.get("functions")
    if not isinstance(functions, list):
        raise ValueError("functions must be a list")
    old = {}
    for row in functions:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("each function needs a nonempty name")
        name = row["name"]
        if name in old:
            raise ValueError(f"duplicate function {name}")
        counts = row.get("near_mul")
        value = counts.get(key) if isinstance(counts, dict) else None
        if type(value) is not int or value < 0:
            raise ValueError(f"{name}: near_mul N={window} must be a nonnegative integer")
        old[name] = value
    return [(r["name"], old.get(r["name"], 0), r["near_mul"][key]) for r in rows
            if r["tags"] != "-" and r["near_mul"][key] > old.get(r["name"], 0)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dis", nargs="?", default=str(ROOT / "build/felucca.dis"))
    ap.add_argument("--ir", help="unoptimized LLVM IR of the same build (default: felucca.ll beside the listing)")
    ap.add_argument("--window", "-N", type=int, default=8, help="instructions between a multiply and a load (default 8)")
    ap.add_argument("--json", help="write the machine-readable result here (default: build/mul64_hload.json)")
    ap.add_argument("--top", type=int, default=25, help="table rows (0 = all)")
    ap.add_argument("--fail-on-new", metavar="BASELINE", help="exit 1 (2 without usable IR) if an ISR/CPU1-reachable function has more "
                    "multiplies near a 16-bit load than in BASELINE (a --json file); not part of tests/run_tests.sh")
    a = ap.parse_args(argv)
    if a.window <= 0 or a.top < 0:
        ap.error("window must be positive and top must be nonnegative")
    dis = Path(a.dis)
    baseline = None
    if a.fail_on_new:                     # read first: --json may name the same file
        try:
            baseline = json.loads(Path(a.fail_on_new).read_text())
            new_findings([], baseline, a.window)  # validate before --json can overwrite the baseline
        except (OSError, ValueError) as e:
            print(f"mul64_hload: baseline: {e}", file=sys.stderr)
            return 2
    try:
        funcs = parse(dis.read_text().splitlines())
    except (OSError, UnicodeError) as e:
        print(f"mul64_hload: {e}", file=sys.stderr)
        return 2
    if not any(funcs.values()):
        print(f"mul64_hload: {dis}: no recognized function instructions", file=sys.stderr)
        return 2
    if baseline is not None:
        missing = [root for tag in "AT" for root in ROOTS[tag] if not funcs.get(root)]
        if missing:
            print(f"mul64_hload: --fail-on-new needs a full target listing; missing instructions for "
                  + ", ".join(missing), file=sys.stderr)
            return 2
    windows = sorted({*WINDOWS, a.window})
    rows = analyse(funcs, windows)
    ir = Path(a.ir) if a.ir else dis.with_name("felucca.ll")
    sets, warn = {}, None
    if ir.is_file():
        try:
            sets = reach(ir.read_text())
        except (OSError, ValueError) as e:
            print(f"mul64_hload: {e}", file=sys.stderr)
            return 2
    else:
        warn = f"no IR at {ir}: reachability unknown, every function is shown as '-'"
    if baseline is not None and not (sets.get("A") and sets.get("T")):
        # '-' would mean "main loop only" and be skipped by new_findings(): never gate on unknown reachability
        why = f"no IR at {ir}" if warn else f"{ir} lacks the audio or TIMER5 ISR root"
        print(f"mul64_hload: --fail-on-new needs reachability data: {why}. Provide the matching unoptimized "
              "LLVM IR as felucca.ll beside the listing, or pass it with --ir PATH.", file=sys.stderr)
        return 2
    src = sources([r["name"] for r in rows])
    for r in rows:
        r["tags"] = tag(r["name"], sets)
        r["src"] = src.get(r["name"], "")
    print(table(rows, a.window, a.top))
    tot = totals(rows, windows)
    for label, t in tot.items():
        print(f"{label:12} {t['functions']:3} functions with a 64-bit multiply: mul64={t['mul64']} hload={t['hload']} "
              + " ".join(f"N={n}: {t['near_mul'][n]} mul/{t['functions_with_near'][n]} fn/{t['near_pairs'][n]} pairs" for n in map(str, windows)))
    if warn:
        print("warning:", warn)
    rows.sort(key=lambda r: r["name"])
    result = {"schema": 1, "dis": str(dis), "dis_sha256": hashlib.sha256(dis.read_bytes()).hexdigest(),
              "ir_sha256": hashlib.sha256(ir.read_bytes()).hexdigest() if ir.is_file() else None,
              "windows": windows, "roots": {t: list(r) for t, r in ROOTS.items()},
              "reachable_counts": {t: len(s) for t, s in sets.items()}, "totals": tot, "functions": rows}
    out = Path(a.json) if a.json else ROOT / "build/mul64_hload.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"wrote {out}")
    if baseline is not None:
        try:
            bad = new_findings(rows, baseline, a.window)
        except (ValueError, KeyError) as e:
            print(f"mul64_hload: baseline: {e}", file=sys.stderr)
            return 2
        for name, was, now in bad:
            print(f"NEW: {name}: multiplies near a 16-bit load {was} -> {now} (N={a.window})")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
