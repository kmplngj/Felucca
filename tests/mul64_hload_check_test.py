#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fixtures for tests/mul64_hload_check.py: synthetic JieLi-style listings and IR, no toolchain."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
import mul64_hload_check as M
import size_fns as S


def listing(funcs):
    """funcs: {name: [instruction text]} -> objdump-like text with increasing addresses"""
    out, addr = ["build/felucca.elf:\tfile format ELF32-pi32v2", "", "Disassembly of section .text:"], 0x2000000
    for name, insns in funcs.items():
        out.append(f"{name}:")
        for text in insns:
            out.append(f" {addr:x}:    f8 e1 40 5e       \t{text}")
            addr += 4
    return "\n".join(out) + "\n"


MUL_S, MUL_U, ACC = "r5_r4 = r4 * r14 (s)", "r7_r6 = r1 * r2 (u)", "r15_r14 += r2 * r3 (s)"
LOAD_S, LOAD_U, NOP = "r5 = h[r4+2] (s)", "r0 = h[r7+r3<<1] (u)", "r0 = r0 + 1"


class Parse(unittest.TestCase):
    def kinds(self, *insns):
        return "".join(k for _, k in M.parse(listing({"f": list(insns)}).splitlines())["f"])

    def test_recognised_forms(self):
        self.assertEqual(self.kinds(MUL_S, MUL_U, ACC, "r9_r8 -= r1 * r2 (u)  #", LOAD_S, LOAD_U,
                                    "r1 = h[++r4=r8] (s)", "r1 = h[sp+12] (u)"), "MMMMLLLL")

    def test_not_matched(self):
        self.assertEqual(self.kinds("r1 *= r2", "r1 = r2 * 3", "r1 = r2 * r3", "r5_r4 = r5_r4 / r1 (u)", "h[r4+2] = r5",
                                    "r1 = b[r4+0] (u)", "r1 = [r4++=4]", "r5_r4 = d[sp+8]", "r5_r4 >>= 16"), "." * 9)

    def test_jump_table_label_stays_in_function(self):
        text = listing({"f": [MUL_S]}) + ".L1:\n" + listing({"g": []}).split("\n", 3)[3]
        text = text.replace("g:\n", "")
        self.assertEqual([k for _, k in M.parse(text.splitlines())["f"]], ["M"])


class Window(unittest.TestCase):
    def test_distance_counts_instructions_either_side(self):
        insns = [(0, "L")] + [(0, ".")] * 3 + [(0, "M")] + [(0, ".")] * 5 + [(0, "L")]   # distances 4 and 6
        self.assertEqual(M.near(insns, 3), (0, 0))
        self.assertEqual(M.near(insns, 4), (1, 1))
        self.assertEqual(M.near(insns, 6), (2, 1))

    def test_pairs_and_distinct_multiplies(self):
        insns = [(0, k) for k in "LLMM"]
        self.assertEqual(M.near(insns, 8), (4, 2))

    def test_only_functions_with_a_multiply_are_listed(self):
        funcs = M.parse(listing({"a": [LOAD_S, LOAD_U], "b": [MUL_S, NOP, LOAD_S], "c": [MUL_S] + [NOP] * 20 + [LOAD_S]}).splitlines())
        rows = {r["name"]: r for r in M.analyse(funcs, (4, 16))}
        self.assertEqual(sorted(rows), ["b", "c"])
        self.assertEqual((rows["b"]["near_mul"]["4"], rows["c"]["near_mul"]["4"], rows["c"]["near_mul"]["16"]), (1, 0, 0))


def ir(isr="", scan="", c1="", extra=""):
    def fn(name, body="ret void"):
        return f"define void @{name}() #0 {{\n  {body}\n}}\n"
    return (fn("fm1_alnk0_irq", isr) + fn("fm1_timer5_irq", scan) + (fn("c1_parts", c1) if c1 is not None else "") + extra +
            "attributes #0 = { nounwind }\n")


