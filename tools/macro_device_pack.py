#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generate offline MACRO FM-1 device fixtures through the real firmware serializer.

First use: uv run --locked --group build tools/macro_device_pack.py --generate-headers
Later: python3 tools/macro_device_pack.py --out build/macro-device-pack-another
Requires a host C compiler and macro-profile generated headers, not a JieLi build.
Writes files only. Importing A..D in the WebApp is a separate, explicit device action.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
STEMS = ("A-legacy-poly", "B-bank-heavy", "C-mixed", "D-song")
PROJECT_PARSER = "kmplngj/Felucca-WebApp:fm1backup.js:readProject (felucca-project v1)"


def vlq(value):
    out = [value & 127]
    while value >> 7:
        value >>= 7
        out.insert(0, (value & 127) | 128)
    return bytes(out)


def midi_workload():
    """SMF0, 480 PPQN, 120 BPM, exactly 64 seconds, no dependencies or device I/O."""
    events = []
    phases = []

    def at(seconds, data):
        events.append((round(seconds * 960), len(events), bytes(data)))

    def cc(seconds, channel, control, value):
        at(seconds, [0xB0 | channel, control, value])

    def notes(start, duration, channel, pitches):
        for pitch in pitches:
            at(start, [0x90 | channel, pitch, 100])
            at(start + duration, [0x80 | channel, pitch, 0])

    at(0, b"\xff\x51\x03\x07\xa1\x20")
    at(0, b"\xff\x58\x04\x04\x02\x18\x08")
    for channel in range(4):
        cc(0, channel, 64, 0)
        cc(0, channel, 123, 0)
    for channel in range(3):
        start = channel * 8
        phases.append({"start_seconds": start, "end_seconds": start + 8,
                       "workload": f"channel {channel + 1}: eight-note chord, sustain, explicit note-offs"})
        cc(start + 0.25, channel, 64, 127)
        notes(start + 0.5, 5, channel, [48, 52, 55, 59, 60, 64, 67, 71])
        cc(start + 6, channel, 64, 0)
    phases.append({"start_seconds": 24, "end_seconds": 56,
                   "workload": "channels 1-4 simultaneously, two notes each, repeated strikes and sustain"})
    for start in range(24, 56, 4):
        for channel in range(4):
            cc(start, channel, 64, 127)
            notes(start + 0.125, 2, channel, [48 + channel * 3, 55 + channel * 3])
            cc(start + 3, channel, 64, 0)
    phases.append({"start_seconds": 56, "end_seconds": 60,
                   "workload": "channels 1-4 simultaneous strikes every 125 ms, explicit note-offs"})
    for strike in range(32):
        for channel in range(4):
            notes(56 + strike / 8, 0.0625, channel, [60 + channel + strike % 3])
    for channel in range(4):
        cc(60, channel, 64, 0)
        cc(60, channel, 123, 0)
    phases.append({"start_seconds": 60, "end_seconds": 64,
                   "workload": "release tail, no held notes or sustain"})
    at(64, b"\xff\x2f\x00")
    track, last = bytearray(), 0
    for tick, _, data in sorted(events):
        track += vlq(tick - last) + data
        last = tick
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" +
            struct.pack(">I", len(track)) + track), phases


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def compile_helper(gen, output):
    resolved = json.loads((gen / "resolved-profile.json").read_text())
    if resolved.get("profile") != "macro" or 14 not in resolved.get("engine_ids", []):
        raise ValueError("generated headers must select the macro profile including engine 14")
    compiler = shlex.split(os.environ.get("CC", "cc"))
    command = [*compiler, "-O1", "-w", "-UNDEBUG", "-DFELUCCA_ARENA_CHECK=1",
               "-I" + str(gen), "-I" + str(ROOT / "firmware/src"),
               str(ROOT / "tools/macro_device_pack.c"), "-lm", "-o", str(output)]
    subprocess.run(command, cwd=ROOT, check=True)
    return command, subprocess.check_output([*compiler, "--version"], text=True).splitlines()[0]


