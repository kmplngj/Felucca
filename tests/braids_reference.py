#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare pinned 96 kHz C++ / C offline, with the WAV LINE endpoint guarded."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, default=root / "build/braids-reference")
parser.add_argument("--sanitize-bounds", action="store_true")
args = parser.parse_args()
dst = args.out.resolve()
src = root / "assets/braids/upstream"
for folder in ("braids", "stmlib/utils"):
    (dst / folder).mkdir(parents=True, exist_ok=True)
for f in src.iterdir():
    if f.suffix not in (".h", ".cc"):
        continue
    folder = "stmlib" if f.name == "stmlib.h" else "stmlib/utils" if f.name in ("dsp.h", "random.h", "random.cc") else "braids"
    shutil.copyfile(f, dst / folder / f.name)

# Full TIMBRE reaches scan segment 63 at block 14. The pinned source reads
# wave_line[64] from a 64-entry array there. Comparing that undefined read across
# different C/C++ layouts is not a DSP oracle. Duplicate the terminal wave in
# this build copy, matching gen_braids.py --reference and production MACRO's
# existing endpoint clamp. Leave the pinned, hash-verified sources untouched.
reference = dst / "braids/digital_oscillator.cc"
def wave_line_endpoint(match):
    values = re.findall(r"\b\d+\b", match[2])
    assert len(values) == 64
    return match[1] + match[2].rstrip() + ", " + values[-1] + "\n" + match[3]
text, endpoints = re.subn(r"(static const uint8_t wave_line\[\] = \{)(.*?)(\};)",
                         wave_line_endpoint, reference.read_text(), flags=re.S)
assert endpoints == 1
reference.write_text(text)
print("reference: WAV LINE terminal-wave guard on both C++ and C; all model/control comparisons retained", flush=True)
subprocess.run([sys.executable, str(root / "tools/gen_braids.py"), str(dst / "reference.h"), "--reference"], check=True)
flags = ["-O2", "-fwrapv"]
if args.sanitize_bounds:
    flags += ["-fsanitize=bounds", "-fno-sanitize-recover=bounds"]
subprocess.run(["cc", *flags, "-I" + str(dst), "-c", str(root / "tests/braids_reference_port.c"), "-o", str(dst / "port.o")], check=True)
files = [root / "tests/braids_reference.cc", *(dst / "braids" / (f + ".cc") for f in ("analog_oscillator", "digital_oscillator", "macro_oscillator", "resources")), dst / "stmlib/utils/random.cc", dst / "port.o"]
subprocess.run(["c++", *flags, "-I" + str(dst), *map(str, files), "-o", str(dst / "ref_compare")], check=True)
subprocess.run([str(dst / "ref_compare")], check=True)
