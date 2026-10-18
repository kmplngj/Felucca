#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare real INSERT PCM and complete persistent state with the original quotient."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"INSERT adapter requires exactly one {old!r}; review changed DSP")
    return source.replace(old, new)


def generation(out):
    spec = importlib.util.spec_from_file_location("insert_generator", ROOT / "tools/gen_tables.py")
    generator = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(generator)
    header = out / "felucca_tables.h"
    generator.main(header)
    tables = {}
    for name in ("SVF_G", "INS_LPK"):
        match = re.search(r"static const uint16_t " + name + r"\[128\] = \{([^}]+)\};", header.read_text())
        if not match:
            raise ValueError(f"missing uint16_t {name}[128]")
        tables[name] = [int(x) for x in match[1].split(",") if x.strip()]
    if len(tables["SVF_G"]) != 128 or len(tables["INS_LPK"]) != 128:
        raise ValueError("expected 128 coefficients")
    for g, q in zip(tables["SVF_G"], tables["INS_LPK"]):
        if not 0 <= g << 16 <= 0xffffffff or not 0 <= q <= 0xffff or q != (g << 16) // (4096 + g):
            raise ValueError("coefficient differs from bounded original formula")
    for tangent in (-1, 16):
        with patch.object(generator.math, "tan", return_value=tangent):
            try:
                generator.main(out / "invalid.h")
            except SystemExit as error:
                if "does not fit uint32_t" not in str(error):
                    raise
            else:
                raise ValueError("generator accepted out-of-range numerator")
    with patch.object(generator.fe, "svf_g", return_value=[]):
        try:
            generator.main(out / "invalid.h")
        except SystemExit as error:
            if "quantization differs" not in str(error):
                raise
        else:
            raise ValueError("generator accepted engine quantization drift")
    print("INSERT coefficients: 128 exact uint16 entries; numerator bounds and quantization-drift rejection pass", flush=True)


def build(raw, out, cc, flags, header):
    out.mkdir(parents=True, exist_ok=True)
    fx = out / "fx.c"
    fx.write_text(raw)
    host = (ROOT / "tests/hostsim.c").read_text()
    host = replace_once(host, '#include "../firmware/src/fx.c"', f'#include "{fx}"')
    host = host.replace('"../firmware/src/', f'"{ROOT}/firmware/src/')
    inc = out / "hostsim.c"
    inc.write_text(host)
    binary = out / "insert_lpk_test"
    subprocess.run(cc + flags + ["-w", "-I" + str(header), "-I" + str(ROOT / "build/gen"),
                   "-I" + str(ROOT / "firmware/src"), f'-DINSERT_LPK_HOSTSIM="{inc}"',
                   str(Path(__file__).with_suffix(".c")), "-lm", "-o", str(binary)], check=True)
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/host/insert_lpk")
    parser.add_argument("--sanitize", action="store_true", help="run the sanitizer configuration instead of O2/Os")
    parser.add_argument("--mutation-check", action="store_true", help="require an off-by-one coefficient to change PCM/state")
    args = parser.parse_args()
    cc = shlex.split(args.cc)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    generation(out)
    raw = (ROOT / "firmware/src/fx.c").read_text()
    formula = replace_once(raw, "return INS_LPK[clamp(c, 0, 127)];",
                           "uint32_t g = SVF_G[clamp(c, 0, 127)];\n    return (int32_t)((g << 16) / (4096u + g));")
    novec = ["-fno-vectorize", "-fno-slp-vectorize"]
    probe = subprocess.run(cc + novec + ["-x", "c", "-c", "-o", os.devnull, "-"], input="", text=True, capture_output=True)
    if probe.returncode:
        novec = ["-fno-tree-vectorize", "-fno-tree-slp-vectorize"]
    configs = [("O2", ["-O2"]), ("Os", ["-Os"] + novec)]
    if args.sanitize:
        configs = [("san", ["-O1", "-g", "-fsanitize=address,undefined",
                        "-fno-sanitize=signed-integer-overflow,shift,bounds,object-size,pointer-overflow",
                        "-fno-sanitize-recover=undefined"])]
    for name, flags in configs:
        print(f"INSERT formula comparison: {shlex.join(cc + flags)}", flush=True)
        bins = [build(source, out / name / variant, cc, flags, out)
                for variant, source in (("lookup", raw), ("formula", formula))]
        for tracks in (1, 4):
            result = [subprocess.run([str(binary), str(tracks)], check=True, stdout=subprocess.PIPE).stdout for binary in bins]
            if not result[0] or result[0] != result[1]:
                raise ValueError(f"{name}/{tracks} tracks: PCM or persistent INSERT state differs")
            print(f"INSERT {name}/{tracks} tracks: 2048 blocks PCM/full state match ({len(result[0])} bytes)", flush=True)
    if args.mutation_check:
        broken = replace_once(raw, "return INS_LPK[clamp(c, 0, 127)];",
                              "return INS_LPK[clamp(c, 0, 127)] + 1;")
        binary = build(broken, out / "mutation", cc, ["-O2"], out)
        mutated = subprocess.run([str(binary), "1"], check=True, stdout=subprocess.PIPE).stdout
        reference = subprocess.run([str(bins[1]), "1"], check=True, stdout=subprocess.PIPE).stdout
        if mutated == reference:
            raise ValueError("off-by-one coefficient mutation escaped PCM/state comparison")
        print("INSERT: off-by-one coefficient mutation detected", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"INSERT formula comparison: FAIL: {error}", file=sys.stderr)
        sys.exit(1)
