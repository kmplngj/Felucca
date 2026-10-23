#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Reference vectors of the retired sounds (#299, part A): run the host tool and compare with the committed copy.

    python3 tests/retired_vectors.py --check  build/host/retired_vectors    # fails on any difference (run_tests.sh)
    python3 tests/retired_vectors.py --update build/host/retired_vectors    # rewrites tests/fixtures/retired_vectors.json

The binary is tests/retired_vectors.c built as in tests/run_tests.sh (u_retired_vectors). It prints the vectors, from the
firmware's own conversion code, as JSON on stdout. A difference means a conversion (or an input of it) changed: review
the diff, and only then --update. docs/legacy-formats.md section 4 describes the file and how a client compares to it.
"""
import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "retired_vectors.json"
SECTIONS = ("projects", "presets", "favourites", "load")


def generate(binary):
    out = subprocess.run([binary], check=True, stdout=subprocess.PIPE, text=True).stdout
    json.loads(out)  # must be valid JSON before it is compared or written
    return out


def describe(old, new):
    """Names of the cases that differ, for a readable failure."""
    msgs = []
    if old.get("constants") != new.get("constants"):
        msgs.append("constants differ")
    for sec in SECTIONS:
        a = {c["name"] + "|" + str(c.get("format", c.get("via", ""))): c for c in old.get(sec, [])}
        b = {c["name"] + "|" + str(c.get("format", c.get("via", ""))): c for c in new.get(sec, [])}
        for k in sorted(set(a) | set(b)):
            if k not in a:
                msgs.append("%s: new case %s" % (sec, k))
            elif k not in b:
                msgs.append("%s: missing case %s" % (sec, k))
            elif a[k] != b[k]:
                fields = [f for f in sorted(set(a[k]) | set(b[k])) if a[k].get(f) != b[k].get(f)]
                msgs.append("%s: %s changed (%s)" % (sec, k, ", ".join(fields)))
    return msgs


def main(argv):
    if len(argv) != 3 or argv[1] not in ("--check", "--update"):
        print(__doc__)
        return 2
    new = generate(argv[2])
    if argv[1] == "--update":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(new)
        print("wrote %s (%d bytes)" % (FIXTURE, len(new)))
        return 0
    if not FIXTURE.exists():
        print("FAIL: %s is missing; run with --update" % FIXTURE)
        return 1
    old = FIXTURE.read_text()
    if old == new:
        cases = sum(len(json.loads(new)[s]) for s in SECTIONS)
        print("retired vectors: %d cases identical to %s    ok" % (cases, FIXTURE.name))
        return 0
    print("FAIL: the retired-sound conversions no longer give tests/fixtures/retired_vectors.json")
    for m in describe(json.loads(old), json.loads(new)) or ["(whitespace or key order only)"]:
        print("  " + m)
    print("If the change is intended: python3 tests/retired_vectors.py --update %s, then review the diff." % argv[2])
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
