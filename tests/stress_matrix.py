#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Rebuild and replay the issue #46 host stress matrix; no device access."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
METADATA_TIMEOUT = 15
TRACK_PARAMS = {
    "level": "P_LEVEL", "voice": "P_VOICE", "release": "P_REL",
    "chorus": "P_CHOR", "delay": "P_DLY", "reverb": "P_REV",
    "seq_length": "P_SLEN", "seq_div": "P_SDIV", "seq_gate": "P_SGATE",
    "mod_source": "P_M1SRC", "mod_dest": "P_M1DST", "mod_amount": "P_M1AMT",
    "insert_type": "P_ITYPE", "insert_mix": "P_IMIX", "insert_a": "P_IA",
}
GLOBAL_PARAMS = {"bpm": "G_BPM", "reverb_type": "G_RTYPE", "reverb_size": "G_RSIZE",
                 "delay_feedback": "G_DFDBK"}
OPS = {"preset": "EV_PRESET", "param": "EV_PARAM", "global": "EV_GLOBAL",
       "on": "EV_ON", "off": "EV_OFF", "step": "EV_STEP",
       "transport": "EV_TRANSPORT", "perform": "EV_PERFORM",
       "usb_midi": "EV_USB_MIDI", "trs_byte": "EV_TRS_BYTE"}


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"expected integer {low}..{high}, got {value!r}")
    return value


def validate(matrix):
    if matrix.get("version") != 1 or matrix.get("sample_rate") != 44100 or matrix.get("block_frames") != 32:
        raise ValueError("unsupported matrix version/rate/control block")
    names = set()
    scenarios = matrix["scenarios"]
    if not 1 <= len(scenarios) <= 64:
        raise ValueError("expected 1..64 scenarios")
    for s in scenarios:
        name = s["name"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name) or name in names:
            raise ValueError("scenario names must be unique safe filenames")
        names.add(name)
        frames = integer(s["frames"], 44100, 44100 * 60)
        integer(s["seed"], 1, 0xffffffff)
        if frames % 32 or len(s["events"]) > 512:
            raise ValueError("unaligned duration or more than 512 events")
        previous = 0
        for frame, op, part, a, b in s["events"]:
            integer(frame, previous, frames - 32)
            if frame % 32 or op not in OPS:
                raise ValueError("unaligned event or unknown operation")
            previous = frame
            integer(part, 0, 3)
            if op in ("param", "global"):
                integer(b, 0, 32767)  # Base parameter units; renderer enforces the descriptor range.
                if a not in (TRACK_PARAMS if op == "param" else GLOBAL_PARAMS):
                    raise ValueError(f"unknown {op} parameter {a!r}")
                if op == "global" and part != 0:
                    raise ValueError("global events use part 0")
            elif op == "step":
                integer(a, 0, 63)
                if not isinstance(b, dict) or set(b) != {"notes", "ratchet", "drums", "velocity"}:
                    raise ValueError("step requires notes/ratchet/drums/velocity")
                if not isinstance(b["notes"], list) or not 0 <= len(b["notes"]) <= 4:
                    raise ValueError("step needs at most four notes")
                for note in b["notes"]:
                    integer(note, 0, 127)
                integer(b["ratchet"], 1, 4)
                integer(b["drums"], 0, 255)
                integer(b["velocity"], 1, 127)
            elif op == "usb_midi":
                integer(a, 0x80, 0xef)
                integer(b, 0, 0x7f7f)
                if b & 0x8080 or a >> 4 in (0xc, 0xd) and b >> 8:
                    raise ValueError("invalid MIDI data bytes")
            elif op == "trs_byte":
                integer(a, 0, 0)
                integer(b, 0, 255)
            elif op in ("transport", "perform"):
                integer(a, 0, 0 if op == "transport" else 15)
                integer(b, 0, 1)
                if part != 0:
                    raise ValueError("transport/performance events use part 0")
            else:
                integer(b, 0, 127)
                integer(a, 0, 127)
                if op == "on" and b == 0 or op == "off" and b != 0:
                    raise ValueError("on needs nonzero velocity; off uses zero")
        checks = s["checks"]
        if type(checks["silent"]) is not bool:
            raise ValueError("silent check must be boolean")
        integer(checks["min_peak"], 0, 32767)
        integer(checks["min_voices"], 0, 8)
        integer(checks["min_starts"], 0, 10000)
        integer(checks["tail_peak_max"], 0, 32767)
        if len(checks["final_engines"]) != 4:
            raise ValueError("expected four final engines")
        for engine in checks["final_engines"]:
            integer(engine, 0, 127)
    if "shared_eight" not in names:
        raise ValueError("retain the shared_eight baseline and its negative controls")
    return scenarios


