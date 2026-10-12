#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise real regress reports/exit codes with deterministic counter failures."""
import os
from pathlib import Path
import platform
import shlex
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    system = platform.system()
    if system not in ("Darwin", "Linux"):
        print("skip counter injection (requires macOS or Linux)")
        return 0
    binaries = sys.argv[1:]
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
        tmp = Path(tmp)
        shim = tmp / ("counter.dylib" if system == "Darwin" else "counter.so")
        command = shlex.split(os.environ.get("CC", "cc"))
        command += ["-Wall", "-Wextra", "-Werror", "-dynamiclib" if system == "Darwin" else "-shared",
                    "-fPIC", str(ROOT / "tests/regress_counter_shim.c"), "-o", str(shim)]
        if system == "Linux":
            command += ["-ldl"]
        subprocess.run(command, check=True)
        state, baseline = tmp / "state", tmp / "baseline.txt"
        # Full-mix counts exceed these budgets; missing preset entries are allowed.
        original = "cpu/mix/idle 1\ncpu/mix/idle_drums 1\ncpu/mix/3parts_full_drums 1\ncpu/mix/idle_click 1\n"

        def run(binary, fail_job=0, update=False, missing=False, crash=False):
            state.write_bytes(struct.pack("I", 0))
            baseline.write_text(original)
            env = dict(os.environ)
            for key in ("BUDGET_UPDATE", "GOLDEN_UPDATE", "COUNTER_CRASH"):
                env.pop(key, None)
            env.update(COUNTER_STATE=str(state), COUNTER_FAIL_JOB=str(fail_job))
            env["DYLD_INSERT_LIBRARIES" if system == "Darwin" else "LD_PRELOAD"] = str(shim)
            if update:
                env["BUDGET_UPDATE"] = "1"
            if crash:
                env["COUNTER_CRASH"] = "1"
            result = subprocess.run([str(ROOT / binary), "tests/golden.txt",
                                     str(tmp / "missing.txt") if missing else str(baseline)],
                                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=120)
            count = struct.unpack("I", state.read_bytes())[0]
            return result, count

        def skipped(result, should_fail=False):
            assert bool(result.returncode) == should_fail, result.stdout + result.stderr
            assert "CPU budget not checked" in result.stdout, result.stdout
            assert "CPU OVER BUDGET" not in result.stdout, result.stdout
            assert "CPU note " not in result.stdout, result.stdout
            assert "CPU baseline " not in result.stdout, result.stdout
            assert baseline.read_text() == original, "partial counts rewrote the baseline"

        for binary in binaries:
            result, count = run(binary)
            assert result.returncode == 1 and "CPU OVER BUDGET" in result.stdout, result.stdout + result.stderr
            assert "CPU budget not checked" not in result.stdout, result.stdout
            # A late failure must invalidate comparisons for earlier successful workers too.
            result, _ = run(binary, fail_job=count)
            skipped(result)
            print(f"counter fixtures: {binary}: complete counts fail; late unavailable count skips")
        binary = binaries[0]
        for fail_job in (1, 2):
            result, _ = run(binary, fail_job=fail_job)
            skipped(result)
        result, _ = run(binary, fail_job=2, missing=True)
        skipped(result)
        result, _ = run(binary, fail_job=2, update=True)
        skipped(result)
        assert "no baseline written" in result.stdout, result.stdout
        result, _ = run(binary, fail_job=2, crash=True)
        skipped(result, should_fail=True)
        assert "CRASH  cpu/" in result.stdout, result.stdout
        result, _ = run(binary, update=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "# Compiler: " in baseline.read_text(), baseline.read_text()
        assert "CPU baseline " in result.stdout and "rewritten" in result.stdout, result.stdout
        print("counter fixtures: first/middle failure, missing baseline, update preservation, crash: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
