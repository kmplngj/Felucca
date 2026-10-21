#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Focused real-serializer fixture/SMF checks; needs macro build/gen, no target build.

python3 tests/macro_device_pack_test.py [--webapp ../Felucca-WebApp]
The optional WebApp path exercises its unmodified production readProject parser.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import macro_device_pack as pack


def smf_events(data):
    assert data[:4] == b"MThd"
    assert struct.unpack(">IHHH", data[4:14]) == (6, 0, 1, 480)
    assert data[14:18] == b"MTrk"
    assert struct.unpack(">I", data[18:22])[0] == len(data) - 22
    i, tick, out = 22, 0, []

    def vlq():
        nonlocal i
        value = 0
        for _ in range(4):
            b = data[i]
            i += 1
            value = value * 128 + (b & 127)
            if b < 128:
                return value
        raise AssertionError("overlong MIDI variable length number")

    while i < len(data):
        tick += vlq()
        status = data[i]
        i += 1
        if status == 255:
            kind = data[i]
            i += 1
            size = vlq()
            payload = data[i:i + size]
            i += size
            out.append((tick, status, kind, payload))
        else:
            assert status & 240 in (0x80, 0x90, 0xB0)
            out.append((tick, status, data[i], data[i + 1]))
            assert data[i] < 128 and data[i + 1] < 128
            i += 2
    assert i == len(data)
    return out


def check_midi(data):
    events = smf_events(data)
    assert events[-1] == (61440, 255, 0x2F, b"")
    assert (0, 255, 0x51, b"\x07\xa1\x20") in events
    active, pedal, channels, max_poly = set(), [0] * 4, set(), [0] * 4
    for tick, status, a, b in events:
        if status == 255:
            continue
        channel = status & 15
        assert channel < 4
        channels.add(channel)
        if status & 240 == 0x90:
            assert (channel, a) not in active
            active.add((channel, a))
            max_poly[channel] = max(max_poly[channel], sum(c == channel for c, _ in active))
        elif status & 240 == 0x80:
            assert (channel, a) in active
            active.remove((channel, a))
        elif a == 64:
            pedal[channel] = b
        elif a == 123:
            assert not any(c == channel for c, _ in active)
        if tick >= 57600:
            assert status & 240 != 0x90
    assert not active and not any(pedal) and channels == set(range(4))
    assert max_poly[:3] == [8, 8, 8] and max_poly[3] == 2
    print("SMF: standard header/tempo,64s,channels1-4,eight-note chords,sustain,paired note-offs,cleanup OK")


def check_webapp(webapp, out):
    if webapp is None:
        print("SKIP production WebApp readProject parser: pass --webapp PATH to its source checkout")
        return
    parser = webapp / "fm1backup.js"
    if not parser.is_file() or not shutil.which("node"):
        raise AssertionError("--webapp requires fm1backup.js and Node.js")
    # No copied/reimplemented client parser: import its exact checked-out source.
    script = r"""
import {readFileSync} from 'node:fs';
const {readProject} = await import(process.argv[1]);
for (const [index, name] of process.argv.slice(2).entries()) {
  const text = readFileSync(name, 'utf8'), p = readProject(text);
  if (p.slot !== index || p.size !== 3840) throw Error('wrong slot/size');
  const bad = JSON.parse(text); bad.object.crc ^= 1;
  let rejected = false;
  try { readProject(bad); } catch (_) { rejected = true; }
  if (!rejected) throw Error('corrupt CRC accepted');
}
console.log('WebApp production readProject: all four files accepted; corrupt CRCs refused');
"""
    subprocess.run(["node", "--input-type=module", "-e", script, parser.resolve().as_uri(),
                    *[str(out / f"{stem}.felucca-project.json") for stem in pack.STEMS]], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--webapp", type=Path)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="macro-device-pack-") as tmp:
        out = Path(tmp) / "pack"
        manifest = pack.generate(out, ROOT / "build/gen")
        for slot, stem in enumerate(pack.STEMS):
            file = json.loads((out / f"{stem}.felucca-project.json").read_text())
            data = base64.b64decode(file["object"]["data"], validate=True)
            assert file["format"] == "felucca-project" and file["version"] == 1
            assert file["slot"] == slot and file["object"]["size"] == 3840
            assert data == (out / f"{stem}.fun10").read_bytes()
            assert zlib.crc32(data) == file["object"]["crc"]
            assert struct.unpack("<I", data[:4])[0] == 0x46554E41
            assert data[66] == manifest["parameter_count"]
            # Real serialized engine/model bytes and first note match independent
            # slot specifications, catching a coherent but wrong fixture recipe.
            np = data[66]
            engines = ([14] * 4, [14] * 4, [14, 9, 12, 0], [14] * 4)[slot]
            models = ([0, 1, 2, 0], [26] * 4, [29, None, None, None], [0, 26, 29, 38])[slot]
            for track in range(4):
                base = 68 + track * (np + 2 + 64 * 9)
                assert data[base + np] == engines[track]
                if models[track] is not None:
                    assert data[base + np - 8] - 64 == models[track]
                assert data[base + np + 2] == 48 + 3 * track + 2 * slot
        assert manifest["projects"][3]["sections"] == [
            {"slots": [0, 0, 0, 0], "repeat": 8}, {"slots": [1, 2, 0, 1], "repeat": 8},
            {"slots": [2, 0, 1, 2], "repeat": 8}, {"slots": [1, 1, 1, 1], "repeat": 8},
            {"slots": [4, 4, 4, 4], "repeat": 1}]
        for name, expected in manifest["files_sha256"].items():
            assert hashlib.sha256((out / name).read_bytes()).hexdigest() == expected
        helper = ROOT / "build/host/macro_device_pack"
        subprocess.run([str(helper), "--verify", str(out)], check=True)
        raw = out / f"{pack.STEMS[0]}.fun10"
        good = raw.read_bytes()
        for corrupt in (good[:100] + bytes([good[100] ^ 1]) + good[101:], good + b"\x00", good[:-1]):
            raw.write_bytes(corrupt)
            result = subprocess.run([str(helper), "--verify", str(out)], capture_output=True)
            assert result.returncode != 0
        raw.write_bytes(good)
        try:
            pack.generate(out, ROOT / "build/gen")
        except ValueError as error:
            assert "not empty" in str(error)
        else:
            raise AssertionError("existing output silently overwritten")
        check_midi((out / "macro-ch1-4.mid").read_bytes())
        check_webapp(args.webapp, out)
    print("MACRO device pack focused checks passed (no physical device accessed)")


if __name__ == "__main__":
    main()
