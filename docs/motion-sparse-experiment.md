<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Sparse motion-mask experiment (#615, first stage)

This is an optional candidate against main
`f101979be19de475a6733e917bccc07733c87a65`, not adoption or completion of
[#615](https://github.com/kmplngj/Felucca/issues/615). Only the parameter-mask
walks in `motion_restore` and `motion_unlock` change. The motion-record index is
a separate, pending experiment. No target or device performance improvement is
established here. The recommendation is **do not adopt this variant into main**:
the synthetic
dense restore has a material host regression, code and local stack frames grow,
and no target or device timing win is established. Rejecting the candidate or
continuing a focused target/dense experiment are open choices for the owner.

## Production boundary

[motion.c](../firmware/src/motion.c) walks mask words in ascending order and
uses `__builtin_ctz` only inside `while (bits)`. Clearing the lowest set bit
visits the same parameter IDs in the original ascending order. The current
111-parameter domain occupies four words; the final word admits only its low
15 bits. Masking that word preserves the old scan's behavior even for synthetic
unused tail bits. Both complete mask arrays are still cleared where the
original functions cleared them.

The tail test uses `w == P_COUNT / 32u`: if a future parameter count is an exact
multiple of 32, that word lies outside the loop and no tail mask is applied.
This avoids the JieLi compiler's constant-logical-operand warning from the
first candidate's equivalent conjunction; no shift by 32 is introduced.

`motion_restore` retains its interrupt guard and base assignments.
`motion_unlock` retains its entire per-parameter record search, latest-step
selection, track/kind filtering, current-engine descriptor and `param_fit`.
It still accepts the caller's `const motion_store_t *`, including prepared song
sources. Record order, loop/stop/bypass restoration, base ownership, RNG order,
publication and saved/wire formats have no intended changes. No allocations,
index, persistent/static state, cache, rebuild or new lock is introduced.

The source now performs four outer word visits plus one inner visit per set
valid bit instead of 111 parameter-bit tests. That structural difference is
not a cycle count: dense masks, target `ctz` expansion and added instructions can
change the tradeoff. The record search remains bounded by 128 records for each
locked parameter. No budget or golden has been changed.

## Independent reference and observations

[motion_sparse_reference.h](../tests/motion_sparse_reference.h) preserves the
two original functions, including attribution, from exact main f101. Their
concatenated body SHA-256 is
`36342533be817781ee6f7c392684eb767742dcf0c2ff6e81ad7bc815c3d4a831`.
The complete original `motion.c` SHA-256 is
`493c044d62abf0f98f0688611b55f3da162a4ddc54336da489b3996befffaa8a`.
Both were archived and the unchanged-reference fixture passed before production
editing. The test rejects an altered frozen reference rather than regenerating
expected results from the candidate.

[motion_sparse_test.py](../tests/motion_sparse_test.py) compiles the real
sequencer, voice, UI/project and mixer sources twice: with the frozen original
walks, and with the candidate walks. Exact-count source adapters under ignored
`build/` observe actual motion assignments and note-on/off entry calls without
adding production hooks. Both sides use the same other source and generated
inputs. Adapters must be reviewed if those source seams change.

[motion_sparse_test.c](../tests/motion_sparse_test.c) compares every emitted
int32 stereo PCM word. Separate binary streams retain ordered parameter-write
and note observations, control-block sample timestamps, sequence index/position,
and explicit state at each boundary. State includes all sounding parameters and
base values, active/locked masks, base-valid bits, RNG, sequencer and ratchet/
nudge/live-record state, selected voice lifecycle fields, transport/song-chain
progress and used records in all four prepared song stores. It does not compare
struct padding or reduce equality to an audio hash. Note timestamps describe
the actual control-block call boundary, not a physical MIDI or DMA timestamp.

Two fixed RNG seeds cover empty/one/sparse/full 128-record stores; chance,
ratchets, swing and nudges; loop, stop and restart; internal and external clock;
four alternate prepared song stores and a silent lane; capture/overwrite, move,
kind toggle, delete, lock clear, undo/redo, shift/double/half, engine change,
project restore, copy/replace, bypass and track clear. Direct walk cases cover
every track, empty/single/dense masks, IDs around each word boundary, ID 110,
unused tail bits and a separate const store with out-of-order automation plus a
lock. Synthetic masks intentionally include every valid ID, even IDs that
normal motion capture does not set, to preserve the full original scan domain.

## Focused results (dirty candidate on f101)

Apple Clang 21.0.0 (`clang-2100.3.34.2`) on macOS arm64; standard M8Stealth generated inputs identify
clean f101. No assets were regenerated after editing. The CPU2-on build compiles
worker support; these fixtures render serially and do not establish worker
concurrency or device inter-core behavior.

| Comparison, each of two seeds | PCM words compared | Explicit snapshots | Ordered events |
| --- | ---: | ---: | ---: |
| `-O2`, `FELUCCA_CPU2=1` | 229,376 | 3,694 | 3,836 / 3,792 |
| `-Os`, vectorization disabled, `FELUCCA_CPU2=0` | 229,376 | 3,694 | 3,836 / 3,792 |
| Strict ASan/UBSan, changed walks only | 0 | 96 | 1,856 / 1,856 |

All six comparisons match exactly. Strict walk-only runs use
`-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all`, fatal runtime
options and **no sanitizer exclusions**. They perform restore/unlock/domain
cases without rendering DSP. An unchanged full-DSP strict reference attempt
aborted at `firmware/engines/src/eng_analog.c:184` with a negative-value left
shift. Its exit -6 and diagnostic are retained. That independent pre-existing
failure is neither fixed nor suppressed here; full-DSP PCM/event/state evidence
is the normal O2/Os comparison, not a full-DSP sanitizer pass.

Six mandatory causal controls also pass: omit a valid low bit, omit the high
word, remove the tail guard, reverse within-word order, omit the active-mask
clear and omit the locked-mask clear. The first, second and order controls must
change ordered events; the clear controls must change explicit state, even if
events also differ. The tail control must fail the explicit invalid-parameter
write assertion. This demonstrates observation sensitivity; it does not claim
the real source currently has any of those defects.

Existing `motion`, `ratchet`, `seq155`, `fun10` and `project` runner units pass,
as do all 27 `coverage_contract_test.py` tests. The new comparison runs inside
the existing asset-dependent `motion` unit, with declared normal and strict-walk
producer outcomes. `SANITIZE=0` explicitly reports the strict outcome skipped;
it cannot establish strict CI coverage. No focused check was skipped in the
recorded default run.

Evidence is under ignored `build/issue615/`:

- `reference/provenance.json` and the archived original source/reference;
- `reference-proof-v2/summary.json`: unchanged scan proof before production edits;
- `reference-proof/strict-full-reference-result.json` and matching stderr:
  the unchanged full-DSP strict failure;
- `candidate-warning-free/summary.json`: positive comparisons, commands, exact
  hashes and all six controls, with complete binary streams and compiler logs;
- `existing-warning-free/summary.json` and per-unit logs; the motion unit's repeat
  comparison also saves `build/host/motion_sparse/summary.json`;
- `freeze-v3/`: final nine-file diff, untracked input archive, input hashes and scope.

`candidate-focused-v2/`, `existing-focused/` and `freeze/` preserve the earlier
equivalent conjunction candidate and are historical after the warning fix.
Its first target build passed budget/package checks but reported two new
constant-logical-operand warnings. The corrected target comparison is below.
`freeze-v2/` preserves the warning-free seven-file state before the optional
cost reproducer and this report were added; the production hash is unchanged.

The first candidate run's failed control classification is retained separately
in `candidate-focused/`: missing active-mask clear changed events before state,
while the initial evaluator inspected only the first differing stream. The
corrected evaluator requires the intended stream to differ independently.
No production correction or reference change was needed for that finding.

Reproduce the focused comparison after generating the selected profile's assets:

```sh
uv run --locked --group build python tests/motion_sparse_test.py --out build/issue615/recheck
```

The full runner also executes it through `tests/run_tests.sh --ai-output`.
Full integrated suite execution is a separate remaining gate.

## Paired host cost and its limits

The original measurement ran once, after explicit CPU coordination, using Apple
Clang 21.0.0 on macOS 27.0.1 arm64. Both O2 and Os-without-vectorization builds
finished compiling before timing. Each build covers 24 cases: restore batch,
unlock batch and a separate restore guard-window proxy; empty, one-high-ID-110,
sparse-eight and dense-111 masks; zero and 128 records. Restore does not inspect
records; its repeated record-count factor makes that input independence explicit.
The 128-record const store has REV/E7 events across 64 steps and mixed AUTO/LOCK
kinds, searched at step 31. Dense-111 is a synthetic complete valid-ID mask,
including IDs ordinary motion capture excludes; it is not a claim about a usual
patch or a demonstrated FM-1 slowdown.

Each case calibrates iteration count from the original, warms both variants,
then runs nine AB/BA alternating pairs with identical iteration counts, masks,
store and final observable parameter/mask checksum. A volatile function pointer,
memory barriers and an observable sink prevent call/store elimination. Batch
cost includes the identical mask re-arm and indirect wrapper-call overhead.
Candidate batches can be shorter because paired iteration counts stay equal.
All pair sinks match. Raw samples and median/min/max/MAD remain available;
these are descriptive samples, not confidence intervals or isolated device cycles.

The guard proxy puts host clock bookends inside copies of the original/candidate
restore guard boundaries, excluding mask re-arm. It **does not disable host or
FM-1 interrupts**. Bookends and instrumentation/codegen remain in its value:
empty-bookend medians were 13.09 ns (O2) and 12.93 ns (Os), without subtraction.
The empty/single-bit candidate window is close to that floor. Hook-induced
codegen and scheduling effects also limit dense-window interpretation.

Selected results below use per-call nanoseconds and paired percent changes.
The full 48-case data, including empty and one-bit cases, are retained rather
than selecting only favorable sparse results.

| Host build / workload (128 records) | Original median ns | Candidate median ns | Paired change: median [min, max] |
| --- | ---: | ---: | --- |
| Os restore batch, sparse 8 | 63.25 | 3.71 | −94.06% [−94.19, −93.80] |
| Os restore batch, dense 111 | 29.97 | 42.31 | **+41.22%** [+39.82, +42.32] |
| Os unlock batch, one ID 110 | 147.45 | 87.27 | −41.00% [−41.56, −38.67] |
| Os unlock batch, sparse 8 | 670.73 | 615.12 | −8.04% [−10.45, −4.78] |
| Os unlock batch, dense 111 | 8,023.89 | 7,975.28 | −0.57% [−2.07, +4.30] |
| Os restore guard proxy, dense 111 | 29.68 | 37.98 | **+27.29%** [+25.63, +29.43] |
| O2 restore batch, dense 111 | 30.42 | 38.08 | **+25.25%** [+23.98, +26.28] |
| O2 restore guard proxy, dense 111 | 36.27 | 35.44 | −2.45% [−4.04, −1.52] |

The different O2 guard/batch result reinforces that an instrumented host window
does not predict target IRQ-off time. The unchanged
[host counter](../tests/host_instructions.h) also recorded process retired
instructions through `proc_pid_rusage(RUSAGE_INFO_V4)`, following the existing
[measurement policy](performance.md). Every recorded batch had an available
counter. For example, Os dense-restore batch instructions/call fall about
1,029.18→955.32 while host time rises; instructions are not cycles. No dynamic
pi32v2 counter or FM-1 timing measurement was made.

Original raw evidence remains in `build/issue615/cost-warning-free/summary.json`,
`O2.jsonl` and `Os-novec.jsonl`, bound to production SHA-256
`405b918a2d4ba8aa6b38ffcecbd14e23e9372b26c19a4c434f9acb06534636ab`.
The executed ignored `cost-pairs.py` and `cost-driver.c` and their recorded hashes
are preserved unchanged. That measurement predates the opt-in source reproducer;
it must not be relabelled as its later smoke run.

[motion_sparse_bench.py](../tests/motion_sparse_bench.py) and its
[C driver](../tests/motion_sparse_bench.c) make the same method reproducible
without ignored frozen-input metadata. They verify the pinned original function
bodies, capture current source/generated-input hashes before and after, refuse
an existing output directory, and retain commands, raw samples and summaries.
They run only when explicitly invoked; they add no CI timing budget or default
suite run. With generated assets and otherwise quiet CPU:

```sh
uv run --locked --group build python tests/motion_sparse_bench.py --out build/issue615/cost-independent
uv run --locked --group build python tests/motion_sparse_bench.py --smoke --out build/issue615/cost-smoke-independent
```

The actual reproducer smoke in `build/issue615/bench-reproducer-smoke/` passes
both builds, all 24 cases and two alternating pairs with at most 1,024 loops,
matching sinks and unchanged source/input snapshots. It checks the published
reproducer's execution and result contract, not performance qualification.

## Target evidence and remaining qualification

The maintainer captured an unchanged exact-f101 standard target baseline using
JieLi Clang 4.0.1 and selective minsize: app 496,316 B, RAM 62,392 B, POOL
336,440 B, RAMTEXT 3,152 B and NOINIT 15,576 B, archived as
`build/issue615/baseline-standard`. The maintainer's warning-free dirty-candidate
build passes budgets, resource verification and packaging; its only warning is
the unchanged `ui_draw.c:728` unused `x`. `target-review-v2.json` records app
496,412 B (+96 B), with all listed RAM-region totals and stack reservations
unchanged. This is a **dirty-versus-clean** comparison: three identity defines
change to include `-dirty`, so +96 B is not a final clean production delta.
Other effective flags match (baseline CPU2 default 1, candidate explicit 1).
A clean committed target comparison remains required.

`target-code-review-v2/summary.json` records disassembly-local results:

| Function | Code bytes before → candidate | Local frame before → candidate | Calls before / candidate |
| --- | --- | --- | --- |
| `motion_restore` | 112 → 146 (+34) | 20 → 44 (+24) | `memset`, `memset` / unchanged |
| `motion_unlock` | 234 → 292 (+58) | 60 → 80 (+20) | `param_fit`, `memset` / unchanged |

Each candidate has one inline `clz` operation implementing `ctz` with bit
operations and no new helper call. Both functions remain ISR-reachable with
`optsize`, without `minsize`. These local frames are not full call-chain stack
requirements or measured live high-water marks. Function bytes, linked app
bytes, retired host instructions and local frames must not be added into a
runtime claim. Source zero-before-ctz and final-word bounds remain covered by
the strict walk/domain comparison.

Matched empty, sparse, dense and worst target restore/unlock timing, including
the interrupt-off restore interval, remain unmeasured. There is no new index
rebuild cost in this stage. Fresh integrated host/target/emulator checks and
nested-interrupt stack/deadline qualification remain gates. Passing additional
correctness tests would not resolve the measured tradeoff or adopt the candidate.

FM-1 listening and timing under nested scanning, USB audio/MIDI and loaded
transport remain pending. Bind any hardware handoff to the future candidate
commit/package and matched baseline, with disposable sparse and dense projects.
The panel route is unchanged: ALGORITHM selects T1–T4; tap SEQ until AUTOMATION,
KNOB 1/PRESETS chooses the row, KNOB 2 the step, KNOB 3 the parameter and KNOB 4
the value; OCT+ toggles a record LOCK/AUTO. PLAY starts/stops transport. Compare
the same baseline/candidate projects through loop boundaries, automation bypass
(PLAY row, KNOB 4 OFF/ON), stop/restart and song section changes: locks should
restore the latest eligible automation or base, stop/bypass should restore base,
and notes, tails and controls should remain identical. Exact workload package,
installable artifact and complete device setup remain to be supplied before
requesting physical execution; none was installed during this experiment.

README assessment: no edit. Its experimentation, measurement and validation
overview already describes this unadopted internal candidate; engines, controls,
installation and compatibility have no intended change. Changelog assessment:
no entry until a measured retention decision establishes a noteworthy result.
No source or assets from another firmware were copied. #615 remains open for
the retention decision and the separate record-index design/experiment.