def header(scenarios):
    rows = []
    for i, s in enumerate(scenarios):
        rows.append(f"static const stress_event_t EVENTS_{i}[] = {{")
        for frame, op, part, a, b in s["events"]:
            if op == "param":
                a = TRACK_PARAMS[a]
            elif op == "global":
                a = GLOBAL_PARAMS[a]
            extra = ""
            if op == "step":
                notes = ",".join(map(str, b["notes"])) or "0"
                extra = f", {{{{{notes}}}, {len(b['notes'])}, ST_NOTE, {(b['ratchet']-1)<<3}, {b['velocity']}, {b['drums']}, 0}}"
                b = 0
            rows.append(f"    {{{frame}u, {OPS[op]}, {part}u, {a}, {b}u{extra}}},")
        rows.append("    {0, 0, 0, 0, 0}\n};")  # portable nonempty array for idle
    rows.append("static const stress_scenario_t STRESS_SCENARIOS[] = {")
    for i, s in enumerate(scenarios):
        rows.append(f'    {{"{s["name"]}", {s["frames"]}u, {s["seed"]}u, {len(s["events"])}u, EVENTS_{i}}},')
    return "\n".join(rows) + "\n};\n"


def logged_run(command, stdout_path, stderr_path=None, **kwargs):
    """Keep captured output even when subprocess.run raises on a timeout."""
    def raw(value):
        return value.encode("utf-8") if isinstance(value, str) else value or b""

    def save(stdout, stderr):
        stdout_path.write_bytes(raw(stdout) + (raw(stderr) if stderr_path is None else b""))
        if stderr_path is not None:
            stderr_path.write_bytes(raw(stderr))

    kwargs.setdefault("text", True)
    try:
        result = subprocess.run(command, capture_output=True, check=False, **kwargs)
    except subprocess.TimeoutExpired as error:
        save(error.stdout, error.stderr)
        raise
    save(result.stdout, result.stderr)
    return result


def run(binary, index, directory):
    directory.mkdir(parents=True, exist_ok=True)
    result = logged_run([str(binary), str(index), str(directory / "audio.s32"),
                         str(directory / "audio.wav")], directory / "stdout.txt", directory / "stderr.txt", timeout=90)
    if result.returncode:
        raise ValueError(f"{directory}: renderer exited {result.returncode}; see stderr.txt")
    state = json.loads(result.stdout)
    state["pcm_sha256"] = hashlib.sha256((directory / "audio.s32").read_bytes()).hexdigest()
    if (directory / "audio.s32").stat().st_size != state["frames"] * 8:
        raise ValueError("incomplete raw PCM")
    return state


def stable(result):
    return {k: v for k, v in result.items() if k not in ("render_ns", "instructions", "instruction_skip")}


