<!-- SPDX-License-Identifier: GPL-3.0-only -->
# User-preset browsing validity cache

This candidate for [#165](https://github.com/kmplngj/Felucca/issues/165) caches only the
structural validity of the 32 RAM-mirrored user-preset records for main-loop display
and browsing. FM-1 acceptance is pending. It does not cache flash reads, change stored
records or authorize a sound load.

## Contract and lifecycle

[`up_valid` / `up_used`](../firmware/src/upreset.c) remain the authoritative parser checks.
Loading, rename, pattern loading, editor GET/LIST, FM6 patch access and incoming backup
validation still use them. In particular, a stale positive display result cannot make
`up_load` accept a record whose last packed byte is invalid.

[`up_browse_used`](../firmware/src/ui.c) owns one 32-bit mask, a generation and an explicit
ready flag. Its first in-range query validates all 32 slots, then subsequent queries
reuse the mask. A generation mismatch also rebuilds it. The source struct is 12 bytes;
actual target symbols allocate three 4-byte `.bss` members. Linked RAM changes include
the target's layout/alignment effects. No allocation, IRQ-off
window, flash operation or interrupt reader is added. A cold rebuild examines at most
32 records and 4,608 packed bytes (32×144); it can do more work than the previous single
slot query. This is bounded main-loop work, not a measured device latency.

Explicit invalidation covers boot (including no-flash builds), bank checking after
boot/whole-bank restore, and committed `up_put` writes/erase/rename/category changes.
A failed flash write first restores the original RAM record/header, then invalidates;
the next query therefore sees the rollback. Successful writes retain the existing
`up_gen` increment. Explicit invalidation also covers a generation cycle returning to
a cached tag, and bank replacement with no generation change. Favorites and FM6 patch
changes alone do not alter structural record validity; their metadata is read normally.

The cache serves source labels, engine-scoped preset lists, user count/nth/rank, and
USER rows/action styling. Pattern eligibility and RECENT fingerprint validation keep
their existing authoritative paths. Factory aliases, DIGITAL conversion, categories,
favorites and slot order are unchanged. No engine/parameter/wire IDs, formats, default,
dependency, font, icon, layout or audio arithmetic changes are involved.

## Controlled source and workload comparison

The original source is exact clean firmware
`265949e6e9492cf4b0aa0fe16847cd4f573acdef`, Engines
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. Original source and generated standard headers
were preserved before editing. Ignored experiment artifacts live under
`build/issue165/`; the handoff manifest binds commands, compiler/configuration, source,
generated inputs and outputs. The first baseline attempt failed before compilation
because the reused checkout's pinned submodule was empty. That failure is retained;
the explicit retry followed initialization of exactly the unchanged gitlink.

An actual-source UI workload calls engine-list position, user count/nth/rank and full
preset enumeration. Its instrumentation counts entry to the real validator and each
evaluated packed-byte read, including early rejection. The timing executable disables
both counters. All eight original/candidate catalog-order hashes match.

| Bank/list workload | Original calls / packed reads per pass | Candidate cold calls / reads | Candidate warm calls / reads |
| --- | ---: | ---: | ---: |
| Empty | 1,616 / 0 | 32 / 0 | 0 / 0 |
| Eight valid slots | 1,856 / 54,168 | 32 / 888 | 0 / 0 |
| Full | 2,672 / 296,592 | 32 / 3,552 | 0 / 0 |
| Malformed v4 or v5, alternating last byte192 | 2,128 / 236,208 | 32 / 3,552 | 0 / 0 |
| DIGITAL records | 2,672 / 296,592 | 32 / 3,552 | 0 / 0 |
| SAMPLE alias route | 2,672 / 296,592 | 32 / 3,552 | 0 / 0 |
| Favorites filter | 6,312 / 700,632 | 32 / 3,552 | 0 / 0 |

These are exact counts for the scripted query batch, not a whole frame, flash traffic,
CPU percentage or FM-1 speedup. The pre-edit host timing and the single paired sample
are exploratory. The paired sample uses seven alternating original/candidate pairs,
500 warm query batches per case, a volatile sink, a non-inlined reader and a compiler
memory barrier before each invocation. Actual host disassembly retains the reader
call inside the counted loop. Source/binary hashes match before/after; catalog hashes
match throughout. Setup and one cold read are outside the timed batch.

| Workload | Original median µs (min–max) | Candidate median µs (min–max) |
| --- | ---: | ---: |
| Empty | 1.52 (1.46–2.22) | 2.69 (2.55–2.88) |
| Eight valid slots | 17.20 (16.54–23.85) | 3.18 (3.10–3.70) |
| Full | 84.15 (82.77–92.53) | 4.70 (4.39–4.77) |
| Malformed v4 | 71.43 (70.62–81.17) | 3.54 (3.35–3.72) |
| Malformed v5 | 71.80 (71.19–72.69) | 3.57 (3.41–3.77) |
| DIGITAL | 83.78 (82.74–87.86) | 4.60 (4.22–4.83) |
| SAMPLE alias route | 84.34 (81.48–115.07) | 4.48 (4.22–5.69) |
| Favorites | 212.07 (209.52–244.66) | 22.65 (21.46–23.32) |

**The empty-bank host workload regresses in every pair**: median paired ratio 1.74,
range 1.18–1.92. Ambient one-minute load average was 16.08 before and 8.77 afterward on this 12-CPU
host; no coordinated quiet release was available for the sample. It is not a qualified
quiet-window comparison. No repeat was used to manufacture a quieter result. These
are scripted host query batches, not frame/UI/IRQ latency or target cycles; no device
timing has been collected. Raw pairs and ambient/provenance records are retained in
`build/issue165/paired/`.

Actual full RGB565 buffers also match byte for byte for 240 frames: eight bank scenarios
× ten palettes ×USER/PRESETS/EDIT-layer views, with the same frozen generated inputs.
This checks renderer output, not physical LCD readability or interaction deadlines.

## Preliminary target resources

JieLi Clang 4.0.1, M8Stealth, the existing ISR-aware size policy and identical explicit
profile/CPU2 settings were used for each pair. SDK input is recorded in the artifact
manifest. Every build passed target budgets, resource verification and package checks.
The existing unused `ui_draw.c` variable warning is retained. No budget was changed.

**These are clean original versus dirty candidate measurements, including different
build identity strings. They are not an isolated code-only delta or a final clean-head
comparison.** Root's signed-head qualification must resolve that identity confound.

| Profile | App original →candidate | RAM original →candidate | POOL | RAMTEXT | NOINIT |
| --- | ---: | ---: | ---: | ---: | ---: |
| Standard CPU2=1 | 496,316 →496,888 | 62,392 →62,408 | 336,440 unchanged | 3,152 unchanged | 15,576 unchanged |
| Standard CPU2=0 | 492,768 →491,400 | 55,764 →55,796 | 336,440 unchanged | 2,924 unchanged | 15,564 unchanged |
| MACRO CPU2=1 | 580,368 →580,976 | 62,392 →62,408 | 354,200 unchanged | 3,152 unchanged | 15,576 unchanged |

MACRO application headroom falls from 1,196 to **588 bytes** in this preliminary build.
Retention must account for that capacity cost; a host query-count reduction does not
justify accepting it silently. Stack reservations/guards are unchanged: main user
24,320 bytes plus 256-byte guard, supervisor 7,936 plus 256-byte guard, and CPU2 builds'
worker 4,096 bytes including its guard plus 256-byte supervisor allocation. Reserved
space is not a live stack watermark or a proof of whole-call-chain margin.

The actual target disassembly adds a 100-byte `up_browse_used` with a 32-byte entry-local
frame and only the existing `up_used` call. `eng_list_pos` changes from 36 to 40 local
frame bytes and `up_put` from 232 to 236; `up_used` (4), `up_valid` (8) and bank checking
(32) are unchanged. These figures count initial saved registers and immediate SP
allocation, excluding callers, callees and interrupts. Whole main-loop stack margin
remains unmeasured. All three IR reachability checks keep the cache off the ISR closure;
the existing size pass applies `minsize` to it. Compiler/compile flags match within each
pair; only `FELUCCA_BUILD_DIRTY`, `FELUCCA_BUILD_ID` and `FELUCCA_SPLASH_ID` effective defines differ.

## Validation and remaining gates

[`tests/ui_test.c`](../tests/ui_test.c) adds actual-path coverage for cold/empty browsing,
slot 0/31 order, RAM save, rename/category, erase, generation wrap, same-generation bank
replacement, malformed v4/v5 last bytes, stale-positive load/rename rejection, full-bank
alternating erase and no-flash boot. Existing NOR rollback, actual backup restore and
editor GET/LIST tests cover warmed caches; direct-bank fixture resets explicitly notify
the cache. Deliberate poison tests intentionally omit notification to exercise authority.

All six ignored negative controls fail their intended assertions: missing commit
invalidation, missing bank replacement invalidation, missing no-flash boot invalidation,
omitted slot 31, cached load permission and cached editor permission. Normal focused
UI/persistence/backup/editor/record/engine-ID/FM6 checks pass. All-check ASan/UBSan passes
the new UI cache path, record tests and persistence tests. Full strict editor and backup
abort at the pre-existing `eng_slice.c:134` sample-array bounds check; the exact pinned
original independently reproduces both failures. This is tracked separately in
[#638](https://github.com/kmplngj/Felucca/issues/638). No check is suppressed or DSP source
fixed in this change, and those runs are not sanitizer passes.

The full standard host suite completed **failed**: 126 units passed, 2 failed, none blocked
or cancelled, 3 not applicable. The strict verifier also failed. Reverb SPRING measured
119 versus ROOM 90 instructions/sample (+33%, limit 30%). Regression exceeded existing
O2 ANALOG budgets and reported an Os LOFI STEP_LEAD excess plus six missing Os DRUM
baseline entries. Across the four regression routes, all 98 PCM goldens were unchanged,
with zero health/voice/routing failures or crashes. No baseline or golden was rewritten.

One focused frozen-original replay per failed unit used the same runner flags, platform
and generated inputs. Reverb and O2 ANALOG failures reproduced. The Os LOFI excess did
not reproduce in that single original pass; importantly, the original and candidate
`reverb_test`, `regress`, `regress_os` and `regress_cpu2_0` executables are **byte-identical**.
The differing LOFI observation therefore occurs with identical compiled code; its
counter/runtime cause is unresolved, and the failed full run remains failed.

Actual macOS instruction counters were available; threaded C1 CPU comparison remains
unqualified. DaisySP reference input and the proprietary official V15 package were
unavailable. TSAN was not requested, and MACRO/ASan MACRO units were excluded by the
selected standard profile. The retained editor also declares its three existing
missing MENU/FM6-bank/MIDI-LEARN features. Diagnostic skip-line counts include ordinary
assertion text and are not a count of omitted tests.

Fresh native/Wasm emulator checks passed, followed by the actual Chromium browser gate
with 10/10 checks (`build/browser/run-mhIh6i/summary.json`), including USER save/restart/load.
These remain host/browser evidence. FM-1 loaded browsing/audio, save/reboot/restore,
CPU2 modes and MACRO capacity/stack/deadline qualification remain pending. No device
access, flash, release or adoption decision is implied.

## Recommendation

Keep this as a reviewable draft choice, not a demonstrated general performance win.
Do not merge before the explicit retention decision, clean-head profile comparison and
FM-1 qualification: the empty-bank host regression and MACRO's 588-byte preliminary
application spare are real tradeoffs to investigate, even though populated catalog
queries perform fewer validations. Rejecting the candidate or separately refining its
empty-bank/capacity cost remain options; this change silently selects neither.
