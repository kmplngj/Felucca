<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Selective minsize ISR protection

`python3 tests/size_fns_test.py` exercises the production selector with 16
portable tests. It covers both ISR roots, recursion/transitive calls, directly
taken addresses, global pointer initializers, nested constant tables, aliases
and cycles, unrelated globals, runtime-written hooks, unknown dispatch, changed
call counts, missing roots, final annotations and attribute idempotence. These
are analysis fixtures, not proof that arbitrary LLVM modules are valid.

`python3 tests/size_fns_target_test.py` separately generates fresh unoptimized IR
with JieLi Clang 4.0.1 using the production flags, verifies actual callback-table
protection, and compiles annotated IR back to a target object. It includes
`local_unnamed_addr` before `minsize` and retains the compiler's attribute groups.
Source, IR, object, disassembly and compiler/flag provenance stay in ignored
`build/host/size_fns_target/`. Missing default toolchain is an explicit skip;
an explicitly configured broken toolchain or compiler failure is an error.
Both tests run in the normal host suite.

## Analysis and dispatch contract

The graph includes function bodies and global initializer/alias references.
Starting only at the configured ISR roots avoids protecting functions merely
because unrelated UI tables contain their addresses. Each reachable table is a
conservative superset: all its function fields and their transitive callees are
protected, including fields not currently called in an ISR.

This lightweight selector does not infer pointer provenance or runtime writes.
Every reachable indirect call therefore needs an explicit `ISR_INDIRECT` source
contract: its caller, expected number of indirect call sites in unoptimized IR,
and complete possible target definitions or immutable tables/aliases. Missing
contracts, count drift (including a drop to zero calls), unknown call forms, empty/missing targets and aliases or
tables leading to mutable dispatch objects fail the size pass. For runtime-written
hooks the contract must list every possible callback function explicitly. Ordinary
mutable DSP state referenced inside those callback bodies remains allowed.

When changing a contracted caller, audit its source even when the call count is
unchanged: the count catches additions/removals, not a changed target or ownership
invariant. Adding a callback to a reviewed constant engine table automatically
protects it and its callees. Unknown dispatch never falls back to main-loop-only.
The CLI requires both hardware roots; `roots=()` is an explicit fixture-only
way to disable analysis. Missing/malformed root/body input and pre-existing
`minsize` on a protected definition are failures. Eligible existing `minsize`
annotations are preserved without duplication.

## Production audit, 2026-10-12

Base: `78424c7` (#117), default features (`FELUCCA_FM4=0`, SLICE enabled).
`firmware/hal/fm1_isr.S` binds the assembly wrappers to `fm1_alnk0_irq` and
`fm1_timer5_irq`. Boot's audio/TIMER5 registration passes those wrappers; it
does not create another C callback root.

| Indirect caller | Call sites | Reviewed target source |
| --- | ---: | --- |
| `voice_start` | 1 | `ENGINES[t->engine]->note_on` |
| `track_render` | 4 | Engine `block`, `done`, `amp`, `render` |
| `kb_engine` | 1 | Engine `keys` |
| `chord_kit` | 1 | Engine `keys` |
| `seq_step` | 1 | Engine `keys` |

These callers use the immutable `ENGINES` pointer array and immutable `engine_t`
definitions in `engines.c`/`eng_*.c`. Their contract deliberately protects all
table fields. Fresh production IR contains no other reachable indirect call sites.

Registered service hooks were also inspected: `fm6_bank_read = fvb_read` in
`fm6_vbank.c` is called by `fm6_load_slot`/editor handling; `slc_man_load =
slc_store_load` in `slice_store.c` is called by `slc_user_scan`. These hook-call
functions and their registration/boot paths are outside the ISR graph. UI layer
action/name/LED tables likewise dispatch in the main loop. This establishes their
current classification, not permission to move storage or hook loading into an ISR.

The old body-only analysis protected 326 definitions; the new symbol graph protects
542. Of the 216 additional definitions, exactly two are `SIZE_FILES` candidates:
`fm4_gone_note_on` and `fm4_gone_render` from `fm4_convert.c`. They are no-op
callbacks for reserved engine ID 1 when DIGITAL is disabled (the track converts
old sounds to FM6); both now retain `-Os`. This is a confirmed annotation gap
in the current build, not an observed audio glitch or slow ISR. The other added
functions were already outside the size candidate list. No file-list expansion,
firmware source, engine ID, sound, persistence or golden/budget changes are made.

## Target comparison

Same JieLi Clang 4.0.1, `-Os -ffunction-sections -fno-builtin -Wall
-Wno-unused-function`, default generated assets, SDK
`d179b4484759423312073f5fbb232501aa491047`, and package identity `FM-1_900`.
Unchanged size-pass baseline and `FELUCCA_SIZE=0` reference were built before
the selector change. Candidate builds use `FELUCCA_SIZE=1`.

| Resource | Previous size pass | New size pass | All `-Os` (`SIZE=0`) |
| --- | ---: | ---: | ---: |
| App payload | 495,620 B | 495,620 B | 512,772 B |
| `.data + .bss` | 54,964 B | 54,964 B | 54,964 B |
| `.pool` | 327,800 B | 327,800 B | 327,800 B |
| `.ram_text` | 2,924 B | 2,924 B | 2,924 B |
| `.noinit` | 15,564 B | 15,564 B | 15,564 B |

The candidate has zero app/RAM delta and byte-identical app, ELF, disassembly,
loader and package. Removing the entire size pass costs 17,152 app bytes; that
comparison is not a saving introduced by this issue. Both RAM/POOL margins and
the 916-instruction no-call RAM-text check remain unchanged.

All 59 present tracked DSP/ISR function cost dictionaries are unchanged before/
after. The all-`-Os` reference changes only `fm1_alnk0_irq`: 38,871 to 38,984
weighted cost (+113, 0.29%); `fm1_timer5_irq` and all other entries remain equal.
All three configurations pass existing target budgets without updates. These
are static loop heuristics, not target cycles or measured device headroom.

Raw baseline/candidate artifacts, section/symbol reports, costs and build/test
logs are kept under ignored `build/pr-review/`. The full applicable suite passed, including 92 golden renders at both host
optimization settings, 720 engine-memory switches, target DSP/scan budgets,
sanitisers/fixed-seed fuzz, package/installer tests and native/Wasm parity. The
final storage-kind followup passed all 15 portable cases normally and with
Python -O, the real IR smoke, and reproduced identical production annotation.
DaisySP and original stock V15 restore checks were skipped because their inputs
are absent. The selector SHA-256 for these measurements is
`88df3fe7147ea3919fef5f52ee49127e2d830b538402ef9ccd476479b8ac179b`.
Device validation remains deferred; no flashing or device timing was performed.

The subsequent count-to-zero review fix adds one portable regression (16 cases
pass normally and with Python -O) and passes a fresh target IR smoke. It emits
byte-identical production annotation to the measured candidate above. Its selector
SHA-256 is `3fdf1e6262f1caf64df584c1be13a5408681859600b945b27476b09efcc55bed`.
The earlier full suite belongs to the previous selector revision; the count-zero
followup is covered by the focused checks and a fresh target build.
