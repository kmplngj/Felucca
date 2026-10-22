#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Burst/silence equivalence for #153, without merging its DSP dependencies.

The source adapter adds force-off and skip counters only to ignored host copies.
Every insertion is exact-count checked; changed DSP requires adapter review.
Default: current firmware/src/fx.c. --fx-source accepts PR #41/#159/#172 sources.
"""
import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


class EquivalenceMismatch(ValueError):
    """Successful renders disagree on audio/state or violate a rest gate."""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"FX test adapter requires exactly one {old!r}; review changed DSP")
    return source.replace(old, new)


def instrument(source):
    if "hall_rest" not in source and "cho_live" not in source and "sp_live" not in source:
        return None, False
    source = replace_once(source, "rc = fx.cho_live", "rc = fx_test_force || fx.cho_live")
    source = replace_once(source, "rd = fx.dly_live", "rd = fx_test_force || fx.dly_live")
    source = replace_once(source, "fx.cho_ph += n * cinc, fx.cho_w += n;",
                          "fx_test_skips[0]++; fx.cho_ph += n * cinc, fx.cho_w += n;")
    source = replace_once(source, "else\n        fx.dly_w += n;",
                          "else { fx_test_skips[1]++; fx.dly_w += n; }")
    source = replace_once(source, "if (!hall_rest(rev_in, n))",
                          "if (fx_test_force || !hall_rest(rev_in, n))")
    source = replace_once(source, "hl.ph += HL_LFO;\n    return 1;",
                          "fx_test_skips[2]++; hl.ph += HL_LFO;\n    return 1;")
    spring = "sp_live" in source
    if spring:
        if "static __attribute__((noinline)) int spring_rest(" in source:
            source = replace_once(source, "if (!spring_rest(rev_in, n))",
                                  "if (fx_test_force || !spring_rest(rev_in, n))")
            source = replace_once(source, "fx.sp_w = (uint16_t)(fx.sp_w + n);\n    return 1;",
                                  "fx_test_skips[3]++; fx.sp_w = (uint16_t)(fx.sp_w + n);\n    return 1;")
        else:
            source = replace_once(source, "if (!fx.sp_live", "if (!fx_test_force && !fx.sp_live")
            source = replace_once(source, "fx.sp_w = (uint16_t)(fx.sp_w + n);\n        return;",
                                  "fx_test_skips[3]++; fx.sp_w = (uint16_t)(fx.sp_w + n);\n        return;")
    return "static int fx_test_force;\nstatic uint64_t fx_test_skips[4];\n" + source, spring


def build(source, out, cc, flags, spring, timeout):
    out.mkdir(parents=True, exist_ok=True)
    fx = out / "fx_instrumented.c"
    fx.write_text(source)
    hostsim = (ROOT / "tests/hostsim.c").read_text()
    hostsim = replace_once(hostsim, '#include "../firmware/src/fx.c"', f'#include "{fx}"')
    hostsim = hostsim.replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
    host = out / "hostsim_instrumented.c"
    host.write_text(hostsim)
    binary = out / "fx_rest_test"
    subprocess.run(cc + flags + ["-w", "-I" + str(ROOT / "build/gen"),
                   "-I" + str(ROOT / "firmware/src"), f'-DFX_TEST_HOSTSIM="{host}"',
                   f"-DFX_TEST_SPRING={int(spring)}",
                   str(ROOT / "tests/fx_rest_test.c"), "-lm", "-o", str(binary)], check=True, timeout=timeout)
    return binary


def compare(binary, spring, timeout, boundary=False):
    rows = []
    for forced in (0, 1):
        command = [str(binary), str(forced)] + (["boundary"] if boundary else [])
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise ValueError(f"render exited {result.returncode}: {shlex.join(command)}\n{result.stderr.strip()}")
        rows.append([line.split() for line in result.stdout.splitlines()])
    ids = {f"{model}/boundary/{sign}" for model in range(3) for sign in (-1, 1)}
    ids |= {f"0/fixed/{lp}/{fb}/{color}"
            for lp in (-1, 1) for fb in (0, 127) for color in (0, 127)}
    if not boundary:
        ids |= {f"{model}/{feedback}/{sends}/{(fb + sends) % 3}"
                for model in range(3) for fb, feedback in enumerate((0, 60, 120)) for sends in range(1, 8)}
    expected = len(ids)
    if len(rows[0]) != expected or len(rows[1]) != expected:
        raise ValueError(f"expected {expected} configurations in each run")
    for rendered in rows:
        for row in rendered:
            if len(row) != 8:
                raise ValueError("expected configuration, two digests, four skip counters and gate errors")
            if row[0] not in ids:
                raise ValueError(f"invalid configuration ID: {row[0]!r}")
            if any(not re.fullmatch(r"[0-9a-f]{16}", field) for field in row[1:3]):
                raise ValueError(f"{row[0]}: invalid audio/state digest")
            if any(not re.fullmatch(r"[0-9]+", field) for field in row[3:]):
                raise ValueError(f"{row[0]}: expected nonnegative skip/gate counters")
        if len({row[0] for row in rendered}) != expected:
            raise ValueError("duplicate configuration IDs")
    errors = []
    mismatch = False
    totals = [0] * 4
    for normal, forced in zip(*rows):
        if normal[0] != forced[0]:
            raise ValueError("normal and forced-off configuration IDs differ")
        if normal[:3] != forced[:3]:
            errors.append(f"{normal[0]}: audio/state differs with rest forced off")
            mismatch = True
        skips = [int(n) for n in normal[3:7]]
        if int(normal[7]) or int(forced[7]):
            errors.append(f"{normal[0]}: skipped input/live state ({normal[7]}/{forced[7]})")
            mismatch = True
        if any(int(n) for n in forced[3:7]):
            errors.append(f"{normal[0]}: forced-off path still skips")
        model = int(normal[0].split("/")[0])
        required = [0, 1] + ([2] if model == 2 else []) + ([3] if model == 1 and spring else [])
        for bus in required:
            if skips[bus] == 0:
                errors.append(f"{normal[0]}: bus {bus} never skipped")
        totals = [a + b for a, b in zip(totals, skips)]
    if errors:
        raise (EquivalenceMismatch if mismatch else ValueError)("\n".join(errors))
    return totals


def mutation_check(source, out, cc, spring, timeout, name, old, new, boundary=True):
    broken = replace_once(source, old, new)
    binary = build(broken, out / ("mutation_" + name.lower()), cc, ["-O2"], spring, timeout)
    try:
        compare(binary, spring, timeout, boundary=boundary)
    except EquivalenceMismatch:
        print(f"FX rest: deliberate {name} mutation detected by reference/gate check", flush=True)
    else:
        raise ValueError(f"deliberately broken {name} passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fx-source", type=Path, default=ROOT / "firmware/src/fx.c")
    parser.add_argument("--require-rest", action="store_true", help="fail instead of skip if dependency is absent")
    parser.add_argument("--mutation-check", action="store_true", help="also verify broken HALL/SPRING advances are detected")
    parser.add_argument("--out", type=Path, default=ROOT / "build/host/fx_rest")
    parser.add_argument("--timeout", type=float, default=180, help="seconds per compile/render subprocess (default: 180)")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    started = time.monotonic()
    raw = args.fx_source.read_text()
    source, spring = instrument(raw)
    if source is None:
        print("FX rest: SKIP (#153 depends on unmerged #41; no silent-bus paths in selected fx.c)")
        return int(args.require_rest)
    cc = shlex.split(args.cc)
    print(f"FX rest: source={args.fx_source.resolve()} sha256={hashlib.sha256(raw.encode()).hexdigest()}", flush=True)
    out = args.out.resolve()
    print("FX rest: harness sha256=" + hashlib.sha256((ROOT / "tests/fx_rest_test.c").read_bytes()).hexdigest(), flush=True)
    version = subprocess.run(cc + ["--version"], check=True, capture_output=True, text=True, timeout=args.timeout)
    print(f"FX rest: {version.stdout.splitlines()[0]}", flush=True)
    novec = ["-fno-vectorize", "-fno-slp-vectorize"]
    probe = subprocess.run(cc + novec + ["-x", "c", "-c", "-o", os.devnull, "-"],
                           input="", text=True, capture_output=True, timeout=args.timeout)
    if probe.returncode:
        novec = ["-fno-tree-vectorize", "-fno-tree-slp-vectorize"]
    for name, flags in (("O2", ["-O2"]), ("Os", ["-Os"] + novec)):
        print(f"FX rest: compiler={shlex.join(cc + flags)}", flush=True)
        binary = build(source, out / name, cc, flags, spring, args.timeout)
        totals = compare(binary, spring, args.timeout)
        print(f"FX rest {name}: 77 audio/state matches; input/live gates intact; skips chorus/delay/HALL/SPRING={totals}", flush=True)
    if not spring:
        print("FX rest: SPRING skip assertion pending #39/#172 (SPRING sound/state comparison ran)")
    # Mandatory compact controls cover chorus/delay advancement and an input
    # scan that overlooks the final sample. They never edit the selected source.
    for name, old, new in (
        ("CHORUS", "fx_test_skips[0]++; fx.cho_ph += n * cinc, fx.cho_w += n;",
         "fx_test_skips[0]++; fx.cho_ph += n * cinc, fx.cho_w += n - 1u;"),
        ("DELAY", "fx_test_skips[1]++; fx.dly_w += n;",
         "fx_test_skips[1]++; fx.dly_w += n - 1u;"),
        ("EARLY_GATE", "for (i = 0; i < n; i++)\n        z |= x[i];",
         "for (i = 0; i + 1u < n; i++)\n        z |= x[i];"),
    ):
        mutation_check(source, out, cc, spring, args.timeout, name, old, new)
    if args.mutation_check:
        mutations = [("HALL", "fx_test_skips[2]++; hl.ph += HL_LFO;",
                      "fx_test_skips[2]++; hl.ph += HL_LFO - 1u;")]
        if spring:
            mutations.append(("SPRING", "fx_test_skips[3]++; fx.sp_w = (uint16_t)(fx.sp_w + n);",
                              "fx_test_skips[3]++; fx.sp_w = (uint16_t)(fx.sp_w + n - 1u);"))
        for name, old, new in mutations:
            mutation_check(source, out, cc, spring, args.timeout, name, old, new)
    print(f"FX rest: PASS ({time.monotonic() - started:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"FX rest: FAIL: {error}", file=sys.stderr)
        sys.exit(1)
