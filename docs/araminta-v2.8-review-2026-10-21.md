<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Araminta v2.8 adoption review — 2026-10-21

Tracking: [adoption plan #230](https://github.com/kmplngj/Felucca/issues/230) and [experimental instrument integration #228](https://github.com/kmplngj/Felucca/issues/228). This refresh preserves the earlier source-pinned assessment rather than replacing its evidence.

### Current decision

Keep selective adoption. The requested [v2.8 release](https://github.com/Wulgaren/Araminta/releases/tag/v2.8) resolves to `b22d51d13a3662f812e4b1ec3ddee0b32abfffed`, also donor main at intake. Native comparison is `63f49060e3e625e3bf5bacdb726798ff8f58c363`. Full non-shallow DAG: **304 reachable commits**, **20 in v2.7→v2.8**, **265 since the original 7304acfe snapshot**. This is a pinned release/source review, not 304 individually assessed commits or a new native benchmark.

v2.8 mainly improves storage representation, RAM and LCD transfers. It adds no new synthesis engine/bank in the v2.7→v2.8 interval. Source currently has SAMPLE/GRAIN/NOISE selectable again despite the older 2.1 changelog; SLICE remains retired and DRUM ID10 is still DRUM-X. Our standard catalog and saved identities stay intact.

### Integration reconciliation — 2026-10-23

The original source review below remains pinned to its intake revisions. The
combined handoff reconciles documentation and registration with Felucca main
`f8ed365d845af789ce7237e3bd531f6d0c67fff9`, where Araminta is already registered once
and the historical target remains unchanged. This does not refresh canonical scan
progress or rerun the donor audit. [Clipper](clipper-adoption-2026-10-19.md) and
[FM1 Open V14](fm1-open-adoption-2026-10-21.md) share the same preservation and
independent-measurement gates; none of these plans changes default behavior.

### Updated work order

| Priority | Work | Existing/new owner and gate |
| --- | --- | --- |
| First | Qualify remaining cold UI/editor files for selective minsize | **[#521](https://github.com/kmplngj/Felucca/issues/521)**; preserve native ISR/callback/worker/flash closure; independent of #462 noinline boundaries |
| First | Prototype differential LCD transport over native RGB565 | **Existing #59**, with #99/#102/#191; added current donor evidence. Exact comparison/completion ownership required, independent of #224 palette quantization |
| Next | Reduce live/copied step RAM with accessors and explicit packing | **[#520](https://github.com/kmplngj/Felucca/issues/520)**, focused child of #20; preserve native wire bytes/conditions and resolve donor's documented main-loop/recording-ISR byte-sharing race |
| Later, optional | Use measured per-part execution costs for native CPU1 split weights | **[#523](https://github.com/kmplngj/Felucca/issues/523)**; cumulative v2.6 change included in v2.8, probe timer/units/publication and preserve native retained failure guard/default OFF |
| Low priority / capacity gate | Evaluate 84→36-byte song-section codec | **[#522](https://github.com/kmplngj/Felucca/issues/522)**, under #213; explicit native format decision and all 128 native motion records retained |
| Independent instrument track | Refresh DRUM-X/FOLD and optional ANALOG COMB audition | **Existing #228** + GPL Engines #12/#136/#71; no duplicate port, sample rights and exact collection pins remain gates |

Do not sum donor savings across commits or claim native gains. Capture one unchanged native baseline, compare each cause independently, and only combine two/three related retained changes into one hardware handoff after isolated evidence. Keep sound-changing instrument/routing/storage work out of the exact optimization batch.

### Feature and instrument reuse

- **DRUM-X:** #228 now pins v2.8 and adds the cumulative FM/FOLD correction (effective FOLD replaces hardcoded zero, changing ratio/index/feedback). Keep its zero/extreme/transition audition matrix and per-part ownership. GPL Engines #12 remains the reusable implementation owner, #136 rate/quality. #212 is already merged; the host now owns allocation in the current 64-ID space. #360 still blocks GPL collection build consumption.
- **Generators/FX/drone/punch-ins:** Grids through #214/#215/#182; routing #441; punch banks #440 and performance lane #443/#226; ARP DRONE #442; tape delay #73 and expanded reverb #187. Current native already has playhead following with timed manual hold in ui.c, so no duplicate follow feature.
- **FM6:** current donor carrier table is additional evidence on #512, not a competing issue. Its zero-input arithmetic/inline changes must preserve future envelope/LFO state and be measured separately under #89/#498/#511/#366. A nonzero AMS at zero AMD still has native attenuation math; do not remove it as "zero modulation".
- **Worker/overload:** #523 owns measured steering only. Donor single-half >92% and two-voice >100% shedding alter the musical admission/degradation policy; evaluate separately under #92 if justified. #218 owns victim-scan optimization, not these threshold changes. Keep our worker held-off/fallback rules.
- **USB:** donor tighter UAC fill-band values need #427's clock/ring/deadline evidence; do not copy thresholds from a different render workload. Donor insert-SEND snapshot elimination has no current six-stage native counterpart; retain it as a future #441 constraint rather than create an inapplicable optimization ticket.
- **Client:** new producer/client contracts must be linked. Felucca-WebApp Issues remains disabled; any justified client ticket uses a firmware fallback owner naming that implementation repository. No new client implementation is needed merely to publish this review.

### Rejected direct transfers and source evidence

The 9-byte step idea can preserve our current native 9-byte wire encoding, including chance/conditions 102..112, without changing project format. It cannot preserve edit concurrency by itself: donor core.h explicitly acknowledges a new RMW race. #520 must fix ownership, not accept a lost edit as a trade for RAM.

Donor FUN16/FUNG is 3,840 B with 88 saved motion records and 192 RAM records; native FUNA retains **128 in RAM and on disk**. Donor's larger-than-disk session clips on save. Do not replace native persistence with it or claim it expands our motion capacity. #522 only evaluates the 48-byte song encoding reduction behind a native version/capacity decision; preserve retained extents, backup/malformed/torn-write/downgrade behavior and native family semantics.

Donor LCD skips depend on FNV hashes of 4-bit indices. A hash collision can hide a changed band; exact native pixel equivalence needs an exact comparison or an explicitly changed reviewed contract. Its timeout counter/cache invalidation is not a proven DMA abort. Cache validity must follow actual successful transfer completion. Keep RGB565 fidelity, fault recovery, in-flight source ownership and all reset/wake/direct-write paths in scope. The donor's 20-byte retained UI-stat object is not an authorized native NOINIT allocation.

Donor reports -2,688 B RAM/-768 B POOL/+1,184 B app for packed steps, then spends +1,280 B RAM/+1,216 B POOL for the larger motion pool; its minsize change reports -2,032 B app. These numbers belong to the donor revisions/configuration. No matched native target builds, host CPU tests or FM-1 runs were performed here.

[Core/accessors](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/core.h), [project codec](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/project.c), [LCD renderer](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/gfx.c), [LCD transport](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/lcd.c), [size pass](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/tools/size_fns.py), [part timing/splitter](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/fx.c), [FM6](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/fm6_core.c), [DRUM-X](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/drumx_voice.c), [generator](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/firmware/src/generation.c), [sample generator](https://github.com/Wulgaren/Araminta/blob/b22d51d13a3662f812e4b1ec3ddee0b32abfffed/tools/gen_samples.py). CR78's attribution remains restrictive; the current generator explicitly omits those WAVs. Keep them excluded until rights are established.

### Watcher and completion

**At the original intake, already registered on both main and automation/firmware-watch:** Wulgaren/Araminta, repository ID 1414058478, branch main, frozen historical target `7304acfe34cbf43825d33c15ef13bef0aab5c85d` (39 at setup). At the original 2026-10-21 intake, canonical source-specific state had one historical terminal review, zero recent reviewed and observed/pinned tip `b16f1b2ed424172fe238779e9101328d8e732d8a`. Keep those existing targets and journal records. Normal serialized sync discovers later main tips and schedules missing graph work; this release snapshot credits no individual commits. No duplicate source registration, scheduler or cadence change is needed.

A documentation PR publishes the full review and links it from docs/firmware-watch.md. README assessment: existing collection/review/measurement and experimental-engine descriptions remain accurate; no running capability changed. Changelog: no entry for planned/unmerged work. Every retained implementation still needs current source/pin/compiler/profile provenance, focused/full native tests, app/all-region/stack evidence and real FM-1 listening/timing/USB/MIDI acceptance.

### Review method

Read the release notes, four v2.8 implementation changes and their native consumers, current routing/engine/generator sources, current project codecs and focused donor fixtures without executing donor code. Read the earlier adoption/instrument owners, open/closed issues and PR inventories across all four implementation repositories, and relevant comments. Main comparison `63f49060e3e625e3bf5bacdb726798ff8f58c363`, MIT Engines pin `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`; collection mains at intake were MIT `7cf364f6c2ce0130be4fe8bf436ffe62077cb175` and GPL `1406b3ac7008bad2a87a2f41e44da93eb621bc40`. Do not confuse current collection main with the firmware's consumed pin.

The donor clone is non-shallow and `git fsck --full --no-dangling` passes. Tag v2.8 and donor main resolve to the full immutable pin above; v2.7 is `9563565a5317b8e7fc1c5f1ad6d91b20f35fa73b`. The release object is not marked immutable, so source evidence uses the resolved commit. No donor scripts, builds, tests or binaries were run. This source review does not establish numerical speed/size savings or device qualification.
