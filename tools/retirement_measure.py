#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Issue #309 host-only observation; never patches the checkout or target firmware.

Run with plain Python 3.12+ (sample generation uses the existing build dependencies):
  uv run --locked --group build python tools/retirement_measure.py \
    --samples-dir /absolute/path/to/assets/samples-cc0 --out build/issue309/run-1

Exports the specified committed tree and exact Engines gitlink; retains all inputs,
anchored host-copy patches, build commands, raw PCM, logs and hashes under build/.
Counterfactual ONLY excludes inactive gates from the fresh-phrase predicate. It
does not implement retirement, change note ownership or propose a product policy.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SEED_REF = "1523fd0e9bb1483082ba5a71834e7255c04e7ff5"
VARIANTS = ("pristine", "observer", "counterfactual")
OVERLAYS = ("tests/retirement_probe.c", "tests/retirement_observer.h")
PHRASE = "    for (i = 0; i < NVOICE; i++)\n        any |= t->v[i].gate;\n"
BLOCK = "static uint32_t track_render(track_t *t, int32_t *out, uint32_t n)\n{\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hashes(root):
    return {str(p.relative_to(root)): digest(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}


def export(command, destination):
    data = subprocess.check_output(command)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(destination, filter="data")


def metadata_repo(destination, objects, revision):
    """Local disposable metadata for the existing profile source-pin checks.

    Exported source bytes remain authoritative. Objects are read-only alternates;
    index and detached HEAD live solely inside the ignored snapshot. No refs,
    index or worktree in the original repositories are changed.
    """
    subprocess.run(["git", "-c", "init.templateDir=", "init", "--quiet", destination], check=True)
    gitdir = destination / ".git"
    (gitdir / "objects/info/alternates").write_text(str(objects.resolve()) + "\n")
    (gitdir / "HEAD").write_text(revision + "\n")
    subprocess.run(["git", "-C", destination, "read-tree", revision], check=True)


def run(command, cwd, log, env, check=True):
    result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                            capture_output=True, timeout=600)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(result.stdout)
    log.with_suffix(log.suffix + ".stderr").write_bytes(result.stderr)
    log.with_suffix(log.suffix + ".command.json").write_text(json.dumps({
        "command": list(map(str, command)), "cwd": str(cwd), "returncode": result.returncode}, indent=2))
    if check and result.returncode:
        raise RuntimeError(f"exit {result.returncode}: see {log} and its stderr")
    return result


def patch_host_copy(tree):
    path = tree / "firmware/src/voice.c"
    source = path.read_text()
    if source.count(PHRASE) != 1 or source.count(BLOCK) != 1:
        raise ValueError("voice.c anchors changed: inspect source; refusing substitution")
    source = '#include "../../tests/retirement_observer.h"\n' + source
    source = source.replace(PHRASE, "    any = rv_phrase_gates(t, note);\n")
    source = source.replace(BLOCK, BLOCK + "    rv_observe_block(t);\n")
    path.write_text(source)


def pcm_compare(a, b):
    left, right = a.read_bytes(), b.read_bytes()
    offset = next((i for i, (x, y) in enumerate(zip(left, right)) if x != y), None)
    if offset is None and len(left) != len(right):
        offset = min(len(left), len(right))
    return {"equal": left == right, "first_different_byte": offset,
            "first_different_stereo_frame": None if offset is None else offset // 8,
            "reference_sha256": digest(left), "candidate_sha256": digest(right),
            "reference_bytes": len(left), "candidate_bytes": len(right)}


def event_counts(path):
    result = {"event_file_present": path.exists(), "note_events": 0, "inactive_gate_note_events": 0,
              "note_reset_suppressed_by_inactive_only": 0, "per_engine": {},
              "max_observed_inactive_gate_slot_blocks_per_pid": {}}
    if not path.exists():
        return result
    for line in path.open():
        event = json.loads(line)
        pid = str(event["pid"])
        totals = result["max_observed_inactive_gate_slot_blocks_per_pid"]
        totals[pid] = max(totals.get(pid, 0), event["inactive_gate_slot_blocks"])
        if event["kind"] != "note":
            continue
        result["note_events"] += 1
        result["inactive_gate_note_events"] += bool(event["inactive_gate_mask"])
        affected = event["note_reset_suppressed_by_inactive_only"]
        result["note_reset_suppressed_by_inactive_only"] += affected
        key = str(event["engine"])
        row = result["per_engine"].setdefault(key, {"note_events": 0, "suppressed": 0})
        row["note_events"] += 1
        row["suppressed"] += affected
    return result


