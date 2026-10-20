#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""Build the main-loop code for size (build.py): the functions defined in SIZE_FILES get LLVM's
minsize (about -Oz) while everything else (the sound, render and ISR code, the flash and OTA code,
the main loop) keeps -Os. The JieLi clang 4 has no '#pragma clang attribute' and its minsize
attribute is an error on variables, so build.py compiles felucca.c to LLVM IR without the
optimizer, this script adds 'minsize' to those definitions, and the IR is then compiled at -Os
(without the edit, that round trip is byte-identical to compiling felucca.c directly).
A module compiled as its own translation unit (build.py SEPARATE, #454) is annotated with --module: it holds no
interrupt root, and felucca.c's own run fails if interrupt-reachable code calls a function defined outside it, so
nothing in such a module can be ISR code.
  size_fns.py [--module] IN.ll OUT.ll"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
SRC = _ROOT / "firmware" / "src" if (_ROOT / "firmware" / "src").is_dir() else _ROOT / "src"   # either layout
# the UI, the stores, the editor and the console: main loop only, never called by sound code; and (1.1) every
# other file without DSP: USB, MIDI, the sequencer, the drawing, the LCD, OTA, ... Of those, what an interrupt
# reaches (ISR_ROOTS and everything they call or name, from the IR) keeps -Os (isr_reach)
SIZE_FILES = ["ui.c", "favorites.c", "menu_items.c", "icons.c", "ui_graph.c", "ui_draw.c", "ui_menu.c", "ui_knob.c", "ui_input.c",
              "storage.c", "upreset.c", "project.c", "settings_persist.c",
              "editor.c", "editor_preferences.c", "editor_backup.c", "editor_menu.c", "console.c",
              "usb.c", "midi_uart.c", "midi_control.c", "midi_clock.c", "seq.c", "song_chain.c", "chord.c", "motion.c",
              "panel.c", "lcd.c", "gfx.c", "ota.c", "ota_hw.c", "up_fm6.c", "slice_store.c", "params.c", "editor_fm6.c",
              "ui_layer.c", "ui_name.c", "ui_slice.c", "ui_events.c", "main.c", "libc.c", "storage_hw.c", "engines.c", "fm4_convert.c", "sound.c", "sound_port.c"]
ISR_ROOTS = ("fm1_alnk0_irq", "fm1_timer5_irq")      # hal/fm1_isr.S: the audio ISR, the key / LED scan (+ USB poll)
DEF = re.compile(r"^(?:static|void|int|uint\w*|int\w*|const)\b[^;=(]*?\b([A-Za-z_]\w*)\s*\(", re.M)
IR_NAME = r'(\"(?:\\.|[^\"])*\"|[-\w.$]+)'
IR_DEF = re.compile(r"^(define [^\n]*?@" + IR_NAME + r"\([^\n]*\)(?: unnamed_addr| local_unnamed_addr)?)([^\n]*\{)$", re.M)


def definitions(text):
    """names of the functions text defines (a signature at column 0 whose ')' is followed by '{')"""
    names = []
    text = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)        # comments (none hold code)
    for m in DEF.finditer(text):
        i, depth = m.end() - 1, 0
        while i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
            if depth == 0:
                break
        rest = re.sub(r"^(__attribute__\s*\(\(.*?\)\)\s*)+", "", text[i:i + 200].lstrip())
        if rest.startswith("{"):
            names.append(m.group(1))
    return names


def size_names():
    names = set()
    for f in SIZE_FILES:
        names.update(definitions((SRC / f).read_text()))
    return names


IR_DECL = re.compile(r"^declare [^\n]*?@" + IR_NAME + r"\(", re.M)
IR_BODY = re.compile(r"^define [^\n]*?@" + IR_NAME + r"\([^\n]*\)[^\n]*\{\n(.*?)^\}", re.M | re.S)
IR_REF = re.compile(r"@" + IR_NAME)
IR_GLOBAL = re.compile(r"^@" + IR_NAME + r"\s*=(.*?)(?=^(?:@|define |declare |attributes |!|%|source_filename |target |;)|\Z)",
                       re.M | re.S)

# Reviewed source contract: these callers dispatch only through ENGINES/engine_t.
# The count is the number of indirect call sites in unoptimized JieLi LLVM 4 IR.
# A new/changed indirect caller must fail until its complete possible target set
# is reviewed here. This is an explicit contract, not inferred pointer provenance.
ISR_INDIRECT = {
    "chord_kit": (1, ("ENGINES",)),       # keys
    "kb_engine": (1, ("ENGINES",)),       # keys
    "seq_step": (1, ("ENGINES",)),        # keys
    "track_render": (4, ("ENGINES",)),    # block, done, amp, render
    "voice_start": (1, ("ENGINES",)),     # note_on
}


def references(text):
    return {m[1].strip('"') for m in IR_REF.finditer(text)}


def immutable_global(text):
    # Storage kind precedes the initializer. Names/types/strings can contain
    # these words too (e.g. mutable global void ()* @constant).
    masked = re.sub(r'[@%]' + IR_NAME + r'|"(?:\\.|[^"\\])*"', " ", text)
    kind = re.search(r"\b(global|constant|alias)\b", masked)
    return bool(kind and kind[1] in ("constant", "alias"))


