#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real JieLi arithmetic emission/link evidence and final-image soft-double policy."""
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
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
        parent = ROOT / "build/host/build_guard_target"
        parent.mkdir(parents=True, exist_ok=True)
        cls.out = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        cls.runtime = tc / "pi32v2/lib/libcompiler_rt.a"
        (cls.out / "provenance.json").write_text(json.dumps({
            "compiler": B.tc("pi32v2/bin/clang", "--version"), "flags": B.CFLAGS,
            "toolchain": str(tc), "compiler_sha256": hashlib.sha256((tc / "pi32v2/bin/clang").read_bytes()).hexdigest(),
            "linker_sha256": hashlib.sha256((tc / "pi32v2/bin/ld").read_bytes()).hexdigest(),
            "objdump_sha256": hashlib.sha256((tc / "common/bin/objdump").read_bytes()).hexdigest(),
            "test_only_runtime": str(cls.runtime),
            "runtime_sha256": hashlib.sha256(cls.runtime.read_bytes()).hexdigest() if cls.runtime.is_file() else None,
            "scope": "compile/link smoke only; no target execution or device timing",
        }, indent=2) + "\n")
        print(f"JieLi arithmetic artifacts: {cls.out}")

    def compile_link(self, name, code, *, runtime=False):
        src, obj, elf = (self.out / (name + ext) for ext in (".c", ".o", ".elf"))
        src.write_text("/* SPDX-License-Identifier: GPL-3.0-only */\n" + code + "\n")
        B.tc("cc", *B.CFLAGS, "-c", src, "-o", obj)
        (self.out / (name + ".object.syms")).write_text(B.tc("common/bin/objdump", "-t", obj))
        libraries = []
        if runtime:
            self.assertTrue(self.runtime.is_file(), f"missing test-only generic compiler runtime: {self.runtime}")
            libraries = ["/opt/jieli/pi32v2/lib/libcompiler_rt.a" if B.use_docker() else str(self.runtime)]
        output = io.StringIO()
        error = None
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                B.tc("pi32v2/bin/ld", "-e", "probe", "-Ttext=0x01c0a800", obj, *libraries, "-o", elf)
            except SystemExit as e:
                error = e
        (self.out / (name + ".link.log")).write_text(output.getvalue())
        return error, output.getvalue(), obj, elf

    def final_soft_double_check(self, name, elf):
        hdr = B.tc("common/bin/objdump", "-h", elf)
        syms = B.tc("common/bin/objdump", "-t", elf)
        (self.out / (name + ".hdr")).write_text(hdr)
        (self.out / (name + ".syms")).write_text(syms)
        (self.out / (name + ".dis")).write_text(B.tc("common/bin/objdump", "-d", elf))
        result = B.soft_double_check(hdr, syms)
        (self.out / (name + ".guard.json")).write_text(json.dumps({"errors": result[0], "notes": result[1]}, indent=2) + "\n")
        return result

    def test_soft_double_dynamic_arithmetic_and_conversions_are_rejected(self):
        # Only this isolated probe links compiler_rt; the firmware's explicit-object link is unchanged.
        name = "soft_double_conversions"
        error, log, _, elf = self.compile_link(name, """
volatile double da, db;
volatile float fa;
volatile int si;
volatile unsigned ui;
volatile long long di;
volatile unsigned long long udi;
void probe(void) {
    da = da + db;
    da = da - db;
    da = da * db;
    da = da / db;
    db = (double)fa;
    fa = (float)da;
    da = (double)si;
    si = (int)db;
    da = (double)ui;
    ui = (unsigned)db;
    da = (double)di;
    di = (long long)db;
    da = (double)udi;
    udi = (unsigned long long)db;
}
""", runtime=True)
        self.assertIsNone(error, log)
        emitted = (self.out / (name + ".object.syms")).read_text()
        errors, notes = self.final_soft_double_check(name, elf)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("soft-double helpers defined in final executable sections", errors[0])
        self.assertEqual(notes, [])
        for helper in ("__adddf3", "__subdf3", "__muldf3", "__divdf3", "__extendsfdf2", "__truncdfsf2",
                       "__floatsidf", "__fixdfsi", "__floatunsidf", "__fixunsdfsi",
                       "__floatdidf", "__fixdfdi", "__floatundidf", "__fixunsdfdi"):
            with self.subTest(helper=helper):
                self.assertTrue(any(p[-3] == "*UND*" and p[-1] == helper
                                    for p in map(str.split, emitted.splitlines()) if len(p) >= 4), emitted)
                self.assertIn(helper, errors[0])

    def test_soft_double_fp32_control_passes(self):
        name = "fp32_arithmetic_control"
        error, log, _, elf = self.compile_link(name, """
volatile float fa, fb;
volatile int si;
void probe(void) {
    fa = fa + fb;
    fa = fa - fb;
    fa = fa * fb;
    fa = fa / fb;
    fa = (float)si;
    si = (int)fb;
}
""", runtime=True)
        self.assertIsNone(error, log)
        errors, notes = self.final_soft_double_check(name, elf)
        self.assertEqual(errors, [])
        self.assertIn("no known soft-double helpers defined in final executable sections", notes)

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
