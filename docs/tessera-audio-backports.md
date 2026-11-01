<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Tessera PHYS decay and overload recovery

These two bounded firmware fixes come from
[Rastapopolix/tessera](https://github.com/Rastapopolix/tessera), inspected at
`99c71cb7d4144ecaf06ab6bb0f00ae3151547c6a`. They retain the donor implementation
and Felucca's existing fixed-point DSP, voice ownership and interrupt instrumentation.
No donor engine, preset, signal-path rewrite or tool is adopted.

## Source and compatibility

| Fix | Exact donor source | Felucca adaptation |
| --- | --- | --- |
| PHYS modes ring out without a fixed-point noise floor | [`e1224163b12498a3d0ed922ac849d09186dbdff0`](https://github.com/Rastapopolix/tessera/commit/e1224163b12498a3d0ed922ac849d09186dbdff0), `firmware/src/phys_dsp.c` | Copy `px_modes_bound` and both calls directly. Retain the MIT notice and Theo Dainis credit. |
| Held-note PHYS decay regression | [`c976aef33a22f0d457d3a7d2b0a3000b020a177c`](https://github.com/Rastapopolix/tessera/commit/c976aef33a22f0d457d3a7d2b0a3000b020a177c), `tests/phys_test.c` | Extract the decay check through the real note/mixer path; bound the last partial block. Felucca's existing gain/output rounding needs a 1.25 LSB RMS tolerance instead of the donor's 1 LSB. |
| Earlier deadline protection | [`abe4983ef72c68b4f4fca5ce90b49c07c49800cb`](https://github.com/Rastapopolix/tessera/commit/abe4983ef72c68b4f4fca5ce90b49c07c49800cb), `firmware/src/audio.c`, `tests/audio_test.c` | Copy the thresholds and ISR assertions, retaining Felucca's names and render-stage hooks. |

MODAL and MEMB already clamp their resonator states once per control block. The
copied helper additionally zeros a mode when both states are below the donor's
2^-12 threshold. This removes low-level rounding residue while preserving the
existing bounds. STRING/SYMP synthesis, knob mappings, gains and factory preset parameters
are unchanged. Five PHYS render hashes intentionally change: MARIMBA, BOWED METAL,
KALIMBA, HAND DRUM and TOMS.

The switch oracle changes only the 314 of 720 sequences whose primary path plays
PHYS preset 1, 3 or 4, or whose accompaniment plays PHYS preset 1 in its second
segment. All 406 other hashes are retained. Preset indices in a switch include
the segment offset; checking only the initial engine would miss accompaniment.

Overload recovery now requests one bounded voice fade after a DMA half above
92% of its deadline, or two consecutive halves above 80%, including nested
TIMER5 work. The old rule waited for two halves above 85%. Quiet released tails
remain the first victims; each part's lowest POLY note and MONO/LEGATO lead remain
protected. This trades earlier voice reduction for deadline headroom. It does
not expand polyphony or establish a CPU speedup.

Engine/parameter IDs, saved project and preset layouts, wire formats, profile
selection and diagnostics fields are unchanged. Old sounds still load; PHYS's
quiet decay is an intentional sound difference. Optional profiles can omit PHYS.
[Licensing](../LICENSING.md#tessera-audio-fixes) records the copied source closure.

## Measurement and validation

The initial matched target comparison starts at clean fork main
`73c1ed4fce36308e9adab550a99a65059d94d00f` and applies these source changes.
Both builds use FM-1, the standard profile, `FELUCCA_CPU2=1` (runtime OFF by
default), selective minsize, JieLi Clang 4.0.1 and the same SDK, generators and
engine pin `7cf364f6c2ce0130be4fe8bf436ffe62077cb175`. The candidate below is
the patched dirty tree with its recorded source diff; its build-identity suffix
also contributes image bytes. The PR records the final clean-head allocation.
Archived input hashes,
source diff, build identity, artifacts and reports live under ignored
`build/tessera-audio/{baseline,candidate}/` in the implementation checkout.

| Allocation | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| App image | 503,508 B | 503,576 B | +68 B |
| RAM `.data+.bss` | 62,900 B | 62,900 B | 0 B |
| POOL | 336,244 B | 336,244 B | 0 B |
| RAMTEXT including worker code | 3,152 B | 3,152 B | 0 B |
| NOINIT | 15,576 B | 15,576 B | 0 B |

CPU0 user/supervisor reservations remain 24,320/7,936 B, with 256 B guards each.
The worker retains 4,096 B including its user guard plus 256 B supervisor stack,
already counted in RAM. These are reservations, not measured live stack use.
The fresh target builds pass resource and flash-safe-code guards and retain the
same pre-existing `ui_draw.c` unused-variable warning. The static loop heuristic
for `px_modal_block` changes 111 to 118 and `px_memb_block` 106 to 113; both pass
the existing thresholds. `px_modal_run` is unchanged at 195. No budget is refreshed.

On the unchanged latest-main firmware, the new held-C4/velocity-110 MODAL DAMP=0
regression measures 4.55 LSB RMS over seconds 1.5–2 and fails; the copied cleanup
reduces it to 1.01. The new overload assertions fail the old firmware for two
80–85% halves, one half above 92%, and one half beyond the deadline.

Thirteen focused host units pass with prerequisite closure: PHYS, its 298-case
DaisySP reference, audio, regression, union, arena, ASan union/audio-stage,
all four sparse catalogs and ASan catalog 11. The regression unit passes all
98 audio goldens in its normal, size, CPU2-off and threaded variants; default,
owner-checked and ASan union runs match all 720 audited hashes. No warning is
reported by those host units. The selected run is retained as
`build/host/test-run-u726udsy/summary.json`; it is focused evidence on the patched
latest-main source, not a complete or final-head CI qualification.
Host instruction counters are unavailable on this runner; host wall time is not
a target CPU claim. Additional profile fit checks are recorded in the PR.
The full MACRO profile already exceeds the XIP limit in the
[upstream 1.8 backport](upstream-1.8-backport.md#known-build-limits); this change
does not resolve that capacity gate. Exact-head full CI, FM-1 listening,
loaded deadlines and live stack behavior remain separate acceptance checks.

## Remaining FM-1 checks

Use the PR's exact artifact and physical procedure. With transport stopped and
2ND CORE OFF, select PHYS BELL TREE, set BODY DAMP to 0 and EXCT BOW to 0, then
hold middle C: the strike should decay without a persistent buzz. Compare MARIMBA,
KALIMBA, HAND DRUM and TOMS, including retriggers and switches to another engine.

Compare the same dense FM6 MIDI score on base and candidate for a declared
duration, with identical presets, levels, notes, traffic and 2ND CORE OFF. Record
audio lateness and shedding together, surviving voices, listening and panel
response. Earlier shedding may remove notes sooner; a quieter or smaller
workload alone is not a timing improvement. These device checks are pending;
no firmware was flashed for this backport.
