<!-- SPDX-License-Identifier: GPL-3.0-only -->
# WaveLoop Kits adoption review — 2026-10-30

<!-- felucca-upstream:lucian-labs/fm1-waveloop-kits@20ca3180a238df07b9efec913e42954b60356090:adoption-plan -->
## Recommendation

Selectively adapt this **source-porting kit**, preserving Felucca's native clock, UI/voice ownership, data and storage. [PORTING.md](https://github.com/lucian-labs/fm1-waveloop-kits/blob/20ca3180a238df07b9efec913e42954b60356090/PORTING.md) defines the right integration boundaries. It is not firmware or a universal patch.

Reviewed 2026-10-30: kit main `20ca3180a238df07b9efec913e42954b60356090`, repository ID **1437618050**; full `felucca_comparison_sha` `f9e0fa7cd90112ebfe093f696268eea7f0bd1116`. Complete non-shallow main DAG fetched, `git fsck --full` passed, **9 reachable commits**. This topic/snapshot review grants **zero per-commit assessments**.

## Priority and owners

| Order | Candidate | Decision / issue |
| --- | --- | --- |
| 1 | Exact native DRUM drive normalization cache | **#814**: bounded optimization that can start now; establish baseline then preserve exact PCM/state. Discovered in native comparison, not supplied by donor; no measured gain yet. |
| 2 | SHAYPE drawn arp | **#812**: pure-core/parity and default-off RAM pilot, native scheduling/UI next. Saved patterns await capacity allocation. |
| 3 | Modified 808, then CR78 | **#815** host experiment + [Engines-GPL #14](https://github.com/kmplngj/Felucca-Engines-GPL/issues/14) existing portable/content owner. One separately selectable variant first. General per-lane edits stay #71. |
| 4 | Full active-pattern pitch/chord/hold overview | **#813**: optional extension to existing HOME TRACKS, initially one selected track at 64 steps; reuse native palette/fonts/snapshots/damage. |
| Existing | Played hold durations | **#63**, updated with exact donor patch and incompatibility evidence; separate timing state, never overload native hit/acc bytes. |
| Existing | Persistent named-song/setlist workflow | **#169**, updated with named-save/switch/resume/duplicate questions over native A–D slots; core autosave/restore already exists. |
| Defer | 128-step extension | Requires explicit capacity/format/client design through #213's plan, #314–#320 and #62/#319 where relevant. Keep native 64 steps meanwhile. |
| Optional | Bank themes | Presentation only; native palette first. Upstream token-source ancestry/license closure was unavailable for independent verification. |

## Present already, and incompatible shortcuts

