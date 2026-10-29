#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run actual app/loader flash paths against a busy NOR and TIMER4 model."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / "firmware/hal/fm1_flash.h"
LOADER = ROOT / "firmware/loader/loader.c"


def function(source, name):
    """Keep the current production body, replacing only the hardware below it."""
    match = re.search(r"^(?:static (?:RAMFN )?|RAMINL )(?:int|void) " +
                      re.escape(name) + r"\([^;]*?\)\s*\{",
                      source, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"actual production function missing: {name}")
    depth = 1
    end = match.end()
    while depth:
        if end >= len(source):
            raise RuntimeError(f"unclosed production function: {name}")
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end] + "\n"


def main():
    cc = shlex.split(os.environ.get("CC", "cc"))
    hal, loader = HAL.read_text(), LOADER.read_text()
    # loader.c includes the same HAL; extract its actual direct-call hooks too.
    bodies = "\n".join(function(hal, name) for name in
                       ("fl_erase4k_ram", "fl_prog_ram", "fl_erase4k", "fl_write"))
    bodies += "\n" + "\n".join(function(loader, name) for name in ("ldr_erase", "ldr_prog"))
    with tempfile.TemporaryDirectory(prefix="felucca-flash-wait-") as temp:
        out = Path(temp)
        (out / "flash_driver.inc").write_text(bodies)
        (out / "flash_reset.inc").write_text(function(hal, "fl_reset_busy"))
        binary = out / "flash_wait_test"
        flags = shlex.split(os.environ.get("CFLAGS", "-O2"))
        subprocess.run([*cc, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                        "-I", str(out), str(ROOT / "tests/flash_wait_test.c"),
                        "-o", str(binary)], check=True, cwd=ROOT)
        subprocess.run([str(binary)], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