def health(s, result):
    c = s["checks"]
    if any(result.get(k, 0) for k in ("midi_pending", "uart_drops", "performance_held")):
        raise ValueError("pending/dropped MIDI or unreleased performance effect")
    if result["frames"] != s["frames"] or result["playing"] or len(result["parts"]) != 4:
        raise ValueError("wrong duration or running transport")
    if (result["peak"] == 0) != c["silent"] or result["peak"] < c["min_peak"]:
        raise ValueError("unexpected silence or missing signal")
    if result["max_voices"] < c["min_voices"] or result["voice_starts"] < c["min_starts"]:
        raise ValueError("scenario did not exercise its required voice load")
    if result["tail_peak"] > c["tail_peak_max"]:
        raise ValueError("tail did not settle")
    for p, e in zip(result["parts"], c["final_engines"]):
        if p["engine"] != e or p["requested"] != e or any(p[k] for k in ("active", "gated", "held", "fading")):
            raise ValueError("unreleased voice or incomplete engine switch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=ROOT / "tests/stress_scenarios.json")
    parser.add_argument("--out", type=Path, help="new directory under build/ (default: unique build/stress/run-*)")
    args = parser.parse_args()
    os.chdir(ROOT)
    matrix_bytes = args.matrix.read_bytes()
    matrix = json.loads(matrix_bytes)
    scenarios = validate(matrix)
    if sys.byteorder != "little":
        raise ValueError("the hostsim WAV/raw adapter requires a little-endian host")
    # Keep every run's evidence; refuse to overwrite a prior measurement.
    if args.out:
        out = args.out.resolve()
        if not out.is_relative_to(ROOT / "build"):
            raise ValueError("stress artifacts must stay under ignored build/")
        out.mkdir(parents=True, exist_ok=False)
    else:
        (ROOT / "build/stress").mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="run-", dir=ROOT / "build/stress"))
    (out / "matrix.json").write_bytes(matrix_bytes)
    (out / "stress_schedule.h").write_text(header(scenarios))
    cc = shlex.split(os.environ.get("CC", "cc"))
    report = {"version": 1, "revision": None,
              "host": platform.platform(), "byteorder": sys.byteorder,
              "compiler": None,
              "matrix_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
              "source_sha256": {}, "builds": [], "results": [],
              "instruction_scope": "count-only fresh replay loop: events, DSP, clocks, PCM checksum and health checks; no PCM/WAV file IO; no warmup exclusion",
              "device": "unmeasured", "status": "running"}
    try:
        revision = logged_run(["git", "rev-parse", "HEAD"], out / "revision.log", timeout=METADATA_TIMEOUT)
        revision.check_returncode()
        report["revision"] = revision.stdout.strip()
        compiler = logged_run(cc + ["--version"], out / "compiler-version.log", timeout=METADATA_TIMEOUT)
        compiler.check_returncode()
        report["compiler"] = compiler.stdout
        logged_run(["git", "diff", "--binary", "HEAD"], out / "local.diff", out / "diff-stderr.txt",
                   text=False, timeout=METADATA_TIMEOUT).check_returncode()
        logged_run(["git", "status", "--porcelain"], out / "status.txt", out / "status-stderr.txt",
                   text=False, timeout=METADATA_TIMEOUT).check_returncode()
        for pattern in ("firmware/**/*", "build/gen/*", "tests/hostsim.c", "tests/stress_render.c", "tests/stress_matrix.py", "tests/host_instructions.h"):
            for path in ROOT.glob(pattern):
                if path.is_file():
                    report["source_sha256"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        # These test sources may be untracked during a local experiment. Keep their
        # contents as well as hashes so the recorded revision is not the only input.
        for name in ("stress_render.c", "stress_matrix.py", "hostsim.c", "host_instructions.h"):
            (out / name).write_bytes((ROOT / "tests" / name).read_bytes())
        # Compiler probe follows the host runner's Clang/GCC policy.
        probe = logged_run(cc + ["-fno-vectorize", "-fno-slp-vectorize", "-x", "c", "-c", "-o", os.devnull, "-"],
                           out / "probe.log", input="int main(void){return 0;}\n", timeout=METADATA_TIMEOUT)
        no_simd = ["-fno-vectorize", "-fno-slp-vectorize"] if probe.returncode == 0 else ["-fno-tree-vectorize", "-fno-tree-slp-vectorize"]
        reference = {}
        for label, flags in (("o2", ["-O2"]), ("os", ["-Os"] + no_simd)):
            binary = out / f"stress_{label}"
            command = cc + flags + ["-w", "-DFELUCCA_ARENA_CHECK=1", "-Ibuild/gen", "-Ifirmware/src", f"-I{out}",
                                    "-o", str(binary), "tests/stress_render.c", "-lm"]
            report["builds"].append(command)
            built = logged_run(command, out / f"build_{label}.log", timeout=120)
            if built.returncode:
                raise ValueError(f"build {label} failed; see build_{label}.log")
            for i, s in enumerate(scenarios):
                runs = [run(binary, i, out / label / s["name"] / str(k)) for k in range(2)]
                for r in runs:
                    health(s, r)
                if stable(runs[0]) != stable(runs[1]):
                    raise ValueError(f'{s["name"]}: repeated replay differs')
                if label == "o2":
                    reference[s["name"]] = stable(runs[0])
                elif reference[s["name"]] != stable(runs[0]):
                    raise ValueError(f'{s["name"]}: O2/Os PCM or checkpoint differs')
                cost_dir = out / label / s["name"] / "cost"
                cost_dir.mkdir()
                cost = logged_run([str(binary), str(i), "--count"], cost_dir / "stdout.txt", cost_dir / "stderr.txt", timeout=90)
                cost.check_returncode()
                cost_state = json.loads(cost.stdout)
                health(s, cost_state)
                if {k: v for k, v in stable(cost_state).items() if k != "pcm_sha256"} != {k: v for k, v in reference[s["name"]].items() if k != "pcm_sha256"}:
                    raise ValueError("count replay changed checkpoint state")
                report["results"].append({"scenario": s["name"], "build": label, "runs": runs,
                                          "instructions_per_frame": cost_state["instructions"] / s["frames"] if cost_state["instructions"] is not None else None,
                                          "instruction_skip": cost_state["instruction_skip"],
                                          "instruction_source": cost_state["counter_source"],
                                          "ns_per_frame": [r["render_ns"] / s["frames"] for r in runs]})
                print(f'stress: {label} {s["name"]}: repeated PCM/state and health ok', flush=True)
        # Negative controls: the comparator must notice missing sound; health
        # must reject a sustained note that never receives its release.
        original = next(s for s in scenarios if s["name"] == "shared_eight")
        changed = copy.deepcopy(original)
        changed["events"] = [e for e in changed["events"] if e[1] != "on"]
        stuck = copy.deepcopy(original)
        stuck["events"] = [e for e in stuck["events"] if e[1] != "off"]
        controls = [changed, stuck]
        for name, operations in (("dense_ratchets_modulation", {"transport"}),
                                 ("effects_throws", {"perform"}), ("usb_trs_midi", {"usb_midi", "trs_byte"})):
            if name in reference:
                control = copy.deepcopy(next(s for s in scenarios if s["name"] == name))
                control["events"] = [e for e in control["events"] if e[1] not in operations]
                controls.append(control)
        (out / "negative_scenarios.json").write_text(json.dumps(controls, indent=2) + "\n")
        (out / "stress_schedule.h").write_text(header(controls))
        negative = out / "stress_negative"
        command = report["builds"][0].copy()
        command[command.index("-o") + 1] = str(negative)
        report["negative_build"] = command
        built = logged_run(command, out / "build_negative.log", timeout=120)
        if built.returncode:
            raise ValueError("negative-control build failed; see build_negative.log")
        if run(negative, 0, out / "negative/drop_on")["pcm_sha256"] == reference[original["name"]]["pcm_sha256"]:
            raise ValueError("dropped note-on negative control was invisible")
        stuck_result = run(negative, 1, out / "negative/drop_off")
        if not any(p["gated"] for p in stuck_result["parts"]):
            raise ValueError("missing note-off fixture did not leave a sustained voice")
        try:
            health(original, stuck_result)
        except ValueError:
            pass
        else:
            raise ValueError("missing note-off negative control passed health")
        for i, control in enumerate(controls[2:], 2):
            result = run(negative, i, out / "negative" / control["name"])
            if result["pcm_sha256"] == reference[control["name"]]["pcm_sha256"]:
                raise ValueError(f"{control['name']}: removed stress events were invisible")
            if control["name"] != "effects_throws":
                try:
                    health(control, result)
                except ValueError:
                    pass
                else:
                    raise ValueError("removed required input passed health")
        report["negative_controls"] = "passed"
        report["status"] = "passed"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        (out / "stress_schedule.h").write_text(header(scenarios))
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"stress: PASS; evidence in {out}")


if __name__ == "__main__":
    main()