def indirect_calls(body):
    """Count SSA dispatch; reject other unnamed call forms rather than ignoring them."""
    count = 0
    for line in body.splitlines():
        if not re.search(r"\b(?:call|invoke)\b", line) or re.search(r'\basm(?:\s+(?:sideeffect|alignstack|inteldialect))*\s+"', line):
            continue
        # LLVM's actual argument list is the last top-level (...) group. Cast
        # function types have their own groups; named arguments are not callees.
        masked = re.sub(r'"(?:\\.|[^"\\])*"', lambda m: " " * len(m[0]), line)
        depth, start, groups = 0, None, []
        for i, char in enumerate(masked):
            if char == "(":
                if depth == 0:
                    start = i
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and start is not None:
                    groups.append((start, i))
        if depth or not groups:
            raise ValueError(f"unrecognized call form: {line.strip()}")
        callee = line[:groups[-1][0]].rstrip()
        if re.search(r"%" + IR_NAME + r"$", callee):
            count += 1
        elif re.search(r"@" + IR_NAME + r"$", callee):
            continue
        elif len(groups) >= 2 and re.search(r"\bbitcast\s*$", line[:groups[-2][0]]):
            operand = line[groups[-2][0] + 1:groups[-2][1]].rsplit(" to ", 1)[0].rstrip()
            if re.search(r"%" + IR_NAME + r"$", operand):
                count += 1
            elif not re.search(r"@" + IR_NAME + r"$", operand):
                raise ValueError(f"unrecognized call form: {line.strip()}")
        else:
            raise ValueError(f"unrecognized call form: {line.strip()}")
    return count


def isr_reach(ir, roots=ISR_ROOTS, indirect=ISR_INDIRECT):
    """Follow body/global/alias references; unresolved ISR dispatch requires a reviewed contract.

    Every configured root must exist. roots=() explicitly disables ISR analysis
    for a fixture; the production CLI always requires both hardware roots.
    """
    body = {m[1].strip('"'): m[2] for m in IR_BODY.finditer(ir)}
    headers = {m[2].strip('"') for m in IR_DEF.finditer(ir)}
    defined = {m[1].strip('"') for m in re.finditer(r"^define [^\n]*?@" + IR_NAME, ir, re.M)}
    if defined != headers or headers != set(body):
        raise ValueError("malformed function body in unoptimized IR")
    missing = set(roots) - set(body)
    if missing:
        raise ValueError(f"missing ISR roots: {', '.join(sorted(missing))}")
    globals_ = {m[1].strip('"'): m[2] for m in IR_GLOBAL.finditer(ir)}
    declared = {m[1].strip('"') for m in IR_DECL.finditer(ir)}
    edges = {name: references(text) for name, text in {**globals_, **body}.items()}
    seen, todo = set(), list(roots)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        if f in body:
            count = indirect_calls(body[f])
            contract = indirect.get(f)
            if count or contract is not None:
                if contract is None or contract[0] != count:
                    raise ValueError(f"{f}: {count} indirect ISR call(s) need a reviewed target/count contract")
                targets = set(contract[1])
                if not targets or not targets <= edges.keys():
                    raise ValueError(f"{f}: indirect ISR contract has missing or empty targets")
                for target in targets:
                    closure, pending = set(), [target]
                    while pending:
                        g = pending.pop()
                        if g not in closure:
                            closure.add(g)
                            if g in globals_:
                                if not immutable_global(globals_[g]):
                                    raise ValueError(f"{f}: mutable dispatch requires explicit function targets, not {g}")
                                pending += list(edges.get(g, set()) - closure)
                    if not closure & body.keys():
                        raise ValueError(f"{f}: indirect ISR target {target} has no defined callbacks")
                todo += list(targets - seen)
        todo += list(edges.get(f, set()) - seen)
    outside = sorted(n for n in seen & declared if not n.startswith("llvm."))
    if outside:
        raise ValueError(f"ISR-reachable code calls {', '.join(outside)}, defined outside this translation unit "
                         "(a separately compiled module is main-loop only: docs/modules.md)")
    return seen & body.keys()


def annotate(ir, candidates, roots=ISR_ROOTS, indirect=ISR_INDIRECT):
    protected = isr_reach(ir, roots, indirect)
    names, hit = candidates - protected, set()
    groups = dict(re.findall(r"^attributes (#\d+) = (.*)$", ir, re.M))

    def mark(m):
        name = m[2].strip('"')
        attributes = m[3] + " " + " ".join(groups.get(g, "") for g in re.findall(r"#\d+", m[3]))
        already = bool(re.search(r"\bminsize\b", attributes))
        if name in protected and already:
            raise ValueError(f"{name}: ISR-reachable definition already has minsize")
        if name not in names:
            return m[0]
        hit.add(name)
        return m[0] if already else m[1] + " minsize" + m[3]
    return IR_DEF.sub(mark, ir), hit, protected


def main(src, dst, module=False):
    ir = Path(src).read_text()
    candidates = size_names()
    annotated, hit, isr = annotate(ir, candidates, roots=() if module else ISR_ROOTS)
    names = candidates - isr
    Path(dst).write_text(annotated)
    if module:
        print(f"size: {Path(src).stem}: {len(hit)} main-loop functions built for size (own unit, no interrupt roots)")
        return 0
    print(f"size: {len(hit)} main-loop functions built for size ({len(names) - len(hit)} not in this build; "
          f"{len(candidates & isr)} reached from an interrupt kept -Os)")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    module = args[:1] == ["--module"]
    try:
        sys.exit(main(*args[module:module + 2], module=module))
    except (OSError, ValueError) as e:
        sys.exit(f"size: {e}")
