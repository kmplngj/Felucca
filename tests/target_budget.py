#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""Target-side cost estimate of the hot DSP code, from the pi32v2 objdump listing tools/build.py writes
(build/felucca.dis). For each engine's render function and the audio ISR: the instructions
inside loops (every address range closed by a backward branch: the per-sample loops and what they
contain), and the hardware divides and calls in them. cost = the loop instructions, each weighted 4 per
level of nesting (an inner loop runs several times per sample) and 1 + 8 for a divide (many cycles). A static count, not a cycle count: it changes only when the compiled code changes,
so it is exact run to run, and it catches a render loop that grew (more work per sample, a new divide,
something not inlined any more). Compared with tests/target_budget.txt at +10 %. The host
CPU check (regress.c) is the primary one; this one sees the target compiler's code.
  tests/target_budget.py [DIS [BUDGET]]      BUDGET_UPDATE=1 rewrites BUDGET"""
import os
import json
import hashlib
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_coverage import Producer
coverage = Producer()

FUNCS = ["adp_render", "adp_block", "adp_post", "analog_render", "analog_render_1", "digital_render", "digital_render_legacy", "digital_render_custom", "phase_render", "phase_render_f", "lofi_render", "sample_render", "formant_render",
         "trio_render", "trio_pass", "wheel_render", "wheel_block",
         "grain_render", "grain_block", "phys_render", "drum_render", "noise_render", "fm6_render", "fm6_op_run", "fm6_op_fb", "px_modal_block", "px_modal_run", "px_memb_block",
         "px_string_excite", "px_string_run", "px_symp_run",
         "dv_metal_run", "dv_kick_run", "dv_snare_run", "dv_clap_run", "dv_hat_run", "dv_tom_run",   # drum_voice.c
         "dv_rim_run", "dv_bell_run", "dv_cym_run", "dv_out", "dv_metal_mix",
         "slicer_track", "macro_render", "mac_waveline", "mac_fold", "mac_fbfm",
         # Clang inlines the other full-bank methods into these dispatchers and
         # macro_render. Check their actual target boundaries, including reset.
         "macro_block", "braids_AnalogOscillator_Render",
         "braids_DigitalOscillator_ComputeDelay", "braids_DigitalOscillator_ComputePhaseIncrement",
         "braids_DigitalOscillator_InterpolateFormantParameter", "braids_DigitalOscillator_Render",
         "braids_DigitalOscillator_RenderDigitalFilter", "braids_DigitalOscillator_dispatch",
         "braids_MacroOscillator_RenderDigital", "braids_MacroOscillator_RenderDualSync",
         "braids_MacroOscillator_RenderSub", "braids_MacroOscillator_RenderTriple", "braids_Svf_Process",

         "slice_render", "slc_rev",                          # SLICE (eng_slice.c): the render, the reverse windows
         "fm1_alnk0_irq", "fm1_timer5_irq",               # the audio ISR; TIMER5: the key / LED scan (hal/fm1_input.h)
         "usb_poll", "fm1_input_tick", "fm1__frame", "fm1__keys",  # shared rescue calls can outline TIMER5 work
         "uac_service", "sie_rd", "sie_wr",                 # outlined hot USB callees; caller scores exclude their bodies
         "mix_part",                                        # a part's block (fx.c), on either core since the second
         "mix_spread", "send_begin", "send_add",             # send-ramp helpers: count their loops separately from callers
         "c1_params",                                       # bounded canonical snapshot/restore around a worker job
         "uac_tap48",                                       # the USB audio input at 48 kHz: the 44.1 -> 48 resampler (usb.c)
         "click_render",                                    # the metronome's click (click.c), while it sounds
         "mod_begin", "mod_voice", "mod_end",                 # the modulation matrix (mod.c), called when active
         "perf_begin", "perf_mute", "perf_pre", "perf_block", "perf_master",   # the FX layer (perform.c), when busy
         "perf_flanger", "perf_phaser",                     # .. FLANGER, PHASER (1.2), while held or fading
         "perf_throw",                                      # .. REV / ECHO THROW (1.5.1): per part, while held or gliding
         "rev_room", "rev_spring", "rev_hall", "rev_side_mix",   # the reverb bus (fx.c): REVERB TYPE ROOM / SPRING / HALL (and its stereo)
         "zeros32", "hall_rest",                           # out-of-line silent-bus checks, not counted in callers
         "spring_rest", "spring_live",                     # SPRING gate and line/allpass liveness scan (#39)
         "track_insert", "ins_drive", "ins_swept"]          # the per-track INSERT (fx.c, 1.5), while a TYPE plays
# The artifact's hashed sidecar owns sparse engine coverage. A listing without a sidecar
# retains the historical full checks; mutable build/gen outputs never select its functions.
# built only with FELUCCA_FM4=1 (DIGITAL, src/eng_digital.c; not in the default build, so not in BUDGET): absent,
# they are skipped; present, checked against these (their budget lines until the engine was retired in 1.0)
OPTIONAL = {"adp_render": 2577, "adp_block": 102, "adp_post": 309, "digital_render": 12, "digital_render_legacy": 333, "digital_render_custom": 558,
            "uac_tap48": 504,           # (absent from a FELUCCA_UAC_48K=0 or FELUCCA_UAC=0 build)
            "mix_part": 3549,           # CPU2 build: cold epilogue layout after word memset; see docs/performance.md
            "c1_params": 83,           # 15 temporary values per handed part; absent with FELUCCA_CPU2=0
            # New outlined TIMER5 coverage; maxima of matched default/CPU2-off
            # target listings. Existing caller/engine budgets stay unchanged.
            "usb_poll": 23757, "fm1_input_tick": 536,  # 1.8 analog scan, default/CPU2-off measured; see performance guide
            "fm1__frame": 134, "fm1__keys": 204,
            # Separate hot USB bodies, absent if disabled/inlined; source-matched
            # standard/CPU2-off maxima, not whole-service or cycle bounds.
            "uac_service": 13, "sie_rd": 5, "sie_wr": 5}
# a FELUCCA_CPU2=0 build (no mix_part: inlined into the audio ISR, as 1.6) has the one-core ISR, checked against this
ONE_CORE = {"fm1_alnk0_irq": 37502}
TOL = 0.10                      # exact (no noise): small edits pass, a grown render loop does not
DIV_W = 8                       # a divide weighs 1 + 8 instructions
NEST = 4                        # an instruction in a loop inside a loop weighs 4, two deep 16, ...
MAXD = 4

dis = sys.argv[1] if len(sys.argv) > 1 else "build/felucca.dis"
budget = sys.argv[2] if len(sys.argv) > 2 else "tests/target_budget.txt"
LABEL = re.compile(r"^([A-Za-z_][A-Za-z_0-9.]*):$")
INSN = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$")
TARGET = re.compile(r"goto -?\d+ <[^>]*: ([0-9a-f]+) >")
ADDRESS = re.compile(r"^\s*[0-9a-f]+:")
UNDECODED = re.compile(r"^(?:\.\w+|\(bad\)|unknown\b|unknown_instruction\b)", re.I)


def functions(path):
    """{name: [(addr, text)]}: a function runs to the next label not starting with '.' (the compiler's
    jump-table labels are inside functions); jump-table data ('< n : 0x.. >') is left out"""
    out, cur, name = {}, None, None
    with open(path) as f:
        for no, line in enumerate(f, 1):
            m = LABEL.match(line.strip())
            if m:
                name = m.group(1)
                if not name.startswith("."):
                    cur = out.setdefault(name, []) if name in FUNCS else None
                continue
            m = INSN.match(line)
            if cur is None:
                continue
            if not m:
                if ADDRESS.match(line):
                    raise ValueError(f"{path}:{no}: {name}: unparsed instruction: {line.strip()}")
                continue
            text = m.group(3).strip()
            if text.startswith("<"):               # objdump jump-table data
                continue
            if not text or UNDECODED.match(text):
                raise ValueError(f"{path}:{no}: {name}: undecoded instruction: {text or '(empty)'}")
            cur.append((int(m.group(1), 16), text))
    return out


def spans(heads):
    """the loops of {head: end}: spans that overlap without one holding the other are one loop entered at two
    heads (the compiler's layout: a rarely taken path branching back to a little before the loop's head), joined
    into one; only a span inside another is a loop nested in it"""
    out = []
    for h, e in sorted(heads.items()):
        i = 0
        while i < len(out):
            h0, e0 = out[i]
            if h0 < h <= e0 < e or h < h0 <= e < e0:
                del out[i]
                h, e = min(h, h0), max(e, e0)
                i = 0
            else:
                i += 1
        out.append((h, e))
    return out


def cost(insns):
    """loops: overlapping loop heads are joined; an instruction inside d
    spans weighs NEST ** (d - 1) (an inner loop runs several times per pass of the outer one)"""
    lo = insns[0][0]
    heads = {}
    for a, t in insns:
        m = TARGET.search(t)
        if m and lo <= int(m.group(1), 16) < a:
            h = int(m.group(1), 16)
            heads[h] = max(heads.get(h, a), a)
    loops = spans(heads)
    n = divs = calls = 0
    w = 0
    for a, t in insns:
        d = min(sum(1 for h, e in loops if h <= a <= e), MAXD)
        if not d:
            continue
        k = NEST ** (d - 1)
        n += 1
        if re.search(r"= r\d+ / r\d+", t):
            divs += 1
            k *= 1 + DIV_W
        calls += t.startswith("call")
        w += k
    return {"insns": len(insns), "loop": n, "div": divs, "call": calls, "cost": w}


def artifact_functions(path):
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".profile.json")
    if not sidecar.exists():
        return FUNCS, set()
    try:
        metadata = json.loads(sidecar.read_text())
        profile = metadata["resolved_profile"]
        excluded = profile["excluded_engine_budget_functions"]
        if (metadata["schema_version"] != 1 or profile["schema_version"] != 1
                or metadata["dis_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()
                or not isinstance(excluded, list) or any(not isinstance(n, str) for n in excluded)
                or len(excluded) != len(set(excluded)) or set(excluded) - set(FUNCS)):
            raise ValueError("invalid or stale disassembly profile sidecar")
        return [name for name in FUNCS if name not in excluded], set(excluded)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid disassembly profile sidecar: {sidecar}") from error


def main():
    if not os.path.exists(dis):
        print(f"target: skip ({dis} missing: run ./build.sh)")
        coverage.outcome('target-budget', 'skipped', 'disassembly-missing')
        return 0
    try:
        active, excluded = artifact_functions(dis)
        fns = functions(dis)
        if excluded & fns.keys():
            raise ValueError("disassembly contains engines its profile excludes: " + ", ".join(sorted(excluded & fns.keys())))
    except (OSError, ValueError) as e:
        print(f"target: FAIL {e}")
        return 1
    res = {n: cost(fns[n]) for n in active if fns.get(n)}
    missing = [n for n in active if n not in res and n not in OPTIONAL]
    base = {}
    if os.path.exists(budget):
        with open(budget) as f:
            for no, line in enumerate(f, 1):
                p = line.split()
                if len(p) >= 2 and not line.startswith("#"):
                    try:
                        value = int(p[1])
                        if value < 0:
                            raise ValueError
                    except ValueError:
                        print(f"target: FAIL {budget}:{no}: invalid budget for {p[0]}: expected a nonnegative integer")
                        return 1
                    base[p[0]] = value
    if os.environ.get("BUDGET_UPDATE"):
        with open(budget, "w") as f:
            f.write("# FELUCCA target cost budget (tests/target_budget.py): instructions in the loops of each\n"
                    f"# function in build/felucca.dis, x{NEST} per nesting level, divides x{1 + DIV_W}. The check allows "
                    f"+{TOL * 100:.0f} %.\n# Rewritten by BUDGET_UPDATE=1.\n")
            for n in FUNCS:
                # Sparse artifacts cannot measure excluded engines; retain their shared baselines.
                if n in excluded and n in base:
                    f.write(f"{n} {base[n]}\n")
                elif n in res and n not in OPTIONAL:
                    f.write(f"{n} {res[n]['cost']}\n")
        print(f"target: budget {budget} rewritten ({len(res)} functions)")
    fail = 0
    for n in missing:
        print(f"target: FAIL {n} not found in {dis} (renamed? inlined? update FUNCS)")
        fail += 1
    for n, r in res.items():
        b = base.get(n, OPTIONAL.get(n))
        if "mix_part" not in res and n in ONE_CORE:
            b = ONE_CORE[n]
        state = "no budget (BUDGET_UPDATE=1 adds it)" if b is None else "ok"
        if b is not None and not os.environ.get("BUDGET_UPDATE"):
            if b == 0:
                if r["cost"] > 0:
                    state = f"OVER BUDGET (cost {r['cost']} exceeds zero baseline)"
                    fail += 1
            elif r["cost"] > b * (1 + TOL):
                state = f"OVER BUDGET (+{(r['cost'] / b - 1) * 100:.0f} %, limit +{TOL * 100:.0f} %)"
                fail += 1
            elif r["cost"] < b * (1 - TOL):
                state = f"note: {(r['cost'] / b - 1) * 100:.0f} % (BUDGET_UPDATE=1 to keep it)"
        print(f"target: {n:15s} {r['insns']:5d} instructions, {r['loop']:4d} in loops, {r['div']} divides, "
              f"{r['call']:2d} calls there: cost {r['cost']:5d} (budget {b if b is not None else '-'}) {state}")
    unbudgeted = [n for n in res if n not in base and n not in OPTIONAL and not (n in ONE_CORE and 'mix_part' not in res)]
    coverage.outcome('target-budget', 'failed' if fail or unbudgeted else 'passed',
                     checked=len(res), excluded=sorted(excluded), missing_functions=missing,
                     missing_budgets=unbudgeted, disassembly_sha256=hashlib.sha256(Path(dis).read_bytes()).hexdigest())
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
