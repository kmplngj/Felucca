#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""Fixture tests of tests/target_budget.py: small hand-written pi32v2 listings, run through its parser
(functions), its estimator (cost) and its checker (main). No toolchain, no build/felucca.dis; run from the
repo root (tests/run_tests.sh runs it before the real target_budget run):
  python3 tests/target_budget_test.py

What the fixtures pin is the CURRENT behaviour, approximations and gaps included: a fixture marked
"APPROXIMATE" or "GAP" asserts what the code does today where a precise (or safer) estimator would say
something else, so a change of the estimator that fixes it fails here and the expectation is updated with it (the real numbers are tests/target_budget.txt).

The listing shape is the one target_budget.py parses (its LABEL / INSN / TARGET patterns), written from those
patterns: a bare "name:" line per function, "  addr:<TAB>xx xx <TAB>text" per instruction, branches as
"goto <disp> <sym: target >", calls as "call <addr> <sym>", divides as "rN = rM / rK". The mnemonics are made
up around that; the real pi32v2 objdump's spelling (unsigned or immediate divides, undecoded words, FPU) has
not been seen here (no toolchain), so the unusual spellings below are stand-ins, not captured output.

How the estimator counts (cost(), all of it static, nothing is executed):
  loop         every backward branch (target >= the function's first address and < the branch's own) closes a
               span target..branch; spans sharing a head collapse to the farthest branch. Forward branches,
               a branch to itself, and branches out of the function are not loops.
  weight       an instruction inside d spans weighs 4 ** (d - 1), d capped at 4; a divide x9 on top; the call
               is counted ("call" in the line) and weighs 1: the callee's own loops are not added.
  APPROXIMATE  a backward branch that is a block-placement jump, not a loop, makes a span too: its code is
               counted as a loop body. A real loop whose trip count is 1 or 1000 weighs the same. Nested
               loops weigh 4 per level whatever their real trip count. A divide is the 'rN = rM / rK' text only.
  GAP          what the parser cannot read is dropped without a trace: a line not matching INSN, text
               starting with '<' (it is how the jump-table data is skipped; an undecoded word printed so goes
               with it). Undecoded text not starting with '<' counts as one ordinary instruction. Neither
               prints a warning or fails, so a function with unreadable code can look smaller (or loop-free)
               and still pass; main() also passes a function that has no budget line, a missing budget file,
               and a missing listing ("skip"), and ignores budget lines for names it does not know."""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failed = 0


def ok(cond, what):
    global failed
    failed += not cond
    print(f"{what:<92} {'ok' if cond else 'FAIL'}")


_argv = sys.argv
sys.argv = ["target_budget.py"]     # the module reads DIS / BUDGET from argv when imported
spec = importlib.util.spec_from_file_location("target_budget", ROOT / "tests" / "target_budget.py")
TB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TB)
sys.argv = _argv

TMP = Path(tempfile.mkdtemp(prefix="target_budget_test_"))

# ---- the fixtures ------------------------------------------------------------------------------
# one function per fixture, instructions 4 bytes apart from 1000; "goto -d" is d bytes back from its own line.
# Between the functions: the header lines of a real listing (neither is a label or an instruction).
HEAD = """felucca.elf:     file format elf32-pi32v2


Disassembly of section .text:

