<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Optimist adoption review — 2026-10-19

Optimist has useful implementation references for this fork's existing direction:
custom builds, more instruments and measured resource work. Adopt small parts
through the native contracts and existing backlog. This review creates plans and
watch scope; it does not enable an instrument, change firmware behavior or claim
measured device improvements.

Coordination: [Felucca #461](https://github.com/kmplngj/Felucca/issues/461).

## Pinned review

| Input | Reviewed revision |
| --- | --- |
| Optimist main | `5fc3ee51a4aa64fd22cef217c8498c9be567eb69` |
| Felucca main | `e20985aa7baae96313190526deb5a72c02cf6659` |
| MIT Engines, firmware pin | `9630426f5c4a34a209ca851356fbe8ba3c4c6d19` |
| MIT Engines, current main inspected | `53ad1f5c9afb593f29305d79779bfd30aacc14cd` |
| GPL Engines main | `cb2a3b372ee3f813f621aad737506837a18bbd3c` |
| WebApp main | `74e961439a76dd9da777264d068122e1d0fc2460` |

The source clone is non-shallow, passed Git connectivity checking and has 2,018
reachable commits at the pin. Snapshot source review is not a commit-by-commit
audit: **zero completed assessments** are added to the watcher journal.
Open/closed issues, issue comments and PRs were paginated across all four native
repositories. Existing instrument issues and merged implementations were checked
before creating new work. WebApp Issues remains disabled; its client ticket is
tracked in Felucca with the explicit implementation repository.

## Goal and recommendation

Bring useful Optimist ideas into our existing integration fork through bounded, opt-in work. Highest near-term value: cold-code size boundaries and a reproducible profile/budget path. Next: a browser builder and native instrument auditions. Keep the standard Felucca sound, four interchangeable parts and existing recovery route.

Optimist is a substantially evolved SLOOP/Felucca platform, not a compatible patch series. Its registry has its own UID/slot distinction and fallback sounds, three synth parts plus a dedicated drum part, a different memory split and 256-frame DMA halves. Felucca uses stable native IDs, N/A/silent unavailable engines and 128-frame halves. Port designs deliberately rather than replacing these contracts.

## Staged delivery

1. **Scope and watch:** register `w0ts/optimist` main, repository ID 1410403115, immutable initial target `5fc3ee51a4aa64fd22cef217c8498c9be567eb69`. The complete non-shallow DAG contains 2,018 commits at this pin; zero are credited by this snapshot. Use the normal reviewed registration PR, then state-branch merge and verified initialization on the next audit.
2. **Optimizations first:** https://github.com/kmplngj/Felucca/issues/462 tests cold minsize boundaries; https://github.com/kmplngj/Felucca/issues/463 separately tests a curved-string kernel. Reuse #22 for storage scratch/mirror lifetimes and #153 for silent-bus reactivation evidence. The compact octave pitch table is already in the pinned MIT Engines generator; do not file another port. Shared-DSP source deduplication is maintainability work unless target output proves savings.
3. **Builder foundation:** https://github.com/kmplngj/Felucca/issues/465 extends `tools/profile.py` and the existing native manifest (#28/#341/#360); https://github.com/kmplngj/Felucca/issues/466 produces a reproducible, bounded custom-build service. https://github.com/kmplngj/Felucca/issues/467 owns the browser configuration/build/install flow in WebApp. Reuse the firmware browser-runtime producer #413, identity #422 and migration #456/#457 rather than duplicate them.
4. **Instruments:** https://github.com/kmplngj/Felucca/issues/468 owns host audition/qualification; https://github.com/kmplngj/Felucca-Engines-GPL/issues/23 owns GPL portable ANALOG 2. Reuse GPL Engines #2 for JUNO, #4 for CZ, #7 for 303/808/909 and #13 for SLOOP kits/content. Compare Optimist variants and original patches before deciding which improve our catalog. Keep native FM6 and its SysEx/library owners #61/#318.
5. **Features after capacity/contracts:** ENV2/LFO2 maps to #356; insert type metadata to #312 and reorderable chains to #441; scenes/undo/patterns to #32/#60/#62, with #213/#316/#319 capacity gates; optional help to #355; native navigation to #404. Radio stays with #431, rescue with #116/#429. CPU guard, reverb algorithms, richer shapers and alternate UI are experiments to select after first auditions, not automatic defaults.

## What transfers, and what requires caution

- Builder: one pure configuration evaluator shared by CLI/browser/CI, exported registry, visible dependencies, estimates distinguished from actual linked sizes, a canonical source+configuration build identity, and matching simulator artifacts. Native rules and margins remain authoritative.
- Sound: ANALOG 2's oscillator/sync/swarm/filter ideas and selected original presets; JUNO/CZ/ACID/drums through existing collection owners. Do not remove native ANALOG/SUPER or import donor IDs, factory banks or uncleared samples.
- CPU guard: predictive load plus hysteresis and musical voice protection is interesting, but its quality reductions deliberately change output. Donor comments/docs contain dated model and hardware caveats. Recalibrate at native 128-frame halves and validate release/recovery before a focused follow-up.
- Effects: donor shared reverb buffers and effect instance limits are useful allocation examples. New algorithms, half-rate tanks, compressed delay lines and new routing intentionally change sound/state and belong in separate experiments. A zero return does not alone prove a native tail may be discarded.
- Measurement: symbol sizes and independent C/assembly comparisons are useful. Do not treat donor `dis_diff.py` output as equivalence proof: it masks large numeric operands and symbolic targets, which can hide changed constants or destinations. A native comparer must distinguish relocations from semantics.

## Completion criteria

- [ ] Linked implementation owners, dependencies and source pins are maintained; overlapping work is reused.
- [ ] Watch registration is merged and initialized separately, retaining all prior pending sources/history and zero snapshot credit.
- [ ] At least one bounded optimization has native baseline/candidate evidence, including a documented no-win result if applicable.
- [ ] First custom-profile build is reproducible from exported source/configuration and rejects invalid or over-budget selections.
- [ ] Each accepted instrument has collection, host and client ownership, license closure, native controls/data compatibility and FM-1 acceptance before entering a release.

Sources: [registry](https://github.com/w0ts/optimist/blob/5fc3ee51a4aa64fd22cef217c8498c9be567eb69/firmware/src/core/registry.h), [builder core](https://github.com/w0ts/optimist/blob/5fc3ee51a4aa64fd22cef217c8498c9be567eb69/tools/builder/core.py), [builder verification](https://github.com/w0ts/optimist/blob/5fc3ee51a4aa64fd22cef217c8498c9be567eb69/tools/builder/verify.py), [cloud workflow](https://github.com/w0ts/optimist/blob/5fc3ee51a4aa64fd22cef217c8498c9be567eb69/.github/workflows/cloud-build.yml), [licensing](https://github.com/w0ts/optimist/blob/5fc3ee51a4aa64fd22cef217c8498c9be567eb69/LICENSING.md), [native resolver](https://github.com/kmplngj/Felucca/blob/e20985aa7baae96313190526deb5a72c02cf6659/tools/profile.py), [native integration contracts](https://github.com/kmplngj/Felucca/blob/e20985aa7baae96313190526deb5a72c02cf6659/docs/extending.md).

## First implementation batches

| Order | Bounded deliverable | Dependency and exit gate |
| --- | --- | --- |
| 1 | Cold-code minsize boundary experiment (#462) | Keep the completed #127 ISR protection; accept only after target byte and service-latency evidence |
| 2 | Native profile/budget export (#465) | Extend #28/#341; current supported profiles first, mixed collections through #360 |
| 3 | Maintainer-triggered custom profile build (#466) | Exact reports and source/configuration reproduction before public requests |
| 4 | Browser selection, estimates and build/install flow (#467) | Same evaluator and artifact identity; preview uses runtime producer #413 |
| 5 | Optional ANALOG 2 collection/host pilot (GPL #23, #468) | Collection commit first, then exact host pin, controls and capacity; no replacement of native ANALOG/SUPER |
| Separate | Curved-string PHYS target kernel (#463) | Independent C/state oracle and real target execution; keep apart from compiler-size changes and #179 coefficient caching |

These are suggested batches, not implementation authorization in this review.
The first optimization and builder can progress independently. New instruments
do not block the first browser builder for already supported profiles.

## Feature fit and existing owners

| Optimist idea | Native adoption path | Important limit |
| --- | --- | --- |
| JUNO, CZ, ACID, 808/909 | GPL Engines #2/#4/#7 and host audition #468 | Compare variants; no second implementation owner or copied factory ROM bank |
| Original FM6 packs and on-device editing | Existing native FM6, #61/#318; audition #468 | Donor operator/state layout differs; our patch ownership, macros and stored sound remain native |
| Synthesized kit catalog and editor | GPL Engines #13/#7 with native host controls | Donor dedicated drum part/lanes are not our four interchangeable parts |
| Dictionary-coded voices, unique drum sounds | Profile/content experiment after #468 selection | Net linked bytes include decoder/offsets/dictionary; no automatic 80-voice saving for eight native factory patches |
| ENV2/LFO2 | #356 | Stable target IDs, explicit precedence and extra state budgets |
| Two inserts, new shapers, effect returns | #312/#441; choose focused algorithms after auditions | Routing/order/tails deliberately affect sound and require native persistence/protocol design |
| Patterns, scenes, snapshots, undo | #62/#32/#60 and capacity #213/#316/#319 | No free flash sectors or new retained-RAM allocation implied |
| Contextual interface and help | #404/#355 | Select native interactions; a full alternate UI is a separate optional proposal |
| BLE / radio, USB rescue | #431 and #116/#429 | Use existing rights/hardware/recovery owners; do not copy captured radio data without their audit |
| Predictive CPU guard | Later opt-in experiment after measured load analysis; relate #92/#94 | Quality cuts are not equivalent-workload speedups; recalibrate half duration and model |
| Browser simulator/editor bridge | #413 plus client #467 | Match exact source/profile; browser timing does not establish physical device deadlines |

## What is already present or should not be copied

- The compact octave pitch table is already in the firmware's pinned MIT
  [generator](https://github.com/kmplngj/Felucca-Engines/blob/9630426f5c4a34a209ca851356fbe8ba3c4c6d19/tools/gen_engine_tables.py).
  Optimist's 8,192-to-768-byte table change is not a new native saving.
- Per-part engine arenas, silent-bus skipping, selective minsize, stable sparse
  engine IDs, source-complete releases, browser emulation and CPU1 fault handling
  already exist. Reuse #22 for proven scratch lifetimes, #153 for exact
  burst/silence reactivation coverage and #425 for target multiply hazards.
- Moving state from main RAM to POOL reallocates one physical SRAM budget. It does
  not reduce total state. Optimist's 96 KiB/336 KiB main/POOL split is not our
  72 KiB/360 KiB split; use native linker regions and minimum margins.
- Keep the native 128-frame DMA halves (about 2.902 ms nominal) when evaluating
  donor work designed around 256-frame halves. Do not import latency changes as
  an optimization prerequisite.
- Do not import Optimist's dense engine slots, unavailable-sound fallbacks,
  FUN/section log formats, flash map, retired engine conversions or replacement
  FM6/ANALOG behavior. Preserve native stable IDs and explicit N/A semantics.
- Donor source deduplication often leaves identical inlined machine code, so its
  own DSP review reports no resource improvement for most merges. Useful source
  organization is not a measured CPU/RAM saving.
- Address-normalized disassembly is supporting evidence only. In particular the
  donor comparator masks large numeric operands and symbolic targets; equal
  output can hide semantic differences. Changed constants, calls, global data,
  cache effects and hardware timing require separate checks.

## Validation and compatibility gates

Every optimization records an unchanged revision, exact compiler/SDK, profiles,
assets and dependency pins, then repeats identical workloads after changing one
cause. Report app, RAM, POOL, RAMTEXT, NOINIT and stack deltas independently;
retain native 4 KiB RAM, 8 KiB POOL and 100 B NOINIT margins. Compare full PCM and
future state for exact changes, plus preset/engine transitions and both relevant
core configurations. Real FM-1 render maxima, late halves, shedding, nested scan
cost and USB/MIDI errors remain unmeasured by this review.

For musical changes, document intentional differences and audition levels,
release tails and controls. GPL portable code belongs in GPL Engines; source
closure may retain individual MIT/Apache/BSD notices. Unknown factory data,
samples and artwork remain excluded until provenance is established.

Coordinate format retirement with #456/#457. Future supported-schema changes
must retain the requested download-original / optional browser-convert / upload
recovery path; do not add donor-specific firmware migration layers. Native
storage allocation, project extensions and settings stay with the capacity plan.

## Watch activation and recovery

The registration PR adds Optimist to `pending_source_additions`, preserving all
other registrations, pins, journals and coverage. It is not active scan coverage
until the PR is merged and the runner merges main into
`automation/firmware-watch`, verifies repository ID/main/full DAG/pin, and
initializes it. The initial historical target stays fixed; subsequent changes
enter the recent queue independently. Source initialization and queueing never
credit reviews.

The existing enabled daily firmware watch already consumes this registry at
09:00 Europe/Berlin. No new automation, cadence change or broadening of unrelated
source scope is needed. The watcher reuses these issue markers/owners and stays
quiet unless it finds actionable work or a meaningful blocker. See the
[watch guide](firmware-watch.md) and
[firmware-watch skill](../.agents/skills/firmware-watch/SKILL.md).
