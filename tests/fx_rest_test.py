#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Burst/silence equivalence for #153, without merging its DSP dependencies.

The source adapter adds force-off and skip counters only to ignored host copies.
Every insertion is exact-count checked; changed DSP requires adapter review.
Default: current firmware/src/fx.c. --fx-source accepts PR #41/#159/#172 sources.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


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


def build(source, out, cc, flags):
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
                   str(ROOT / "tests/fx_rest_test.c"), "-lm", "-o", str(binary)], check=True)
    return binary


def compare(binary, spring):
    rows = []
    for forced in (0, 1):
        result = subprocess.run([str(binary), str(forced)], check=True, capture_output=True, text=True)
        rows.append([line.split() for line in result.stdout.splitlines()])
    if len(rows[0]) != 63 or len(rows[1]) != 63:
        raise ValueError("expected 63 configurations in each run")
    errors = []
    totals = [0] * 4
    for normal, forced in zip(*rows):
        if len(normal) != 7 or len(forced) != 7:
            raise ValueError("expected configuration, two digests, and four skip counters")
        if normal[:3] != forced[:3]:
            errors.append(f"{normal[0]}: audio/state differs with rest forced off")
        skips = [int(n) for n in normal[3:]]
        if any(int(n) for n in forced[3:]):
            errors.append(f"{normal[0]}: forced-off path still skips")
        model = int(normal[0].split("/")[0])
        required = [0, 1] + ([2] if model == 2 else []) + ([3] if model == 1 and spring else [])
        for bus in required:
            if skips[bus] == 0:
                errors.append(f"{normal[0]}: bus {bus} never skipped")
        totals = [a + b for a, b in zip(totals, skips)]
    if errors:
        raise ValueError("\n".join(errors))
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fx-source", type=Path, default=ROOT / "firmware/src/fx.c")
    parser.add_argument("--require-rest", action="store_true", help="fail instead of skip if dependency is absent")
    parser.add_argument("--mutation-check", action="store_true", help="verify broken HALL/SPRING advances are detected")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    args = parser.parse_args()
    raw = args.fx_source.read_text()
    source, spring = instrument(raw)
    if source is None:
        print("FX rest: SKIP (#153 depends on unmerged #41; no silent-bus paths in selected fx.c)")
        return int(args.require_rest)
    cc = shlex.split(args.cc)
    print(f"FX rest: source={args.fx_source.resolve()} sha256={hashlib.sha256(raw.encode()).hexdigest()}", flush=True)
    out = ROOT / "build/host/fx_rest"
    novec = ["-fno-vectorize", "-fno-slp-vectorize"]
    probe = subprocess.run(cc + novec + ["-x", "c", "-c", "-o", os.devnull, "-"],
                           input="", text=True, capture_output=True)
    if probe.returncode:
        novec = ["-fno-tree-vectorize", "-fno-tree-slp-vectorize"]
    for name, flags in (("O2", ["-O2"]), ("Os", ["-Os"] + novec)):
        print(f"FX rest: compiler={shlex.join(cc + flags)}", flush=True)
        binary = build(source, out / name, cc, flags)
        totals = compare(binary, spring)
        print(f"FX rest {name}: 63 audio/state matches; skips chorus/delay/HALL/SPRING={totals}", flush=True)
    if not spring:
        print("FX rest: SPRING skip assertion pending #39/#172 (SPRING sound/state comparison ran)")
    if args.mutation_check:
        broken = replace_once(source, "fx_test_skips[2]++; hl.ph += HL_LFO;",
                               "fx_test_skips[2]++; hl.ph += HL_LFO - 1u;")
        binary = build(broken, out / "mutation", cc, ["-O2"])
        try:
            compare(binary, spring)
        except ValueError as error:
            if "audio/state differs" not in str(error):
                raise
            print("FX rest: deliberate hall_rest drift mutation detected")
        else:
            raise ValueError("deliberately broken hall_rest passed")
        if spring:
            broken = replace_once(source, "fx_test_skips[3]++; fx.sp_w = (uint16_t)(fx.sp_w + n);",
                                   "fx_test_skips[3]++; fx.sp_w = (uint16_t)(fx.sp_w + n - 1u);")
            binary = build(broken, out / "spring_mutation", cc, ["-O2"])
            try:
                compare(binary, spring)
            except ValueError as error:
                if "audio/state differs" not in str(error):
                    raise
                print("FX rest: deliberate SPRING write-index mutation detected")
            else:
                raise ValueError("deliberately broken SPRING advance passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"FX rest: FAIL: {error}", file=sys.stderr)
        sys.exit(1)
