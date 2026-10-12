#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Separate JieLi compile/link evidence for unsupported variable 64-bit division helpers."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as B


class TargetArithmetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("JIELI_TOOLCHAIN")
        tc = Path(configured or Path.home() / ".jieli/toolchain")
        if not (tc / "pi32v2/bin/clang").exists():
            if configured:
                raise RuntimeError(f"configured JieLi toolchain has no pi32v2/bin/clang: {tc}")
            raise unittest.SkipTest("JieLi toolchain unavailable; target helper evidence not measured")
        cls.env = patch.dict(os.environ, {"JIELI_TOOLCHAIN": str(tc)})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        cls.out = ROOT / "build/host/build_guard_target"
        cls.out.mkdir(parents=True, exist_ok=True)
        (cls.out / "provenance.json").write_text(json.dumps({
            "compiler": B.tc("pi32v2/bin/clang", "--version"), "flags": B.CFLAGS,
            "scope": "compile/link smoke only; no target execution or device timing",
        }, indent=2) + "\n")

    def compile_link(self, name, code):
        src, obj, elf = (self.out / (name + ext) for ext in (".c", ".o", ".elf"))
        src.write_text("/* SPDX-License-Identifier: GPL-3.0-only */\n" + code + "\n")
        B.tc("cc", *B.CFLAGS, "-c", src, "-o", obj)
        output = io.StringIO()
        error = None
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                B.tc("pi32v2/bin/ld", "-e", "probe", "-Ttext=0x01c0a800", obj, "-o", elf)
            except SystemExit as e:
                error = e
        (self.out / (name + ".link.log")).write_text(output.getvalue())
        return error, output.getvalue(), obj, elf

    def test_variable_divide_and_remainder_require_missing_helpers(self):
        for name, typ, op, helper in (("udiv64", "unsigned long long", "/", "__udivdi3"),
                                       ("sdiv64", "long long", "/", "__divdi3"),
                                       ("urem64", "unsigned long long", "%", "__umoddi3")):
            with self.subTest(name=name):
                error, log, obj, _ = self.compile_link(name, f"{typ} probe({typ} a, {typ} b) {{ return a {op} b; }}")
                self.assertIsNotNone(error, log)
                self.assertIn(helper, log)
                (self.out / (name + ".dis")).write_text(B.tc("common/bin/objdump", "-d", obj))

    def test_widened_multiply_and_fixed_shifts_link(self):
        error, log, _, elf = self.compile_link("mul_shift64",
            "unsigned long long probe(unsigned a, unsigned b) { return (((unsigned long long)a * b) >> 17) + ((unsigned long long)a << 9); }")
        self.assertIsNone(error, log)
        (self.out / "mul_shift64.dis").write_text(B.tc("common/bin/objdump", "-d", elf))


if __name__ == "__main__":
    unittest.main()
