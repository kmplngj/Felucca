<!-- SPDX-License-Identifier: GPL-3.0-only -->
# 64-bit multiplies next to 16-bit loads: target inventory (issue #425, phase 1)

**Scope.** A static inventory of the compiled pi32v2 code. It follows
[felucca-bsp `docs/CPU.md` @ f20c2c3](https://github.com/hugelton/felucca-bsp/blob/f20c2c383b1fa51d8592b4eaa6a20f23c05d56d8/docs/CPU.md)
(MPL-2.0; its idea is used here, none of its text or code), which reports that inlined
32x32->64 multiplies among 16-bit loads now and then leave a register one bit off on the
AC79/pi32v2. **No fault has been reproduced on Felucca, no FM-1 test was performed, and this
phase changes no firmware, flag, golden or budget.** A function listed here is a place to look,
not a defect. Mitigation, its cost and the device soak are later phases of #425.

## Reproduce

```sh
./build.sh                                        # writes build/felucca.dis and build/felucca.ll
python3 tests/mul64_hload_check.py                # table + build/mul64_hload.json (N=8; JSON holds N=4/8/16)
python3 tests/mul64_hload_check.py --window 4 --top 0 --json build/mul64-n4.json
python3 tests/mul64_hload_check_test.py           # the checker's own fixtures (in tests/run_tests.sh)
```

`tests/mul64_hload_check.py` reads `build/felucca.dis` (the objdump `tools/build.py` writes) and
the unoptimized IR `build/felucca.ll` of the same build. Per function it counts 64-bit multiplies,
16-bit loads, and the multiplies that have a 16-bit load within N instructions (`near_mul`) and
the (multiply, load) pairs within N (`near_pairs`). The window is N instructions in address order
inside one function; it does not follow branches, so a pair in different loop arms still counts
and a pair across a taken branch is measured by layout, not by execution.

Reachability reuses `tools/size_fns.py` `isr_reach` unchanged (its roots and reviewed indirect
`ENGINES` dispatch contract) on the IR: **A** = `fm1_alnk0_irq` (audio), **T** = `fm1_timer5_irq`
(scan), **C** = `c1_parts`, the function `C1_RUN` hands to core 1 (`fx.c`; absent with
`FELUCCA_CPU2=0`), **-** = none of them (main loop only, or not in the IR). Reachability is by
name in the unoptimized IR; code the optimizer inlined is counted in the caller of the final
listing. Because every engine render callback is reached through the `ENGINES` table, "reachable"
means *may run in the audio ISR*, not *runs for the current preset*.

Optional baseline gate for future CI, **not wired into `tests/run_tests.sh`**:

```sh
cp build/mul64_hload.json tests/mul64_hload_baseline.json     # once, reviewed
python3 tests/mul64_hload_check.py --fail-on-new tests/mul64_hload_baseline.json   # exit 1: more near multiplies
```

It exits 1 only when an A/T/C-reachable function has more `near_mul` (at `--window`, default 8)
than the baseline records (missing = 0), and 2 for unusable input.

## Instruction syntax found

From the real listing (`build/felucca.dis`, JieLi objdump for ELF32-pi32v2):

| Kind | Text | Example from the build |
| --- | --- | --- |
| 32x32->64 multiply | `rX_rY = rA * rB (s)` / `(u)` | `f8 e1 40 5e  r5_r4 = r4 * r14 (s)` (`fm6_op_run`) |
| multiply-accumulate | `rX_rY += rA * rB (s)` / `(u)` | `fc e1 20 f3  r15_r14 += r2 * r3 (s)` (`uac_tap48`) |
| 16-bit load | `rD = h[...] (s)` / `(u)`, modes `[r+imm]`, `[r+r<<1]`, `[++r=r]`, `[r++=imm]`, `[sp+imm]` | `54 ed 42 40  r4 = h[r4+2] (s)` |

No `-=` form occurs (the checker accepts it). 32-bit multiplies (`rD *= rS`, `rD = rA * rB`,
`rD = rA * imm`) are a different instruction and not counted; stores `h[...] = rS` are not loads.
Whole build: 234 64-bit multiplies (204 plain, 30 accumulating; 142 `(s)`, 92 `(u)`) and no
call to a libgcc-style multiply helper.

Excerpt of the pattern closest to the donor's report (`uac_tap48`, the 44.1 -> 48 kHz USB audio
tap, a FIR whose 16-bit coefficient/history loads sit between accumulating multiplies):

```
200a584: r2 = h[r0+128] (s)
200a588: r0 = h[r0+0] (s)
200a58c: r15_r14 += r2 * r3 (s)
200a590: r13 = r13 + 1
200a594: r9_r8 += r0 * r3 (s)
200a598: if (r13 != 24) goto -32 <uac_tap48+0xD4 : 200a57c >
```

## Provenance

