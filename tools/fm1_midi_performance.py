#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Send the eight PR803 MIDI performance scenarios to an explicitly selected port.

Uses channel messages only; never installs firmware or writes a user-preset slot.
See docs/midi-hardware-testing.md for device setup and audio acceptance.
"""
import argparse
import datetime
import json
from pathlib import Path
import time


class Sequence:
    def __init__(self, channel):
        self.channel, self.at, self.events = channel - 1, 0.0, []

    def mark(self, label):
        self.events.append({"at_s": round(self.at, 3), "label": label})

    def send(self, status, *data):
        self.events.append({"at_s": round(self.at, 3), "bytes": [status | self.channel, *data]})
        self.at += 0.01  # Separate CC/selector bytes even on a slow physical link.

    def cc(self, number, value): self.send(0xB0, number, value)

    def nrpn(self, address, value):
        for cc, v in ((99, address >> 7), (98, address & 127), (6, value)):
            self.cc(cc, v)

    def wait(self, seconds=0.8): self.at += seconds

    def note(self, pitch=60, velocity=100):
        self.send(0x90, pitch, velocity)
        self.wait()
        self.send(0x80, pitch, 0)
        self.wait(0.5)

    def rpn(self, number, msb, lsb=None):
        self.cc(101, 0); self.cc(100, number); self.cc(6, msb)
        if lsb is not None: self.cc(38, lsb)


CASES = {
    "nrpn": "Both parts: LEVEL mute/restore; bright/dark ANALOG cutoff on T1.",
    "mix": "One held note: T1 only, both, T2 only via assigned CC20.",
    "keys": "T1 notes0..59; T2 notes60..127; release a held59 after a bounds edit.",
    "velocity": "T1 velocity1..79; T2 velocity80..127; then raw100 with Soft Pedal.",
    "articulation": "Detached mono, connected legato, then glide on overlapping C4/E4.",
    "tuning": "Held A4: neutral, +50 cents, +12 semitones, neutral.",
    "soft": "Normal100, soft100, normal50 reference, soft1, normal100.",
    "banks": "Factory PC2, saved U01, unsupported bank2 ignored. Prepare U01 first.",
}


def reset(s):
    s.mark("Known test baseline; original project/controller values are NOT restored")
    for cc, v in ((64, 0), (123, 0), (120, 0), (121, 0), (0, 0), (32, 0), (7, 100), (11, 127)):
        s.cc(cc, v)
    s.rpn(1, 64, 0); s.rpn(2, 64)
    s.cc(101, 127); s.cc(100, 127)
    # This order reaches A0/B1 from every valid previous pair, including A1/B0.
    s.nrpn(0x3100, 0)
    for field, value in ((1, 2), (2, 1), (1, 0), (2, 1)):
        s.nrpn(0x3100 + field, value)
    for part in (0, 1):
        for field, value in enumerate((0, 127, 1, 127)):
            s.nrpn(0x3000 + 16 * part + field, value)
    s.cc(99, 127); s.cc(98, 127)


def phrase(s):
    s.send(0x90, 60, 100); s.wait(0.6)
    s.send(0x90, 64, 100); s.wait(1.2)
    s.send(0x80, 64, 0); s.wait(0.6)
    s.send(0x80, 60, 0); s.wait()


def scenario(name, channel=1):
    s = Sequence(channel)
    reset(s)
    s.mark(CASES[name])
    if name == "nrpn":
        s.send(0x90, 60, 100)
        for label, address, value in (("Mute", 0, 0), ("Restore LEVEL100", 0, 100),
                                      ("Dark cutoff", 0x84, 0), ("Bright cutoff", 0x84, 127)):
            s.mark(label); s.nrpn(address, value); s.wait(1.2)
        s.send(0x80, 60, 0)
    elif name == "mix":
        s.nrpn(0x3100, 20); s.send(0x90, 60, 100)
        for value, label in ((0, "T1 only"), (64, "Both at LEVEL100"), (127, "T2 only")):
            s.mark(label); s.cc(20, value); s.wait(2)
        s.send(0x80, 60, 0)
    elif name == "keys":
        s.nrpn(0x3001, 59); s.nrpn(0x3010, 60)
        s.mark("59: T1 only"); s.note(59)
        s.mark("60: T2 only"); s.note(60)
        s.mark("Held59 remains T1; edited range must still allow its original note-off")
        s.send(0x90, 59, 100); s.wait(); s.nrpn(0x3001, 58); s.wait()
        s.send(0x90, 59, 0); s.wait(1.5)
    elif name == "velocity":
        s.nrpn(0x3003, 79); s.nrpn(0x3012, 80)
        for velocity in (79, 80, 100):
            s.mark(f"Raw velocity{velocity}"); s.note(60, velocity)
        s.mark("Raw100 still selects T2; CC67 reduces attack velocity to50")
        s.cc(67, 127); s.note(60, 100)
    elif name == "articulation":
        s.nrpn(37, 42)  # Authored VCE MONO through the stable scaled registry.
        s.cc(5, 100)
        for legato, glide, label in ((0, 0, "Mono: pitch jump and retrigger"),
                                     (127, 0, "Legato: pitch jump, connected envelope"),
                                     (127, 127, "Legato with pitch glide")):
            s.mark(label); s.cc(68, legato); s.cc(65, glide); phrase(s)
    elif name == "tuning":
        s.cc(65, 0); s.send(0x90, 69, 100); s.wait(2)
        s.mark("Fine +50c: nominal452.893Hz from stable440Hz reference")
        s.rpn(1, 96, 0); s.wait(2)
        s.mark("Coarse +12: nominal880Hz")
        s.rpn(1, 64, 0); s.rpn(2, 76); s.wait(2)
        s.mark("Neutral again"); s.rpn(2, 64); s.wait(2)
        s.send(0x80, 69, 0)
    elif name == "soft":
        for pedal, velocity in ((0, 100), (127, 100), (0, 50), (127, 1), (0, 100)):
            s.mark(f"CC67={pedal}, input velocity={velocity}")
            s.cc(67, pedal); s.note(60, velocity)
    elif name == "banks":
        s.mark("Bank0 PC2: factory preset2 on the current engine")
        s.send(0xC0, 2); s.wait(1); s.note()
        s.mark("Bank1 U01: saved sound; Bank Select alone must not change sound")
        s.cc(32, 1); s.wait(1); s.send(0xC0, 0); s.wait(1); s.note()
        s.mark("Unsupported bank2: same sound as U01")
        s.cc(32, 2); s.send(0xC0, 0); s.wait(1); s.note()
    s.wait(1)
    reset(s)
    return s.events


def export_midi(events, path, mido):
    midi = mido.MidiFile(ticks_per_beat=1000)
    track = mido.MidiTrack(); midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000))
    previous = 0
    for event in events:
        tick = round(event["at_s"] * 2000)
        message = (mido.Message.from_bytes(event["bytes"]) if "bytes" in event else
                   mido.MetaMessage("marker", text=event["label"]))
        message.time = tick - previous
        track.append(message); previous = tick
    track.append(mido.MetaMessage("end_of_track", time=1000))
    midi.save(path)


def transmit(events, send, channel, clock=time.monotonic, sleep=time.sleep):
    report = {"status": "sent", "audio_acceptance": "unverified", "events": [],
              "cleanup_events": [], "cleanup_errors": []}
    start = clock()
    try:
        for event in events:
            sleep(max(0, start + event["at_s"] - clock()))
            if "bytes" in event: send(event["bytes"])
            else: print(event["label"], flush=True)
            report["events"].append({**event, "actual_s": round(clock() - start, 6)})
    except KeyboardInterrupt:
        report.update(status="interrupted", error="KeyboardInterrupt")
    except Exception as error:
        report.update(status="send_failed", error=str(error))
    finally:
        # Also run after interruption/disconnect. Each failed attempt is recorded.
        for event in scenario_cleanup(channel):
            attempt = {**event, "actual_s": round(clock() - start, 6)}
            try: send(event["bytes"])
            except Exception as error:
                attempt["error"] = str(error)
                report["cleanup_errors"].append(str(error))
            report["cleanup_events"].append(attempt)
            sleep(0.01)
    if report["cleanup_errors"] and report["status"] == "sent": report["status"] = "cleanup_failed"
    return report


def scenario_cleanup(channel):
    s = Sequence(channel); reset(s)
    return [event for event in s.events if "bytes" in event]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="list MIDI outputs; send nothing")
    p.add_argument("--case", choices=CASES, default="mix")
    p.add_argument("--channel", type=int, choices=range(1, 17), default=1)
    action.add_argument("--port", help="exact MIDI output name; omission prints a dry-run plan")
    action.add_argument("--export-midi", type=Path, help="export this case for a MIDI player; send nothing")
    p.add_argument("--report", type=Path, help="JSON message/timing log (default build/midi-hardware/UTC.json)")
    p.add_argument("--firmware-label", default="unverified", help="installed device commit/package, recorded without verification")
    args = p.parse_args()
    events = scenario(args.case, args.channel)
    if not (args.list or args.export_midi or args.port):
        print(json.dumps(events, indent=2)); return 0
    try:
        import mido
        if args.export_midi:
            args.export_midi.parent.mkdir(parents=True, exist_ok=True)
            export_midi(events, args.export_midi, mido)
            print(args.export_midi); return 0
        names = mido.get_output_names()
        if args.list:
            print("\n".join(names) if names else "No MIDI outputs found."); return 0
        if args.port not in names: p.error("output not found; use --list and copy the exact name")
        with mido.open_output(args.port) as output:
            result = transmit(events, lambda raw: output.send(mido.Message.from_bytes(raw)), args.channel)
    except Exception as error:
        p.exit(2, f"MIDI unavailable: {error}\nRun on the device-connected computer with: uv run --locked --group midi tools/fm1_midi_performance.py --list\n")
    result.update(case=args.case, channel=args.channel, port=args.port, firmware_label=args.firmware_label,
                  utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    path = args.report or Path("build/midi-hardware") / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['status']}; log {path}; audio/physical acceptance remains unverified")
    return 0 if result["status"] == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
