<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO flash fit — 2026-11-01

The MACRO profile retains all fourteen installed engines, all 48 oscillator models,
51 MACRO factory sounds and the existing sample bank. Two lossless storage changes
and an extension of the existing selective size pass restore its FM-1 flash fit.

## Changes

`gen_braids.py` emits the two 256-entry formant tables as signed bytes instead of
signed 16-bit samples. Every value fits exactly; generation rejects out-of-range
values or a changed table length. This removes 512 bytes of table payload. The
heterogeneous waveform-pointer table uses `const void*`; BUZZ still reads its
16-bit comb tables at the original indices. Upstream sources remain unchanged.

`size_fns.py` also selects `ui_fm6op.c`, `ui_tools.c`, `editor_learn.c` and
`editor_palette.c` for the existing main-loop `minsize` pass. Audio, DSP and
interrupt-reachable functions retain `-Os`. The main-loop functions `tl_order`
and `tl_motion_plan` are explicitly excluded because their record scans/copies
run with interrupts disabled. The selection regression checks both eligible
functions and these exclusions.

No sample-loop calls, runtime table decompression, feature exclusions or memory-map
changes are introduced. Main-loop size optimization can change redraw and command
service time; host correctness tests do not measure those target timings.

## Matched target measurements

Baseline: unmodified `f0fea3c`, FM-1, `FELUCCA_PROFILE=macro`, default feature flags
(including compiled CPU2 support), JieLi Clang 4.0.1 from
`jieli-linux-toolchains-20260730.1`, selective size enabled. Engines pin:
`7cf364f6c2ce0130be4fe8bf436ffe62077cb175`. The three SDK inputs match the build's
AC79NN 1.2.1 hashes. Both runs use the same generated M8Stealth fonts/icons and
126,244-byte ADPCM sample bank. The candidate has the same revision with this
working-tree change, including the compiled dirty identity.

The normal baseline build fails to link. For measurement only, its unchanged
object was separately linked with `FELUCCA_APP_SLOT=600000` under the ignored
baseline directory. Its actual app load extent is 582,884 bytes, 1,320 bytes over
the production 581,564-byte slot. The candidate uses the unchanged production
linker limit and completes packaging normally. Different build identities or
feature configurations can produce a different initial overflow.

| Resource | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| App load image | 582,884 B | 580,664 B | **−2,220 B** |
| App spare | −1,320 B | **900 B** | +2,220 B |
| Regular RAM span, including section alignment | 62,436 B | 62,436 B | 0 |
| POOL | 353,976 B | 353,976 B | 0 |
| `.ram_text` | 2,924 B | 2,924 B | 0 |
| `.c1_text` | 228 B | 228 B | 0 |
| `.noinit` | 15,576 B | 15,576 B | 0 |

Regular RAM has 11,292 bytes spare; POOL has 14,664; NOINIT has 120. Reserved stack
regions are unchanged. These are static allocations, not measured stack peaks.
The loader is unchanged at 9,484 bytes. The padded installable candidate package
is 612,640 bytes; package size is not app-slot utilization.

An isolated same-IR target comparison of the additional main-loop selection saves
1,704 bytes. Its complete `tl_order` (49 instructions), `tl_motion_plan` (78),
`memcpy` (24), `memset` (25) and `motion_count` (22) bodies retain identical operations,
registers and normalized branches. Whole-image savings also include generated
lookup code, alignment and the clean-to-dirty build identity; isolated byte
figures should not be added as though they were a separately linked image.

## Validation and reproduction

Unchanged baseline host workloads pass 149 golden renders with zero changed hashes,
health failures or voice/routing failures, and all full-bank bounds/reset/part/
transition checks. Host instruction budgets are unavailable in this environment.
Candidate validation is recorded with its logs in `build/macro-size-after/` and
the full suite's separate `build/host/test-run-*/` directory.

```sh
FELUCCA_PROFILE=macro uv run --locked --group build ./build.sh
FELUCCA_PROFILE=macro uv run --locked --group build tests/run_tests.sh --ai-output
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
```

The existing Braids reference comparison checks all emitted formant values and
compares all 48 models against the pinned C++ implementation. The full suite
additionally covers sound goldens, switches, controls, persistence, sanitizers
and native/Wasm parity. Keep baseline and candidate logs, ELF, disassembly and its
profile sidecar under ignored directories when repeating the comparison.

No FM-1 was flashed or timed. Remaining device checks are loaded playback while
using SEQ TOOLS, FM6 operator editing and editor LEARN/PALETTE commands, plus audio
deadlines, panel/MIDI responsiveness and stack guards. The optimization does not
establish a device CPU speedup or close existing MACRO hardware qualification.
