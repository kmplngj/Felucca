#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""One-off native replay of the exact issue670 IR; not a production build entry point."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time

SOURCE = "baae84778dc3dc4602b1a2c3a1e1d40e8885f777"
ENGINE = "9630426f5c4a34a209ca851356fbe8ba3c4c6d19"
IR_SHA = "5b3f6adc24ec1877f462d4fa990373012b61622fbd00bab27d29fbcc00eab518"
OBJECT_SHA = "0aa38c3ee4e84acfdce6a1576351927331a1412bf98e1a70756ac70f17778b5d"
TOOLS = {
    "pi32v2/bin/clang": "c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f",
    "pi32v2/bin/ld": "fd61aff15616bb6f6b58fd2e9ede7af741c7bf05facb3e0cb3d3c9817c268fd9",
    "common/bin/objdump": "f7e449e2c8001d5ed4493a45d1f5f304c8910418e4074acdc8715079ef64e08a",
    "common/bin/objcopy": "295151226e28891115c97262e6460a06fe67fc0753858e0df3234eb000ea6e66",
}
BACKEND = ["-Os", "-ffunction-sections", "-fno-builtin"]
ARTIFACTS = (
    "build/felucca.bin", "build/felucca.fwsc", "build/resource-report.json",
    "build/felucca.dis", "build/profile-contract.json", "build/felucca.dis.profile.json",
    "build/felucca.elf", "build/loader/ota.bin",
    "build/gen/engine_categories.inc", "build/gen/ui_keycaps.h",
    "build/gen/felucca_profile.h", "build/gen/engine_includes.inc",
    "build/gen/engine_order.inc", "build/gen/felucca_tables.h",
    "build/gen/build-identity.json", "build/gen/engine_names.inc",
    "build/gen/engine_cc.inc", "build/gen/ui_fonts.h", "build/gen/felucca_fm6.h",
    "build/gen/felucca_samples.h", "build/gen/engine_registry.inc",
    "build/gen/ui_icons.h", "build/gen/build_identity.h", "build/gen/ui_palettes.h",
    "build/gen/resolved-profile.json", "build/gen/engine_metadata.inc",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def clean_source(root):
    if git(root, "rev-parse", "HEAD") != SOURCE or git(root, "status", "--porcelain"):
        raise ValueError("frozen source revision is wrong or dirty")
    engine = root / "firmware/engines"
    if git(engine, "rev-parse", "HEAD") != ENGINE or git(engine, "status", "--porcelain"):
        raise ValueError("frozen engine revision is wrong or dirty")


def main(root, out):
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValueError("comparison requires native Linux x86_64")
    clean_source(root)
    if os.environ.get("GOLDEN_UPDATE") or os.environ.get("BUDGET_UPDATE"):
        raise ValueError("baseline updates are forbidden")
    # Only this isolated process gets ordinary clean-source identity. Do not write GITHUB_ENV.
    orchestration = {key: os.environ.get(key) for key in
                     ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "EXPERIMENT_HEAD")}
    for key in list(os.environ):
        if key.startswith(("FELUCCA_", "EMU_")):
            os.environ.pop(key)
    os.environ.update(GITHUB_ACTIONS="false", JIELI_DOCKER="0", FELUCCA_PROFILE="standard",
                      FELUCCA_CPU2="1", FELUCCA_FM4="0", FELUCCA_SLICE="1",
                      FELUCCA_SIZE="1", FELUCCA_FONT="m8stealth",
                      PYTHONDONTWRITEBYTECODE="1", PYTHON=sys.executable)
    sys.dont_write_bytecode = True
    os.chdir(root)
    sys.path.insert(0, str(root / "tools"))
    import build as B
    import ci

    tools = {name: digest(B.toolchain() / name) for name in TOOLS}
    write(out / "tool-gate.json", {"expected": TOOLS, "actual": tools})
    if tools != TOOLS or B.use_docker():
        raise ValueError("toolchain hash/native-execution gate failed before compiler execution")
    ci.check_sdk(Path(os.environ["AC79_SDK"]))
    sdk = {name: digest(Path(os.environ["AC79_SDK"]) / "cpu/wl82/tools" / name)
           for name in B.SDK_SHA256}
    cpuinfo = Path("/proc/cpuinfo").read_bytes()
    os_release = Path("/etc/os-release").read_bytes()
    (out / "runner-cpuinfo.txt").write_bytes(cpuinfo)
    (out / "runner-os-release.txt").write_bytes(os_release)
    cpu_models = sorted({line.split(":", 1)[1].strip()
                         for line in cpuinfo.decode(errors="replace").splitlines()
                         if line.split(":", 1)[0].strip() == "model name" and ":" in line})
    write(out / "PROVENANCE.json", {
        "source": SOURCE, "engine": ENGINE, "expected_ir_sha256": IR_SHA,
        "expected_object_sha256": OBJECT_SHA, "tools": tools, "sdk": sdk,
        "platform": platform.platform(), "machine": platform.machine(),
        "python": sys.version, "logical_cpus": os.cpu_count(),
        "cpu_models": cpu_models,
        "cpuinfo": {"file": "runner-cpuinfo.txt", "sha256": hashlib.sha256(cpuinfo).hexdigest()},
        "os_release": {"file": "runner-os-release.txt", "sha256": hashlib.sha256(os_release).hexdigest()},
        "helper_sha256": digest(Path(__file__)),
        "orchestration": orchestration, "backend_flags": BACKEND,
        "identity_policy": "GITHUB_ACTIONS=false in helper process only; clean fixed Git source",
        "execution_backend": "native; no Docker", "target_source_modified": False,
    })

    original_run, original_tc = subprocess.run, B.tc
    records, events, mutex = [], [], threading.Lock()
    active = "initial-build"

    def observed(args, *positional, **kwargs):
        # Log subprocess.run calls (native tools and size pass). Generator Popen output
        # remains in each aggregate build log; generation has a separate phase interval.
        if positional or isinstance(args, (str, bytes)) or kwargs.get("shell"):
            raise ValueError("unexpected subprocess invocation in fixed producer")
        options = dict(kwargs)
        capture = bool(options.get("capture_output"))
        echo_stdout = not capture and options.get("stdout") is None
        echo_stderr = not capture and options.get("stderr") is None
        if not capture:
            if any(options.get(key) not in (None, subprocess.PIPE) for key in ("stdout", "stderr")):
                raise ValueError("unexpected explicit stream redirection in fixed producer")
            options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        start, utc = time.perf_counter_ns(), datetime.now(timezone.utc).isoformat()
        error = None
        try:
            result = original_run(args, **options)
        except subprocess.CalledProcessError as failure:
            result, error = failure, failure
        except OSError as failure:
            result = subprocess.CompletedProcess(args, -1, b"", str(failure).encode())
            error = failure
        end = time.perf_counter_ns()
        with mutex:
            stem = f"raw-{len(records):03d}"
            for name in ("stdout", "stderr"):
                value = getattr(result, name, None) or b""
                (out / f"{stem}.{name}").write_bytes(value.encode() if isinstance(value, str) else value)
            row = {"run": active, "argv": [str(a) for a in args],
                   "returncode": result.returncode, "start_ns": start, "end_ns": end,
                   "seconds": (end-start)/1e9, "utc_start": utc,
                   "stdout": f"{stem}.stdout", "stderr": f"{stem}.stderr"}
            records.append(row)
            with (out / "commands.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")
        if echo_stdout:
            value = result.stdout or ""
            sys.stdout.write(value.decode(errors="replace") if isinstance(value, bytes) else value)
        if echo_stderr:
            value = result.stderr or ""
            sys.stderr.write(value.decode(errors="replace") if isinstance(value, bytes) else value)
        if error:
            raise error
        return result

    def relative_tc(tool, *args):
        normalized = []
        for value in args:
            text = str(value)
            if isinstance(value, Path) or text.startswith(str(root) + os.sep):
                text = Path(value).resolve().relative_to(root).as_posix()
            normalized.append(text)
        return original_tc(tool, *normalized)

    def gate(label):
        actual = {"ir": digest(root / "build/felucca_size.ll"),
                  "object": digest(root / "build/felucca.o")}
        write(out / f"{label}-comparison-gate.json", {
            "expected": {"ir": IR_SHA, "object": OBJECT_SHA}, "actual": actual,
            "matches": actual == {"ir": IR_SHA, "object": OBJECT_SHA}})
        for name in ("felucca.ll", "felucca_size.ll", "felucca.o", "resource-report.json"):
            shutil.copyfile(root / "build" / name, out / f"{label}-{name}")
        if actual != {"ir": IR_SHA, "object": OBJECT_SHA}:
            raise ValueError("native IR/object differs; comparison refused without normalization")

    def snapshot(label):
        hashes = {}
        for name in ARTIFACTS:
            hashes[name] = digest(root / name)
            copied = out / f"{label}-artifacts" / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, copied)
            if digest(copied) != hashes[name]:
                raise ValueError("native artifact changed during evidence copy")
        return hashes

    def wrap(name, fn):
        def call(*args, **kwargs):
            start = time.perf_counter_ns()
            try:
                return fn(*args, **kwargs)
            finally:
                with mutex:
                    events.append({"run": active, "phase": name, "start_ns": start,
                                   "end_ns": time.perf_counter_ns()})
        return call

    B.tc, B.subprocess.run = relative_tc, observed
    for name in ("generate", "build_loader", "build_app"):
        setattr(B, name, wrap(name, getattr(B, name)))
    try:
        with (out / "initial-build.log").open("x") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            B.main([])
        clean_source(root)
        gate("initial")  # No timed replay is allowed before both exact-byte gates pass.
        before = snapshot("initial")
        write(out / "INITIAL_ARTIFACTS.json", before)
        runs = []
        replay_dir = root / "build/compiler-profile-native"
        replay_dir.mkdir()
        for index in range(1, 4):
            for mode in ("control", "timed"):
                clean_source(root)
                active = f"{mode}-{index}"
                options = [] if mode == "control" else ["-ftime-report", "-mllvm", "-time-passes"]
                obj = replay_dir / f"{active}.o"
                start, load = time.perf_counter_ns(), os.getloadavg()
                with (out / f"{active}.combined.log").open("x") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    B.tc("cc", *BACKEND, *options, "-c", root / "build/felucca_size.ll", "-o", obj)
                end = time.perf_counter_ns()
                copied = out / obj.name
                shutil.copyfile(obj, copied)
                row = {"label": active, "mode": mode, "options": options,
                       "start_ns": start, "end_ns": end, "seconds": (end-start)/1e9,
                       "load_before": load, "load_after": os.getloadavg(),
                       "object_sha256": digest(copied), "ir_sha256": digest(root / "build/felucca_size.ll"),
                       "matches_original_standard_object": digest(copied) == OBJECT_SHA}
                row["pass_breakdown_present"] = "Pass execution timing report" in (
                    out / f"{active}.combined.log").read_text()
                runs.append(row)
                write(out / "REPLAYS.json", runs)
                if row["ir_sha256"] != IR_SHA or not row["matches_original_standard_object"]:
                    raise ValueError("replay changed IR/object; no normalized comparison accepted")
                if mode == "timed" and not row["pass_breakdown_present"]:
                    raise ValueError("timed compiler emitted no pass breakdown")
        active = "whole-build"
        start = time.perf_counter_ns()
        with (out / "whole-build.log").open("x") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            B.main([])
        end = time.perf_counter_ns()
        clean_source(root)
        gate("whole")
        after = snapshot("whole")
        matches = {name: before[name] == after[name] for name in ARTIFACTS}
        write(out / "WHOLE_BUILD.json", {
            "head": SOURCE, "start_ns": start, "end_ns": end, "seconds": (end-start)/1e9,
            "events": [event for event in events if event["run"] == "whole-build"],
            "before": before, "after": after, "artifact_matches": matches,
            "all26_native_artifacts_literal_equal": all(matches.values()),
            "profiling_flags_in_whole_build": False,
            "boundary": "imported build.main; excludes interpreter/import and build.sh prerequisites",
        })
        if not all(matches.values()):
            raise ValueError("fresh whole build changed native artifacts")
        write(out / "RESULT.json", {"status": "PASS", "head": SOURCE,
              "replay_count": len(runs), "all_objects_match_original": True,
              "all26_wholebuild_artifacts_equal": True, "native_sameIR_run": "measured",
              "ir_sha256": IR_SHA, "object_sha256": OBJECT_SHA})
    finally:
        B.tc, B.subprocess.run = original_tc, original_run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source.resolve(), args.out.resolve()
    if output.is_relative_to(root):
        parser.error("evidence output must be outside the frozen source")
    output.mkdir(parents=True, exist_ok=False)
    status = 0
    try:
        main(root, output)
    except BaseException as error:
        status = 1
        write(output / "FAILURE.json", {"type": type(error).__name__, "message": str(error),
                                       "comparison_qualified": False})
        print(f"native comparison failed: {error}", file=sys.stderr)
    finally:
        manifest = {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": digest(path)}
                    for path in sorted(output.rglob("*")) if path.is_file()}
        write(output / "MANIFEST.json", {"status": "PASS" if status == 0 else "FAIL",
                                        "files": manifest})
    raise SystemExit(status)