def generate(out, gen, candidate=None):
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"output directory is not empty: {out}; choose a new --out")
    out.mkdir(parents=True, exist_ok=True)
    host = ROOT / "build/host"
    host.mkdir(parents=True, exist_ok=True)
    helper = host / "macro_device_pack"
    command, compiler = compile_helper(gen, helper)
    check = subprocess.check_output([str(helper), str(out)], cwd=ROOT, text=True)
    print(check, end="")
    projects = json.loads((out / "firmware-projects.json").read_text())
    revision = git("rev-parse", "HEAD")
    firmware = re.search(r'^#define FELUCCA_VERSION "([^"]+)"',
                         (ROOT / "firmware/src/felucca.c").read_text(), re.M).group(1)
    for slot, stem in enumerate(STEMS):
        data = (out / f"{stem}.fun10").read_bytes()
        project = {"format": "felucca-project", "version": 1, "firmware": firmware,
                   "slot": slot, "object": {"size": len(data), "crc": zlib.crc32(data),
                   "data": base64.b64encode(data).decode("ascii")}}
        (out / f"{stem}.felucca-project.json").write_text(json.dumps(project, indent=2) + "\n")
    midi, phases = midi_workload()
    (out / "macro-ch1-4.mid").write_bytes(midi)
    inputs = [p for folder in ("firmware/src", "firmware/engines/src", "assets/braids")
              for p in sorted((ROOT / folder).rglob("*")) if p.is_file()]
    inputs += [ROOT / p for p in ("tools/macro_device_pack.c", "tools/macro_device_pack.py",
               "tools/profile.py", "tests/hostsim.c", "tests/ui_test.c", "profiles/macro.json", "profiles/catalog.json")]
    source_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in sorted(set(inputs))}
    generated = {p.name: sha256(p) for p in sorted(gen.iterdir()) if p.suffix in (".h", ".inc")}
    manifest = {
        "format": "felucca-macro-device-pack", "version": 1,
        "source_revision": revision, "device_candidate": candidate or revision,
        "profile": "macro", "required_engine_ids": [0, 9, 12, 14],
        "device_validation": "pending; generated/validated on host only",
        "import_parser": PROJECT_PARSER,
        "prerequisites": ["Export a complete backup and individually export existing A, B, C, D before importing.",
            "All four slots A-D must be disposable. Import explicitly replaces the chosen saved slot.",
            "Stop transport. Import each matching JSON via WebApp PROJECT > PROJECTS > slot Import, then confirm.",
            "Use A->A, B->B, C->C, D->D. Slot numbers inside files are advisory; the clicked UI slot wins.",
            "Load is a separate action. D SONG references A/B/C sequences and keeps D sounds.",
            "The generator does not contact a device, import, restore, load, or send MIDI."],
        "slots": [{"slot": chr(65 + i), "slot_index": i, "backup_object_id": i + 2,
                   "file": f"{stem}.felucca-project.json", "raw": f"{stem}.fun10"}
                  for i, stem in enumerate(STEMS)],
        "setup": {"bpm": 120, "clock": "internal", "midi_in": "CH1-4", "reverb_type": "ROOM",
                  "all_tracks": {"level": 64, "attack": 0, "decay": 0, "sustain": 100, "release": 25,
                      "chorus": 20, "delay": 20, "reverb": 35, "length": 16, "division": "1/16",
                      "gate": 80, "swing": 0, "arp": "OFF", "voice_request": "POLY"},
                  "macro_controls": {"SHAPE": "per project/track", "TIMBRE": 64, "COLOR": 64,
                      "TUNE": 0, "CUT": 110, "RES": 8, "DRIVE": 127, "FINE": 0},
                  "voice_policy": "Eight shared legacy voices; models >=3 cap each part at one voice. Chords request allocation; they do not promise all notes sound."},
        "midi": {"file": "macro-ch1-4.mid", "seconds": 64, "channels": [1, 2, 3, 4],
                 "tempo_bpm": 120, "playback": "Transport stopped; play the SMF once with original channels, no looping or transposition.",
                 "phases": phases},
        "song_seconds": 66, "song_expected": "Four 16-second sections, then a two-second silent section, automatic STOP; D sounds retained.",
        "host_validation": check.strip().splitlines(), "compiler": compiler, "compile_command": command,
        "source_sha256": source_hashes, "generated_sha256": generated,
        "files_sha256": {p.name: sha256(p) for p in sorted(out.iterdir()) if p.is_file()},
        **projects,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Generated {len(STEMS)} importable projects, song, MIDI and manifest: {out}")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "build/macro-device-pack")
    ap.add_argument("--gen-dir", type=Path, default=ROOT / "build/gen")
    ap.add_argument("--generate-headers", action="store_true", help="generate macro/UI assets only; use the locked build dependency group")
    ap.add_argument("--candidate", help="installed firmware commit/package label, recorded separately from source revision")
    args = ap.parse_args(argv)
    try:
        if args.generate_headers:
            os.environ["FELUCCA_PROFILE"] = "macro"
            sys.path.insert(0, str(ROOT / "tools"))
            import build
            build.GEN = args.gen_dir.resolve()
            build.generate()
        generate(args.out.resolve(), args.gen_dir.resolve(), args.candidate)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        ap.exit(1, f"macro device pack: {error}\n")


if __name__ == "__main__":
    main()