class Reach(unittest.TestCase):
    def test_tags_per_root(self):
        text = ir("call void @a()", "call void @b()", "call void @c()", "".join(
            f"define void @{n}() #0 {{\n  ret void\n}}\n" for n in "abcd"))
        sets = M.reach(text)
        self.assertEqual([M.tag(n, sets) for n in "abcd"], ["A", "T", "C", "-"])

    def test_cpu1_root_may_be_absent(self):
        self.assertEqual(M.reach(ir(c1=None))["C"], set())


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = M.main(list(args))
        return rc, out.getvalue()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp))
        (self.tmp / "felucca.ll").write_text(ir("call void @hot()", extra="define void @hot() #0 {\n  ret void\n}\n"
                                                "define void @cold() #0 {\n  ret void\n}\n"))

    def dis(self, hot_gap):
        p = self.tmp / "felucca.dis"
        p.write_text(listing({"fm1_alnk0_irq": [NOP], "fm1_timer5_irq": [NOP],
                              "hot": [MUL_S] + [NOP] * hot_gap + [LOAD_S], "cold": [MUL_S, LOAD_S]}))
        return str(p)

    def test_table_json_and_exit_zero(self):
        rc, out = self.run_cli(self.dis(2), "--json", str(self.tmp / "o.json"))
        self.assertEqual(rc, 0)
        data = json.loads((self.tmp / "o.json").read_text())
        rows = {r["name"]: r for r in data["functions"]}
        self.assertEqual((rows["hot"]["tags"], rows["cold"]["tags"]), ("A", "-"))
        self.assertEqual(data["totals"]["isr_or_cpu1"]["near_mul"]["8"], 1)
        self.assertEqual(data["totals"]["main_only"]["near_mul"]["8"], 1)
        self.assertLess(out.index("hot "), out.index("cold "))           # reachable first

    def test_fail_on_new_is_relative_to_baseline_and_ignores_main_only(self):
        base = self.tmp / "base.json"
        self.assertEqual(self.run_cli(self.dis(20), "--json", str(base))[0], 0)       # hot: no pair within 8
        self.assertEqual(self.run_cli(self.dis(20), "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))[0], 0)
        rc, out = self.run_cli(self.dis(2), "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))
        self.assertEqual(rc, 1)
        self.assertIn("NEW: hot", out)
        self.assertNotIn("NEW: cold", out)

    def test_missing_input_and_baseline_window(self):
        self.assertEqual(self.run_cli(str(self.tmp / "none.dis"))[0], 2)
        base = self.tmp / "base.json"
        self.run_cli(self.dis(2), "--json", str(base))
        self.assertEqual(self.run_cli(self.dis(2), "--window", "5", "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))[0], 2)

    def test_fail_on_new_without_reachability_data_exits_2(self):
        base = self.tmp / "base.json"
        self.assertEqual(self.run_cli(self.dis(20), "--json", str(base))[0], 0)
        (self.tmp / "felucca.ll").unlink()
        rc, out = self.run_cli(self.dis(2), "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))
        self.assertEqual(rc, 2)
        self.assertNotIn("NEW:", out)
        # IR present but without the ISR roots is equally unusable
        (self.tmp / "felucca.ll").write_text("define void @hot() #0 {\n  ret void\n}\nattributes #0 = { nounwind }\n")
        self.assertEqual(self.run_cli(self.dis(2), "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))[0], 2)

    def test_fail_on_new_with_ir_exit_codes(self):
        base = self.tmp / "base.json"
        self.run_cli(self.dis(20), "--json", str(base))
        self.assertEqual(self.run_cli(self.dis(20), "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))[0], 0)
        self.assertEqual(self.run_cli(self.dis(2), "--json", str(self.tmp / "o.json"), "--fail-on-new", str(base))[0], 1)

    def test_missing_ir_reports_unknown_reachability(self):
        (self.tmp / "felucca.ll").unlink()
        rc, out = self.run_cli(self.dis(2), "--json", str(self.tmp / "o.json"))
        self.assertEqual(rc, 0)
        self.assertIn("reachability unknown", out)

    def test_unrecognized_or_empty_listing_is_not_a_clean_inventory(self):
        path = self.tmp / "empty.dis"
        for text in ("", "build/felucca.elf: file format ELF32-pi32v2\n", "hot:\n", "hot:\n unrecognized assembly\n"):
            with self.subTest(text=text):
                path.write_text(text)
                output = self.tmp / "o.json"
                self.assertEqual(self.run_cli(str(path), "--json", str(output))[0], 2)
                self.assertFalse(output.exists())

    def test_gate_requires_both_isr_roots_in_listing_and_ir(self):
        base = self.tmp / "base.json"
        self.assertEqual(self.run_cli(self.dis(2), "--json", str(base))[0], 0)
        for root in ("fm1_alnk0_irq", "fm1_timer5_irq"):
            with self.subTest(root=root):
                (self.tmp / "felucca.ll").write_text(ir())
                dis = Path(self.dis(2))
                dis.write_text(dis.read_text().replace(root + ":", "missing_" + root + ":"))
                self.assertEqual(self.run_cli(str(dis), "--json", str(self.tmp / "o.json"),
                                              "--fail-on-new", str(base))[0], 2)
                dis = self.dis(2)
                (self.tmp / "felucca.ll").write_text(ir().replace("@" + root + "()", "@missing_" + root + "()"))
                self.assertEqual(self.run_cli(dis, "--json", str(self.tmp / "o.json"),
                                              "--fail-on-new", str(base))[0], 2)

    def test_invalid_baseline_exits_2_without_overwriting_it(self):
        base = self.tmp / "base.json"
        good = {"schema": 1, "windows": [8], "functions": []}
        invalid = [None, [], {}, dict(good, windows=None), dict(good, functions=None),
                   dict(good, functions=[None]), dict(good, functions=[{"name": "hot", "near_mul": {"8": -1}}]),
                   dict(good, functions=[{"name": "hot", "near_mul": {"8": True}}]),
                   dict(good, functions=[{"name": "hot", "near_mul": {"8": 1}}] * 2)]
        for value in invalid:
            with self.subTest(baseline=value):
                text = json.dumps(value)
                base.write_text(text)
                self.assertEqual(self.run_cli(self.dis(2), "--json", str(base), "--fail-on-new", str(base))[0], 2)
                self.assertEqual(base.read_text(), text)

    def test_valid_listing_with_no_multiply_can_pass_the_gate(self):
        base = self.tmp / "base.json"
        self.run_cli(self.dis(2), "--json", str(base))
        path = self.tmp / "felucca.dis"
        path.write_text(listing({"fm1_alnk0_irq": [NOP], "fm1_timer5_irq": [LOAD_S]}))
        self.assertEqual(self.run_cli(str(path), "--json", str(self.tmp / "o.json"),
                                      "--fail-on-new", str(base))[0], 0)


if __name__ == "__main__":
    unittest.main()
