#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Select host CPU baselines using the compiler that builds the harness."""
import hashlib
import platform
import subprocess
import sys


def baseline_paths(system, machine, macros):
    # Retain the historical Apple-clang arm64 baselines; other toolchains get their own.
    if system == "Darwin" and machine == "arm64" and "__apple_build_version__" in macros:
        return "tests/cpu_baseline.txt", "tests/cpu_baseline_os.txt"
    if "__clang__" in macros:
        family, version = "clang", macros["__clang_version__"]
        parts = [macros[f"__clang_{p}__"] for p in ("major", "minor", "patchlevel")]
    elif "__GNUC__" in macros:
        family, version = "gcc", macros["__VERSION__"]
        parts = [macros[p] for p in ("__GNUC__", "__GNUC_MINOR__", "__GNUC_PATCHLEVEL__")]
    else:
        raise ValueError("CPU baselines require a recognized Clang or GCC compiler")
    # Full vendor/build version distinguishes toolchains with the same release number.
    digest = hashlib.sha256(version.encode()).hexdigest()[:12]
    key = f"{system.lower()}_{machine}_{family}_{'_'.join(parts)}_{digest}"
    return f"tests/cpu_baseline_{key}.txt", f"tests/cpu_baseline_{key}_os.txt"


def main():
    try:
        result = subprocess.run(sys.argv[1:] + ["-dM", "-E", "-x", "c", "-"],
                                input="", text=True, capture_output=True, check=True)
        macros = {}
        for line in result.stdout.splitlines():
            fields = line.split(None, 2)
            if len(fields) == 3 and fields[0] == "#define":
                macros[fields[1]] = fields[2]
        print("\n".join(baseline_paths(platform.system(), platform.machine(), macros)))
    except (OSError, subprocess.CalledProcessError, KeyError, ValueError) as exc:
        print(f"CPU baseline compiler detection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
