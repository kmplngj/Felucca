#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Focused production-source regressions; requires coordinator-built build/gen.

No baseline updates, target builds, or generated shared assets. ASan/UBSan are
fatal with no sanitizer exclusions. All binaries, schedules and logs are isolated.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/focused-agent/candidate")
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "build"):
        parser.error("--out must be under ignored build/")
    out.mkdir(parents=True, exist_ok=True)
    cc = shlex.split(os.environ.get("CC", "cc"))
    base = cc + ["-g", "-Wall", "-Wno-unused-function", "-Wno-int-to-pointer-cast",
                 "-U_FORTIFY_SOURCE", "-D_FORTIFY_SOURCE=0", "-Ibuild/gen", "-Ifirmware/src"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")

    def invoke(command, log, expected=0, contains=None):
        result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / log).write_text(result.stdout)
        if result.returncode != expected or contains and contains not in result.stdout:
            raise RuntimeError(f"{log}: exit {result.returncode}, expected {expected}\n{result.stdout[-4000:]}")
        print(f"PASS {log}", flush=True)

    cases = [("timer5_midi", []), ("timer5_midi", ["-DFELUCCA_UART=0"]),
             ("timer5_midi", ["-DTIMER5_SYNTH_TEST"]), ("uart_dma", []),
             ("signed_audio_scaling", []), ("phys_signed", []), ("beat_samples", [])]
    for mode, flags in [("optimized", ["-O2"]),
                        ("strict", ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"])]:
        for index, (name, extra) in enumerate(cases):
            label = f"{mode}-{index}-{name}"
            binary = out / label
            invoke(base + flags + extra + [f"tests/{name}_test.c", "-lm", "-o", str(binary)], label + "-build.log")
            invoke([str(binary)], label + ".log")
            if name == "signed_audio_scaling":
                invoke([str(binary), "--fm6"], label + "-fm6.log")

    # Use the actual stress schedule generator and actual C event publisher.
    # Bad tempo must be rejected before publication; valid endpoints must render.
    spec = importlib.util.spec_from_file_location("stress_matrix", ROOT / "tests/stress_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values = [0, -1, 39, 241, 32767, 40, 120, 240]
    schedules = [dict(name=f"bpm_{i}", frames=44160, seed=1,
                      events=[[0, "global", 0, "bpm", value]]) for i, value in enumerate(values)]
    (out / "stress_schedule.h").write_text(module.header(schedules))
    binary = out / "stress-tempo-publication"
    invoke(base + ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(out), "tests/stress_render.c", "-lm", "-o", str(binary)], "stress-tempo-build.log")
    for index, value in enumerate(values):
        invalid = not 40 <= value <= 240
        invoke([str(binary), str(index), str(out / "stress.raw"), str(out / "stress.wav")],
               f"stress-tempo-{index}.log", 2 if invalid else 0,
               "outside 40..240" if invalid else '"frames":44160')
    print(f"Focused MIDI/DSP regressions passed; logs: {out}")


if __name__ == "__main__":
    main()
