<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Clipper adoption review — 2026-10-19

Use Clipper as a source of optional instruments, Instrument-workflow ideas and
bounded resource/quality experiments. It fits our modular integration fork and
the existing Instrument mode plan. Adopt individual designs through native
contracts; retain four interchangeable parts, sequencer, storage and hardware policy.

Tracking plan: [Felucca #481](https://github.com/kmplngj/Felucca/issues/481).
This is source research and planning, not implemented firmware or measured gains.

## Evidence and revisions

| Source | Immutable revision inspected |
| --- | --- |
| Clipper main | `7008d31e78da5d4e5e0a1f25a994ba7b2266c702` |
| Felucca main | `a3bedd48578110d279e2af903efd0f5e8aca0661` |
| MIT Engines, firmware pin | `9630426f5c4a34a209ca851356fbe8ba3c4c6d19` |
| MIT Engines, main at intake | `53ad1f5c9afb593f29305d79779bfd30aacc14cd` |
| GPL Engines main at intake | `cb2a3b372ee3f813f621aad737506837a18bbd3c` |
| WebApp main at intake | `74e961439a76dd9da777264d068122e1d0fc2460` |

The complete non-shallow Clipper main DAG has **49 reachable commits** and passed
Git connectivity checking. This snapshot grants **zero per-commit assessments**.
Open/closed issues, all issue comments and PRs were paginated across all four native
repositories before intake; relevant merged work and source were checked. WebApp
Issues is disabled; future concrete client tickets follow the explicit firmware
fallback described in [AGENTS.md](../AGENTS.md).

Clipper advertises 23 engines and 407 sounds. Its 1.0 status is experimental:
the donor explicitly leaves new features, target resource use and substantial
FM-1 qualification pending. No donor scripts, tests or binaries were executed for
this review; no firmware build, flash or device benchmark was performed.

## Integration reconciliation — 2026-10-23

This dated source review is retained with its original donor/native pins and
intake evidence. The combined planning handoff reconciles it with Felucca main
`f8ed365d845af789ce7237e3bd531f6d0c67fff9`; it does not repeat the donor audit or
credit any commit assessments. Main now includes [#479 via PR #509](https://github.com/kmplngj/Felucca/pull/509)
and the first profile-contract/build-report stage of #465. Reuse those results;
remaining instrument/profile experiments still need their own acceptance gates.
The other plans in this handoff are [FM1 Open V14](fm1-open-adoption-2026-10-21.md)
and [Araminta v2.8](araminta-v2.8-review-2026-10-21.md).

## First implementation batches

| Order | Work and owner | Exit gate |
| --- | --- | --- |
| 1 | [#478](https://github.com/kmplngj/Felucca/issues/478): optional synth-only profile with unused factory-sample consumers/assets pruned | Trace actual native dependencies; target symbols and linked bytes prove removal; standard content and restore remain intact |
| Existing validation | [#479](https://github.com/kmplngj/Felucca/issues/479), delivered by [PR #509](https://github.com/kmplngj/Felucca/pull/509): cross-feature audio-transition checks | Reuse `tests/audio_transition_test.py` and extend only for a concrete new transition; existing checks include injected discontinuity controls |
| Separate A/B | Existing [#17](https://github.com/kmplngj/Felucca/issues/17): half-rate delay | Deliberate bandwidth tradeoff, native impulse/spectral/tail evidence and real memory/timing result |
| Separate A/B | Existing [#234](https://github.com/kmplngj/Felucca/issues/234): exact ANALOG waveform dispatch outside the sample loop | Preserve native equations/state and inspect actual target loop dispatch before deciding |
| 2 | [GPL Engines #24](https://github.com/kmplngj/Felucca-Engines-GPL/issues/24): portable VPS pilot, then TERRAIN | Source/license closure, eight-control contract, standalone sound/state/extreme tests and measured cost |
| 3 | [#480](https://github.com/kmplngj/Felucca/issues/480): native instrument integration/qualification | [#360](https://github.com/kmplngj/Felucca/issues/360) GPL collection support, exact pin, stable ID/profile, arena/services/UI/MOD and FM-1 checks |
| Later | VECTOR/WSEQ/STRINGS/MACRO-lite, then HYBRID/FMX | Retain/reject each audition; deep patches require explicit producer, storage and editor design |

These are proposed work batches, not authorization to implement the firmware in
this review. Optimizations compare unchanged/candidate revisions one cause at a
time. Sample pruning and half-rate delay deliberately trade installed capability
or sound for space; neither is equivalent-output CPU optimization. Do not sum
independent source estimates into a fit claim.

## Instrument selection

| Candidate | Why it is useful | Native boundary and priority |
| --- | --- | --- |
| VPS | Phase inflection/formant motion without an exclusive table pack | First pilot; explicit phase/filter/DC state, alias/endpoint checks; donor “alias-free” wording is not proof |
| TERRAIN | Orbit over original generated surfaces | Second pilot; eight 32×32 int16 tables = **16,384 raw B**, before code and descriptors; test high-pitch/extreme shaping |
| VECTOR | Four original wave corners and animated X/Y paths | Later; 16×(512+128+32)×2 = **21,504 raw B** of wave samples, before code/metadata; host MOD targets and filter choice |
| WSEQ | Tempo-synced wave/pitch/level steps with crossfades | Later; extract actual FMX wave/helper dependencies without requiring an unused full FMX engine; bounded tempo service |
| STRINGS | Divide-down registers and three-line ensemble | Later; qualify ensemble state and stereo host/effect contract |
| MACRO-lite | Four original CHORD/SWARM/ADDITIVE/SPEECH models | Compare against current catalog; distinct from full Braids [#27](https://github.com/kmplngj/Felucca/issues/27) |
| HYBRID | Three oscillators, two filters, per-voice modulators and 16-slot patch matrix | Deep experiment: separate **128-byte patch** plus voice/part state, controls and generation-safe publication |
| FMX | Arbitrary six-operator PM/FM/RING routing and non-sine waves | Deep experiment: separate **128-byte patch**, own envelope/termination contract; native FM6 stays unchanged |
| WAVE | Spectral storage and main-loop IFFT construction | Compare with existing DUELL WAVE/WAVE S owners before selecting a third design |
| JUNO / ACID | Alternative lightweight implementations and original patches | Reuse GPL Engines [#2](https://github.com/kmplngj/Felucca-Engines-GPL/issues/2)/[#7](https://github.com/kmplngj/Felucca-Engines-GPL/issues/7), host [#464](https://github.com/kmplngj/Felucca/issues/464)/[#468](https://github.com/kmplngj/Felucca/issues/468), stereo chorus [#474](https://github.com/kmplngj/Felucca/issues/474) |
| Existing engine families / generated sample sources | Selected presets and VOX/GLASS/PAD/AIR may enrich content | Audition provenance and musical value; no duplicate native engine or replacement under an existing source ID |

Collection code, engine-exclusive generators/assets and tests belong in GPL Engines
when copied from Clipper's GPL sources. Firmware owns global IDs, exact dependency
pins, profiles, UI/MOD, voice/arena/services, persistence/protocol, emulator and FM-1
qualification. Collection work lands before a firmware pin update. Client work
belongs in Felucca-WebApp after its firmware producer contract is chosen.

## Fit with existing feature plans

| Clipper feature | Existing path / remaining decision |
| --- | --- |
| Instrument, LAYER/SPLIT/MULTI | [#203–#205](modularity.md); one usage workflow over the same native catalog/core; no deletion of native parts |
| ENV2/LFO2 and larger matrix | [#356](https://github.com/kmplngj/Felucca/issues/356); LFO3, 12 slots and looping envelopes are later explicit capacity/addressing decisions |
| Four macros, morph and compare | [#33](https://github.com/kmplngj/Felucca/issues/33)/[#32](https://github.com/kmplngj/Felucca/issues/32); sound undo/compare needs its own capacity design, distinct from pattern undo #60 |
| Alternate tuning / Scala | [#70](https://github.com/kmplngj/Felucca/issues/70)/[#69](https://github.com/kmplngj/Felucca/issues/69); user import needs a chosen producer/client/storage contract after tuning semantics |
| MPE | [#269](https://github.com/kmplngj/Felucca/issues/269); native per-note note-off/bend/pressure ownership |
| Turing, SPICE/DICE, MOD SEQ | [#214](https://github.com/kmplngj/Felucca/issues/214)/[#208](https://github.com/kmplngj/Felucca/issues/208)/[#447](https://github.com/kmplngj/Felucca/issues/447); select bounded deterministic providers separately |
| PING/TAPE | [#73](https://github.com/kmplngj/Felucca/issues/73); keep default delay/tails and native IDs |
| Plate/shimmer, filters, voice spread | Evaluate selected algorithms later alongside [#187](https://github.com/kmplngj/Felucca/issues/187)/[#474](https://github.com/kmplngj/Felucca/issues/474)/[#271](https://github.com/kmplngj/Felucca/issues/271); related controls are not interchangeable implementations |
| Deep editor pages and patch storage | [#317](https://github.com/kmplngj/Felucca/issues/317) DEEP, [#316](https://github.com/kmplngj/Felucca/issues/316) PRX, [#318](https://github.com/kmplngj/Felucca/issues/318) FVL, then focused WebApp delivery |

Clipper complements the Optimist builder/profile plan: the existing resolver and
initial [profile contracts/build reports](build-profiles.md#machine-readable-build-evidence)
already implement the first stage of [#465](https://github.com/kmplngj/Felucca/issues/465).
Further budget estimation/builder work can expose qualified instruments. The first
builder does not need these new engines first.
Instrument mode likewise does not require shipping Clipper's entire catalog.

## Resource findings and limits

- Clipper's half-rate delay has 32,768 int16 entries versus native 65,536:
  **65,536 raw B less**, retaining about 1.49 s through a sound-quality tradeoff.
  New implementation/impulse references were added to existing #17. Native linked
  deltas, CPU cost and FM-1 behavior still need measuring.
- Clipper HYBRID dispatches oscillator types outside sample loops. That is supporting
  evidence for #234's control-flow experiment; copying its equations changes sound
  and licensing. Implement the idea with the existing MIT ANALOG code in Engines
  if it wins; do not relabel Clipper GPL code MIT.
- Removing sample content creates synthesis space, but Clipper's historical roughly
  300 KB claim does not apply to our newer generated catalog. #478 must inspect
  actual generators/providers/defaults and retained consumers, including DRUM and
  backup services. It must not erase user slots or change standard sounds.
- WAVE allocates **65,024 raw B** of mip data and **8,192 B** of IFFT scratch.
  It has one shared resident table: two donor sounds may use the first part's table.
  Four independent native parts need deliberate table/service/ownership design.
  IFFT construction is an option for later WAVE owners, not a speedup to a currently
  shipped native WAVE engine. Donor IFFT timings are estimates and output rounding
  differs from its earlier additive builder.
- Native engine arenas, shared ROOM/SPRING/HALL buffers, word-copy loops, silent
  effect buses, selective minsize, guarded CPU1 recovery and initial profiles already
  exist. Their presence in Clipper does not justify duplicate optimization tickets.
  Exact TUNE/filter caches, chorus ramps and compiler-size experiments retain
  #223/#86/#110/#462 ownership.
- Clipper uses 256-frame audio halves (~5.805 ms nominal), native uses 128
  (~2.902 ms). Its 96 KiB main RAM / 336 KiB POOL and lowram allocations differ
  from native 72/360. Relocation does not reduce total state; larger buffers do not
  prove more native deadline headroom. Retain native debug/reserved/stack regions.
- Clipper's voice-split CPU1 model is not our part-split ownership. No 12/16-voice
  increase, changed second-core default or failure policy is assumed.

## Compatibility and licensing

Do not import dense donor engine numbers, extended parameter numbering, FM6 bank
flags or encodings in otherwise-unused track/lock/nudge fields. All four native
parts can use those fields. Use native stable IDs, DEEP/PRX/FVL capacity allocation
and producer descriptors. Coordinate supported schemas and browser recovery with
[#456](https://github.com/kmplngj/Felucca/issues/456)/[#457](https://github.com/kmplngj/Felucca/issues/457);
do not add another donor-specific firmware migration layer.

Clipper per-file GPL notices permit GPL adoption with corresponding source and
attribution. Retain MIT/Apache notices where applicable. Its LICENSING.md contains
stale SLOOP-era asset text, so audit actual files, dependencies and generator outputs.
An MIT design reference does not relicense a GPL implementation. Original procedural
tables/sample sources can be evaluated; uncleared banks, recordings and artwork
remain excluded. No donor assets are copied by this review.

Every retained implementation needs unchanged-baseline/candidate evidence under
[performance.md](performance.md), source/toolchain/profile provenance, all memory
regions and stack margins, native sound/state/transition checks, fresh target and
applicable host/emulator tests. Real FM-1 listening, render maxima, late halves,
shedding, nested scan and USB/UART errors remain separate, pending evidence.

## Watch registration

Register `isod89/clipper-fm1` main, repository ID **1424928986**, with the immutable
main pin above and 49 historical commits, all unreviewed. The combined handoff
adds Clipper alongside FM1 Open as two pending
registrations while preserving previous registrations, pins and the append-only
journal. It does not edit canonical runtime state or fabricate commit coverage.

After the registration reaches main, the existing watcher merges main into
`automation/firmware-watch`, verifies identity/branch/pin/full DAG and current tip,
then initializes the source and queues complete history. Until that succeeds,
registration is pending rather than active/completed monitoring. The registry is
consumed by the existing watcher workflow; its requested
schedule is **09:00 Europe/Berlin**. This reconciliation does not verify the external
scheduler or require an automation/cadence change. Notifications remain limited to
actionable findings,
meaningful blockers, completed historical coverage or required input.

## Source entry points

All donor links below are pinned to the inspected revision:
[status/catalog](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/README.md),
[engine registration](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/engines.c),
[core/IDs](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/core.h),
[linker map](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/app.ld),
[WAVE/service](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/eng_wave.c),
[VPS](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/eng_vps.c),
[TERRAIN](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/eng_terrain.c),
[HYBRID](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/eng_hybrid.c),
[FMX](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/eng_fmx.c),
[FX/delay](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/firmware/src/fx.c),
[transition tests](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/tests/clean_test.c),
[sample generator](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/tools/gen_clipper_sets.py),
[licensing](https://github.com/isod89/clipper-fm1/blob/7008d31e78da5d4e5e0a1f25a994ba7b2266c702/LICENSING.md).
