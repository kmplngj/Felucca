#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Rebuild both sides of the original 96 kHz C++ / C bit comparison offline."""
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
dst = root / "build/braids-reference"
src = root / "assets/braids/upstream"
for folder in ("braids", "stmlib/utils"):
    (dst / folder).mkdir(parents=True, exist_ok=True)
for f in src.iterdir():
    if f.suffix not in (".h", ".cc"):
        continue
    folder = "stmlib" if f.name == "stmlib.h" else "stmlib/utils" if f.name in ("dsp.h", "random.h", "random.cc") else "braids"
    shutil.copyfile(f, dst / folder / f.name)
subprocess.run([sys.executable, str(root / "tools/gen_braids.py"), str(dst / "reference.h"), "--reference"], check=True)
subprocess.run(["cc", "-O2", "-fwrapv", "-I" + str(dst), "-c", str(root / "tests/braids_reference_port.c"), "-o", str(dst / "port.o")], check=True)
files = [root / "tests/braids_reference.cc", *(dst / "braids" / (f + ".cc") for f in ("analog_oscillator", "digital_oscillator", "macro_oscillator", "resources")), dst / "stmlib/utils/random.cc", dst / "port.o"]
subprocess.run(["c++", "-O2", "-fwrapv", "-I" + str(dst), *map(str, files), "-o", str(dst / "ref_compare")], check=True)
subprocess.run([str(dst / "ref_compare")], check=True)
