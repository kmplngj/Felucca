#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Selected native host renders and digital level reports; never writes trims.

Adapted from Optimist tools/level_presets.py and tools/level_drumkits.py at
2ab989d5a2012160d6488bf56f23d89000d9f855 (GPL-3.0-only). Role schedules live in
loudness-phrases.json. Rate-correct K weighting uses the bilinear shelf/high-pass
equations and BS.1770 constants; pyloudnorm is an independent test oracle only.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import time
import wave

import numpy as np
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parents[1]
PHRASES = ROOT / "tools/loudness-phrases.json"
FS, CTL = 44100, 32
STANDARD_ENGINES = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
MAX_CASES, MAX_FRAMES, MAX_TOTAL_FRAMES = 8, FS * 12, FS * 60
DONOR = "2ab989d5a2012160d6488bf56f23d89000d9f855"


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def k_coefficients(rate):
    """BS.1770 K shelf and RLB high-pass; coefficients for the declared rate.

    At 48 kHz these reproduce BS.1770-3 Tables 1/2. Shelf gain at Nyquist
    is Vh; Vb is the geometric interpolation exponent from that analogue model.
    RLB's numerator remains [1,-2,1], as the published table specifies.
    """
    if type(rate) is not int or rate < 8000 or rate > 192000:
        raise ValueError("unsupported sample rate")
    k = math.tan(math.pi * 1681.974450955533 / rate)
    q, vh = 0.7071752369554196, 10 ** (3.999843853973347 / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k*k
    shelf = ([ (vh + vb*k/q + k*k)/a0, 2*(k*k-vh)/a0,
               (vh-vb*k/q+k*k)/a0 ],
             [1, 2*(k*k-1)/a0, (1-k/q+k*k)/a0])
    k = math.tan(math.pi * 38.13547087602444 / rate)
    q = 0.5003270373238773
    a0 = 1 + k/q + k*k
    highpass = ([1, -2, 1], [1, 2*(k*k-1)/a0, (1-k/q+k*k)/a0])
    return shelf, highpass


def meter(samples, rate=FS):
    """Float samples relative to virtual Q15 full scale, mono or stereo only.

    Complete 400 ms blocks on a 100 ms grid; no padded/partial gate blocks.
    Stereo is a sum of channel energies, never an arithmetic mono fold-down.
    """
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2 or x.shape[1] not in (1, 2):
        raise ValueError("expected mono or stereo frames")
    coeff = k_coefficients(rate)
    if not np.isfinite(x).all():
        raise ValueError("nonfinite samples")
    n = len(x)
    window, hop = round(rate*.4), round(rate*.1)
    peak = float(np.max(np.abs(x))) if n else None
    energy_sum = float(np.sum(x*x))
    if not math.isfinite(energy_sum):
        raise ValueError("sample energy overflow")
    result = {"frames": n, "channels": x.shape[1], "sample_rate": rate,
              "sample_peak": peak, "sample_peak_dbfs": 20*math.log10(peak) if peak else None,
              "headroom_db": -20*math.log10(peak) if peak else None,
              "overrange_samples": int(np.count_nonzero(np.abs(x) > 1)),
              "q15_rail_or_beyond_samples": int(np.count_nonzero((x >= 32767/32768) | (x <= -1))),
              "energy": energy_sum, "integrated_lufs": None,
              "loudest_100ms_lkfs": None,
              "gate_blocks": 0 if n < window else 1 + (n-window)//hop,
              "absolute_gate_blocks": 0, "relative_gate_blocks": 0,
              "true_peak": None, "true_peak_status": "not_implemented"}
    if not n:
        return dict(result, status="empty")
    if not peak:
        return dict(result, status="silence")
    y = x
    for b, a in coeff:
        y = lfilter(b, a, y, axis=0)
    z = np.sum(y*y, axis=1)
    if not np.isfinite(z).all():
        raise ValueError("filter energy overflow")
    cumulative = np.r_[0.0, np.cumsum(z)]
    short = round(rate * .1)
    if n >= short:
        loudest = float(np.max((cumulative[short:] - cumulative[:-short]) / short))
        result["loudest_100ms_lkfs"] = -0.691 + 10*math.log10(loudest) if loudest > 0 else None
    if n < window:
        return dict(result, status="short")
    starts = np.arange(0, n-window+1, hop)
    energy = (cumulative[starts+window] - cumulative[starts]) / window
    return dict(result, **gate_energy(energy))


def gate_energy(energy):
    """Normative strict gates; separate from window formation for edge fixtures."""
    energy = np.asarray(energy, dtype=np.float64)
    if energy.ndim != 1 or not np.isfinite(energy).all() or (energy < 0).any():
        raise ValueError("invalid gate energies")
    levels = np.full(len(energy), -np.inf)
    positive = energy > 0
    levels[positive] = -0.691 + 10*np.log10(energy[positive])
    absolute = levels > -70
    result = {"gate_blocks": len(energy), "absolute_gate_blocks": int(absolute.sum()),
              "relative_gate_blocks": 0, "integrated_lufs": None}
    if not absolute.any():
        return dict(result, status="all_gated")
    # Compare powers directly: converting the threshold to dB can round an exact
    # relative-gate equality into a spurious strictly-greater comparison.
    relative_energy = float(energy[absolute].mean()) / 10
    selected = absolute & (energy > relative_energy)
    result["relative_gate_blocks"] = int(selected.sum())
    if not selected.any():
        return dict(result, status="all_gated")
    result["integrated_lufs"] = -0.691 + 10*math.log10(float(energy[selected].mean()))
    return dict(result, status="ok")


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {label}")
    return value


def make_case(spec, phrases):
    """Explicit manual roles, no unreviewed preset-name classifier."""
    fields = {"id", "engine_id", "preset", "role", "reverb", "kit", "lane"}
    if not isinstance(spec, dict) or set(spec) - fields or not {"id", "engine_id", "preset", "role", "reverb"} <= set(spec):
        raise ValueError("incomplete/unknown case fields")
    name = spec["id"]
    if not isinstance(name, str) or not name or len(name) > 48 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
        raise ValueError("invalid case id")
    engine = integer(spec["engine_id"], 0, 63, "engine")
    integer(spec["preset"], 0, 65535, "preset")
    if spec["reverb"] not in ("room", "hall"):
        raise ValueError("explicit room/hall required")
    role = spec["role"]
    step = FS * 60 // phrases["bpm"] // 4
    events = []
    if engine == 10:
        integer(spec.get("kit"), 0, 11, "kit")
        if role not in ("drum-hit", "drum-beat") or spec.get("kit") not in phrases["canonical_drum_kits"]:
            raise ValueError("native canonical drum kit/role required")
        if role == "drum-hit":
            lane = integer(spec.get("lane"), 0, 7, "lane")
            events = [[0, phrases["drum_notes"][lane], 110]]
            body = 0
        else:
            if "lane" in spec:
                raise ValueError("mixed beat has no single lane")
            events = [[st*step, phrases["drum_notes"][lane], velocity]
                      for st, lane, velocity in phrases["drum_beat"]]
            body = 16*step
        tail = FS*2
    else:
        if "kit" in spec or "lane" in spec or role not in phrases["roles"]:
            raise ValueError("explicit native synth role required")
        for st, notes, numerator, denominator, velocity in phrases["roles"][role]:
            off = st*step + step*numerator//denominator
            for note in notes:
                events.extend([[st*step, note, velocity], [off, note, 0]])
        body, tail = 32*step, FS//4
    # Floor to control-block boundaries, off before on at a shared boundary.
    events = sorted([[f//CTL*CTL, n, v] for f, n, v in events], key=lambda e: (e[0], e[2] != 0, e[1]))
    if len(events) > 256 or len({tuple(e) for e in events}) != len(events):
        raise ValueError("duplicate/too many events")
    frames = (body+tail+CTL-1)//CTL*CTL
    if not events or max(e[0] for e in events) >= frames or frames > MAX_FRAMES:
        raise ValueError("invalid duration")
    return dict(spec, frames=frames, body_frames=body, tail_frames=frames-body,
                event_rounding="floor_to_CTL_off_before_on", events=events)


def inventory(root=ROOT):
    paths = subprocess.check_output(["git", "ls-files", "--recurse-submodules", "-z"], cwd=root).decode().split("\0")
    paths += ["tools/loudness_audit.py", "tests/loudness_probe.c", "tools/loudness-phrases.json",
              "tests/loudness_audit_test.py", "docs/loudness-audit.md"]
    return {name: sha(root/name) for name in sorted(set(paths)) if name and (root/name).is_file()}


def command(argv, directory, label, cwd=ROOT, timeout=120):
    start = time.time_ns()
    try:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", FELUCCA_SLICE="1")
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        (directory/f"{label}.stdout").write_bytes(exc.stdout or b"")
        (directory/f"{label}.stderr").write_bytes(exc.stderr or b"")
        write_json(directory/f"{label}.command.json", {"argv": argv, "start_ns": start, "end_ns": time.time_ns(), "status": "timeout"})
        raise ValueError(f"{label}: timeout") from exc
    (directory/f"{label}.stdout").write_bytes(proc.stdout)
    (directory/f"{label}.stderr").write_bytes(proc.stderr)
    write_json(directory/f"{label}.command.json", {"argv": argv, "start_ns": start, "end_ns": time.time_ns(), "returncode": proc.returncode})
    if proc.returncode:
        raise ValueError(f"{label}: child exited {proc.returncode}; see raw logs")
    return proc.stdout


def prepare(directory):
    """Only hostsim's generated closure, isolated from all production build paths.

    Output has the same depth as build/gen because production engine_includes.inc
    uses ../../firmware paths. Call unchanged generators with private output/cache.
    """
    if directory.resolve().parent != (ROOT/"build").resolve() or not directory.name.startswith("audit-run-") or (directory/"resolved-profile.json").exists():
        raise ValueError("preparation needs a fresh build/audit-run-* directory")
    def load(name):
        spec = importlib.util.spec_from_file_location("audit_"+name, ROOT/"tools"/(name+".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    generated = load("profile").generated(ROOT, "standard", "m8stealth",
                                          feature_flags={"FELUCCA_FM4": "0", "FELUCCA_SLICE": "1"})
    for name, text in generated.items():
        (directory/name).write_text(text)
    load("gen_tables").main(directory/"felucca_tables.h")
    load("gen_fm6_patches").main(directory/"felucca_fm6.h")
    samples = load("gen_samples")
    samples.GENDIR, samples.CACHE = directory/"waves", directory/"samples.cache"
    if not samples.CC0.is_dir() or not any(samples.CC0.glob("*/*.wav")):
        raise ValueError("native CC0 sample assets required; no silent missing-sample fallback")
    samples.main(directory/"felucca_samples.h")


def compile_probe(directory, cflags=(), cc=None):
    command([sys.executable, str(Path(__file__).resolve()), "--prepare", str(directory)], directory, "prepare")
    compiler = shlex.split(cc or os.environ.get("CC", "cc"))
    command(compiler+["--version"], directory, "compiler-version")
    argv = compiler + ["-O2", "-I"+str(directory), "-Ifirmware/src", *cflags,
                       "-ffp-contract=off", "-fsanitize=signed-integer-overflow",
                       "-fno-sanitize-recover=signed-integer-overflow",
                       "tests/loudness_probe.c", "-lm", "-o", str(directory/"probe")]
    command(argv, directory, "compile")
    return directory/"probe"


def capture(probe, case, directory):
    directory.mkdir()
    (directory/"events.txt").write_text("".join(f"{f} {n} {v}\n" for f, n, v in case["events"]))
    argv = [str(probe), str(case["engine_id"]), str(case["preset"]), str(case.get("kit", 255)),
            str(2 if case["reverb"] == "hall" else 0), str(case["frames"]), str(directory/"events.txt"),
            str(directory/"pre.i32le"), str(directory/"post.i32le")]
    command(argv, directory, "render", timeout=60)
    meta = read_json(directory/"render.stdout")
    required = {"schema", "engine_id", "engine_name", "compiled_engine_ids", "preset", "preset_name", "kit", "frames", "sample_rate", "ctl", "tap_replay_blocks", "flags", "master_q12", "lowcut", "usb_fixed", "performance", "reverb", "track_parameter_count", "global_parameter_count", "track_parameters", "global_parameters"}
    if not isinstance(meta, dict) or set(meta) != required or type(meta["schema"]) is not int or meta["schema"] != 1:
        raise ValueError("malformed probe metadata")
    compiled = meta["compiled_engine_ids"]
    if (not isinstance(compiled, list) or any(type(e) is not int or not 0 <= e < 64 for e in compiled)
            or compiled != sorted(set(compiled)) or compiled != STANDARD_ENGINES):
        raise ValueError("compiled engine selection differs from canonical standard13 profile")
    for field in ("engine_id", "preset", "frames"):
        if type(meta[field]) is not int or meta[field] != case[field]:
            raise ValueError(f"probe {field} mismatch")
    if any(type(meta[field]) is not int for field in ("sample_rate", "ctl", "tap_replay_blocks", "master_q12", "lowcut", "usb_fixed", "reverb", "kit")) or meta["performance"] is not False:
        raise ValueError("malformed probe policy types")
    if (meta["sample_rate"], meta["ctl"], meta["tap_replay_blocks"], meta["master_q12"], meta["lowcut"], meta["usb_fixed"], meta["performance"], meta["reverb"], meta["kit"]) != (FS, CTL, case["frames"]//CTL, 4096, 0, 0, False, 2 if case["reverb"] == "hall" else 0, case.get("kit", 255)):
        raise ValueError("probe tap/policy mismatch")
    if not all(isinstance(meta[k], str) and meta[k] for k in ("engine_name", "preset_name")):
        raise ValueError("missing actual names")
    if not all(isinstance(meta[k], list) and meta[k] and all(type(v) is int for v in meta[k]) for k in ("track_parameters", "global_parameters")):
        raise ValueError("invalid parameter snapshots")
    if any(type(meta[count]) is not int or meta[count] != len(meta[values]) for count, values in (("track_parameter_count", "track_parameters"), ("global_parameter_count", "global_parameters"))):
        raise ValueError("incomplete parameter snapshots")
    if not isinstance(meta["flags"], dict) or set(meta["flags"]) != {"cpu2", "fm4", "slice", "macro"} or any(type(v) is not int or v not in (0, 1) for v in meta["flags"].values()):
        raise ValueError("invalid profile flags")
    arrays = {}
    for tap_name in ("pre", "post"):
        path = directory/f"{tap_name}.i32le"
        if path.stat().st_size != case["frames"]*8:
            raise ValueError("truncated/oversized raw capture")
        arrays[tap_name] = np.fromfile(path, dtype="<i4").reshape(-1, 2)
    return meta, arrays


def run_audit(spec_path, output, cflags=(), cc=None):
    output = Path(output).absolute()
    build = (ROOT/"build").resolve()
    if output.resolve().parent != build or not output.name.startswith("audit-run-") or output.exists():
        raise ValueError("output must be a fresh direct build/audit-run-* directory")
    spec, phrases = read_json(spec_path), read_json(PHRASES)
    if not isinstance(spec, dict) or set(spec) != {"schema", "cases"} or type(spec["schema"]) is not int or spec["schema"] != 1 or not isinstance(spec["cases"], list) or not 1 <= len(spec["cases"]) <= MAX_CASES:
        raise ValueError("expected schema1 with 1..8 selected cases")
    cases = [make_case(s, phrases) for s in spec["cases"]]
    if len({c["id"] for c in cases}) != len(cases) or sum(c["frames"] for c in cases) > MAX_TOTAL_FRAMES:
        raise ValueError("duplicate case or total duration budget")
    before = inventory()
    authority = read_json(ROOT/"profiles/engine-identities.json")
    keys = {s["id"]: s["key"] for s in authority["slots"]}
    catalog = read_json(ROOT/"profiles/catalog.json")
    names = {s["id"]: s["name"] for s in catalog["engines"]}
    standard = set(STANDARD_ENGINES)
    if any(c["engine_id"] not in standard or not keys.get(c["engine_id"]) for c in cases):
        raise ValueError("first audit slice supports canonical standard13 engines only")
    output.mkdir(parents=True)
    write_json(output/"source-before.json", before)
    write_json(output/"selection.json", spec)
    provenance = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "engines_revision": subprocess.check_output(["git", "-C", "firmware/engines", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "working_tree": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
                  "host": platform.platform(), "python": sys.version,
                  "numpy": np.__version__, "scipy": __import__("scipy").__version__,
                  "donor_revision": DONOR, "profile": "standard",
                  "budgets": {"max_cases": MAX_CASES, "max_frames_per_case": MAX_FRAMES, "max_total_frames": MAX_TOTAL_FRAMES,
                              "raw_bytes": sum(c["frames"]*16 for c in cases), "wav_bytes": sum(44+c["frames"]*4 for c in cases)}}
    write_json(output/"provenance.json", provenance)
    try:
        probe = compile_probe(output, cflags, cc)
        resolved = read_json(output/"resolved-profile.json")
        if set(resolved["engine_ids"]) != standard:
            raise ValueError("canonical standard13 selection changed; review audit scope")
        provenance["resolved_profile"] = resolved
        write_json(output/"provenance.json", provenance)
        write_json(output/"probe.json", {"sha256": sha(probe)})
        command([str(probe), "--self-test"], output, "master-fixture")
        reports = []
        for case in cases:
            directory = output/case["id"]
            meta, arrays = capture(probe, case, directory)
            if meta["engine_name"] != names[case["engine_id"]]:
                raise ValueError("compiled engine differs from catalog")
            flags = resolved["build_flags"]
            if any(meta["flags"][k] != int(flags[f"FELUCCA_{k.upper()}"]) for k in ("fm4", "slice")):
                raise ValueError("compiled feature flags differ from generated profile")
            if meta["flags"]["macro"] != int(14 in resolved["engine_ids"]):
                raise ValueError("compiled MACRO selection differs from generated profile")
            values = {tap: data.astype(np.float64)/32768 for tap, data in arrays.items()}
            metrics = {tap: meter(data) for tap, data in values.items()}
            mono = {tap: meter(data.mean(axis=1)) for tap, data in values.items()}
            for tap, data in values.items():
                metrics[tap]["tail_energy"] = float(np.sum(data[case["body_frames"]:]**2))
            # Fixed shared Q15 scale; no per-file gain or peak normalization.
            post = arrays["post"]
            if (post < -32768).any() or (post > 32767).any():
                raise ValueError("post-master outside Q15; refuse clipped audition")
            with wave.open(str(directory/"post-master.wav"), "wb") as wav:
                wav.setparams((2, 2, FS, 0, "NONE", "not compressed"))
                wav.writeframes(post.astype("<i2").tobytes())
            report = {"case": case, "engine_key": keys[case["engine_id"]], "probe": meta,
                      "stereo": metrics, "mono_fold_down": mono,
                      "tap_names": {"pre": "post-buses-and-master_before-DC-lowcut-limiter-softclip", "post": "actual-mix_block-output"},
                      "scale": "signed Q15 / 32768; virtual digital full scale",
                      "audition": "fixed Q15 scale, actual post-master, no normalization",
                      "decision": "review_required", "listening": "not_performed",
                      "hashes": {p.name: sha(p) for p in directory.iterdir() if p.is_file()}}
            write_json(directory/"report.json", report)
            reports.append(report)
        write_json(output/"report.json", {"schema": 1, "cases": reports, "physical_dac_usb": "not_measured", "trims": "unchanged"})
    finally:
        after = inventory()
        write_json(output/"source-after.json", after)
        if before != after:
            raise ValueError("source/generated inputs changed during audit")
    write_json(output/"manifest.json", {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*")) if p.is_file()})
    return output/"report.json"


def main():
    # Internal child mode keeps generator stdout/stderr and timing as raw evidence.
    if len(sys.argv) == 3 and sys.argv[1] == "--prepare":
        sys.dont_write_bytecode = True
        prepare(Path(sys.argv[2]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list supported standard engine IDs/keys and manual roles; no render")
    parser.add_argument("--cases", type=Path, help="explicit selected-case JSON")
    parser.add_argument("--out", type=Path, help="fresh ignored build/ path")
    parser.add_argument("--cc", help="host compiler command, recorded verbatim as argv")
    parser.add_argument("--cflag", action="append", default=[], help="explicit host build flag; use --cflag=-D...")
    args = parser.parse_args()
    try:
        if args.list:
            catalog = read_json(ROOT/"profiles/catalog.json")
            phrases = read_json(PHRASES)
            print(json.dumps({"profile": "standard", "engines": [{k: e[k] for k in ("id", "key", "name")} for e in catalog["engines"] if e["id"] in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)],
                              "roles": list(phrases["roles"]), "drum_roles": ["drum-hit", "drum-beat"],
                              "canonical_drum_kits": phrases["canonical_drum_kits"]}, indent=2, allow_nan=False))
            return
        if args.cases is None or args.out is None:
            parser.error("--cases and --out are required for capture")
        print(run_audit(args.cases, args.out, args.cflag, args.cc))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"loudness audit failed: {exc}\n")


if __name__ == "__main__":
    main()
