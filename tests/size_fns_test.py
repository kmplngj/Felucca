#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable fixtures for selective minsize's ISR exclusion and final annotation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import size_fns as S


def function(name, body="ret void", attrs="#0"):
    return f"define void @{name}() {attrs} {{\n  {body}\n}}\n"


def module(audio="ret void", scan="ret void", extra=""):
    return (function(S.ISR_ROOTS[0], audio) + function(S.ISR_ROOTS[1], scan) + extra +
            "attributes #0 = { nounwind optsize }\n")


class Reachability(unittest.TestCase):
    def test_both_roots_transitive_calls_and_recursion(self):
        ir = module("call void @a()", "call void @b()",
                    function("a", "call void @b()") + function("b", "call void @a()") + function("ui"))
        self.assertEqual(S.isr_reach(ir), set(S.ISR_ROOTS) | {"a", "b"})

    def test_directly_taken_function_address_and_quoted_name(self):
        ir = module('store void ()* @"callback.name", void ()** @slot', extra=
                    '@slot = global void ()* null\n' + function('"callback.name"'))
        self.assertIn("callback.name", S.isr_reach(ir))

    def test_mutable_global_pointer_initializer_and_reviewed_dispatch(self):
        ir = module("%f = load void ()*, void ()** @dispatch\n  call void %f()", extra=
                    "@dispatch = global void ()* @callback\n" + function("callback", "call void @leaf()") + function("leaf"))
        # The graph follows the initializer, but it cannot establish runtime pointer ownership.
        with self.assertRaisesRegex(ValueError, "reviewed target/count contract"):
            S.isr_reach(ir)
        contract = {S.ISR_ROOTS[0]: (1, ("callback",))}
        self.assertEqual(S.isr_reach(ir, indirect=contract), set(S.ISR_ROOTS) | {"callback", "leaf"})
        with self.assertRaisesRegex(ValueError, "mutable dispatch"):
            S.isr_reach(ir, indirect={S.ISR_ROOTS[0]: (1, ("dispatch",))})

    def test_nested_constant_table_aliases_cycles_and_unrelated_global(self):
        ir = module("%f = load void ()*, void ()** @alias\n  call void %f()", extra="""
@alias = alias void ()*, void ()** @table
@table = constant { [2 x void ()*], void ()** } {
  [2 x void ()*] [void ()* @callback, void ()* @other],
  void ()** @alias
}
@unrelated = constant void ()* @ui
""" + function("callback", "call void @leaf()") + function("other") + function("leaf") + function("ui"))
        contract = {S.ISR_ROOTS[0]: (1, ("table",))}
        self.assertEqual(S.isr_reach(ir, indirect=contract), set(S.ISR_ROOTS) | {"callback", "other", "leaf"})
        out, hit, protected = S.annotate(ir, {"callback", "other", "leaf", "ui"}, indirect=contract)
        self.assertEqual(hit, {"ui"})
        self.assertIn("@ui() minsize #0", out)
        self.assertNotIn("@callback() minsize", out)

    def test_runtime_written_null_hook_requires_explicit_complete_targets(self):
        ir = module("%f = load void ()*, void ()** @hook\n  call void %f()", extra=
                    "@hook = global void ()* null\n" + function("register", "store void ()* @callback, void ()** @hook") +
                    function("callback", "call void @leaf()") + function("leaf") + function("ui"))
        with self.assertRaisesRegex(ValueError, "reviewed target/count contract"):
            S.isr_reach(ir)
        contract = {S.ISR_ROOTS[0]: (1, ("callback",))}
        self.assertEqual(S.isr_reach(ir, indirect=contract), set(S.ISR_ROOTS) | {"callback", "leaf"})

    def test_alias_and_constant_table_cannot_hide_mutable_dispatch(self):
        extra = ("@dispatch = global void ()* @first\n"
                 "@alias = alias void ()*, void ()** @dispatch\n"
                 "@table = constant void ()** @alias\n" + function("first") +
                 function("later", "store i32 1, i32* @state") + "@state = global i32 0\n" +
                 function("register", "store void ()* @later, void ()** @dispatch"))
        ir = module("%f = load void ()*, void ()** @alias\n  call void %f()", extra=extra)
        for target in ("alias", "table"):
            with self.assertRaisesRegex(ValueError, "mutable dispatch"):
                S.isr_reach(ir, indirect={S.ISR_ROOTS[0]: (1, (target,))})
        # Explicit complete callback targets may use mutable ISR state normally.
        contract = {S.ISR_ROOTS[0]: (1, ("first", "later"))}
        self.assertEqual(S.isr_reach(ir, indirect=contract), set(S.ISR_ROOTS) | {"first", "later"})

    def test_callback_names_and_strings_cannot_impersonate_storage_kind(self):
        for name in ("constant", "alias", '"constant alias"'):
            ir = module("%f = load void ()*, void ()** @dispatch\n  call void %f()", extra=
                        f"@dispatch = global void ()* @{name}\n" + function(name))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "mutable dispatch"):
                S.isr_reach(ir, indirect={S.ISR_ROOTS[0]: (1, ("dispatch",))})
        self.assertFalse(S.immutable_global('global %constant { i8* @alias }, section "constant alias"'))
        self.assertTrue(S.immutable_global('internal constant void ()* @global'))

    def test_unknown_dispatch_does_not_hide_behind_unrelated_callbacks(self):
        ir = module("call void %unknown()", extra="@unrelated = constant void ()* @ui\n" + function("ui"))
        with self.assertRaisesRegex(ValueError, "indirect ISR call"):
            S.isr_reach(ir)

    def test_changed_count_empty_and_missing_contract_targets(self):
        ir = module("call void %unknown()", extra=function("callback"))
        for contract in ({S.ISR_ROOTS[0]: (2, ("callback",))}, {S.ISR_ROOTS[0]: (1, ())},
                         {S.ISR_ROOTS[0]: (1, ("missing",))}):
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                S.isr_reach(ir, indirect=contract)
        with self.assertRaisesRegex(ValueError, "no defined callbacks"):
            S.isr_reach(ir + "@empty = constant void ()* null\n", indirect={S.ISR_ROOTS[0]: (1, ("empty",))})

    def test_unreachable_indirect_call_is_main_loop_only(self):
        ir = module(extra=function("ui", "call void %unknown()"))
        self.assertEqual(S.isr_reach(ir), set(S.ISR_ROOTS))
        self.assertEqual(S.annotate(ir, {"ui"})[1], {"ui"})

    def test_zero_calls_still_check_an_existing_dispatch_contract(self):
        ir = module(extra=function("callback"))
        with self.assertRaisesRegex(ValueError, "0 indirect ISR call"):
            S.isr_reach(ir, indirect={S.ISR_ROOTS[0]: (1, ("callback",))})
        self.assertEqual(S.isr_reach(ir, indirect={}), set(S.ISR_ROOTS))
        self.assertIn("callback", S.isr_reach(ir, indirect={S.ISR_ROOTS[0]: (0, ("callback",))}))

    def test_roots_missing_disabled_and_malformed_bodies(self):
        ir = function("ui")
        with self.assertRaisesRegex(ValueError, "missing ISR roots"):
            S.isr_reach(ir)
        with self.assertRaisesRegex(ValueError, "missing ISR roots"):
            S.isr_reach(function(S.ISR_ROOTS[0]))
        self.assertEqual(S.isr_reach(ir, roots=()), set())
        self.assertEqual(S.annotate(ir, {"ui"}, roots=())[1], {"ui"})
        with self.assertRaisesRegex(ValueError, "malformed function body"):
            S.isr_reach(module() + "define void @broken() #0 {\n")
        with self.assertRaisesRegex(ValueError, "malformed function body"):
            S.isr_reach(module() + "define void @broken(\n) #0 {\n  ret void\n}\n")

    def test_inline_asm_and_direct_bitcast_call(self):
        ir = module('call void asm sideeffect "icfg = $0", "r,~{memory}"(i32 0)\n'
                    '  call void bitcast (void ()* @callback to void ()*)()', extra=function("callback"))
        self.assertIn("callback", S.isr_reach(ir))
        with self.assertRaisesRegex(ValueError, "unrecognized call form"):
            S.isr_reach(module("call void inttoptr (i32 123 to void ()*)()"))
        with self.assertRaisesRegex(ValueError, "reviewed target/count contract"):
            S.isr_reach(module("call void %asm()"))
        with self.assertRaisesRegex(ValueError, "reviewed target/count contract"):
            S.isr_reach(module("call void bitcast (void (...)* %f to void (void ()*)*)(void ()* @other)",
                              extra=function("other")))

    def test_cli_failure_does_not_write_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            src, dst = Path(tmp) / "in.ll", Path(tmp) / "out.ll"
            src.write_text(module("call void %unknown()"))
            p = subprocess.run([sys.executable, ROOT / "tools/size_fns.py", src, dst], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("reviewed target/count contract", p.stderr)
            self.assertFalse(dst.exists())


class Annotation(unittest.TestCase):
    def test_attributes_idempotence_and_non_candidates(self):
        ir = module(extra=function("ui", attrs="local_unnamed_addr #0") + function("other", attrs="nounwind") +
                    function("existing", attrs="minsize #0"))
        candidates = {"ui", "existing", "absent", *S.ISR_ROOTS}
        out, hit, protected = S.annotate(ir, candidates)
        self.assertEqual(hit, {"ui", "existing"})
        self.assertEqual(protected, set(S.ISR_ROOTS))
        self.assertIn("@ui() local_unnamed_addr minsize #0", out)
        self.assertIn("@other() nounwind", out)
        self.assertEqual(out, S.annotate(out, candidates)[0])
        self.assertIn("attributes #0 = { nounwind optsize }", out)

    def test_group_minsize_not_duplicated_and_isr_minsize_rejected(self):
        ir = module(extra=function("ui", attrs="#1")) + "attributes #1 = { nounwind minsize }\n"
        self.assertEqual(S.annotate(ir, {"ui"})[0], ir)
        for bad in (ir.replace("@fm1_alnk0_irq() #0", "@fm1_alnk0_irq() minsize #0"),
                    ir.replace("@fm1_alnk0_irq() #0", "@fm1_alnk0_irq() #1")):
            with self.assertRaisesRegex(ValueError, "already has minsize"):
                S.annotate(bad, {"ui"})


class ColdBoundaries(unittest.TestCase):
    def test_os_caller_retains_only_eligible_boundary(self):
        ir = module(extra=function("os", "call void @cold()\n  call void @other()") +
                    function("cold", "call void @leaf()") + function("leaf") + function("other"))
        out, hit, protected = S.annotate(ir, {"cold", "leaf"})
        self.assertEqual(hit, {"cold", "leaf"})
        self.assertIn("@cold() minsize noinline #0", out)
        self.assertIn("@leaf() minsize #0", out)
        self.assertNotIn("@leaf() minsize noinline", out)
        self.assertIn("@other() #0", out)
        self.assertEqual(out, S.annotate(out, {"cold", "leaf"})[0])

    def test_existing_group_attributes_and_existing_minsize_caller(self):
        ir = module(extra=function("os", "call void @cold()") + function("cold", attrs="#1") +
                    function("sized", "call void @leaf()", attrs="minsize #0") + function("leaf"))
        ir += "attributes #1 = { nounwind minsize noinline }\n"
        out = S.annotate(ir, {"cold", "leaf"})[0]
        self.assertIn("@cold() #1", out)
        self.assertIn("@leaf() minsize #0", out)
        self.assertNotIn("@leaf() minsize noinline", out)
        self.assertEqual(out, S.annotate(out, {"cold", "leaf"})[0])

    def test_protected_table_and_flash_dependency_not_marked(self):
        ir = module("call void %callback()", extra=
                    "@table = constant void ()* @hot\n" + function("hot", "call void @hot_leaf()") +
                    function("hot_leaf") + function("os", "call void @hot()\n  call void @flash_leaf()") +
                    function("flash", "call void @flash_leaf()", attrs='section ".ram_text" #0') +
                    function("flash_leaf"))
        out, hit, protected = S.annotate(ir, {"hot", "hot_leaf", "flash_leaf"},
                                        indirect={S.ISR_ROOTS[0]: (1, ("table",))})
        self.assertEqual(hit, {"flash_leaf"})
        self.assertIn("hot_leaf", protected)
        self.assertNotIn("noinline", out)
        self.assertIn("@flash_leaf() minsize #0", out)

    def test_alwaysinline_and_direct_existing_noinline_preserved(self):
        ir = module(extra=function("os", "call void @inline()\n  call void @cold()") +
                    function("inline", attrs="alwaysinline #0") + function("cold", attrs="noinline #0"))
        out = S.annotate(ir, {"inline", "cold"})[0]
        self.assertIn("@inline() minsize alwaysinline #0", out)
        self.assertIn("@cold() minsize noinline #0", out)
        self.assertEqual(out, S.annotate(out, {"inline", "cold"})[0])

    def test_quoted_callee_and_noneligible_caller_with_group_minsize(self):
        ir = module(extra=function("os", 'call void @"cold.name"()') + function('"cold.name"') +
                    function("sized", "call void @leaf()", attrs="#1") + function("leaf"))
        ir += "attributes #1 = { minsize nounwind }\n"
        out = S.annotate(ir, {"cold.name", "leaf"})[0]
        self.assertIn('@"cold.name"() minsize noinline #0', out)
        self.assertIn("@leaf() minsize #0", out)

    def test_unknown_flash_dispatch_fails_closed(self):
        ir = module(extra=function("flash", "call void %unknown()", attrs='section ".ram_text" #0'))
        with self.assertRaisesRegex(ValueError, "reviewed target/count contract"):
            S.annotate(ir, {"flash"})


if __name__ == "__main__":
    (ROOT / "build").mkdir(exist_ok=True)
    unittest.main()
