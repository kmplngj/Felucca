<!-- SPDX-License-Identifier: GPL-3.0-only -->
# PERF-1 v0.16.0 adoption review — 2026-11-01

Selectively adapt the sounds and performance ideas to Felucca's four parts and
shared voices. Preserve its existing clock, note ownership, engines, storage and
client contracts. The donor's five-layer application is not a drop-in mode.

The [release](https://github.com/deamonSLINKY/PERF-1/releases/tag/v0.16.0)
resolves to `22c295d6a098fc837f285c641aba4a4acb8c0077`. Native comparison:
`f0fea3c5fce7a0134f84543e09b64001c2991b33`. The earlier intake in
[#808](https://github.com/kmplngj/Felucca/issues/808) used donor
`79fdf21608c77f4987423303f5a9c72397af8e55` and native
`c543e246e7c51b89d4ffe84a05e7c4afaf4dc465`; retain those dated decisions.
The complete donor graph is non-shallow, passes `git fsck --no-dangling`, and
contains 321 reachable commits at the release, versus 294 at the earlier pin.
These snapshot reviews grant zero individual commit assessments.

## Delivery plan

1. Qualify audio DMA acknowledgement through existing
   [#186](https://github.com/kmplngj/Felucca/issues/186). Preserve its pending-bit,
   half-ownership and hardware gates before changing scheduling.
2. Measure [#825](https://github.com/kmplngj/Felucca/issues/825), the isolated exact
   FM6 interpolation experiment. Continue existing
   [#806](https://github.com/kmplngj/Felucca/issues/806) same-block reverb overlap
   only when current hotspot evidence supports the extra handoff. Measure one
   cause per experiment; neither has an established native speedup.
3. Run [#805](https://github.com/kmplngj/Felucca/issues/805) instrument auditions
   in parallel: four to six dry, level-matched native/donor candidates, followed
   by separate effect-enabled examples. Select presets before new engines.
4. Prototype [#826](https://github.com/kmplngj/Felucca/issues/826) selected-part
   performance throws using the existing per-part throw path and shared buses.
   Begin volatile/default-off and retain legacy ALL behavior exactly.
5. Design progressions through [#658](https://github.com/kmplngj/Felucca/issues/658)
   and the existing Generative/provider contracts, then explicit controller
   profiles. Setlist and broader Auto-DJ behavior follow a native workflow and
   capacity decision; they are not prerequisites for using the sounds.

## Release feature decisions

| Donor feature | Native fit and owner |
| --- | --- |
| Eight-slot progressions: degrees, Hold, 1/2/4/8 bars, Walk/Loop | #658 already owns progression sections. Define affected parts, non-seven-note scales, Hold/rest, external-clock boundaries, edits, reset and held-note tails first. Start volatile through #208/#214; do not copy the donor six-byte project tail. |
| Targeted FILTER/DELAY/PHASE | #826 starts smaller, targeting existing throws. #440 owns key banks and #441 chain/send topology. Donor simultaneous effects union their masks; independent per-effect routing is not a proven donor feature. Shared-bus input selection also cannot isolate audio already in a return. |
| Multimode pad/bass/acid filters | Expand #805 to compare notch/peak and driven topology. Native ANALOG already has LP/BP/HP; donor LP/HP use two stages and other outputs one. This is a sound variation, not an exact CPU optimization. |
| Velocity, pitch bend and mod wheel | Already native capabilities. Audition expressive response through native per-track ownership; do not import one global selected-voice controller. |
| Sixteen-piece setlist | #207/#169 source reference. Native song sections already exist. First decide within-project section ordering versus whole-project loading, then preparation/cancel/failure, bar publication, note tails and capacity under #213. Donor genre/piece identifiers are not native project IDs. |
| MPC/M:S/MPK input; GM/M:S/MPC/SP-404 output | Explicit profiles over native routing/Learn. #34 owns relative encodings; #166 supplies a MiniLab-specific precedent without becoming a generic MPK issue. Distinguish incoming performance controls from outgoing sampler maps. Donor relative value 64 means -64; choose native neutral/reserved policy explicitly and test all 128 values. |
| Chord-bright, scale-dim LEDs | Native actual-note/scale feedback already substantially covers it. A global harmony pitch-class overlay is a later #658 UI decision; #147 and active PR #821 own brief-event visibility. |
| Slow-turn encoder correction | Native fm1_input.h already uses one learned rest state and approximately one-second relearning. Do not port donor numeric scan thresholds or file a duplicate defect. |
| Content-driven TRS DMA drain | Existing #526 uses event-gated, width-correct native count reads. Donor missed-count anecdote is not proof of a defect in this baseline. Reproduce with the native HAL before considering sentinel handling, wrap/lapping and concurrent DMA-clear risks. |
| Experimental USB host | Existing #289 feasibility owner. Donor reports no working hardware confirmation; require board/VBUS, powered-hub, descriptor/error/hotplug, note release and host/device recovery evidence. No simultaneous computer-facing device/audio role is established. |
| Industrial and genre-specific arrangements | Optional generator/content recipes under #208/#214. Preserve native startup behavior; no wholesale seventeen-genre application or five-track storage model. |

## MIDI device follow-up

[#828](https://github.com/kmplngj/Felucca/issues/828) now owns concrete opt-in
device profiles and sampler output maps. Start with an exact model/program and
transport matrix, then MPK mini keys/pads/knobs (MK4 relative versus older absolute
CCs), MPC/M:S native performance controls, and independent M:S/MPC/SP-404 drum
output maps. Generic notes, velocity, bend and wheel already work through native
services; device-specific mappings and physical qualification are the new work.
Only bind performance actions that actually exist natively; donor Auto-DJ commands
remain deferred. Preserve Learn precedence and press-time note releases.

#526 now includes a bounded comparison of PERF-1's content-driven TRS drain with
the current native event-gated count reader. Reproduce isolated pad attacks and
releases without a following aftertouch/event, then stress running status, clock,
wraps and full-rate traffic with USB audio and CPU2 OFF/ON. A synthetic missed-count
fixture is a hypothesis, not silicon evidence. Adapt the sentinel approach only
after demonstrating an additional native failure and proving DMA/clear/overrun
ownership. Retaining the current receiver after a documented no-repro is valid.

TRS is currently an input path. Outbound sampler maps use USB through a host or
router; direct USB peripherals remain the separate #289 experiment. Donor M:S mode
and M:S/SP-404 maps still need physical confirmation. This follow-up changes plans
and issue acceptance only, with no firmware or tested compatibility claim.

## Instruments and provenance

Candidate set: Rhodes/glass breathing pad, driven Reese/Hoover bass, CZ/fold acid,
and Super/Hyper/Lead; optionally compare one percussion recipe against native DRUM.
Separate timbre from breath/stab scheduling, harmony and master effects. Use equal
notes, several registers/velocities, dry level matching and separate effects examples.
Classify each candidate as existing sound, new preset/modulation recipe, missing DSP
or reject. Do not add a second reduced FM6 engine or reserve IDs just for audition.

Donor pad/acid local targets initialize at render-call entry while control counters
persist. Preserve #805's render-partition/control-state investigation before any
extraction; this is a donor concern, not a reproduced native bug.

Copied GPL-derived portable DSP/content belongs in Felucca-Engines-GPL after the
actual file, transitive-helper, generator and asset closure is established. A
fixed-point rewrite does not change GPL provenance to MIT. Keep selection and
cross-repository coordination in #805, create collection work only for selected
missing DSP, land reviewed collection commits first, then consume an exact pin
through #360. Firmware owns global IDs/keys, profiles, arena/voices/fades/services,
protocol/storage/native controls and qualification. No client work is justified
before its producer contract exists.

Preserve individual Melodee/Dexed/MSFA notices. Native fm6_core.c has Apache-2.0
provenance; do not paste GPL donor code and retain an Apache-only characterization.
DY/archive bank claims and optional first-118-byte ROM comparisons do not establish
original-author rights. Keep those banks out until cleared; native authored patches
are the audition control. Audit code and data separately instead of assuming a
filename or root license clears every asset. Fonts, artwork and SDK packaging are
outside this instrument experiment.

## Optimization assessment

The donor cleanup `c4e2cd451eb111b6487b8f37023d7b731d38703a` hoists routing
pointers/echo gains, tests low-pass first and avoids pumping an unused target bus.
Native already gates drained buses and computes many coefficients per block.
Reuse #185/#458 mixer work; donor project-state removal accounts for its reported
5.5 KB RAM reduction and cannot be claimed as a native DSP saving.

#825 asks whether the native uint64 EXP2 interpolation can use two bounded 7-bit
products with exactly the same 14-bit rounding. It retains native Q30 tables and
frequency scaling, proves unsigned bounds, exhausts every interval/fraction, and
first checks whether JieLi Clang already lowers the original efficiently. The donor
arithmetic predates this release; it is a newly scoped experiment, not a new release
algorithm. #499 frequency caching, #498 AMS reuse, #93/#128 table representations
and #366/active PR #820 feedback specialization remain independent causes.

Keep #806's same-block native scheduling experiment separate from donor delayed
pad/FM rings and plate predelay. Do not adopt donor event coalescing that changes
timing, a slower control cadence, float migration, voice shedding or added latency
as a transparent optimization. Native already renders four CTL=32 blocks per half.

Every retained implementation needs an unchanged baseline with exact dependency,
compiler/SDK/profile/flag/asset identity; one-cause A/B; PCM and future-state equality
where promised; target output and app/RAM/POOL/RAMTEXT/NOINIT/arena/reserved/stack
used/spare; and whole-half/join/deadline evidence including nested TIMER5. Cover
CPU2 compiled-out and runtime OFF/ON/failure, profile omission, tails and switches.
Rebuilt focused checks precede full applicable frozen-candidate validation and a
fresh warning-free target build. Separate host/static/browser evidence from real
FM-1 listening, controls and loaded USB-audio/USB/TRS-MIDI timing. No gain or fit is
established by this review; a measured no-win is a valid outcome.

## Watcher and validation

PERF-1 is absent from both current main and the fetched canonical state registry.
This PR adds one pending main registration for canonical `deamonSLINKY/PERF-1`,
repository ID `1433400155`, retaining #808's original 294-commit historical pin
`79fdf21608c77f4987423303f5a9c72397af8e55`. All existing entries remain intact.
After review/merge and guarded state-registry reconciliation, the existing runner
must reverify identity/main/pin and the complete graph before initialization and
discovery of the newer release tip. Pending registration is not active tracking.
No schedule, canonical state, journal, frontier or review credit changes here.

Four-repository open/closed issue, issue-comment and PR inventories were fully
paginated; relevant owners and current states were checked before writes.
The fetched canonical ledger copy validates: 434 records, 427 terminal pairs,
37 sources. Registry/helper checks cover this documentation/registration change;
no donor scripts, firmware builds, audio benchmarks or device operations ran.

README assessment: the overview already describes selective integration; no new
implemented feature is claimed. Changelog assessment: planning/registration only,
with no behavior or measured optimization to announce. Diagnostic-guide assessment:
no changed flags, counters, protocols or transports.

## Pinned source map

- Donor [DSP and generators](https://github.com/deamonSLINKY/PERF-1/blob/22c295d6a098fc837f285c641aba4a4acb8c0077/firmware/src/dsp/amb.c): filter dispatch 1409, progression 1872, target masks 4488, pad 6099, bass 6275, acid 6528, routing 7086.
- Donor [UI/controller/setlist](https://github.com/deamonSLINKY/PERF-1/blob/22c295d6a098fc837f285c641aba4a4acb8c0077/firmware/src/app/ui.c), [FM6 arithmetic](https://github.com/deamonSLINKY/PERF-1/blob/22c295d6a098fc837f285c641aba4a4acb8c0077/firmware/src/dsp/fm6_core.inc), [licensing](https://github.com/deamonSLINKY/PERF-1/blob/22c295d6a098fc837f285c641aba4a4acb8c0077/LICENSING.md).
- Native [perform.c](https://github.com/kmplngj/Felucca/blob/f0fea3c5fce7a0134f84543e09b64001c2991b33/firmware/src/perform.c), [fx.c](https://github.com/kmplngj/Felucca/blob/f0fea3c5fce7a0134f84543e09b64001c2991b33/firmware/src/fx.c), [FM6](https://github.com/kmplngj/Felucca/blob/f0fea3c5fce7a0134f84543e09b64001c2991b33/firmware/src/fm6_core.c), [CHORD](https://github.com/kmplngj/Felucca/blob/f0fea3c5fce7a0134f84543e09b64001c2991b33/firmware/src/chord.c), [song sections](https://github.com/kmplngj/Felucca/blob/f0fea3c5fce7a0134f84543e09b64001c2991b33/firmware/src/song_chain.c).