- Native already has eight drum lanes, GM mapping, one-shot recording, hit/accent masks, lane level/mute, hat choke, shared voice budget and 16-row song sections selecting A–D. Its autosave waits for stopped/quiet conditions, rate-limits writes and restores the last session. Do not replace these with the donor scheduler/store.
- Native HOME TRACKS already has four 16-step page timelines, row signatures and meter-only blits. New value is whole-active-pattern pitch/hold detail, not a missing track view or proven redraw optimization. Donor minimum row height 38 differs from native 29 pixels.
- The modified 808 is a recipe pointing to Switch Blade `777aff21f6f00312095965bc826dbb4d9759974f`, not a bundled standalone instrument. Donor kit IDs/control meanings differ. Preserve native sounds and ACC/KICK/DRV; optional Yama/909 are separate licensed dependency closures.
- SHAYPE's 8 pitches/independent durations exceed native ARP's 4 pitches/common release timer. AOCT/AORDER/rates differ. Append validated native configuration and lifecycle state rather than repurpose old parameter meanings.
- Donor played-holds stores synth duration in hit/acc and clears those bytes across synth/DRUM changes. Native uses these as GM hit masks on **any** engine. A direct port loses musical data.
- FOR5/FOR6 uses 6400-byte base-plus-extension projects and retired sample sectors. Native [capacity plan](https://github.com/kmplngj/Felucca/blob/f9e0fa7cd90112ebfe093f696268eea7f0bd1116/docs/flash-capacity.md#4-options-and-their-user-visible-cost) rejects multi-sector projects and protects live samples. Four SHAYPE patterns alone need roughly 512 B plus configuration, exceeding the plan's estimated 368 B unassigned PRX allowance.
- The donor save-guard repair is a useful test lesson, not a native SONG SAVE ERROR fix. Native already allows those addresses and uses them for samples. A later storage-contract improvement can share the exact write-range predicate with NOR tests; do not widen native windows as a port step.
- Bundled renderer/theme code does not establish CPU/RAM savings. Keep native exact coefficient caches, selective compiler policy, flash-safe HAL and per-part arenas.

## Watch registration

Prepare **one pending main registration** for `lucian-labs/fm1-waveloop-kits`, ID/pin above, complete initial history count 9 and zero credited reviews. Watch module source, fixtures, recipes, provenance and patch changes through the existing firmware-watch process. Linked donor repositories/pins are evidence, not silently added watch scope.

Registration must land through an ordinary PR to main, then reconcile into `automation/firmware-watch`. The existing runner independently verifies canonical identity, branch, immutable pin and full DAG before initialization. Preserve all existing registrations, journals and frontiers. Pending registration is not active monitoring; no new runner or schedule is needed.

## Acceptance and boundaries

- [ ] Child issues and existing owner evidence are linked; portable GPL work precedes an exact host dependency pin (#360 remains pending). SHAYPE/UI/scheduler/IDs/storage are firmware-owned.
- [ ] Registration validates and receives review; actual watcher initialization remains pending until merged/reconciled and verified.
- [ ] Each retained implementation records unchanged/candidate SHAs, compiler/SDK/profile/flags/assets/pins, app/RAM/POOL/RAMTEXT/NOINIT/stack and bounded event/audio work. Preserve existing sound/data and profile-absence contracts.
- [ ] Fresh applicable host/target/browser checks precede FM-1 listening/panel, dense four-part/FX, USB/TRS MIDI, UAC 44.1/48 kHz and CPU2 OFF/ON/fallback qualification. Host/static/source evidence stays separate from device results.
- [ ] Audit every copied source/table/generator/asset dependency and preserve Hügelton, Switch Blade, Lucian Labs and optional MIT/9W9/ER-99 notices. No GPL-derived code goes into MIT Engines.
- [ ] Exit each pilot adopt/revise/defer/reject. Planning does not authorize firmware implementation or device flashing.

Deduplication fully paginated all-state issue/PR metadata, issue comments and inline PR comments across Felucca, MIT Engines, GPL Engines and WebApp; WebApp Issues is disabled. No replacement portable 808/Yama issue was needed.

No donor scripts, firmware builds/benchmarks or FM-1 tests were run. No native performance gain is claimed. README already describes selective adoption/watch/experimentation; no shipped milestone or changelog/diagnostic/protocol change is warranted.

## Published work

- [Adoption and watcher owner #816](https://github.com/kmplngj/Felucca/issues/816).
- [SHAYPE #812](https://github.com/kmplngj/Felucca/issues/812).
- [Whole-pattern overview #813](https://github.com/kmplngj/Felucca/issues/813).
- [Native DRUM drive cache #814](https://github.com/kmplngj/Felucca/issues/814).
- [Native 808/CR78 audition #815](https://github.com/kmplngj/Felucca/issues/815), with portable/content work retained in [Engines-GPL #14](https://github.com/kmplngj/Felucca-Engines-GPL/issues/14#issuecomment-6528718694).
- New material evidence on [timed notes #63](https://github.com/kmplngj/Felucca/issues/63#issuecomment-6528719098) and [named songs/setlist #169](https://github.com/kmplngj/Felucca/issues/169#issuecomment-6528719461).

## Review and validation provenance

Two read-only GPT-6.1 Sol workers at high reasoning reviewed musical/storage fit and instrument/optimization fit. The coordinator inspected native callers, source modules/patches and the four-repository inventory and owns all GitHub/configuration writes. This is a topic review, not individual assessment of the nine commits. No journal records or completed coverage were created.

At inventory time Felucca contained 787 all-state issue/PR records, 1,799 issue comments, 278 PRs and 452 inline review comments; MIT Engines contained 13 records, 32 comments, 4 PRs and 16 inline comments; GPL Engines contained 39 records, 41 comments, 2 PRs and 1 inline comment; WebApp had 19 PRs, 157 conversation comments and 68 inline comments with Issues disabled. Relevant open work was checked before publication; no matching kit markers required recovery.

Validation for this documentation/registry-only handoff: complete source DAG integrity/count checks, existing ledger validation, exact pending-entry/immutable-pin/zero-credit checks, unchanged preexisting source/state/journal comparison, local Markdown links and whitespace. Firmware/host DSP/browser/device checks and resource deltas are not applicable to this handoff; their requirements remain on implementation issues. The existing automation was inspected; its schedule and prompt are unchanged.
