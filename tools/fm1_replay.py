#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Replay a versioned shared scenario through the native browser-emulator adapter."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
FS = 44100
MAX_INPUT = 1024 * 1024
MAX_EVENTS = 4096
MAX_CAPTURES = 256
MAX_SAMPLES = FS * 60
MAX_OUTPUT = 96 * 1024 * 1024
BUTTONS = ("FX", "SCL", "ENV", "LFO", "EDIT", "GLO", "HOME", "SAVE", "ARP", "SEQ",
           "PLAY", "REC", "OCT-", "OCT+")
ENCODERS = ("SELECT", "ALGORITHM", "PRESETS", "KNOB 1", "KNOB 2", "KNOB 3", "KNOB 4")
STATE_FIELDS = ("device_ms", "produced_samples", "consumed_samples", "keys_mask", "buttons_mask",
                "gated_voices", "active_voices", "selected_track", "engine_requested", "octave",
                "page", "screen_draws", "playing", "click", "usb_level", "home", "graph", "engine_active", "user_presets")
FLAGS = ("-O2", "-ffp-contract=off", "-std=gnu99", "-w", "-fPIC", "-shared",
         "-Ibuild/gen", "-Ifirmware/src")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field}: expected integer {low}..{high}")
    return value


def fields(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        raise ValueError(f"expected fields {sorted(required)}; optional {sorted(optional)}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def load_scenario(path, max_output=MAX_OUTPUT):
    # Bound the read as well as the decoded event array, before any build/output.
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("scenario exceeds 1 MiB")
    try:
        scenario = json.loads(raw, object_pairs_hook=unique_object)
    except RecursionError as error:
        raise ValueError("scenario nesting is too deep") from error
    fields(scenario, ("schema", "sample_rate", "initial", "events"), ("name",))
    integer(scenario["schema"], 1, 1, "schema")
    integer(scenario["sample_rate"], FS, FS, "sample_rate")
    if "name" in scenario and (not isinstance(scenario["name"], str) or len(scenario["name"]) > 120):
        raise ValueError("name: expected string of at most 120 characters")
    initial = scenario["initial"]
    fields(initial, ("state", "seed", "warmup_samples", "master", "click", "usb_level"))
    if initial["state"] != "factory":
        raise ValueError("only factory initial state (erased simulated NOR) is supported")
    integer(initial["seed"], 1, 0xFFFFFFFF, "seed")
    integer(initial["warmup_samples"], FS // 2, FS * 5, "warmup_samples")
    integer(initial["master"], 0, 1023, "master")
    integer(initial["click"], 0, 2, "click")
    integer(initial["usb_level"], 0, 1, "usb_level")
    events = scenario["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError(f"events: expected 1..{MAX_EVENTS} entries")
    previous = 0
    captures = 0
    # Bound accumulation between UI reads, not only each individual detent.
    # This conservative whole-scenario cap rules out int32 overflow in web_enc.
    detents = 0
    for index, event in enumerate(events):
        if not isinstance(event, dict) or "sample" not in event or "type" not in event:
            raise ValueError(f"event {index}: missing sample/type")
        sample = integer(event["sample"], 0, MAX_SAMPLES, "sample")
        if sample < previous:
            raise ValueError(f"event {index}: samples must be ordered")
        previous = sample
        kind = event["type"]
        if kind in ("key", "button"):
            fields(event, ("sample", "type", "id", "down"))
            if kind == "key":
                integer(event["id"], 0, 26, "key id")
            elif event["id"] not in BUTTONS:
                raise ValueError("unsupported button label")
            if type(event["down"]) is not bool:
                raise ValueError("down: expected boolean")
        elif kind == "encoder":
            fields(event, ("sample", "type", "id", "delta"))
            if event["id"] not in ENCODERS:
                raise ValueError("unsupported encoder role")
            delta = integer(event["delta"], -1024, 1024, "delta")
            detents += abs(delta)
            if detents > 65536:
                raise ValueError("total encoder detents exceed 65536")
        elif kind == "midi":
            fields(event, ("sample", "type", "status", "data1", "data2"))
            integer(event["status"], 0x80, 0xEF, "MIDI channel status")
            integer(event["data1"], 0, 127, "data1")
            integer(event["data2"], 0, 127, "data2")
            if event["status"] >> 4 in (0xC, 0xD) and event["data2"]:
                raise ValueError("two-byte MIDI channel messages require data2=0")
        elif kind == "master":
            fields(event, ("sample", "type", "value"))
            integer(event["value"], 0, 1023, "master value")
        elif kind == "capture":
            fields(event, ("sample", "type"))
            captures += 1
        elif kind == "end":
            fields(event, ("sample", "type"))
            if index != len(events) - 1 or sample == 0:
                raise ValueError("end must be the final event, with positive duration")
        else:
            raise ValueError(f"unsupported event type: {kind!r}")
    if events[-1]["type"] != "end":
        raise ValueError("explicit final end event is required")
    if captures > MAX_CAPTURES:
        raise ValueError(f"at most {MAX_CAPTURES} captures")
    # PCM24 stereo, PPM header+pixels, plus a conservative manifest allowance.
    estimated = (44 + previous * 6 + captures * (240 * 240 * 3 + 15 + 2048)
                 + len(events) * 2048 + MAX_INPUT * 2)
    if estimated > integer(max_output, 1, MAX_OUTPUT, "max-output-bytes"):
        raise ValueError(f"output estimate {estimated} exceeds byte limit {max_output}")
    return scenario, raw, estimated


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def source_inputs():
    # Profile freshness is checked before compilation; retain its consumed engine
    # sources and generated includes for the compile/replay change guards too.
    patterns = ("firmware/src/*.[ch]", "firmware/hal/*.[ch]", "firmware/engines/src/*.[ch]",
                "build/gen/*.h", "build/gen/*.inc",
                "tests/hostsim.c", "tests/host_nor.h", "tests/host_flash_context.h",
                "web/emu/felucca_web.c", "tools/replay_native.c", "tools/fm1_replay.py",
                "tools/gen_*.py", "tools/aa_raster.py", "assets/fonts/**/*", "web/fukiai.ttf")
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for pattern in patterns
            for p in sorted(ROOT.glob(pattern)) if p.is_file()}


def build_adapter():
    if not (ROOT / "build/gen/felucca_tables.h").is_file():
        raise ValueError("run ./build.sh first to generate build/gen assets")
    if sys.platform not in ("linux", "darwin"):
        raise ValueError("native replay currently supports Linux/macOS")
    subprocess.run([sys.executable, str(ROOT / "tools/profile.py"), "--check"], cwd=ROOT, check=True)
    identity = json.loads((ROOT / "build/gen/build-identity.json").read_text())
    compiler = shlex.split(os.environ.get("CC", "cc"))
    version = subprocess.check_output([*compiler, "--version"], text=True).splitlines()[0]
    inputs = source_inputs()
    provenance = {"compiler": version, "compiler_command": compiler, "flags": list(FLAGS), "inputs": inputs, "build_identity": identity}
    cache_key = digest(json.dumps(provenance, sort_keys=True).encode())
    build_dir = ROOT / "build/replay-native"
    build_dir.mkdir(parents=True, exist_ok=True)
    library = build_dir / f"adapter-{cache_key}.so"
    command = [*compiler, *FLAGS, "tools/replay_native.c", "-o", str(library), "-lm"]
    if not library.exists():
        # Publish the cache only after a successful link. Concurrent test runs
        # may compile the same inputs, but cannot load a partly written library.
        with tempfile.TemporaryDirectory(prefix="link-", dir=build_dir) as temporary:
            pending = Path(temporary) / "adapter.so"
            subprocess.run([*compiler, *FLAGS, "tools/replay_native.c", "-o", str(pending), "-lm"],
                           cwd=ROOT, check=True)
            if source_inputs() != inputs:
                raise ValueError("source/assets changed during native compilation; rerun capture")
            pending.replace(library)
    provenance.update({"adapter": "tools/replay_native.c", "binary_sha256": digest(library.read_bytes()),
                       "revision": git("rev-parse", "HEAD"),
                       "diff_sha256": digest(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)),
                       "status": git("status", "--porcelain"), "build_command": command})
    return library, provenance


class Adapter:
    def __init__(self, library):
        self.lib = ctypes.CDLL(str(library))
        for name, types in {
            "replay_init": [ctypes.c_uint32] * 4,
            "replay_pcm": [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8)],
            "replay_rgb": [ctypes.POINTER(ctypes.c_uint8)],
            "replay_observe": [ctypes.POINTER(ctypes.c_uint32)],
            "replay_features": [ctypes.POINTER(ctypes.c_uint32)],
            "web_keys": [ctypes.c_uint32], "web_buttons": [ctypes.c_uint32],
            "web_enc": [ctypes.c_uint32, ctypes.c_int32], "web_master": [ctypes.c_uint32],
            "web_midi": [ctypes.c_uint32] * 3,
        }.items():
            function = getattr(self.lib, name)
            function.argtypes = types
            function.restype = ctypes.c_uint32 if name == "web_midi" else None
        self.pcm = (ctypes.c_uint8 * (128 * 6))()
        self.rgb = (ctypes.c_uint8 * (240 * 240 * 3))()
        self.state = (ctypes.c_uint32 * len(STATE_FIELDS))()

    def observe(self):
        self.lib.replay_observe(self.state)
        result = dict(zip(STATE_FIELDS, self.state))
        result["octave"] = ctypes.c_int32(result["octave"]).value
        return result

    def render(self, count, output=None, pcm_hash=None):
        while count:
            block = min(128, count)
            self.lib.replay_pcm(block, self.pcm)
            if output is not None:
                data = bytes(self.pcm[:block * 6])
                output.writeframesraw(data)
                pcm_hash.update(data)
            count -= block


def output_path(path):
    path = path.resolve()
    build = (ROOT / "build").resolve()
    if build not in path.parents or path == build or path.exists():
        raise ValueError("output must be a new directory under this checkout's ignored build/")
    return path


def replay(scenario, raw, out, library, provenance, estimate):
    if source_inputs() != provenance["inputs"]:
        raise ValueError("source/assets changed before replay; rerun capture")
    adapter = Adapter(library)
    initial = scenario["initial"]
    adapter.lib.replay_init(initial["seed"], initial["master"], initial["click"], initial["usb_level"])
    adapter.render(initial["warmup_samples"])
    origin = adapter.observe()
    features = (ctypes.c_uint32 * 8)()
    adapter.lib.replay_features(features)
    provenance["features"] = dict(zip(("fm4", "slice", "icons", "cdc", "flash", "ota", "uac", "uart"), features))
    provenance["version"] = provenance["build_identity"]["version"]
    out.mkdir(parents=True)
    (out / "scenario.json").write_bytes(raw)
    frames = []
    deliveries = []
    pcm_hash = hashlib.sha256()
    cursor = 0
    keys = buttons = 0
    with wave.open(str(out / "audio.wav"), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(3)
        audio.setframerate(FS)
        for order, event in enumerate(scenario["events"]):
            adapter.render(event["sample"] - cursor, audio, pcm_hash)
            cursor = event["sample"]
            kind = event["type"]
            if kind == "key":
                bit = 1 << event["id"]
                keys = keys | bit if event["down"] else keys & ~bit
                adapter.lib.web_keys(keys)
            elif kind == "button":
                bit = 1 << BUTTONS.index(event["id"])
                buttons = buttons | bit if event["down"] else buttons & ~bit
                adapter.lib.web_buttons(buttons)
            elif kind == "encoder":
                adapter.lib.web_enc(ENCODERS.index(event["id"]), event["delta"])
            elif kind == "master":
                adapter.lib.web_master(event["value"])
            elif kind == "midi":
                if not adapter.lib.web_midi(event["status"], event["data1"], event["data2"]):
                    raise ValueError(f"MIDI queue full at event {order}; no events were silently dropped")
            observed = adapter.observe()
            timing = {"order": order, "type": kind, "requested_sample": cursor,
                      "actual_device_ms": observed["device_ms"],
                      "first_unsynthesized_sample": observed["produced_samples"] - initial["warmup_samples"],
                      "state": observed}
            deliveries.append(timing)
            if kind == "capture":
                adapter.lib.replay_rgb(adapter.rgb)
                data = b"P6\n240 240\n255\n" + bytes(adapter.rgb)
                name = f"frame-{len(frames):04d}.ppm"
                (out / name).write_bytes(data)
                frames.append({**timing, "file": name, "sha256": digest(data),
                               "rgb_sha256": digest(bytes(adapter.rgb))})
    manifest = {
        "schema": 1, "kind": "interaction-replay", "scenario_schema": 1, "scenario_sha256": digest(raw),
        "provenance": provenance, "initial": initial, "timeline_origin": origin,
        "timing": {"sample_rate": FS, "ctl_frames": 32, "dma_half_frames": 128,
                   "device_clock_ms": 1, "ui_frame_ms": 15, "equal_timestamps": "file order",
                   "publication": "at requested consumer position, before the next web_render; queued audio is retained",
                   "capture": "read-only current framebuffer at consumer position; actual producer clock recorded",
                   "end": "trim PCM to requested duration; final DMA half remains fully synthesized"},
        "audio": {"file": "audio.wav", "frames": cursor, "channels": 2, "bits": 24,
                  "tap": "DAC post MASTER/fixed-level attenuation, post metronome, pre hardware codec",
                  "pcm_sha256": pcm_hash.hexdigest(), "wav_sha256": digest((out / "audio.wav").read_bytes())},
        "screen": {"width": 240, "height": 240, "source": "real firmware lcd_fill/lcd_blit",
                   "format": "RGB888 PPM from panel-order RGB565", "frames": frames},
        "events": deliveries, "final_state": adapter.observe(), "estimated_output_bytes": estimate,
        "unavailable": ["real USB/UAC capture, 48k resampling, TRS transport, editor/SysEx",
                        "panel debounce/scan interrupts, USB scheduling, DMA playback latency",
                        "hardware CPU/deadlines, battery/crash behavior, real NOR timing/wear"],
    }
    if source_inputs() != provenance["inputs"]:
        raise ValueError("source/assets changed during replay; rerun capture")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new directory under build/")
    parser.add_argument("--max-output-bytes", type=int, default=MAX_OUTPUT)
    args = parser.parse_args()
    try:
        scenario, raw, estimate = load_scenario(args.scenario, args.max_output_bytes)
        out = output_path(args.out)
        library, provenance = build_adapter()
        replay(scenario, raw, out, library, provenance, estimate)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"replay: {error}", file=sys.stderr)
        return 2
    print(f"replay: {out} ({scenario['events'][-1]['sample']} PCM frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
