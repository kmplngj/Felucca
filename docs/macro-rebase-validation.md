<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO rebase validation

This records the issue #27 experiment rebased from original MACRO revision
`3d1f940` onto current main `3b165ba`. Measurements below use the same JieLi
Clang 4.0.1 toolchain. They are integration evidence, with FM-1 qualification pending.

## Local target resources

These are the clean main baseline and the integrated opt-in `macro` profile
build, reconfirmed after the validation fixes. The PR identifies the exact committed
artifact and its provenance; build identity can alter app bytes. The standard
profile excludes MACRO.

| Resource | Main baseline | MACRO candidate | Delta |
| --- | ---: | ---: | ---: |
| App binary | 486,984 B | 571,640 B | +84,656 B |
| RAM (`.data + .bss`) | 62,088 B | 62,088 B | 0 B |
| POOL | 336,440 B | 354,200 B | +17,760 B |
| NOINIT | 15,576 B | 15,576 B | 0 B |

POOL grows by 4,440 bytes per part across four parts, from the optional MACRO
arena size of 17,328 bytes instead of 12,888. This is static storage accounting;
it does not measure stack high-water use or device timing.

## Integration checks

The integrated local `macro` run exercises 149 factory golden renders: all 98
existing rows remain unchanged, with 51 MACRO rows added separately. `-O1`,
`-Os`, CPU2-disabled and host-thread variants report zero changed/gone renders,
health failures, voice/routing failures or crashes. Host instruction budgets are
**not checked**: `perf_event_open` cannot obtain a PMU counter in this workspace.
Host elapsed time is not FM-1 audio-deadline evidence.

Focused checks cover all 48 models, eight-control preset/project round trips,
65 memory-engine/model switch pairs in both directions, queued-note/fade/reset
ownership and all 45 added models' eight-to-one-to-eight voice-cap transitions.
The MACRO core/model bank passes AddressSanitizer and UndefinedBehaviorSanitizer;
the cross-engine check uses the suite's existing DSP arithmetic exclusions.
UI lint covers 248 scenes in ten palettes with no layout or alignment findings.

Native/Wasm comparison covers all 51 presets and all 48 models with 4,723,110
bit-exact frames. Chromium passes ten browser checks, including real panel model
selection, stereo audio, portrait controls and saved controls restored after a
fresh worklet restart. These checks exercise simulated hardware only.

The initial integrated run found profile-dependent fixture assumptions and an
out-of-bounds endpoint read in the old 96 kHz upstream reference test. The same
reference failure reproduces on original MACRO revision `3d1f940`; production
MACRO uses its separate guarded WAVE path. Both reference build copies now
duplicate the terminal wave, matching that existing guard, without changing the
pinned sources or production header. Normal and bounds-sanitized comparisons
pass all 429 scenarios over 200 blocks each. The final PR records the corrections
and successful reruns; do not interpret the initial aggregate as a passing run.
Official V15 restore is untested because its package is unavailable.

Real FM-1 installation/recovery, physical panel/LCD, USB/TRS MIDI, USB audio and
render deadlines remain **pending**. Follow [the hardware acceptance procedure](macro-hardware-test.md)
using the exact commit's macro-profile package. Issue #27 remains open until the
device acceptance results are recorded.

## Dispatcher static-budget calibration

The generated `felucca_braids.h` is byte-identical between original and rebased
builds, SHA-256 `730e3f046731e4f60b61c418220223f84c8a3999c66b3da01803bcf98e1b6287`.
The 323-line `braids_DigitalOscillator_dispatch` LLVM IR also matches after
normalizing metadata IDs and attribute-group numbers. Both raw and size-annotated
IR retain `nounwind optsize`, without `minsize`; corresponding call attributes
are `nobuiltin optsize`.

| Dispatcher metric | Original MACRO | Rebased MACRO |
| --- | ---: | ---: |
| Total instructions | 4,670 | 4,642 |
| Whole-function divides | 18 | 18 |
| Whole-function calls | 23 | 30 |
| Instructions counted inside backward spans | 2,774 | 4,611 |
| Divides counted inside those spans | 11 | 18 |
| Calls counted inside those spans | 14 | 29 |
| Static weighted cost | 3,960 | 17,649 |

The original's 37 exit branches all jump forward to its common epilogue at
function offset `+0x3532`, followed by its sole return at `+0x3534`. In the
rebased listing the epilogue moves to `+0xb0`, followed by the sole return at
`+0xb2`; all 37 exits now jump backward. The farthest exit at `+0x3584` creates
a 13,524-byte span enclosing 4,611 instructions. The estimator treats this
span as an outer loop and increases the nesting weights of the model bodies.
The path itself cannot repeat: its destination restores the stack and returns.

A diagnostic calculation excluding only that common-return span gives **3,932**
for the candidate versus **3,960** originally. Remaining depth-1/2/3 instruction
counts are 2,508/206/32 versus 2,536/206/32, with 11 divides in both. This diagnostic
does not change the estimator. DSP callsite counts remain identical; seven new
`memset` calls accompany main's word-based libc implementation replacing inline
byte clears. These code-generation differences do not establish runtime savings.

The conservative **17,649** score is accepted for the newly integrated MACRO
`braids_DigitalOscillator_dispatch` budget entry only. Existing main budgets,
the estimator and its 10% tolerance remain unchanged. This calibration records
compiler layout; it does not imply a fourfold runtime increase or prove FM-1
CPU headroom. Hardware render deadlines, nested interrupts and audio remain pending.