| | |
| --- | --- |
| Source revision | `e20985aa7baae96313190526deb5a72c02cf6659` (`origin/main`, merge of #448) plus this change's checker, test and documents (no firmware source differs; build identity read `-dirty`); Engines pin `9630426f5c4a34a209ca851356fbe8ba3c4c6d19` |
| Compiler | JieLi `clang version 4.0.1`, `tools/build.py` `CFLAGS = -Os -ffunction-sections -fno-builtin -Wall -Wno-unused-function`, selective `minsize` pass on (`size: 923 main-loop functions ... 123 reached from an interrupt kept -Os`) |
| Variants | default (`FELUCCA_CPU2=1`, profile FM4=0, SLICE=1, M8Stealth), listing sha256 `3d0caa3ffd3f...`; and `FELUCCA_CPU2=0` |
| Host | Linux x86_64 container; AC79 SDK `AC79NN_SDK_V1.2.1_2023-12-13` files for packaging only |
| Evidence level | target disassembly and IR text. No execution, timing or hardware |

Both variants give identical counts; with `FELUCCA_CPU2=0` the `C` tag disappears and the
function sizes shift by a few instructions (for example `formant_render` 619 -> 614).

## Totals

| N | functions with a near pair | multiplies near a 16-bit load | (multiply, load) pairs |
| --- | --- | --- | --- |
| 4 | 2 | 6 | 10 |
| 8 | 7 | 15 | 27 |
| 16 | 7 | 23 | 51 |

21 functions contain a 64-bit multiply: 234 multiplies and 55 16-bit loads in those functions
(the whole image has about 2,300 16-bit loads). **All 21 are reachable from the audio ISR; 19
are also reachable by the CPU1 job (all but `uac_tap48` and `midi_clock_pulse`); none is
reachable only from the main loop.** No function from the pinned `firmware/engines/` sources (`dsp.c`,
ANALOG, LOFI, TRIO, WHEEL, NOISE) and none in `fx.c` or `audio.c` contains a 64-bit multiply in
this build, although the issue's source-level survey lists `fx.c` accumulators: the compiler
emitted them as 32-bit operations or shifts. Source-level patterns are not a substitute for this
listing, and the result will change with any compiler or code change.

## Function table (N = 4 / 8 / 16 as `near_mul/near_pairs`)

| Function | Source | Reach | Insns | mul64 | h-load | N=4 | N=8 | N=16 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fm6_op_run` | `fm6_core.c` | A C | 104 | 4 | 8 | 0/0 | 4/8 | 4/11 |
| `uac_tap48` | `usb.c` | A | 136 | 4 | 4 | 4/8 | 4/8 | 4/13 |
| `px_symp_run` | `phys_symp.c` | A C | 196 | 8 | 3 | 2/2 | 3/6 | 4/11 |
| `formant_render` | `eng_formant.c` | A C | 619 | 23 | 15 | 0/0 | 1/1 | 3/4 |
| `fm6_render` | `eng_fm6.c` | A C | 509 | 12 | 2 | 0/0 | 1/1 | 2/2 |
| `fres_coef` | `eng_formant.c` | A C | 60 | 7 | 2 | 0/0 | 1/1 | 5/8 |
| `fm6_op_fb` | `fm6_core.c` | A C | 48 | 1 | 2 | 0/0 | 1/2 | 1/2 |
| `px_string_block` | `phys_dsp.c` | A C | 394 | 42 | 0 | 0/0 | 0/0 | 0/0 |
| `px_string_run` | `phys_dsp.c` | A C | 326 | 20 | 0 | 0/0 | 0/0 | 0/0 |
| `px_modal_exciter` | `phys_dsp.c` | A C | 128 | 16 | 0 | 0/0 | 0/0 | 0/0 |
| `px_memb_block` | `phys_dsp.c` | A C | 220 | 15 | 0 | 0/0 | 0/0 | 0/0 |
| `px_string_excite` | `phys_dsp.c` | A C | 194 | 14 | 0 | 0/0 | 0/0 | 0/0 |
| `px_symp_block` | `phys_symp.c` | A C | 132 | 13 | 0 | 0/0 | 0/0 | 0/0 |
| `px_modal_block` | `phys_dsp.c` | A C | 218 | 11 | 0 | 0/0 | 0/0 | 0/0 |
| `px_modal_run` | `phys_dsp.c` | A C | 218 | 9 | 0 | 0/0 | 0/0 | 0/0 |
| `px_modal_q` | `phys_dsp.c` | A C | 31 | 8 | 0 | 0/0 | 0/0 | 0/0 |
| `px_exp2` | `phys_dsp.c` | A C | 80 | 7 | 0 | 0/0 | 0/0 | 0/0 |
| `px_svf_coef` | `phys_dsp.c` | A C | 57 | 7 | 0 | 0/0 | 0/0 | 0/0 |
| `px_sin` | `phys_dsp.c` | A C | 32 | 6 | 0 | 0/0 | 0/0 | 0/0 |
| `midi_clock_pulse` | `midi_clock.c` | A | 174 | 5 | 7 | 0/0 | 0/0 | 0/0 |
| `phys_render` | `eng_phys.c` | A C | 267 | 2 | 12 | 0/0 | 0/0 | 0/0 |

(`T` never appears: the TIMER5 scan reaches no 64-bit multiply.)

## First-pass classification

From the listing context and the callers; loop membership was read from the instructions, not
measured. "Hot" means per-sample or per-operator work inside the audio render; "setup" means
per note or block.

| Class | Functions | Why |
| --- | --- | --- |
| Hot ISR path, near pair at N=4..8 | `fm6_op_run`, `fm6_op_fb` (FM6 operators, `noinline`, per operator per sample), `px_symp_run` (PHYS sympathetic strings, `[r+r<<1]` table loads feeding 3 chained `+=` multiplies), `uac_tap48` (USB audio at 48 kHz: loads between accumulating multiplies in a 24-tap loop, the closest match to the donor report; runs only with UAC input at 48 kHz) | Same shape as the donor's pattern in code that runs every sample |
| ISR-reachable setup, near pair at N=8..16 | `formant_render` (a table load, then `r13_r12 = r8 * r0 (u)` after `fmt_ratio`), `fres_coef` (SINE table read after two `(s)` multiplies, per resonator coefficient), `fm6_render` (`h[r1+210]` next to a coefficient multiply) | Per note or control block, not per sample; still audio-ISR code |
| ISR-reachable, multiplies but no 16-bit load within 16 | `px_string_*`, `px_modal_*`, `px_memb_block`, `px_symp_block`, `px_exp2`, `px_sin`, `px_svf_coef`, `phys_render`, `midi_clock_pulse` | 175 of the 234 multiplies; a different compile of the same source could change this |
| Main loop only | none | No 64-bit multiply is confined to the main loop in this build |

Not in the table: ANALOG, LOFI, TRIO, WHEEL, NOISE and `dsp.c`, the other engines, and the
effects, which emit no 64-bit multiply here. The source-level `phys_dsp.c px_m` multiplies are
present (the `px_*` rows) but not beside 16-bit loads.

## Existing crash material (plan step 2)

A search of `docs/`, `tests/`, `data/` and `README.md` found **no recorded crash, no field
report and no single-bit (`0x00800000`-style) signature**. The retained crash record
(`fm1_crash_t` in `firmware/hal/fm1_irq.h`: `pc`, `rets`, `sp`, `psr`, `icfg`, `emu`, `dbg`, the
`etm[4]` PC trace, uptime, count, early, core) keeps no general-purpose register, so a bad loop
index like the donor's `0x00800012` could not be seen in it; only `sp` is a candidate (the donor
saw it a word off, which a report could check for 4-byte misalignment of an otherwise valid
stack). `tests/crash_record_test.py` and `tests/crash_snapshot_test.py` use synthetic frames, and
`docs/stress-baseline-2026-10-16.md` is a host stress baseline. Recording registers belongs to
#428; until then any unexplained fault needs the `pc`/`rets`/`etm` addresses mapped to this
inventory by hand.

## Proposed phase 2 order

1. **Reproducer first (device).** Synthetic test with this toolchain and flags: 16-bit table loads
   beside inline `int64` multiplies vs `noinline` consumers, and the FM6/PHYS/USB-48k stress presets.
   Without a reproduction on this unit a mitigation has no measured benefit; decide per the result.
2. **`uac_tap48`** (`usb.c`, firmware only, ISR A, only at 48 kHz UAC): smallest, nearest to the donor
   pattern; candidate: out-of-line product helper or 32-bit accumulation if the range allows.
3. **`fm6_op_run` / `fm6_op_fb`** (`fm6_core.c`): already `noinline`, so the multiply stays among the
   loads inside them; the candidate is a product helper (`mul_q31`-style) consumed at once. Highest
   per-sample load (6 operators x voices).
4. **`px_symp_run`** (`phys_symp.c`): then, only if measured needed, the setup rows (`formant_render`,
   `fres_coef`, `fm6_render`).
5. Leave the no-near-pair `px_*`, `phys_render` and `midi_clock_pulse` unchanged; the checker's
   `--fail-on-new` can keep them from gaining a pair.

Any change in `firmware/engines/` must land in kmplngj/Felucca-Engines first, then the gitlink;
no flagged function is in the pinned engine sources today, so none is needed now.

**Measure for each candidate** against the unchanged revision, one cause at a time:
`build/host/regress` and `regress_os` instruction counts with `tests/cpu_baseline*`
(the host counters do not measure pi32v2 cycles); `tests/target_budget.py` and the loop costs
of the changed functions; `build/felucca.bin`, RAM/POOL/NOINIT and `.ram_text`; goldens must
remain unchanged (`tests/golden.txt`, `union_golden.txt`); this checker's totals, and the
worst-case device load: full polyphony FORMANT, PHYS (SYMP) and FM6 on all four parts with
effects and USB audio at 44.1 and 48 kHz, reading `cpu_pct`, `audio_max_us`, `audio_late`,
`voices_shed`, `uac_*` through the diagnostics collector ([diagnostics](diagnostics.md),
[performance](performance.md)). The donor's decoder lost about 50 % speed to the same remedy;
Felucca's deadline headroom per engine is unmeasured here.

## Limits

Static text only. The window is address order, not control flow or pipeline distance. Whether
an affected instruction mix exists on this chip, and whether any of these sites can fault, is
unproven; `nop` padding, pairing and voltage were already shown by the donor not to help, so
a clean checker result would not prove safety either.
