<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Modular builds and usage modes

This is the consolidated plan for build-time engine/effect selection and startup usage
modes, and for adopting ideas from other FM-1 firmwares through them. The initial standard/reduced portable-engine resolver and host identity adapter are implemented
([profile evidence](build-profiles.md)); broader native selection and startup modes remain planned. This page
records vocabulary, ownership, current source constraints, the issue map and open decisions. Acceptance criteria live in the linked issues; when a decision is
made or an issue changes scope, update this page in the same PR.

Plan date 2026-10-12. Source facts refer to `main` at
[`b04f4fa`](https://github.com/kmplngj/Felucca/tree/b04f4fa720a4550c00f042a9eb67f26965784ae3)
unless stated otherwise. Resource numbers are dated measurements, not current fit claims;
no build, flash or device test was made for this document.

## Combining our plan with Felucca 1.6.1 — 2026-10-14

The 1.6.1 backport imports upstream
[`a53ecf4`](https://github.com/hugelton/Felucca/commit/a53ecf428c29c780108fd70a31b71a32a6b5c313)
on top of this fork's stable-id/settings/diagnostics/CI work. Its `firmware/engines`
submodule points at [our Felucca-Engines fork](https://github.com/kmplngj/Felucca-Engines),
pinned to `c46e0086f69bdc26df1cd144dca9e683cc4531dd`. ANALOG, LOFI, TRIO, WHEEL and NOISE,
the portable `engine_t`/voice/parameter types, shared DSP and engine table generator live
there under MIT. Other engines, registration, UI, voices/mixer, persistence and platform
services remain in the GPL firmware. The source split preserves the existing sound IDs;
the backport alone did not implement profile resolution, selective assets, effects modules or usage modes.
The subsequent #341 integration supplies the initial resolver and reduced LOFI profile; effects/modes
remain on their existing owners.

| Order | Work | Existing owner / added integration task |
| --- | --- | --- |
| 1 | Land the pinned backport; preserve default sound/data behavior, recursive CI checkout and clean-clone reproduction | This backport; [#342](https://github.com/kmplngj/Felucca/issues/342) adds complete source release archives |
| 2 | Decide the portable contract boundary, then consolidate host identity metadata | [#340](https://github.com/kmplngj/Felucca/issues/340), [#301](https://github.com/kmplngj/Felucca/issues/301) |
| 3 | Resolve one standard/reduced selection for target, host and emulator, including source pins, assets, tests and licenses | [#28](https://github.com/kmplngj/Felucca/issues/28), [#341](https://github.com/kmplngj/Felucca/issues/341) |
| 4 | Qualify sparse catalogs and client availability before new instrument variants | [#305](https://github.com/kmplngj/Felucca/issues/305), [#306](https://github.com/kmplngj/Felucca/issues/306), representative profile evidence |
| 5 | Add the mandatory Felucca mode adapter, startup selection and Instrument pilot over that same sound catalog | [#203](https://github.com/kmplngj/Felucca/issues/203), [#204](https://github.com/kmplngj/Felucca/issues/204), [#205](https://github.com/kmplngj/Felucca/issues/205) |
| Baseline | Continue with the integrated upstream 1.6.1 optional second-core worker | The independent [#44 experiment](https://github.com/kmplngj/Felucca/issues/44) is retired; no engine/profile/mode requires CPU1 |
| Before new persistent formats | Allocate each proposed object under the capacity plan | [#213](https://github.com/kmplngj/Felucca/issues/213), [#314–#320](flash-capacity.md) |

Keep firmware-specific identity metadata (tags/icons/categories/CC targets, order and stable
IDs) in a host-owned adapter unless both repositories deliberately revise the portable
contract. #301's earlier proposal to extend `engine_t` must account for its new MIT ownership
before implementation; do not add GPL-only fields/code to that fork under an MIT header.
Use **one shared Felucca-Engines fork** for additional reusable engines whose source can
be distributed under MIT. A build profile selects individual engines from that repository;
it does not need one Git repository or submodule per engine. Share the portable contract,
DSP helpers, tables and standalone tests there, with engine-specific source/test files.
Existing firmware-dependent engines (storage, samples, UI, arena lifecycle) stay in
`firmware/src/` until separately extracted and qualified. The additional GPL collection
and mixed-profile direction below supersede the earlier provisional placement rule for
new GPL ports. Do not label GPL-derived work MIT merely to move it into a library.
Repository placement never assigns or changes an engine's stable ID.

Portable changes are committed and tested in Engines first, then consumed by an explicit
Felucca gitlink update. Firmware builds never edit the checked-out dependency or fetch a
floating branch. The full runner checks both standalone engine goldens and the same host
using firmware-generated tables; CI records and checks the clean, committed engine pin.

Second-core support is compiled by default (`FELUCCA_CPU2=1`) but its device preference is
**OFF**. `ON (BETA)` applies after restart; `FELUCCA_CPU2=0` removes its code/stack/buffers/menu.
Both builds remain required evidence. A failed worker is held; unfinished sums are dropped
for that block instead of replaying potentially advanced part state. Later blocks render
serially and the main loop clears the ON preference. Thread equivalence and failure fixtures
do not prove hardware reliability, cache publication, flash quiescence or deadline headroom.
No voltage/clock/FPU change is part of this direction. The independent #44 experiment is
cancelled in favor of continuing with the integrated upstream 1.6.1 approach, including
the backport's reviewed correctness fixes. Its archived hardware checks remain unverified;
closing the experiment does not establish device reliability. It is no longer an active
dependency of engine, profile or mode work.

The capacity plan still applies: moving source does not free a storage sector or authorize
new NOINIT objects. Report measured app/RAM/POOL/RAMTEXT/NOINIT/stack costs for each profile;
the second core's static cost exists even with its runtime preference OFF. Saved mode state,
large donor sample packs and deep patches keep their existing allocations and dependency order.

## GPL collection and mixed engine builds — agreed 2026-10-16

The user requested one additional shared engine collection, named
[`kmplngj/Felucca-Engines-GPL`](https://github.com/kmplngj/Felucca-Engines-GPL), for GPL
engines. Its license, contribution rules, empty design-only catalog and integration
design are published. No engine is implemented there yet; the first firmware pin
and resolver support remain pending. This page does not add a dependency or implement
GPL collection loading.
[Integration #360](https://github.com/kmplngj/Felucca/issues/360) owns that work;
[collection #1](https://github.com/kmplngj/Felucca-Engines-GPL/issues/1) owns the first
WAVE implementation and [Felucca #354](https://github.com/kmplngj/Felucca/issues/354)
owns its host integration/qualification.

The intended arrangement is one firmware build selecting individual engines across the
MIT collection at `firmware/engines/`, the GPL collection at `firmware/engines-gpl/`, and
the existing native catalog. For example, a future custom profile could select MIT
ANALOG/LOFI, GPL WAVE and native FM6. This is a design example, not a profile supported
by today's resolver. The combined firmware remains GPL-3.0-only; MIT files retain
their license and notices. Adapting GPL code under its GPL terms needs no extra
permission, and does not permit offering that derived code under MIT.

Each collection is pinned independently. Extend the firmware-owned resolver, CI,
provenance and complete-source/release tools together: target, host and emulator must
resolve identical source/assets/tests/licenses, and offline source archives must contain
and verify all selected dependency sources and required generators/helpers. A selected
GPL engine requires its clean matching pin and contract; an omitted collection must not
be fetched or needed merely to build a profile without it. Builds never mutate dependencies.

Keep one stable ID namespace and firmware-owned registration/UI identity. Reuse the MIT
engine API and shared DSP without copying them into a divergent GPL interface; WAVE's
main-loop generation/cancellation/publication needs an explicit host bridge. Do not make
the engine collection a second HAL, mixer, MIDI consumer or storage stack. Existing native
engines need no immediate move, and collection discovery cannot change the standard set.

The GPL seed is published. Next qualify its reusable WAVE implementation/service
contract, then pin it into the multi-collection resolver and add an opt-in mixed profile. Require
standard/mixed/omitted builds, stable unavailable-sound round trips, target/host/Wasm
parity, source-archive reproduction and all resource/real-device gates. Collection setup
alone supplies neither a playable WAVE instrument nor target-fit/performance evidence.


## Vocabulary: independent axes

| Axis | Selects | Chosen | Owner |
| --- | --- | --- | --- |
| Build profile | Installed engines, effects, assets, platform features and modes | At build time | [#28](https://github.com/kmplngj/Felucca/issues/28) |
| Usage mode | How the device is played: top-level pages, control policy, allowed transport/recording | At startup | [#203](https://github.com/kmplngj/Felucca/issues/203), [#204](https://github.com/kmplngj/Felucca/issues/204) |
| Part sound | Engine and preset of each of the four parts | By the user, stored | Existing engines/presets |
| Generator provider | A pattern/phrase algorithm a mode or tool can use | Per tool/part | [#214](https://github.com/kmplngj/Felucca/issues/214) |
| View | A presentation such as fullscreen scope or meters | In the UI | [#143](https://github.com/kmplngj/Felucca/issues/143), [#75](https://github.com/kmplngj/Felucca/issues/75) |
| Controller profile | Mapping of an external controller | Device setting | [#166](https://github.com/kmplngj/Felucca/issues/166) |
| Board profile | FM-1 versus other hardware | At build time | [#192](https://github.com/kmplngj/Felucca/issues/192) |
| Content pack | Presets and samples installed into user slots | By the user | Per donor issue |

Engine IDs, mode IDs and generator IDs are separate append-only namespaces. None of them
may depend on how many entries a build includes or on their display order.

A **variant recipe** names one resolved combination: build profile, content pack, installed
modes, controller profile and view. A recipe is how a workflow known from another firmware
is reproduced here (see [Mapping other firmwares](#mapping-other-firmwares)); it is not a
port of that firmware.

## Ownership

- **Core:** HAL, watchdog, bootguard and rescue; audio ISR and TIMER5 scan; the single MIDI
  consumer and queue publication (`RING_PUBLISH()`); note/press-time ownership, voices and
  release tails; the fixed mixer/effect order; the clock; persistence; STOP/panic and the
  global menu. Modes never get their own synth, HAL, USB, MIDI or storage stack.
- **Usage mode:** top-level workflow and pages, physical control map, which actions are
  permitted (transport, recording, sequence participation), and declared bounded
  mode-local state. Unsupported actions are rejected consistently from panel, MIDI,
  controller profile and editor.
- **Engine/effect module:** musical descriptors, presets, edit pages and specialized views.
  The same edit UI is shared by every mode.
- **Generator provider:** a deterministic algorithm with private RNG and bounded state; see
  [#214](https://github.com/kmplngj/Felucca/issues/214).

Felucca's current workflow is mandatory mode 0 and the default. Startup choice is
session-only at first; a remembered default is a later, explicit, versioned setting. Live
switching between modes, per-mode saved sessions and project-driven mode changes are
deferred.

## Constraints in the current source

These are prerequisites. Several plans name them as gates; each now has one owner.

### Engine ID space is full — [#212](https://github.com/kmplngj/Felucca/issues/212)

- [`favorites.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/favorites.c#L5-L8)
  stores favorites as `factory[16][32]` in the settings. Row 14 holds the MIDI Learn map
  ([`midi_learn.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/midi_learn.c#L11-L12),
  compile-time guard `NENGINES <= 14`), and row 15 holds device settings. IDs 0..13 are
  used (1 is the retired DIGITAL, reserved), so `main` has no free engine ID.
- The unmerged [`kori/macro-engine`](https://github.com/kmplngj/Felucca/tree/kori/macro-engine)
  branch ([#27](https://github.com/kmplngj/Felucca/issues/27)) takes ID 14 through a
  one-off appended favorites row (settings layout PER5). The next engine would collide
  with settings row 15. Its full Braids bank leaves 1,204 B of app flash (#27's measurement).
- `NENGINES` is also a value with meaning: the user-preset marker in favorites and in the
  editor's favorite commands
  ([`editor_preferences.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/editor_preferences.c#L101-L123)),
  and `ED_INFO` sends a dense count and name list
  ([`editor.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/editor.c#L459-L467)).
  The marker shifts with every added engine and would differ between profiles.
- 49 `% NENGINES` expressions (mostly `ui.c`, `ui_graph.c`, `ui_layer.c`) map an unknown
  ID onto another engine. A sparse profile catalog would alias stored sounds silently.

About twenty planned engine experiments depend on #212; the issue comments name them.

**Status (branch `feat/engine-id-space-212`, 2026-10-13):** implemented as follows; facts above describe `b04f4fa`.
Engine ids are a fixed space of 64 (`ENG_ID_MAX`, `core.h`); `NENGINES` is only this build's table length.
Favourites have a row per id; MIDI Learn's map and the row-15 device bytes are separate (`settings_ml`,
`settings_dev`). Settings are written as PER4 while no favourite is on an id from 14, else as PER6 (PER4 block plus a
versioned extension with an explicit row count); PER5 is imported (its row is engine 14's). The user-preset marker is
`ENG_USER` (0xFF) internally and 127 on the wire, the old marker (INFO's count) is still accepted. INFO appends
`49 01 64 7F` and an id bitmap after its unchanged prefix. Unknown or omitted ids are kept and shown as N/A (`ENG_NONE`,
silent) instead of `% NENGINES`. `FELUCCA_SLICE=0` is now a sparse catalog (id 13 left out, `NENGINES` stays 14).
A host test build (`FELUCCA_ENG_TEST14=1 FELUCCA_ENG_OMIT=11`) has a placeholder engine 14 and leaves NOISE out.
No new engine id is assigned. Details and downgrade limits: [EDITOR_PROTOCOL.md](../web/EDITOR_PROTOCOL.md#engine-ids-212).

### Flash and retained RAM are allocated — [#213](https://github.com/kmplngj/Felucca/issues/213)

| Range | Use |
| --- | --- |
| `0x97000..0x9EFFF` | Projects 1–4, A/B copies |
| `0x9F000` | FM6 user patches, copy A |
| `0xA0000..0xDBFFF` | User sample slots |
| `0xDC000..0xDFFFF` | User preset banks |
| `0xE0000..0xE4FFF` | OTA staging |
| `0xE5000`, `0xE6000` | Autosave A/B; FM6 voice-bank staging |
| `0xE7000` | FM6 voice bank |
| `0xE8000..` | Stock firmware VM backup, never written |
| `0xFC000` | Settings |
| `0xFE000` | FM6 user patches, copy B |

Source: [`storage.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/storage.c#L20-L31),
[`hal/fm1_flash.h`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/hal/fm1_flash.h#L38-L58).

- A project object is full to the byte: `PROJ_STORE_SIZE 3840u` equals `ST_PAYLOAD_MAX`
  ([`project.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/project.c#L153)).
- NOINIT had 132 B spare in the [2026-10-11 snapshot](development-review-2026-10-11.md);
  retained project copies multiply any growth.
- The settings payload (`persist_t`, about 0.6 KB of 3,840 B) is the only clear reserve,
  and #212 and the remembered startup mode (#204) both want part of it.

Pattern banks, Jam arrangements, generator recall, editable drum kits, deep engine patches,
setlists and Maku likes all need an allocation from #213 before their formats are designed.

**Status (2026-10-14):** the allocation table, options, common rules and proposed follow-up issues are in
[flash-capacity.md](flash-capacity.md), measured at `a373657` (after #212). In short: flash has no free
sector; the settings tail (about 960 B) takes device-wide state; one sidecar sector pair per project takes
per-project state, and its sectors, with the deep-patch, FM6-library and kit objects, come from user
sample slot 3 through an explicit opt-in reclaim; pattern banks (#62) are blocked as specified; NOINIT
(132 B spare) gets no new users. The ranges above are the `b04f4fa` snapshot; the new page has the
current addresses.

### App flash

The dated `main` snapshot had 85,984 B spare; MACRO's full bank would leave 1,204 B.
Donor sample banks alone exceed that: Sloop's five extra sets 141,373 B (#142), Ghoulbox
125,692 B (#133), X0X's 909 samples 221,098 B (#108). Such content is only practical in
a custom build profile or as user-slot packs.

### Boot sequence

[`main.c`](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/main.c#L177-L197)
gates local keys with `kb_boot_hold`, checks OCT−+OCT+ for panel setup, restores the
autosave under a ~400 ms splash during which MIDI IN already plays, then enters the main
loop. The bootguard clears itself at 30 s of absolute uptime
([line 205](https://github.com/kmplngj/Felucca/blob/b04f4fa720a4550c00f042a9eb67f26965784ae3/firmware/src/main.c#L205-L207)).
A chooser must sit before the autosave restore, gate MIDI as well as keys, and restart
the bootguard window when the chosen mode becomes active
([#204 comment](https://github.com/kmplngj/Felucca/issues/204#issuecomment-6124091150)).

## Issue map and order

Sub-issues of [#28](https://github.com/kmplngj/Felucca/issues/28):

| Order | Issue | Role |
| --- | --- | --- |
| 1 | [#212](https://github.com/kmplngj/Felucca/issues/212) | Engine ID space; `NENGINES` no longer stored or sent as a marker |
| 2 | [#213](https://github.com/kmplngj/Felucca/issues/213) | Flash/NOINIT capacity plan |
| 3 | #28 steps 2–4, [#120](https://github.com/kmplngj/Felucca/issues/120) | Manifest/profile resolver, static registration, contributor contracts |
| 4 | [#203](https://github.com/kmplngj/Felucca/issues/203), [#214](https://github.com/kmplngj/Felucca/issues/214) | Usage-mode contract with the Felucca default adapter; generator-provider contract with Euclid ([#124](https://github.com/kmplngj/Felucca/issues/124)) as first provider |
| 5 | [#204](https://github.com/kmplngj/Felucca/issues/204) | Startup chooser, rescue/calibration precedence, bootguard window |
| 6 | [#205](https://github.com/kmplngj/Felucca/issues/205) | Instrument mode, the first pilot |
| 7 | [#207](https://github.com/kmplngj/Felucca/issues/207) stage 1 | Performance track-control pilot; freeze the #203 contract after it |
| 8 | [#208](https://github.com/kmplngj/Felucca/issues/208), [#215](https://github.com/kmplngj/Felucca/issues/215), later #207 stages | Generative, Rhythm; bank/scene launching after [#62](https://github.com/kmplngj/Felucca/issues/62) and #213 |

Instrument mode (#205) mostly disables transport and recording; it exercises little of the
contract (no mode-owned state, scheduler hook or pages). Performance stage 1 is the first
real test of the contract, so the contract is frozen only after it.

## Open decisions

1. **Ambient ([#200](https://github.com/kmplngj/Felucca/issues/200)): mode or overlay.**
   It is planned as enter/exit inside the Felucca workflow, which is a live workflow
   switch. Recommended: make it a Generative-family mode using #214
   ([comment](https://github.com/kmplngj/Felucca/issues/200#issuecomment-6124093303)).
2. **MACRO merge order versus #212.** Either #212 imports PER5 and keeps MACRO at ID 14,
   or MACRO's row becomes an ordinary row in #212's layout and PER5 never ships. The #212 branch
   does both: favourites row 14 is an ordinary row, and a PER5 record is still imported into it, so
   MACRO can rebase onto #212 without its own settings version. Still open: which merges first.
3. **Catalog availability versus presentation.** Every mode exposes the same installed
   engines (#203). Proposed: a mode may set per-part default engines, filter the browser
   and recommend sounds, but never hide or reject an installed engine. This is what
   role-based workflows (Maku roles, ChoralRoot chord/bass, drum-first) need.
4. **Default mode of a custom profile.** The standard release keeps Felucca as default.
   Whether a non-standard profile may ship another default, with Felucca still installed
   and reachable from the chooser, is undecided. Starting with sound already playing
   remains excluded.

## Mapping other firmwares

The [Clipper adoption review](clipper-adoption-2026-10-19.md) adds a staged
VPS/TERRAIN-first instrument experiment through GPL Engines and native optional
profiles. Its synth workflow informs Instrument mode #205; #478 owns the bounded
sample-asset pruning profile experiment. HYBRID/FMX need deep-patch capacity and
producer contracts before client work. These remain plans, not supported profiles.

The [Optimist adoption review](optimist-adoption-2026-10-19.md) maps its browser
builder, instrument auditions and measured optimization candidates to this roadmap
and the existing engine, firmware and WebApp owners. These remain planned work;
the review does not change the supported profiles or standard firmware.

Each donor splits into the axes above. Instruments and presets go through the normal
engine/content path; only the workflow becomes a mode.

| Donor | Profile / content | Usage mode | Other axes | Not reproduced |
| --- | --- | --- | --- | --- |
| Maku ([#202](https://github.com/kmplngj/Felucca/issues/202)) | Recipes, PULSE/BEEP ([#199](https://github.com/kmplngj/Felucca/issues/199)), reverse reverb ([#201](https://github.com/kmplngj/Felucca/issues/201)) | Ambient (#200), decision 1 | – | Playing at boot; removal of sequencer/projects |
| melodee-tess ([#167](https://github.com/kmplngj/Felucca/issues/167)) | – | Generative (#208, providers [#162](https://github.com/kmplngj/Felucca/issues/162)) | – | Sidecar flash map |
| Hortator ([#182](https://github.com/kmplngj/Felucca/issues/182)) | Plaits drums, ACID ([#181](https://github.com/kmplngj/Felucca/issues/181)) | Rhythm (#215) with Grids via #214 | BLE ([#177](https://github.com/kmplngj/Felucca/issues/177)) | Eight tracks, 256-frame halves |
| X0X ([#108](https://github.com/kmplngj/Felucca/issues/108)) | 303/808/909 ([#107](https://github.com/kmplngj/Felucca/issues/107)) | Rhythm (#215) | – | 909 samples in the standard image |
| ChoralRoot ([#189](https://github.com/kmplngj/Felucca/issues/189)) | FM TONE, VA, CZ-1 ([#188](https://github.com/kmplngj/Felucca/issues/188)), HALL ([#187](https://github.com/kmplngj/Felucca/issues/187)) | Performance (#207), strum ([#36](https://github.com/kmplngj/Felucca/issues/36)) | – | Engine restriction per part; removed engines |
| Sloop ([#142](https://github.com/kmplngj/Felucca/issues/142)) | Samples, drum synth ([#141](https://github.com/kmplngj/Felucca/issues/141)) | Performance sections (#207); fills in #215 | Visualizers ([#143](https://github.com/kmplngj/Felucca/issues/143)–[#146](https://github.com/kmplngj/Felucca/issues/146)) | Dedicated drum track outside the four parts |
| Clipper ([#481](https://github.com/kmplngj/Felucca/issues/481)) | VPS/TERRAIN-first GPL pilot, staged synth engines ([#480](https://github.com/kmplngj/Felucca/issues/480)); reduced sample-assets profile (#478) | Instrument (#205) | Modulation #356, tuning #70, MPE #269, delay #73 | Dense donor IDs, repurposed track storage, shared WAVE table policy, 256-frame halves |
| WaveLoop ([#169](https://github.com/kmplngj/Felucca/issues/169)) | Patches, Yama drums ([#168](https://github.com/kmplngj/Felucca/issues/168)) | (Performance) | MiniLab controller profile (#166) | Setlist without an allocation |
| Ghoulbox ([#133](https://github.com/kmplngj/Felucca/issues/133)) | Samples, GURDY ([#129](https://github.com/kmplngj/Felucca/issues/129)) | – | RPG UI/boot scenes as a view | Samples in the standard image |
| JIANT / Jangada ([#137](https://github.com/kmplngj/Felucca/issues/137), [#134](https://github.com/kmplngj/Felucca/issues/134)) | DRUM-X, BYTE/FLOAT ([#135](https://github.com/kmplngj/Felucca/issues/135)), ROBO ([#132](https://github.com/kmplngj/Felucca/issues/132)) | Drone evolution: Ambient/Generative | – | Retired engines, half-rate as a default |
| zp12 / Paula ([#114](https://github.com/kmplngj/Felucca/issues/114), [#190](https://github.com/kmplngj/Felucca/issues/190)) | Sampler engines | A sampler workflow is not planned yet | – | – |
| Doom FM-1/SMK ([#194](https://github.com/kmplngj/Felucca/issues/194)) | Procedural percussion ([#193](https://github.com/kmplngj/Felucca/issues/193)) | None; no non-musical app modes | Board profile (#192) | The game |

Gaps that remain: no sampler workflow, and the Rhythm workflow depends on #212 for any new
drum engine.

## Rules every stage keeps

- Standard and mode-off behavior stays identical: PCM, goldens, controls, boot and restore.
- A non-default mode neither restores nor writes Felucca's autosave; choosing, cancelling
  or idling in a mode writes no flash.
- New stored IDs append; unknown stored IDs are preserved and reported, never remapped.
- Mode and generator work runs at existing control or step boundaries, never per sample,
  and does no allocation, formatting or flash work in interrupts.
- Every stage follows [BUILDING.md](../BUILDING.md) and [performance.md](performance.md):
  unchanged baseline, one cause per change, fresh target build, all-region deltas, and
  real FM-1 checks named when not yet performed.
