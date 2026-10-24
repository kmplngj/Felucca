<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Parameter control contract and bounded test plan

Research for [#29](https://github.com/kmplngj/Felucca/issues/29) and
[#30](https://github.com/kmplngj/Felucca/issues/30), inspected 2026-10-24 at
`5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e` (`main`). This is a source audit and
decision proposal: it establishes neither an existing defect nor a new control
mode. No firmware, tests, formats, goldens or budgets were changed or executed.
The live issue bodies and their initial audit comments
([29](https://github.com/kmplngj/Felucca/issues/29#issuecomment-6383096088),
[30](https://github.com/kmplngj/Felucca/issues/30#issuecomment-6383096239)) were read.

The recommended first implementation is a small set of behavioral tests using
the existing parameter representation and publication owners. Preserve the
three existing value lifetimes below. Decide the MOMENTARY overlap and readback
questions before making a firmware behavior change. Do not import a donor's
composition order as an implicit product decision.

## Evidence conventions and scope

All numbered source links below are immutable links to the inspected revision.
They are observations of that revision, not results from running its harnesses.
The [development review](development-review-2026-10-11.md) is historical context;
its resource totals and test counts do not describe this revision. This report
does not compare or copy Schwung implementation; the donor links in the issues
remain references for a separate comparison if needed. No donor source is
required to establish Felucca's own contract.

Unmerged [PR #597](https://github.com/kmplngj/Felucca/pull/597), including its ENV
gesture and FM6 FIXED work, is outside this baseline. Rebase the plan and add its
new permanent-edit paths only after adoption; its validation cannot establish
coverage for the baseline audited here. UI redesign and controller-mode changes
are outside this batch.

## Current value lifetimes and readers

There are already three distinct values; a fourth full parameter array would
duplicate existing state rather than resolve a demonstrated requirement.

| Name used in this report | Current representation and lifetime | Reader or consumer |
| --- | --- | --- |
| Patch base | `motion_base_value(t,id)`: saved `motion_base` for an active motion/lock id, otherwise current `p[id]` | Project capture/autosave comparison, user-preset capture, DUMP and TRACK_DUMP |
| Control value | `t->p[id]` outside rendering: latest direct edit or sequencer automation/lock value | Panel value pointers, GET/SET and TRACK_PARAM replies, WATCH shadow and pushes, TRACK_MIX |
| Render value | Per-block `p[id] = clamp(kept control value + summed offsets)` between `mod_begin` and `mod_end`; per-voice terms have their own `vmod_t` path | Engine block render and track mixer; engine note-on precedes the temporary block modulation |

Authorities: [motion base/restore/rebase](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/motion.c#L108-L142),
[matrix lifetimes and destination types](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/mod.c#L3-L53),
[block sum/restore](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/mod.c#L171-L243),
[knob pointers and writes](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui_knob.c#L29-L113).

Readback is deliberately described by command, not as one uniform “editor value”:

| Surface | Current observation | Compatibility implication |
| --- | --- | --- |
| Panel ordinary parameter cards and knob starting value | Live control value through target pointers; not the ISR's temporary matrix offset | Showing the patch base instead would change what a turn starts from |
| GET/SET (2/3), TRACK_PARAM (31) | Reply from live pointer / `p[]`; normal parameter writes call `motion_capture` | A live reply can differ from DUMP while motion sounds |
| WATCH/CHANGED, TRACK_CHANGED | Live `p[]`, coalesced; other-track pushes cover level/pan/mute | These are neither a full-rate meter nor a base-value notification API |
| DUMP (4), TRACK_DUMP (29) | `motion_base_value`; DUMP's WATCH shadow is nevertheless initialized from live `p[]` | Do not change these snapshots to include transient motion or render offsets |
| TRACK_MIX (28) | Live level/mute read and direct write; this handler does **not** call `motion_capture` | It must not be silently normalized to SET/31 capture semantics |
| Project / user preset / raw backup | Captured projects and presets use patch base; projects also store motion independently. Raw stored-object export returns stored bytes | A held MOMENTARY edit is not universally excluded from capture: see below |

Sources: [editor value pointers/shadow](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/editor.c#L146-L173),
[WATCH](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/editor.c#L244-L266),
[GET/SET/DUMP](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/editor.c#L512-L549),
[track commands](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/editor.c#L826-L886),
[project capture](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/project.c#L855-L870),
[preset capture](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/upreset.c#L408-L420),
[protocol](../web/EDITOR_PROTOCOL.md).

## Current writes, precedence and stopping behavior

This is an event-order contract with a temporary render stage, not a universal
priority stack. Two ordered direct writes to one parameter normally leave the
later value. A wall-clock notion of “simultaneous” panel, editor and MIDI input
has no independent tie-breaker in the inspected code.

| Overlap or transition | Current behavior | Stop/clear behavior |
| --- | --- | --- |
| Permanent knob / SET / TRACK_PARAM / mapped or learned CC, not selected-and-recording | Write control value, then eligible `motion_capture` updates the valid patch base even if earlier motion was active | Later motion can override the control value; STOP or bypass restores the latest base |
| Same paths on selected armed playing track | Quantized sparse event; immediate value marked transient while base is valid | STOP before the quantized step restores the original patch base |
| Automation event and lock on same track/step/id | One shared record, of either kind; latest record write replaces the earlier kind/value | No simultaneous pair exists for that key |
| Motion plus step lock | Lock applies only when its step plays; next step restores latest automation event in this pass up to that step, otherwise base; step zero restores base before its records | Lock lasts the whole step, including ratchets; removing a currently sounding lock's record lets it expire at the next step |
| Several per-block matrix slots on same id | Each slot's fixed-point offset is computed, offsets summed, then destination clamped once | `mod_end` restores the exact incoming control value, including on the silent early-return path |
| DEPTH / AMP / note-time modulation | DEPTH is computed before the other LFO-dependent slots; AMP/DEPTH gains multiply; VEL/TIME act at note/step time | These are not interchangeable additive parameter offsets; retain rounding and RNG order |
| MIDI packet and due sequencer step in one audio block | `events_block` drains MIDI in queue order, then runs `seq_tick`; a due motion/lock write can therefore follow a CC write | This does not imply that motion always wins over a later main-loop edit |
| Panel/editor write versus audio event | Audio preempts main loop. A knob value write and subsequent capture are distinct operations; no cross-source timestamp arbitration is present | Characterize meaningful legal boundaries; do not promise whole-edit atomicity from scalar writes |
| Step held plus LFO held and knob turn | Step-lock branch is checked before MOMENTARY branch | Follow existing lock gesture arbitration |
| MOMENTARY turn | Caches live pointed value on first turn, writes directly, no capture/undo/LEARN; at most eight distinct pointers | Release/context exit writes cached values back; OCT+ KEEP drops the cache without calling `motion_capture` |
| MOMENTARY plus CC/editor/motion on the same id | Direct writes share `p[]`; newer events can overwrite a held momentary value and release can restore an older cached control value | There is no separate momentary overlay or automatic reconciliation of saved base with that cache |
| TRACK_MIX plus active level motion | Direct level write without capture, unlike SET/31 | Prior motion base can still be restored; policy parity is an open question |

Sources: [capture](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/motion.c#L219-L240),
[record replacement/publication](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/motion.c#L164-L216),
[unlock/step](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/motion.c#L242-L288),
[matrix](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/mod.c#L133-L243),
[render restore paths](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/fx.c#L1105-L1175),
[MIDI/step order](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/seq.c#L1427-L1464),
[momentary target/write](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui_knob.c#L115-L166),
[release/KEEP](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui_input.c#L1507-L1518),
[gesture order](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui_input.c#L1800-L1824).

Concrete combined-control examples, derived from those paths:

1. PAN base 0, motion sets PAN 20, MODW=127 with one `MODW -> PAN AMT 16`
   slot: the matrix contributes +31 (the existing math fixture's value). The
   renderer uses 51; after the block panel/GET read 20, DUMP/project capture
   read 0. A lock of -20 renders 11 for its step; at the next step prior motion
   20 returns, then STOP restores 0. If a nonrecording CC10 value 74 arrives,
   PAN becomes 10 and base becomes 10; a later motion event may sound 20 again,
   but STOP restores 10. The CC mapping is absolute, not a relative CC mode.
2. With no active motion bit on REV, MOMENTARY caches 23 and turns to 30.
   A project snapshot uses 30 because the base accessor falls through to live
   `p[]`. If motion is active on REV with base 23, the same snapshot uses 23.
   A subsequent nonrecording CC can update base; MOMENTARY release still
   writes its cached value. This source-derived counterexample disproves an
   unconditional claim that temporary knob edits never affect saved values;
   it is a policy question, not an established user-facing defect.
3. With MODW=127, two independent MODW-to-PAN slots at amounts +16 and
   -16 produce offsets +31 and -32 under the current signed shifts. PAN base
   50 therefore renders 49 after summing. Clamping after each slot could yield
   31 for one order and 49 for the other. AMP/DEPTH multiplication and unrelated
   RNG histories must not be assigned this permutation invariant.

The +31 and duplicate-slot behavior is anchored in
[existing math tests](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/mod_test.c#L271-L334);
PAN is exactly -64..63 in [TP](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/params.c#L125);
CC PAN endpoints and center are already checked in
[CC tests](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/midi_control_test.c#L778-L846).

## Loads, binding identity and safe rebasing

Sound loading already has an ownership seam. For a sound load, `load_begin`
restores/removes affected MOMENTARY pointers (including global FX pointers),
restores motion before the undo snapshot, then pauses motion. `sound_install`
publishes engine request, preset, sound values and an optional FM6 patch in one
interrupt-state-preserving window. `load_end` filters incompatible motion,
reenables retained records where appropriate, then rebases. Project runtime
restore first calls `mom_back(0)`, stops and replaces the project under its
larger IRQ-off window, installs every track through `sound_install`, and resets
motion active/base validity. Preserve those owners and the `param_kept` policy;
do not restore an old transient array after the new sound has been published.
Sources: [load lifecycle](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui.c#L1040-L1128),
[sound install](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/sound.c#L3-L33),
[publication](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/sound.c#L107-L148),
[project restore](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/project.c#L1047-L1097).

Bulk editing is not automatically a sound transaction. A sequence of SET/31
commands exposes intermediate values and capture behavior; `load_extend`
extends recent audition undo bookkeeping, not an atomic multi-command update.
Any future transaction should prepare/validate in main-loop scratch, reconcile
old temporary state before installation, publish one bounded coherent set,
then rebase against the published values. A base refresh that first restores
stale active motion after writing new values would violate that sequence.
This is a proposed requirement for a future bulk API, not a new implemented API.

| Binding | Current identity across engine changes | Preserve or decide |
| --- | --- | --- |
| Motion/locks on common ids | Retained on sound load; pattern remains | Preserve |
| Motion/locks on E1..E8, DIGITAL operator ids, DRUM lane levels | Same-engine load retains them; different requested engine ids remove them | Preserve; do not make automation follow a different instrument's E-slot |
| MIDI LEARN E-slot | Track + stable learned slot code `ML_E0 + k`, no engine id; learned CC shadows standard map from any heard channel | Preserve slot-following behavior; engine-specific learn would need an explicit new contract/migration |
| Standard CC74/71 | Resolves through current requested engine's brightness/resonance map; unsupported engines ignore it | Preserve semantic per-engine mapping |
| Matrix E1..E8 | Destination code resolves to that track's current engine descriptor | Slot-following binding; sound preset defaults/loading can replace the matrix configuration itself |

Sources: [motion filtering](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/motion.c#L371-L394),
[CC/learn mapping](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/midi_control.c#L209-L300),
[learn replacement](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/midi_learn.c#L15-L68),
[matrix destination lookup](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/mod.c#L55-L68).

No new engine, parameter, enum, motion-kind or wire id is required for this
proposal. Retain the final eight E slots, count-based old-format mapping,
128-record shared pool and append-only engine/destination identities. A changed
readback meaning or MOMENTARY persistence policy is still a compatibility change
even if no byte layout changes. Any protocol change belongs in Felucca, with a
linked WebApp consumer change and capability/version decision when needed;
portable engine DSP has no required change. See
[parameter/format mapping](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/core.h#L94-L156),
[motion layout](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/core.h#L272-L282)
and [extension contracts](extending.md#4-persistence-and-protocol).

## Proposed contract and decisions required

**Proposed compatibility contract v0:** name patch-base, control and render reads
explicitly; retain the current motion/lock lifecycle, one-record replacement,
CC/learn identities, block-sum-then-clamp and exact render restoration. Retain
existing command-specific readback and event execution order for the first
test-only batch. Do not promise activation-order independence for direct writes,
MOMENTARY overlays, RNG/time histories or gain multiplications. Establish
permutation invariance only for independent additive block terms with identical
source snapshots and destination descriptors. No scene/morph layer is proposed.

| Product decision | Choices and recommendation | Gate |
| --- | --- | --- |
| D1: MOMENTARY versus concurrent motion/CC/editor | Keep cached-control restoration, or make release reveal the then-current underlying control state. Recommend preserve first and capture both orders in characterization tests; choose a changed policy with an explicit audible example | Required before changing overlap behavior |
| D2: save/export while MOMENTARY held; KEEP under active motion | Preserve accessor-dependent behavior, exclude temporary edits consistently, or commit KEEP as permanent captured/base edits. Recommend explicitly choose whether KEEP is a base commit and whether it records while armed; KEEP currently only drops cache | Required before new persistence/capture assertions |
| D3: display and editor live/base reads | Retain current command split, or expose separately named base/effective reads with capability negotiation. Recommend document existing split first; no silent GET/WATCH or DUMP change | Required before protocol/UI semantics change |
| D4: TRACK_MIX and edit publication | Preserve direct mix semantics, or align level capture with SET/31; separately decide whether an ordinary main-loop write+capture must be atomic against an audio step | Required before a shared write helper changes call sites or guards |
| D5: stricter “simultaneous” precedence | Keep execution order, or introduce timestamp/source arbitration. Recommend keep current order; timestamp arbitration requires a separate bounded queue/ownership design | No new precedence chosen here |

The minimal possible later seam is a caller-explicit permanent parameter edit
helper near `ui_knob.c`/`motion_capture`, with provenance (recordable edit,
direct mix, temporary edit) rather than hidden policy. Use it only after D4;
MOMENTARY lifetime stays with `mom_*`, sound publication stays with
`sound_install`, and block rendering stays with `mod_begin/end`. A read helper
can make base/control intent explicit without introducing an effective-value
array. No helper implementation is part of this research.

## Coverage audit and meaningful gaps

These are inspected assertions, not newly obtained pass results. Search covered
control symbols throughout `tests/*.c` and followed the runner's affected units.
Include-based harnesses already compile real sources; lack of a separate
`momentary_test.c` or `ui_knob_test.c` is not missing coverage.

| Existing evidence | Already covered; retain as oracle | Meaningful remaining coverage |
| --- | --- | --- |
| [motion_test.c:7-57](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/motion_test.c#L7-L57), [loads:180-203](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/motion_test.c#L180-L203) | Selected armed capture, overwrite/capacity, sounding/base split, project base+events, stop/bypass, manual rebase, same/different-engine filtering, undo/song | Add matrix rendering and real CC/editor readbacks to the same lifecycle, rather than duplicate basic base tests |
| [lock_playback:451-527](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/motion_test.c#L451-L527), lock editing/project/UI/undo later in file | Prior automation/base restore, chance, swing, ratchets, project snapshot under sounding lock, engine parameter before note-on | Combined lock + matrix + permanent/temporary edit and command-specific readback |
| [mod_test.c:157-355](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/mod_test.c#L157-L355) | Off bit identity, source/destination math, duplicate sum/clamp/restore, engine ranges, RNG independence; MIDI and cost cases later | Adversarial mixed-sign additive permutations and activation/clear transitions on motion-owned values |
| [ui_test.c:6261-6387](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/ui_test.c#L6261-L6387), [knob policy:10532-10743](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/ui_test.c#L10532-L10743) | MOMENTARY release/KEEP/no-record, sound load/undo, full cache, actions/layers; target/capture/LEARN parity and acceleration once across views | Concurrent motion/CC/editor source ownership during a held edit and project/user-preset readback; current status tests are not these combinations |
| [ui acceleration:8817-8925](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/ui_test.c#L8817-L8925), [input_test.c:707-800](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/input_test.c#L707-L800) | Threshold examples, 20,000 fixed-seed random reads, actual UI paths, reversals, physical decoder phase/speed/bounce cases | Exhaustive finite arithmetic domains and 24-bit timestamp rollover; do not claim acceleration has no existing property coverage |
| [sound14_test.c:232-276](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/sound14_test.c#L232-L276), [fun10_test.c:3-20](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/fun10_test.c#L3-L20), [v156_test.c:3-7](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/v156_test.c#L3-L7), [fm6bank_test.c:393-455](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/fm6bank_test.c#L393-L455) | DEPTH composition, LFO UNI/SYNC and old motion formats, VEL/TIME/RNG preservation, concrete FM6 enum empty-slot stepping | Extend finite domains and combined controls; these features already have dedicated assertions and must not be reclassified as wholly untested |
| [midi_control_test.c:778-1000](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/midi_control_test.c#L778-L1000) | Standard CC ranges/routing/capture, learned-map shadowing/replacement/capacity and settings persistence | All 128 CC values for representative ranges; CC/step timing boundary and learned E-slot versus motion engine filtering |
| [editor_test.c:114-166](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/editor_test.c#L114-L166), [sync:749-808](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/editor_test.c#L749-L808) | Motion protocol/kinds/capacity, WATCH preservation and own-load no echo | Real rendered motion plus GET versus DUMP versus WATCH and TRACK_MIX capture distinction |
| [sound_install_test.c:1-15](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/sound_install_test.c#L1-L15), [dualcore_test.c:3-14](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/dualcore_test.c#L3-L14), [runner inventory](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/tests/run_tests.sh#L7-L60) | Coherent whole-sound publication at interrupt edges, mixed matrix/engine serial-worker equivalence, audio and arena switch oracles, preempting drum fuzz | Extend exact combined-control boundary fixtures if a new write seam is implemented; existing broad fuzz is complementary to deterministic expectations |

## Bounded combined-control regression matrix

Implement two related test-only commits after contract review: combined lifecycle
fixtures, then finite-domain properties. Prefer extending the existing harnesses;
if fixture ownership becomes awkward, create one host-only combined-control unit
using their actual included sources and add it to the runner. Do not copy the
production algorithm into a second implementation as the oracle. Every row below
has an observable result and an explicit counterexample it should detect.

| ID and setup | Observable invariant / concrete failure detected | Scope and gate |
| --- | --- | --- |
| C1: motion PAN plus deterministic LFO or MODW slot, manual edit or standard/learned CC, then STOP/bypass | Observe render-time value, post-block `p[]`, base snapshot and stop value separately. An offset retained in `p[]`, saved motion value, or lost newly edited base fails | 2 sources x 3 writers x 2 endings = 12 traces; unarmed first, one armed quantized counterpart |
| C2: prior automation + later lock + same matrix; next step, chance-failed step, loop wrap and ratchet | Lock heard only for its eligible step; next step restores prior automation/base before modulation. Detect stale lock, extra offset or note-on seeing post-render offset | Four deterministic traces extending existing lock fixtures |
| C3: two to four independent additive slots to PAN/REV, fixed source snapshot; reverse slot assignment/activation order, clear each | Same final render value for same active additive terms; disabling one removes only its contribution and post-block `p[]` is unchanged. Mixed-sign near-bound fixture detects per-slot clamp/order dependence | 2 destinations x slot counts 2..4 x at most 24 permutations; fixed seeds/time, no AMP/DEPTH permutation promise |
| C4: held MOMENTARY, CC/editor/motion before and after first turn, release and KEEP, snapshot while held | Characterize separate live/base/cache values and both orders. Detect an accidental claim that release reveals latest underlying state or KEEP always updates motion base | 3 writers x 2 orders x 2 endings = 12 traces; freeze changed expected policy only after D1/D2 |
| C5: sounding motion + held MOMENTARY + sound/user preset/engine/project load; release after load | New sound values remain after release; unrelated track's cache remains on a single-track load, project clears all; common motion retained and incompatible engine ids removed according to load type | Four load routes plus one same-engine counterpart; assert undo base too. Detect stale pointer/value restoration over a new sound |
| C6: while motion sounds, actual GET/31, DUMP/29, WATCH and TRACK_MIX; project and user-preset capture | Live commands and base snapshots have the documented distinct values; no matrix transient leaks; direct TRACK_MIX versus normal capture distinction remains visible | One selected and one nonselected track; D3/D4 gate any changed expectations. Decode reply bytes, not source text |
| C7: queued CC before a due step; same CC after step via next block; panel/editor boundary probes if edit publication changes | Scheduled trace establishes queue-before-sequencer behavior; ordered direct writes retain last executed value where no later source intervenes. Detect an undocumented fixed source priority or mixed new sound | Two boundary traces now; reuse sound-install edge-injection style for a later guarded edit, never demand all activation orders match |
| C8: learned E-slot, standard CC74/71 and engine-specific motion under same/different engine load | Learned mapping keeps its E-slot code, semantic CC re-resolves or ignores, incompatible motion removed. Detect treating all three bindings as engine-specific or all slot-following | Two representative engines with different descriptors and one unsupported CC target |

“Clear restores intended value” is source-specific: matrix clear restores control
value, lock expiry restores automation/base, motion bypass/STOP restores base,
MOMENTARY release restores its cached live value, and CC121 resets controllers
without resetting mapped sound parameters. Deleting an event, clearing locks,
disabling motion and stopping are separate transitions, not synonyms.

## Finite-domain property plan

Use existing real `param_turn`, CC dispatch, `accel` and gesture paths. Enumerate
current descriptors dynamically so newly selected engine profiles do not hide
out-of-range cases. Test empty/fixed/action targets separately. These are bounded
test domains, not claims about all integers or all real hardware timing.

| ID | Finite domain and independent invariant | Example failure detected |
| --- | --- | --- |
| P1: absolute CC | Every input 0..127 for representative ranges 0..127, -64..63, -24..24 and a fixed descriptor; then all available standard-map descriptors. Outputs in range, nondecreasing, exact endpoints, center PAN=0, repeated value idempotent | Wrong signed center, reversed range, endpoint lost, same CC spuriously records again. Do not impose odd symmetry on the asymmetric -64..63 domain or require learned enums to follow knob display order |
| P2: plain continuous turn | Every valid start for each distinct continuous descriptor range and every widened hardware delta -32768..32768 with acceleration OFF. Range, zero identity, direction monotonicity, exact detent magnitude away from bounds, saturation at bounds | Sign inversion, discarded multi-detent count, extra multiplication. For symmetric continuous ranges only, mirrored starts/turns mirror outputs; exclude aliases, asymmetric ranges and named step mappings |
| P3: acceleration arithmetic | Normalized state classes: no history, same/reverse sign, previous per-detent intervals 1..127; current elapsed 0..127 ms; signed deltas -8..8; ranges 0,32,33,64,65,127,200; preference OFF/ON. One translated copy across 24-bit rollover | Sign and zero preserved, output magnitude is input magnitude times integer 1..cap; OFF/narrow/list is identity; cold/reversal and first two sustained reads unaccelerated; slow read identity; translation modulo clock width unchanged. Detect squared detent count, double speed multiplier, divide-at-zero or rollover discontinuity |
| P4: caller integration | All four knobs on HOME/HOME LEVELS/MIXER/page/GLO/MOMENTARY with known short slow/fast/reverse traces, resetting timing state per run; unsaturated starts | Same eligible parameter gets the same accelerated delta once; nonselected armed track does not record; MOMENTARY does not capture/LEARN. Existing eight-detent=20 fixture is retained, add negative and multi-detent traces rather than duplicating it |
| P5: enums | Every valid enum start and every widened hardware delta -32768..32768; named division rank monotonically follows declared musical order, clamps at ends; aliases and empty FM6 bank slots skipped; ENV SYNC traverses its declared buckets | Treating stored enum numbers as display order, accelerating enum steps, landing on retired kit/empty slot. Enum rank is separate from numeric monotonicity |
| P6: actions/empty/fixed targets | Every relevant page class and knob, no turn/one turn/LFO-held turn, with before/after snapshots and action side-effect counters; distinguish page/MOMENTARY fixed targets from synthetic fixed HOME | Target resolution/status must not write, capture, pick LEARN or consume encoder timing. Page/MOMENTARY fixed turns are excluded; main5b HOME permanent turns still enter knob_edit. Synthetic fixed-HOME no-capture/no-LEARN is a future guard expectation conditional on #597 adoption, not a main5b pass. Actions retain their owner; MIXER MUTE keeps permanent direction versus numeric momentary distinction |

The HAL accumulates signed 16-bit detents and `panel_enc` multiplies by the
configured direction in int32; there is no -127..127 consumer clamp. P2 therefore
covers the complete widened return domain (65,537 integers, including the
orientation of -32768), deduplicating equal continuous ranges. P5 uses that same
complete delta domain for enum stepping. P3 has about four
million interval/delta/range/preference tuples before the few history classes
and rollover copies. Partition these host workloads, report case counts and
retain compact first-counterexample output; they add no ISR workload. Do not enumerate the entire clock or all possible action
histories. Source authorities: [HAL detent width/take](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/hal/fm1_input.h#L168-L179),
[oriented panel delta](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/panel.c#L58-L66),
[acceleration](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui_input.c#L465-L495),
[turn/enum mapping](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/params.c#L250-L320),
[CC scaling](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/midi_control.c#L225-L234),
[target/gesture policy](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui_knob.c#L10-L166).

## Resource and publication estimates

These are source-derived bounds/reservations for design comparison, **not** a
new link map, pi32v2 timing estimate, CPU percentage or live RAM measurement.
The source enum has `P_E0=103`, `P_COUNT=111`; `NTRK=4`, `MOTION_MAX=128`,
`NMSLOT=4`, `MOM_N=8`. Counts were checked directly from the inspected enum and
declarations. Structure estimates below assume the target's 32-bit pointer and
four-byte alignment ABI; a later target map is authoritative. No new compiled
sizeof probe or link map was executed; the 388 B store is independently enforced
by the existing source static assertion.

| Area | Existing source-derived amount/work | Proposed first batch delta / later design constraint |
| --- | --- | --- |
| Motion RAM | Base: 4 x 111 x 2 = 888 B. Active+locked: 2 x 4 x ceil(111/32) x 4 = 128 B. Store: 128 x 3-byte records + count/on/rsv[2] = 388 B (source static assertion); two byte flags separately, excluding inter-object padding | Tests/docs add 0 target bytes. Another full base/effective bank would add 888 B before masks/ownership; avoid without a measured need |
| Matrix RAM/scratch | `modw_t`: estimated 48 B; CPU2 build reserves four = 192 B, CPU2=0 one = 48 B. Local offset array 4 x int32 = 16 B, excluding other stack frame/compiler spills | Keep existing per-part worker state; do not replace with one shared mutable effective buffer |
| MOMENTARY POOL | Eight pointers + eight int16 values + three byte fields and alignment: estimated 56 B target | Preserve bounded eight-entry cache; adding an int16 underlying-base snapshot per entry would add 16 B before alignment, but does not alone solve policy/ownership |
| NOINIT and flash formats | Current control caches above are not new retained fields; motion disk layout stays 388 B | First batch: 0 added retained bytes and no flash/format writes. New retained state would need capacity/format review rather than borrowing apparently spare NOINIT |
| Block work | At most four slots: bounded first-active scan, DEPTH scan, slot evaluation and at most four unique keeps/restores; duplicate lookup at most 4 x 4 comparisons. No work proportional to notes/files or a new parameter bank per sample | Test-only batch: 0 runtime operations. A later scalar edit helper adds caller work only; emitted instructions, stack and IRQ-off duration are unknown until compiled/measured |
| Motion work | Step scan at most 128 events; restore scans 111 ids per track. Unlock scans 111 ids and up to 128 events per locked id: conservative 111 x 128 = 14,208 record examinations per affected track plus outer work | Existing worst-case source bound, not observed latency; measure dense lock workload if touching this path. Avoid new repeated full-bank work in render |
| Worker recovery | Existing CPU2 canonical snapshot: four parts x 15 int16 = 120 B RAM; no copy when runtime preference OFF | If render-temporary destinations grow, update snapshot/recovery set and CPU2 failure fixtures together |
| Publication | Main-loop sound/motion batches use saved/restored IRQ state; event record payload before count via `RING_PUBLISH`; learned-map two-byte writes guarded; events serialized before worker split | First batch adds no publication objects. A future value+base edit needs a bounded guard or existing-owner request; neither `volatile` nor a compiler barrier makes a multi-field snapshot or cross-core handoff atomic |

Sources: [motion declarations](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/motion.c#L10-L15),
[core counts/layout](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/core.h#L94-L123),
[matrix workspace](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/mod.c#L70-L89),
[momentary POOL](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/ui.c#L1053-L1083),
[worker snapshot/fallback](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/fx.c#L1259-L1280),
[serialization before split and wait](https://github.com/kmplngj/Felucca/blob/5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e/firmware/src/fx.c#L1328-L1368),
[ownership guidance](extending.md#33-queues-publication-and-shared-state),
[linker regions](../firmware/app.ld).

Any firmware follow-up must remain allocation-free and introduce no I/O or new
waiting in interrupts. Keep the existing worker join protocol and main-loop
sound/load owners. Reserve no new global engine id. Unknowns needing a concrete
candidate are code bytes, compiler inlining/spills, final RAM/POOL padding, IRQ-off
duration, dense-lock deadlines and mixed USB/TRS/panel response. Follow
[performance.md](performance.md) with an unchanged baseline and one cause at a
time, both compiled CPU2 variants where applicable; never sum unrelated estimates.

## Validation, handoff and completion mapping

For this research: verify every local path, immutable line anchor and enum count;
run whitespace/link checks on the single Markdown diff. Firmware build, host
suite, target disassembly/budget, browser gate and hardware tests were not run:
this report changes no executable input and establishes no new measured claim.
Ignored build artifacts are not validation evidence for this document.

For a later test implementation: rebuild the affected real-source harnesses,
run focused combined/property cases first, preserve audio goldens and existing
rounding/RNG consumption and engine-switch/arena expectations. Finish the
applicable suite at the exact candidate revision; report unavailable counters,
sanitizers or optional references explicitly. A failed golden or target budget
requires investigation, not `GOLDEN_UPDATE=1` or `BUDGET_UPDATE=1`. Target static
budgets and host instruction counts remain separate from runtime FM-1 deadlines.
Browser replay supplements actual UI/editor paths only where relevant; it does
not qualify real USB/TRS transport or physical controls.

No hardware test or flash is needed to review this documentation-only change.
For any later behavior change, hardware acceptance remains pending: use one
combined handoff after backing up, covering LFO/matrix + motion/locks + manual/CC
overlap, MOMENTARY release/KEEP/load, real USB and TRS, engine switching, audible
transitions and loaded render/scan timing with CPU2 OFF and any supported ON
variant. Prepare full panel routes with the [PR testing skill](../.agents/skills/pr-testing/SKILL.md)
when that candidate exists. This report authorizes no device access, install,
merge, release or deployment.

README assessment: its current “ongoing integration and experimentation” and
development validation descriptions already cover this research stage; no new
engine, control behavior, installation or compatibility capability is delivered.
No README change is needed for this note. Changelog assessment: no entry; the
changelog explicitly keeps plans/unmerged experiments outside implemented work.
Detailed protocol/feature guides should change with any approved behavior change,
especially D1–D4, rather than present this proposal as shipped behavior.

| Issue criterion | Report evidence / remaining gate |
| --- | --- |
| #29 current behavior and proposed contract, combined examples | Value/read/write tables, concrete examples and compatibility contract v0; D1–D5 explicitly undecided |
| #29 compatibility and binding identities | Loads/bindings section; no new IDs/formats, command-specific compatibility and client ownership |
| #29 regression matrix and bounded seam | C1–C8 and P1–P6; tests first, helper only after policy decisions |
| #29 CPU/RAM/POOL/NOINIT/publication estimates | Source-count table and explicit unknowns; no runtime performance claim |
| #29 product decisions and baseline preservation | D1–D5; no baseline regeneration or implementation |
| #30 existing coverage and gaps | Named existing assertions and uncovered combinations; no duplicate basic motion/MOMENTARY/acceleration claims |
| #30 observable invariants and counterexamples | Every C/P row states result and failure class; changed-policy expectations gated |
| #30 bounded combined/property plan | Fixed lifecycle matrix, finite domains and restricted additive permutation invariant |
| #30 sound/rounding/RNG/engine switch expectations | Preserve existing oracles and fixed source histories; no general gain/RNG order-independence claim |
| #30 separate host/target/device evidence | Validation section; all execution and hardware acceptance remain future work |
