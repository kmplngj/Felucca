<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM Lab adoption review — 2026-10-21

Tracking: [adoption plan #517](https://github.com/kmplngj/Felucca/issues/517); [experimental instrument integration #516](https://github.com/kmplngj/Felucca/issues/516).

## Recommendation

Selectively adopt FM Lab's sound-design workflow and original voices around **our existing FM6**, starting with two independent exact-output optimization experiments. Keep operator waves, oversampling and output precision behind separate evidence/compatibility gates. FM Lab is a single DX7 instrument with 20 presets, not a multi-engine catalog to merge wholesale.

Reviewed main `cf35dc26709ede9c974654dfc2135f8c25a00082` (37 reachable commits, complete non-shallow clone) against Felucca `63f49060e3e625e3bf5bacdb726798ff8f58c363`, 2026-10-21. Snapshot/source inspection only: **zero individual-commit review coverage**, no benchmarks/firmware change/device tests. All four implementation repositories' open/closed issues and PR collections were inspected; relevant comments and current source checked. Existing owners are reused below.

## Delivery sequence and issues

| Order | Work | Owner / dependency |
| --- | --- | --- |
| 1 | Measure exact patch-only PMD/PMS/AMD precomputation | [#511](https://github.com/kmplngj/Felucca/issues/511); child of #89 |
| 1 | Measure exact carrier mask reuse across compute/done | [#512](https://github.com/kmplngj/Felucca/issues/512); independent A/B |
| 2 | Prepare original GPL 20-voice content | [GPL Engines #27](https://github.com/kmplngj/Felucca-Engines-GPL/issues/27) |
| 3 | Audition, select and qualify native instrument content | [Experimental host issue](https://github.com/kmplngj/Felucca/issues/516); collection pin/profile consumer needs #360 |
| 4 | Complete missing panel patch fields, ratio browsing and bounded audition | [#513](https://github.com/kmplngj/Felucca/issues/513); reuse #76/#32/#64/#205 |
| 5 | Native operator-wave extension and independent 2x quality trial | [#514](https://github.com/kmplngj/Felucca/issues/514); #317/DEEP for stored extension |
| 6 | Measure tail precision, then decide a bounded wider signal path | [#515](https://github.com/kmplngj/Felucca/issues/515); optional and sound-changing |

Batch #511/#512 for one hardware handoff only after isolated before/after evidence from one baseline; keep logical commits and report the integrated delta without adding overlapping savings. Instrument/content, new storage/protocol and sound-changing quality experiments stay separate. Estimates/priority are engineering judgment, not promised speed/size gains.

## Feature comparison and reused owners

- **Already present:** classic 6-op FM/32 algorithms/feedback/pitch EG/LFO, native OPERATOR/OPERATOR 2/OP ENV editing, routing-derived diagrams, patch/project/preset persistence, shared mono/legato/arp/sequence, USB/TRS MIDI, USB audio, effects and rescue/build guards. Review donor differences instead of replacing those subsystems.
- **Direct Yamaha SysEx:** #61 already owns bounded receive/send/bank/librarian work; add FM Lab source as evidence there. Current editor bank upload is not direct librarian interoperability.
- **Spectrum:** #144 already owns the bounded 512-point spectrum/spectrogram experiment. Donor's 1024-point linear spectrum is a design reference; its ring permits tearing and is not a safe native capture contract.
- **Voice library:** #74/#318 own independent native voice management; #317 owns deep extensions. FM Lab's 32 user slots/settings sectors are incompatible with our allocated flash map.
- **Controls/learning:** #76 owns recipes/compare/discard; #32 scene design; #64 native patch automation; #205/#203/#204 the shared Instrument/mode/startup system. Add missing classic panel fields and explicit temporary operator audition through #513.
- **DSP reuse:** #498 amplitude attenuation reuse, #499 frequency keys, #366 feedback loop specialization and #128 approximate table reduction remain existing owners. Donor AM tables are a different numerical approximation, not a free exact optimization.
- **Platform/FX:** do not copy Dinghy/SLOOP's platform, 96/336 KiB memory split, flash layout, eight-dedicated-voice allocator, 64-frame control or 256-frame DMA halves. Felucca uses 72/360 KiB, CTL=32, DMA half=128, native six FM6 voices/part and eight shared, bounded services and CPU2 ownership. Native FX already include important silence skips/tail policy; donor bypass/clears would alter it.

## Compatibility and licences

Factory source is GPL-3.0-only, credited to Sven Trogus and declared original for sloopDX. Route portable bank/generator to GPL Engines; retain individual Apache-2.0 msfa plus GPL port notices if using donor core changes. No GPL-derived module goes into MIT Engines. Existing native FM6 improvements remain in firmware until a separately scoped extraction. GPL consumption is planned under #360, not implemented.

Donor adds six waveform bytes after its 156-byte voice, hiding wave indices in packed VMEM byte 11 bits 4..6. Native classic VCED is 155 bytes, and unpack/pack drops those reserved bits. Do not silently interpret arbitrary Yamaha banks as extensions or claim single-voice dumps preserve waves. A versioned native extension plus storage/protocol/client design is required before persistence.

The 20 original voices can be auditioned as classic patches; the generator's spare byte is dropped deliberately. Keep source identities/names and do not overwrite F1..F8, OWN or bank/user data. Donor audio is not guaranteed bit-identical due to different sine precision, LFO ownership, envelopes, control size and gain/DC/FX.

## Evidence, budget and promotion

[Donor README](https://github.com/jsmith13/fm_lab/blob/cf35dc26709ede9c974654dfc2135f8c25a00082/README.md), [changes](https://github.com/jsmith13/fm_lab/blob/cf35dc26709ede9c974654dfc2135f8c25a00082/CHANGELOG.md), [core](https://github.com/jsmith13/fm_lab/blob/cf35dc26709ede9c974654dfc2135f8c25a00082/firmware/src/dx7_core.c), [instrument](https://github.com/jsmith13/fm_lab/blob/cf35dc26709ede9c974654dfc2135f8c25a00082/firmware/src/fmlab.c), [voice generator](https://github.com/jsmith13/fm_lab/blob/cf35dc26709ede9c974654dfc2135f8c25a00082/tools/gen_voices.py) and [donor device log](https://github.com/jsmith13/fm_lab/blob/cf35dc26709ede9c974654dfc2135f8c25a00082/tests/cpu_baseline.txt). Native sources: [FM6 core](https://github.com/kmplngj/Felucca/blob/63f49060e3e625e3bf5bacdb726798ff8f58c363/firmware/src/fm6_core.c), [host](https://github.com/kmplngj/Felucca/blob/63f49060e3e625e3bf5bacdb726798ff8f58c363/firmware/src/eng_fm6.c), [panel](https://github.com/kmplngj/Felucca/blob/63f49060e3e625e3bf5bacdb726798ff8f58c363/firmware/src/ui_fm6op.c), [audio](https://github.com/kmplngj/Felucca/blob/63f49060e3e625e3bf5bacdb726798ff8f58c363/firmware/src/audio.c).

Donor reports ~26% for eight voices and ~40% with filter/FX, and ~72% average/~82% peak with 2x enabled. Those are donor observations with different workloads/cadence and metering; **no native speed, memory saving or deadline claim** follows. 2x oversampling costs CPU; a 24-bit DAC container does not prove 24-bit signal precision.

Every implementation needs unchanged baseline/full pins/compiler/SDK/profile/asset provenance; exact PCM and future-state tests for exact optimizations; documented spectral/listening tolerances for intentional sound changes; app, RAM, POOL, RAMTEXT, NOINIT, arena and stack reports; CPU2 OFF/ON/fallback; focused/full host/target checks and real FM-1 timing/listening/USB/MIDI/panel acceptance. Keep current storage and omitted-engine compatibility. No automatic flash or baseline refresh.

## Firmware watcher and documentation

Register `jsmith13/fm_lab` main, repository ID `1424620365`, historical target `cf35dc26709ede9c974654dfc2135f8c25a00082`, 37 reachable commits, zero reviewed. It is absent from both main and current automation/firmware-watch registries at intake. Add as pending initialization in a normal registration PR; after merge the existing daily 09:00 Europe/Berlin runner merges main, verifies identity/branch/pin/full DAG and initializes it. Preserve all other registrations and review history. This snapshot cannot advance per-commit frontiers. No duplicate automation or cadence change is needed.

README already describes collecting engines/features and measured optimization; no running capability changed. Add the focused review to its Development direction and process links. Changelog: no entry because planning/registration is not an implemented firmware feature.

## Registration acceptance

Preparation uses a complete donor clone: `git rev-parse --is-shallow-repository` is `false`, `git rev-list --count HEAD` is `37`, and `git fsck --full --no-dangling` succeeds. Repository identity is `jsmith13/fm_lab` / `1424620365`; default branch `main`; HEAD matches the pinned target above. These checks establish an inventory baseline, not 37 assessed commits.

The live scheduled task is `Felucca firmware watch` (`6ad479c6a89081918e1d11cec1c4c5f8`), enabled daily at 09:00 Europe/Berlin. Its prompt already reads registered/pending sources from current main and the canonical state branch. Keep that task and schedule. This registration PR does not mutate the live state branch, duplicate its already-initialized pending entries, or claim that the new source is actively reviewed before merge.

Companion repository intake: MIT Engines main `7cf364f6c2ce0130be4fe8bf436ffe62077cb175`; GPL Engines main `1406b3ac7008bad2a87a2f41e44da93eb621bc40`. The latter catalog remains design-only. Issues were enabled in Felucca and both engine collections, disabled in Felucca-WebApp. The initial content work requires no new editor UI ticket; future client implementation must follow the documented repository routing.