"""


def insn(addr, text, size=4):
    """one listing line: address, the machine bytes (made up), the text"""
    return f"  {addr:x}:\t{' '.join(f'{(addr >> (8 * i)) & 0xFF:02x}' for i in range(size))} \t{text}\n"


def fn(name, base, texts, step=4):
    """label + one line per text from base"""
    return f"{name}:\n" + "".join(insn(base + i * step, t) for i, t in enumerate(texts))


def listing(*fns):
    return HEAD + "\n".join(fns)


# a simple loop: 1004..1014 is the loop (5 of 7), cost 5
SIMPLE = fn("simple_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",                                    # 1004 head
    "r1 = r1 + r3",
    "[r2] = r1",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -16 <simple_render: 1004 >",  # 1014
    "rts"])

# nested: inner 1008..1014 weighs 4, outer 1004..101c 1
NESTED = fn("nested_render", 0x1000, [
    "r0 = 0",
    "r1 = 0",                                       # 1004 outer head
    "r2 = 0",                                       # 1008 inner head
    "r3 = r3 + r2",
    "r2 = r2 + 1",
    "if (r2 != r5) goto -12 <nested_render: 1008 >",  # 1014
    "r1 = r1 + 1",
    "if (r1 != r6) goto -24 <nested_render: 1004 >",  # 101c
    "rts"])

# five deep: the depth stops at MAXD (4), so the inner instructions weigh 64 and not 256
DEEP = fn("deep_render", 0x1000, [
    "r1 = 0",                                       # 1000 .. 1010: five heads
    "r2 = 0",
    "r3 = 0",
    "r4 = 0",
    "r5 = 0",
    "r7 = r7 + r5",                                 # 1014 the body
    "if (r5 != r8) goto -8 <deep_render: 1010 >",     # 1018
    "if (r4 != r8) goto -16 <deep_render: 100c >",    # 101c
    "if (r3 != r8) goto -24 <deep_render: 1008 >",    # 1020
    "if (r2 != r8) goto -32 <deep_render: 1004 >",    # 1024
    "if (r1 != r8) goto -40 <deep_render: 1000 >",    # 1028
    "rts"])

# two backward branches to one head (an early 'continue' and the loop end): one span, the farthest
SHARED = fn("shared_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",                                    # 1004 head
    "if (r1 == 0) goto -4 <shared_render: 1004 >",    # 1008 early back-edge
    "r3 = r3 + r1",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -16 <shared_render: 1004 >",  # 1014
    "rts"])

# APPROXIMATE: not a loop. The cold block sits after the return and jumps back to the rejoin point; the
# estimator sees a backward branch and counts 100c..101c (the rejoin, the return and the cold block) as a loop
ALT = fn("alt_render", 0x1000, [
    "r0 = [r1]",
    "if (r0 == 0) goto 20 <alt_render: 1018 >",       # 1004 forward to the cold block
    "r2 = r2 + r0",
    "r3 = r3 + r2",                                 # 100c rejoin
    "[r4] = r3",
    "rts",                                          # 1014
    "r2 = 0",                                       # 1018 cold block
    "goto -16 <alt_render: 100c >"])                 # 101c

# not loops either: a forward branch, a branch to itself (a spin wait) and a jump out of the function (a
# tail call: its target is below the function's first address)
NOLOOP = fn("noloop_render", 0x1000, [
    "r0 = [r1]",
    "if (r0 == 0) goto 8 <noloop_render: 100c >",     # 1004 forward
    "r0 = r0 + 1",
    "r2 = [r3]",                                    # 100c
    "if (r2 == 0) goto 0 <noloop_render: 1010 >",     # 1010 spin on itself
    "goto -4116 <other_fn: 0 >"])                     # 1014 out of the function (target < 1000)

# two sibling loops: 1004..1010 (4) and 1018..1028 (5), what is between them (1014) weighs 0
SIBLING = fn("sibling_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",                                    # 1004 head A
    "[r2] = r1",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -12 <sibling_render: 1004 >",  # 1010
    "r6 = r6 + 1",
    "r1 = [r3]",                                    # 1018 head B
    "r1 = r1 + r1",
    "[r3] = r1",
    "r3 = r3 + 4",
    "if (r3 != r5) goto -16 <sibling_render: 1018 >",  # 1028
    "rts"])

# a call in a loop is counted (calls 1, weight 1), a call outside is not, and the callee (a second function
# of the list, with a loop of its own) is not added to the caller
CALL = (fn("call_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",                                    # 1004 head
    "call 4352 <helper_fn: 1100 >",
    "[r2] = r0",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -16 <call_render: 1004 >",    # 1014
    "call 4352 <helper_fn: 1100 >",                 # outside the loop
    "rts"]),
        fn("helper_fn", 0x1100, [
    "r3 = 0",
    "r3 = r3 + 1",                                  # 1104 head
    "if (r3 != r4) goto -4 <helper_fn: 1104 >",
    "rts"]))

# a divide in the loop weighs 9, the one after it is not counted at all
DIV = fn("div_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",                                    # 1004 head
    "r1 = r1 / r3",
    "[r2] = r1",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -16 <div_render: 1004 >",     # 1014
    "r5 = r6 / r7",
    "rts"])

# a divide in the inner loop weighs 4 * 9
DIV_NESTED = NESTED.replace("nested_render", "divn_render").replace("r3 = r3 + r2", "r3 = r3 / r2")

# APPROXIMATE: only 'rN = rM / rK' is a divide. Immediate, remainder, float and library divides are
# other instructions (the library one a call): div 0, call 1, the rest weigh 1 each
DIV_FORMS = fn("divforms_render", 0x1000, [
    "r0 = 0",
    "r1 = r2 / 3",                                  # 1004 head
    "r1 = r2 % r3",
    "f1 = f2 / f3",
    "call 4864 <__divsi3: 1300 >",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -20 <divforms_render: 1004 >",  # 1018
    "rts"])

# GAP: text starting with '<' is dropped like the jump-table data around it; a line whose bytes are not
# 'xx ' pairs is dropped; neither is in "insns" or in the loop (the loop of SIMPLE with three lines gone)
UNREAD = (HEAD + "unread_render:\n"
          + insn(0x1000, "r0 = 0")
          + insn(0x1004, "r1 = [r2]")
          + insn(0x1008, "<unknown>")
          + "  100c:\tffff \tr1 = r1 + r3\n"
          + insn(0x1010, "r2 = r2 + 4")
          + insn(0x1014, "if (r2 != r4) goto -16 <unread_render: 1004 >")
          + insn(0x1018, "rts")
          + "\n.L5:\n"                              # a compiler label inside the function: no end
          + insn(0x101c, "< 2 : 0x1004 >")          # jump-table data
          + insn(0x1020, "< 3 : 0x1008 >"))

# GAP: undecoded text not starting with '<' is one more ordinary instruction (weight 1, 4 or 16 in a nest)
BAD_BODY = fn("badbody_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",                                    # 1004 head
    ".word 0xffffffff",
    "(bad)",
    "r2 = r2 + 4",
    "if (r2 != r4) goto -16 <badbody_render: 1004 >",  # 1014
    "rts"])

# GAP: the loop's back-edge is the word nobody decoded: no span, the function reads as loop-free (cost 0)
BAD_EDGE = fn("badedge_render", 0x1000, [
    "r0 = 0",
    "r1 = [r2]",
    "r1 = r1 + r3",
    "[r2] = r1",
    "r2 = r2 + 4",
    "(bad)",                                        # 1014 was the backward branch
    "rts"])

# the same, the back-edge printed in a form TARGET does not know ('jump', not 'goto')
ODD_EDGE = SIMPLE.replace("simple_render", "oddedge_render").replace("goto -16", "jump -16")

# GAP: a label with no instruction (or only '<' data) is a function the listing does not have
EMPTY = "empty_render:\n" + insn(0x1000, "< 1 : 0x1000 >")


def cost_of(text, name):
    p = TMP / f"{name}.dis"
    p.write_text(text)
    fns = TB.functions(str(p))
    return {k: (TB.cost(v) if v else None) for k, v in fns.items()}


def cost(**kw):
    r = dict(insns=0, loop=0, div=0, call=0, cost=0)
    r.update(kw)
    return r


def check_costs():
    TB.FUNCS = ["simple_render"]
    r = cost_of(listing(SIMPLE), "simple")
    ok(r == {"simple_render": cost(insns=7, loop=5, cost=5)}, "simple loop: 5 of 7 instructions, cost 5")

    TB.FUNCS = ["nested_render"]
    r = cost_of(listing(NESTED), "nested")
    ok(r == {"nested_render": cost(insns=9, loop=7, cost=19)}, "nested loops: inner 4 x 4 + outer 3 x 1 = 19")

    TB.FUNCS = ["deep_render"]
    r = cost_of(listing(DEEP), "deep")
    ok(r == {"deep_render": cost(insns=12, loop=11, cost=362)},
       "five deep: the depth stops at MAXD, 1+4+16+5x64+16+4+1 = 362 (not 5 x 256)")

    TB.FUNCS = ["shared_render"]
    r = cost_of(listing(SHARED), "shared")
    ok(r == {"shared_render": cost(insns=7, loop=5, cost=5)}, "two back-edges to one head: one span (the farthest), cost 5")

    TB.FUNCS = ["alt_render"]
    r = cost_of(listing(ALT), "alt")
    ok(r == {"alt_render": cost(insns=8, loop=5, cost=5)},
       "APPROXIMATE: a cold block jumping back is no loop but counts 5 (the rejoin, rts, the block) as one")

    TB.FUNCS = ["noloop_render"]
    r = cost_of(listing(NOLOOP), "noloop")
    ok(r == {"noloop_render": cost(insns=6)},
       "forward branch, branch to itself, jump out of the function: not loops (cost 0)")

    TB.FUNCS = ["sibling_render"]
    r = cost_of(listing(SIBLING), "sibling")
    ok(r == {"sibling_render": cost(insns=12, loop=9, cost=9)}, "two sibling loops: 4 + 5 = 9, not nested (the line between weighs 0)")

    TB.FUNCS = ["call_render", "helper_fn"]
    r = cost_of(listing(*CALL), "call")
    ok(r == {"call_render": cost(insns=8, loop=5, call=1, cost=5), "helper_fn": cost(insns=4, loop=2, cost=2)},
       "loop with a call: 1 call counted there (the one outside is not), the callee's loop (2) is not added")

    TB.FUNCS = ["div_render"]
    r = cost_of(listing(DIV), "div")
    ok(r == {"div_render": cost(insns=8, loop=5, div=1, cost=13)}, "divide in the loop: 4 + 9 = 13; the divide after it counts nothing")

    TB.FUNCS = ["divn_render"]
    r = cost_of(listing(DIV_NESTED), "divn")
    ok(r == {"divn_render": cost(insns=9, loop=7, div=1, cost=51)}, "divide in the inner loop: 3 x 4 + 36 + 3 = 51")

    TB.FUNCS = ["divforms_render"]
    r = cost_of(listing(DIV_FORMS), "divforms")
    ok(r == {"divforms_render": cost(insns=8, loop=6, call=1, cost=6)},
       "APPROXIMATE: 'r2 / 3', '%', float '/', __divsi3: no divide counted (the last one as a call)")

    TB.FUNCS = ["unread_render"]
    r = cost_of(UNREAD, "unread")
    ok(r == {"unread_render": cost(insns=5, loop=3, cost=3)},
       "GAP: '<unknown>', a line with unpaired bytes and the jump-table data vanish: 5 instructions, cost 3 (5 if read)")

    TB.FUNCS = ["badbody_render"]
    r = cost_of(listing(BAD_BODY), "badbody")
    ok(r == {"badbody_render": cost(insns=7, loop=5, cost=5)},
       "GAP: '.word' and '(bad)' count as ordinary instructions, nothing says they were not decoded")

    TB.FUNCS = ["badedge_render"]
    r = cost_of(listing(BAD_EDGE), "badedge")
    ok(r == {"badedge_render": cost(insns=7)}, "GAP: an undecoded back-edge: no loop, cost 0 (SIMPLE's loop is gone)")

    TB.FUNCS = ["oddedge_render"]
    r = cost_of(listing(ODD_EDGE), "oddedge")
    ok(r == {"oddedge_render": cost(insns=7)}, "GAP: a back-edge not spelled 'goto <d> <sym: addr >' is no loop either (cost 0)")

    TB.FUNCS = ["empty_render"]
    r = cost_of(EMPTY, "empty")
    ok(r == {"empty_render": None}, "a label with no readable instruction: parsed, empty (main() then calls it missing)")


def check_parser():
    TB.FUNCS = ["a_render", "b_render"]
    text = listing(
        fn("a_render", 0x1000, ["r0 = 0", "rts"]),
        "other_fn:\n" + insn(0x1008, "r9 = 9"),                # not in FUNCS: ends a_render, kept nowhere
        fn("b_render", 0x1010, ["r0 = 1"]) + "\n.L9:\n" + insn(0x1014, "rts"))   # a '.' label does not end b_render
    p = TMP / "parse.dis"
    p.write_text(text)
    f = TB.functions(str(p))
    ok(sorted(f) == ["a_render", "b_render"] and [a for a, _ in f["a_render"]] == [0x1000, 0x1004]
       and [a for a, _ in f["b_render"]] == [0x1010, 0x1014],
       "parser: a function ends at the next label not starting with '.'; others and the header are left out")
    ok(f["a_render"][0] == (0x1000, "r0 = 0"), "parser: (address, text) with the text stripped")


# ---- main(): the budget check ----------------------------------------------------------------
def run_main(text, budget=None, funcs=(), optional=None, update=False):
    """-> (exit code, output lines); text None: no listing file, budget None: no budget file"""
    TB.FUNCS = list(funcs)
    TB.OPTIONAL = dict(optional or {})
    TB.dis = str(TMP / "run.dis")
    TB.budget = str(TMP / "run.txt")
    for p in (TB.dis, TB.budget):
        if os.path.exists(p):
            os.unlink(p)
    if text is not None:
        Path(TB.dis).write_text(text)
    if budget is not None:
        Path(TB.budget).write_text(budget)
    if update:
        os.environ["BUDGET_UPDATE"] = "1"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = TB.main()
    finally:
        os.environ.pop("BUDGET_UPDATE", None)
    return rc, buf.getvalue().splitlines()


def line_of(out, name):
    return next((ln for ln in out if ln.startswith(f"target: {name}")), "")


def check_main():
    both = listing(SIMPLE, NESTED)
    F = ("simple_render", "nested_render")
    rc, out = run_main(both, "simple_render 5\nnested_render 19\n", F)
    ok(rc == 0 and line_of(out, "simple_render") == "target: simple_render       7 instructions,    5 in loops, 0 divides,  0 calls there: cost     5 (budget 5) ok"
       and line_of(out, "nested_render").endswith("cost    19 (budget 19) ok"), "main: both at their budget: exit 0, one line each")

    # the limit is cost > budget x 1.1: 19 against 18 passes (19.8), against 17 does not (18.7)
    rc, out = run_main(both, "simple_render 5\nnested_render 18\n", F)
    ok(rc == 0 and line_of(out, "nested_render").endswith("(budget 18) ok"), "main: 19 against a budget of 18 (+5 %): ok")
    rc, out = run_main(both, "simple_render 5\nnested_render 17\n", F)
    ok(rc == 1 and line_of(out, "nested_render").endswith("OVER BUDGET (+12 %, limit +10 %)"), "main: 19 against 17 (+12 %): OVER BUDGET, exit 1")
    rc, out = run_main(both, "simple_render 5\nnested_render 21\n", F)
    ok(rc == 0 and line_of(out, "nested_render").endswith("(budget 21) ok"), "main: 19 against 21 (-10 %): ok")
    rc, out = run_main(both, "simple_render 5\nnested_render 22\n", F)
    ok(rc == 0 and line_of(out, "nested_render").endswith("note: -14 % (BUDGET_UPDATE=1 to keep it)"),
       "main: 19 against 22 (-14 %): a note only, exit 0")

    # a function of FUNCS the listing lacks
    rc, out = run_main(listing(SIMPLE), "simple_render 5\nnested_render 19\n", F)
    ok(rc == 1 and "target: FAIL nested_render not found in " + TB.dis + " (renamed? inlined? update FUNCS)" in out
       and line_of(out, "simple_render").endswith("ok"), "main: a function missing from the listing: FAIL, exit 1, the others still checked")
    rc, out = run_main(listing(EMPTY, SIMPLE), "simple_render 5\n", ("empty_render", "simple_render"))
    ok(rc == 1 and any(ln.startswith("target: FAIL empty_render not found") for ln in out), "main: a label with no instruction is missing too")
    rc, out = run_main(listing(SIMPLE), "simple_render 5\n", F, optional={"nested_render": 19})
    ok(rc == 0 and not any("nested_render" in ln for ln in out), "main: an OPTIONAL function absent: skipped, no FAIL")
    rc, out = run_main(both, "simple_render 5\n", F, optional={"nested_render": 19})
    ok(rc == 0 and line_of(out, "nested_render").endswith("(budget 19) ok"), "main: an OPTIONAL function present: checked against its own number")
    rc, out = run_main(both, "simple_render 5\n", F, optional={"nested_render": 10})
    ok(rc == 1 and "OVER BUDGET" in line_of(out, "nested_render"), "main: .. and fails over it")

    # budget entries
    rc, out = run_main(both, "simple_render 5\n", F)
    ok(rc == 0 and line_of(out, "nested_render").endswith("(budget -) no budget (BUDGET_UPDATE=1 adds it)"),
       "GAP: a function without a budget line prints 'no budget' and passes (exit 0)")
    rc, out = run_main(both, "# comment\n\nsimple_render 5\nnested_render 19\nold_render 77\nlonely\n", F)
    ok(rc == 0 and not any("old_render" in ln for ln in out),
       "GAP: a budget line for a function that is not in FUNCS or the listing is ignored; comments and one-word lines too")
    rc, out = run_main(both, None, F)
    ok(rc == 0 and all("no budget" in line_of(out, n) for n in F), "GAP: no budget file at all: every function 'no budget', exit 0")
    rc, out = run_main(None, "simple_render 5\n", F)
    ok(rc == 0 and out == [f"target: skip ({TB.dis} missing: run ./build.sh)"], "a missing listing: 'skip', exit 0 (by design: no toolchain)")
    try:
        run_main(listing(SIMPLE), "simple_render 0\n", ("simple_render",))
        ok(False, "GAP: a budget of 0 crashes the report (ZeroDivisionError)")
    except ZeroDivisionError:
        ok(True, "GAP: a budget of 0 crashes the report (ZeroDivisionError) instead of 'OVER BUDGET'")

    # a function that lost its loops
    rc, out = run_main(listing(BAD_EDGE), "badedge_render 5\n", ("badedge_render",))
    ok(rc == 0 and line_of(out, "badedge_render").endswith("note: -100 % (BUDGET_UPDATE=1 to keep it)"),
       "GAP: unreadable back-edge against a budget of 5: cost 0, '-100 %' note, exit 0 (passes)")
    rc, out = run_main(listing(UNREAD), "unread_render 5\n", ("unread_render",))
    ok(rc == 0 and line_of(out, "unread_render").endswith("note: -40 % (BUDGET_UPDATE=1 to keep it)"),
       "GAP: dropped lines (cost 3 of 5): only a note, exit 0")

    # BUDGET_UPDATE=1 rewrites the budget (a temp file here, never tests/target_budget.txt)
    rc, out = run_main(both, "simple_render 1\n", F, optional={"nested_render": 3}, update=True)
    body = Path(TB.budget).read_text().splitlines()
    ok(rc == 0 and out[0] == f"target: budget {TB.budget} rewritten (2 functions)" and body[3:] == ["simple_render 5"]
       and body[0].startswith("# FELUCCA target cost budget") and "x4 per nesting level, divides x9" in body[1] and "+10 %" in body[1],
       "BUDGET_UPDATE=1: header + 'name cost' per function, OPTIONAL ones left out, no check that run")
    ok(line_of(out, "simple_render").endswith("(budget 1) ok"), "BUDGET_UPDATE=1: the old budget is only printed, not compared")


check_costs()
check_parser()
check_main()
for p in TMP.glob("*"):
    p.unlink()
TMP.rmdir()
print(f"TARGET BUDGET FIXTURES FAILED ({failed})" if failed else "target budget fixture tests passed")
sys.exit(1 if failed else 0)
