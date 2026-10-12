#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real unoptimized JieLi LLVM 4 callback IR and annotation compile smoke."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as B
import size_fns as S


class TargetIR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("JIELI_TOOLCHAIN")
        tc = Path(configured or Path.home() / ".jieli/toolchain")
        if not (tc / "pi32v2/bin/clang").exists():
            if configured:
                raise RuntimeError(f"configured JieLi toolchain has no pi32v2/bin/clang: {tc}")
            raise unittest.SkipTest("JieLi toolchain unavailable; real IR smoke not measured")
        env = patch.dict(os.environ, {"JIELI_TOOLCHAIN": str(tc)})
        env.start()
        cls.addClassCleanup(env.stop)
        cls.out = ROOT / "build/host/size_fns_target"
        cls.out.mkdir(parents=True, exist_ok=True)

    def test_real_ir_protects_table_callbacks_and_compiles_annotations(self):
        src, ir, annotated, obj = (self.out / name for name in ("probe.c", "probe.ll", "annotated.ll", "probe.o"))
        src.write_text("""/* SPDX-License-Identifier: GPL-3.0-only */
typedef void (*callback_t)(void);
volatile unsigned selector;
static void callback_a(void) { selector++; }
static void callback_b(void) { selector--; }
static const callback_t callbacks[] = { callback_a, callback_b };
void ui_only(void) { selector = 0; }
const callback_t unrelated = ui_only;
void fm1_alnk0_irq(void) { callbacks[selector & 1u](); }
void fm1_timer5_irq(void) { callback_b(); }
""")
        ir_flags = [*B.CFLAGS, "-S", "-emit-llvm", "-Xclang", "-disable-llvm-optzns"]
        B.tc("cc", *ir_flags, "-c", src, "-o", ir)
        contract = {S.ISR_ROOTS[0]: (1, ("callbacks",))}
        text = ir.read_text().replace("@ui_only() #", "@ui_only() local_unnamed_addr #")
        self.assertIn("@ui_only() local_unnamed_addr #", text)
        out, hit, protected = S.annotate(text, {"callback_a", "callback_b", "ui_only"}, indirect=contract)
        self.assertEqual(protected, set(S.ISR_ROOTS) | {"callback_a", "callback_b"})
        self.assertEqual(hit, {"ui_only"})
        annotated.write_text(out)
        B.tc("cc", *B.CFLAGS, "-c", annotated, "-o", obj)
        (self.out / "probe.dis").write_text(B.tc("common/bin/objdump", "-d", obj))
        (self.out / "provenance.json").write_text(json.dumps({
            "compiler": B.tc("pi32v2/bin/clang", "--version"), "ir_flags": ir_flags,
            "object_flags": B.CFLAGS, "protected": sorted(protected), "minsize": sorted(hit),
            "scope": "fresh unoptimized target IR and annotated object; no target execution or timing",
        }, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