def focused_ownership(path):
    states = [json.loads(line) for line in path.read_text().splitlines()]
    held = orphan = 0
    for state in states:
        for voice in state["voices"]:
            if not voice["active"] and voice["gate"]:
                held += bool(voice["logical_midi_held"])
                orphan += not voice["logical_midi_held"]
    return {"sampled_inactive_gate_with_midi_owner": held,
            "sampled_inactive_gate_without_midi_owner": orphan,
            "scope": "focused MIDI-only state snapshots, NOT all regress/stress ownership",
            "events": [{k: v for k, v in state.items() if k != "voices"} for state in states]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", default=SEED_REF)
    ap.add_argument("--samples-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--focused-only", action="store_true", help="probe development only; does not satisfy regress/stress coverage")
    args = ap.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "build") or out.exists():
        raise ValueError("--out must be a NEW directory under this checkout's ignored build/")
    if not list(args.samples_dir.glob("*/*.wav")):
        raise ValueError("real CC0 WAV inputs required; no SAMPLE/GRAIN fallback-sine evidence")
    out.mkdir(parents=True)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("FELUCCA_") or key in ("GOLDEN_UPDATE", "BUDGET_UPDATE", "PSET", "COVERAGE_DIR"):
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cc = shlex.split(env.get("CC", "cc"))
    flags = ["-O2", "-w", "-DFELUCCA_ARENA_CHECK=1", "-Ibuild/gen", "-Ifirmware/src"]
    ref = subprocess.check_output(["git", "-C", ROOT, "rev-parse", args.ref + "^{commit}"], text=True).strip()
    pin = subprocess.check_output(["git", "-C", ROOT, "rev-parse", ref + ":firmware/engines"], text=True).strip()
    common = Path(subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True).strip())
    engine_git = common / "modules/firmware/engines"
    base = out / "frozen"
    report = {"revision": ref, "engines_pin": pin, "host": platform.platform(), "flags": flags,
              "counterfactual": "ONLY fresh-phrase any := OR(gate && active); no voice fields/ownership changed",
              "cpu_budget": "NOT MEASURED: regress CPU_FILE is '-' and observer IO invalidates cost comparisons",
              "device_target_resources": "NOT MEASURED", "focused_only": args.focused_only,
              "runs": [], "comparisons": [], "status": "incomplete"}
    summary = out / "summary.json"
    try:
        export(["git", "-C", ROOT, "archive", ref], base)
        export(["git", "--git-dir=" + str(engine_git), "archive", pin], base / "firmware/engines")
        report["frozen_tracked_inputs"] = hashes(base)
        shutil.copytree(args.samples_dir, base / "assets/samples-cc0", dirs_exist_ok=True)
        report["sample_inputs"] = hashes(base / "assets/samples-cc0")
        metadata_repo(base, common / "objects", ref)
        metadata_repo(base / "firmware/engines", engine_git / "objects", pin)
        for name in OVERLAYS:
            shutil.copyfile(ROOT / name, base / name)
        shutil.copyfile(Path(__file__), out / "retirement_measure.py")
        report["measurement_overlay_inputs"] = {name: digest((ROOT / name).read_bytes()) for name in OVERLAYS}
        report["driver_sha256"] = digest(Path(__file__).read_bytes())
        report["compiler"] = run(cc + ["--version"], base, out / "compiler.log", env).stdout.decode()
        (base / "build/gen").mkdir(parents=True, exist_ok=True)
        for script, target in (("profile.py", None), ("gen_tables.py", "felucca_tables.h"),
                               ("gen_fm6_patches.py", "felucca_fm6.h"), ("gen_samples.py", "felucca_samples.h")):
            command = [sys.executable, "tools/" + script]
            command += ["--profile", "standard", "--out", "build/gen"] if target is None else ["build/gen/" + target]
            run(command, base, out / (script + ".log"), env)
        spec = importlib.util.spec_from_file_location("retirement_frozen_matrix", base / "tests/stress_matrix.py")
        matrix_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(matrix_module)
        matrix = json.loads((base / "tests/stress_scenarios.json").read_text())
        scenarios = matrix_module.validate(matrix)
        (base / "build/gen/stress_schedule.h").write_text(matrix_module.header(scenarios))
        report["generated_inputs"] = hashes(base / "build/gen")
        for variant in VARIANTS:
            print("retirement:", variant, flush=True)
            tree = out / variant / "source"
            shutil.copytree(base, tree)
            if variant != "pristine":
                patch_host_copy(tree)
            run_dir = out / variant
            report.setdefault("variant_voice_sha256", {})[variant] = digest((tree / "firmware/src/voice.c").read_bytes())
            diff = run(["diff", "-u", str(base / "firmware/src/voice.c"), str(tree / "firmware/src/voice.c")],
                       tree, run_dir / "host-only-voice.patch", env, check=False)
            if diff.returncode not in (0, 1):
                raise ValueError("could not record host-copy diff")
            variant_flags = flags + ["-DRV_COUNTERFACTUAL=" + str(int(variant == "counterfactual"))]
            def compile_one(source, binary):
                run(cc + variant_flags + [source, "-lm", "-o", binary], tree, run_dir / (binary + ".build.log"), env)
            compile_one("tests/retirement_probe.c", "probe")
            probes = [(engine, action) for engine in ("SAMPLE", "SLICE", "GRAIN", "DRUM", "LOFI")
                      for action in ("held", "released", "same_pitch", "engine_change")]
            probes.append(("GRAIN", "zone_gap"))
            for engine, action in probes:
                label = engine + "_" + action
                events = run_dir / (label + ".events.jsonl")
                local_env = dict(env, RETIREMENT_EVENTS=str(events))
                pcm = run_dir / (label + ".s32")
                states_path = run_dir / (label + ".states.jsonl")
                run([tree / "probe", engine, action, pcm], tree, states_path, local_env)
                row = {"variant": variant, "workload": label, "counts": event_counts(events),
                       "ownership": focused_ownership(states_path)}
                report["runs"].append(row)
                if variant != "pristine":
                    comparison = pcm_compare(out / "pristine" / pcm.name, pcm)
                    comparison["focused_states_equal"] = states_path.read_bytes() == (
                        out / "pristine" / states_path.name).read_bytes()
                    comparison.update(variant=variant, workload=label)
                    report["comparisons"].append(comparison)
                    if variant == "observer" and not comparison["equal"]:
                        raise ValueError("observer changed focused PCM: " + label)
                    if variant == "observer" and not comparison["focused_states_equal"]:
                        raise ValueError("observer changed focused voice/ownership state: " + label)
            if not args.focused_only:
                compile_one("tests/regress.c", "regress")
                events = run_dir / "regress.events.jsonl"
                result = run([tree / "regress", "tests/golden.txt", "-"], tree,
                             run_dir / "regress.log", dict(env, RETIREMENT_EVENTS=str(events)), check=False)
                report["runs"].append({"variant": variant, "workload": "existing_regress_O2_CPU_FILE_-",
                                       "returncode": result.returncode, "counts": event_counts(events)})
                if variant != "counterfactual" and result.returncode:
                    raise ValueError("pristine/observer regression failed: inspect log")
                compile_one("tests/stress_render.c", "stress")
                for index, scenario in enumerate(scenarios):
                    label = "stress_" + scenario["name"]
                    events = run_dir / (label + ".events.jsonl")
                    pcm = run_dir / (label + ".s32")
                    result = run([tree / "stress", index, pcm, run_dir / (label + ".wav")], tree,
                                 run_dir / (label + ".log"), dict(env, RETIREMENT_EVENTS=str(events)))
                    state = json.loads(result.stdout)
                    matrix_module.health(scenario, state)
                    if pcm.stat().st_size != state["frames"] * 8:
                        raise ValueError("incomplete stress PCM: " + label)
                    report["runs"].append({"variant": variant, "workload": label,
                                           "state": state, "counts": event_counts(events)})
                    if variant != "pristine":
                        comparison = pcm_compare(out / "pristine" / pcm.name, pcm)
                        comparison.update(variant=variant, workload=label)
                        report["comparisons"].append(comparison)
                        if variant == "observer" and not comparison["equal"]:
                            raise ValueError("observer changed stress PCM: " + label)
            summary.write_text(json.dumps(report, indent=2))
        report["status"] = "passed_observer_equivalence; counterfactual_is_not_a_product_decision"
        print("retirement:", summary, flush=True)
    finally:
        summary.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
