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


def project_tracks(raw):
    """Serialized track identities: 68-byte header, np values, identity, 64 nine-byte steps."""
    np = raw[66]
    stride = np + 2 + 64 * 9
    return [(raw[68 + track * stride + np], raw[69 + track * stride + np]) for track in range(4)]


def project_motion(raw, fmt, current_np):
    """Read only the stored event fields; no engine or retirement conversion is applied."""
    np = raw[66]
    modern = fmt == "FUN10"
    pos = 68 + 4 * (np + 2 + 64 * 9) + (84 if modern else 36)
    count = raw[pos]
    if count > (128 if modern else 64):
        raise ValueError("motion count exceeds the serialized format")
    width = 3 if modern else 4
    events = []
    for i in range(count):
        event = raw[pos + 4 + i * width:pos + 4 + (i + 1) * width]
        param = event[1] & 127
        if np < current_np and param >= np - 8:
            param += current_np - np
        events.append({"track": event[0] >> 6, "step": event[0] & 63, "param": param,
                       "lock": event[1] >> 7, "value": int.from_bytes(event[2:], "little", signed=True)})
    return events


def validate_projects(data):
    """Check wire identity independently of the C generator's format selection."""
    formats = {"FUN7": (0x46554E37, 3388), "FUN8": (0x46554E38, 3584), "FUN10": (0x46554E41, 3840)}
    for case in data["projects"]:
        name = case["name"]
        fmt = case["format"]
        if fmt not in formats:
            raise ValueError(f"{name}: unsupported project format {fmt}")
        raw = bytes.fromhex(case["input"])
        magic, size = formats[fmt]
        if (len(raw) != size or int.from_bytes(raw[:4], "little") != magic
                or int.from_bytes(raw[4:8], "little") != size):
            raise ValueError(f"{name}: {fmt} input magic/size does not match its format")
        if raw[66] != case["np"]:
            raise ValueError(f"{name}: {fmt} input parameter count does not match np")
        out = bytes.fromhex(case["output"])
        if (len(out) != 3840 or int.from_bytes(out[:4], "little") != 0x46554E41
                or int.from_bytes(out[4:8], "little") != 3840):
            raise ValueError(f"{name}: output is not a complete FUN10 record")
        if len(case["tracks"]) != 4:
            raise ValueError(f"{name}: track identity count is not four")
        for track, (before, after) in enumerate(zip(project_tracks(raw), project_tracks(out))):
            metadata = case["tracks"][track]
            if (metadata["engine_in"], metadata["preset_in"]) != before:
                raise ValueError(f"{name}: track {track} input identity differs from serialized input")
            if (metadata["engine_out"], metadata["preset_out"]) != after:
                raise ValueError(f"{name}: track {track} output identity differs from serialized output")
        before = project_motion(raw, fmt, out[66])
        after = project_motion(out, "FUN10", out[66])
        if case["motion_dropped"] != [event for event in before if event not in after]:
            raise ValueError(f"{name}: motion_dropped differs from serialized input/output events")


def generate(binary):
    out = subprocess.run([binary], check=True, stdout=subprocess.PIPE, text=True).stdout
    validate_projects(json.loads(out))  # reject misleading identities before --check or --update
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
    try:
        new = generate(argv[2])
    except ValueError as error:
        print(f"FAIL: retired vector wire identity: {error}")
        return 1
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
