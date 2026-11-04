<!-- SPDX-License-Identifier: GPL-3.0-only -->
# OPEN MPK4 adoption review — 2026-11-04

Tracking: [Felucca #837](https://github.com/kmplngj/Felucca/issues/837).

## Recommendation

Adopt selected harmony/performance ideas and study the screen design. Start with
measured improvements to existing UI/history work; audition playable chord-style
recipes through native engines in an optional experiment.

**OPEN MPK4 makes no audio.** Its eight “instruments” are MIDI tracks with channel,
output and note effects. It supplies no audio synthesis engines, sample instruments
or factory synth patches to port. The experimental instrument owner therefore
belongs in Felucca, as a host-owned playing workflow using the existing sound
catalogue, rather than either portable engine collection.

## Reviewed identity and evidence

- Donor: [giusmarci/open-mpk4 main](https://github.com/giusmarci/open-mpk4/tree/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d),
  GitHub repository ID `1445403691`, immutable pin
  `14b01b408ba6fa1d45abb7dbbe321bd97b778b1d`.
- Felucca comparison: freshly fetched main
  `ac86ad10ef382dc5f3e132998806a8b307d70da4`; existing native four-part/strip-rendered architecture.
- Complete non-shallow donor main DAG: **2 reachable commits**, checked with
  `git rev-list --count`, `git rev-parse --is-shallow-repository` and
  `git fsck --full`. This topic snapshot grants **zero per-commit assessments**.
- Read original music/core, application/view, UI/graphics, timing, architecture,
  configuration and licence sources. Inspected representative HOME, track-switch,
  picker, BLOOM, GLIDE, STEP, theme and STUTTER GIF frames. No donor scripts,
  firmware builds, native performance measurements or device tests were run.
- Inventory covered all paginated open/closed issue and PR records plus issue
  comments across the four repositories: Felucca 812 records/1,882 comments,
  Engines 13/32, Engines-GPL 39/42. WebApp access works but Issues is disabled.
  No existing OPEN MPK4 owner/marker was found. Counts precede this intake's writes;
  they are deduplication evidence, not permanent repository totals.
- Canonical watcher branch `9fce2da` validated: 434 journal records,
  427 terminal source/SHA pairs, 37 registered repositories, no pending sources.
  This source is absent there. Existing unrelated history blockers were preserved;
  no sync, frontier, journal, reconciliation or runtime-state change was made.

## Staged delivery and owners

| Order | Work | Owner / decision |
| --- | --- | --- |
| 1 | Measure visual-only cadence independently of musical/input services | New [#839](https://github.com/kmplngj/Felucca/issues/839), default-off A/B |
| 1 | Exact semantic redraw caching; damage/strip budgets | Existing #95/#98 and #59/#102; no competing renderer |
| 1 | Compact edit-history comparison | Existing [#60](https://github.com/kmplngj/Felucca/issues/60), with new pinned take-ID evidence |
| 1 | Exact corner-coverage/blend and existing bitmap resource work | Existing #14/#149/#150; native font/pixel contracts remain authoritative |
| 2 | Six playable chord-style recipes, then bounded RISE/SPREAD | New [#838](https://github.com/kmplngj/Felucca/issues/838), native existing engines |
| 2 | Richer chord shapes/names, timed strum and performance mappings | Existing #273/#36/#33; source evidence added to #36/#33 |
| 3 | Two native panel prototype options, short motion and action-specific feedback | New [#840](https://github.com/kmplngj/Felucca/issues/840); explicit design decision before default changes |
| Later | Free-take capture, duration-aware recording, eight-level undo, generator providers, MIDI-only track | Existing #225/#63/#60/#214/#685 |
| Registration | Pending main-only source, then existing runner initialization | #837 and this registration; review and remote state still pending |

### Features and instrument fit

[Theory](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/firmware/core/theory.c)
provides 27 scale entries, scale/white-key mappings and chord voicing;
[packs](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/firmware/core/packs.c)
provides 53 eight-pad chord-style banks. Native CHORD, voicings, scales and ARP
already exist. Prototype six contrasting banks (Pop 1, Sad 1, Ambient, Jazz 1,
Neo Soul 1 and one audited sparse-scale selection), documenting actual note lists
and any four-note reductions. Native CHORD_MAX is four; donor voicings can produce
more. Native SNAP rounds down, while donor nearest-note quantization ties downward:
do not silently change legacy tuning/key mapping. Keep donor search-heavy smooth
voicing out of the audio interrupt.

[Wheel effects](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/firmware/core/wheelfx.h)
are GLIDE, BLOOM, RISE, SHIMMER, SWELL, SPREAD, STRUM, DENSITY and STUTTER:

| Candidate | Native adoption direction |
| --- | --- |
| RISE / SPREAD | Bounded chord-octave transformations in #838 |
| STRUM | Timed note scheduler under #36, with explicit cancellation/overflow and source ownership |
| BLOOM / SHIMMER | Generated note layers/echo; later bounded paired events and voice/queue qualification |
| SWELL | Velocity/expression articulation; design precedence with existing envelope and CC/matrix controls |
| DENSITY | Existing probability/ratchet/ARP controls as source-aware mappings, not a second sequencer |
| GLIDE / STUTTER | Donor changes MIDI-loop time/pitch or repeats note slices; native audio TAPE/REPEAT is a different mechanism |

The neutral-request catalogue and wheel-zone hysteresis are useful references for
#33. CC1 already drives the native mod matrix; scope, precedence, disable/reset,
held-note cleanup and non-destructive playback behavior need explicit contracts.

The donor [looper](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/firmware/core/looper.h)
uses 96 PPQN, eight tracks, eight patterns, up to 256 track steps, 2,000 shared
events and 16 takes. Native playback/persistence is different. Free-time recording,
independent polymeter, per-track varispeed and mutation are later bounded projects;
do not transplant its engine settings/blob format or eight-track allocator.
More native tracks remains #369; source track count is not an available FM-1 feature.

The donor 8-byte event includes born/dead take IDs; undo changes small stacks and an
applied-ID bitmap rather than copying the event pool. Under #60, compare native
atomic edit deltas against bounded snapshots, including locks/motion and compaction
cost. A 16,000-byte donor event pool is a source capacity, not a native allocation
or measured saving. Native fixed-grid playback cannot simply acquire tombstones.

### Optimization decisions

The most specific new experiment is [#839](https://github.com/kmplngj/Felucca/issues/839).
Donor [ui_frame](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/firmware/src/ui/ui.c)
uses elapsed-time easing and a theme FPS gate (PAPER caps at 12 Hz).
[view_poll](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/firmware/src/app_view.c)
still builds the model before checking that gate. It is a reference mechanism,
not evidence of reduced native audio cost.

Native `music_frame_run/poll` already separates fast input from approximately
15 ms musical frames. UI rolling digits/message/hot/curve/help lifetimes still use
UI-frame advancement. Measure optional 30 Hz visual work first, then a separate
12 Hz static/text variant, while retaining service cadence and establishing an
elapsed-time or independent UI-tick contract. Preserve count-in, REC, capture,
sleep/wake and LCD failure recovery. Naively skipping `ui_draw` would stretch
timeouts and animation; reducing the whole main loop would affect other services.

Donor `lanes()` caches note/tie masks by edit generation, length and visible page;
this strengthens existing #95/#98 semantic invalidation and #813 overview work.
Native signatures and row/meter partial blits already exist. Rounded-corner blend
caching remains #14, font-loop/metadata efficiency remains #149/#150. Fixed-point
math alone is not a new optimization: native DSP already uses it. Do not copy
donor integer 64-bit log/spring calculations or its full redraw/glow passes as
presumed speedups.

For each A/B capture exact unchanged/candidate revisions, JieLi Clang 4.0.1, SDK,
profile, engine pin, assets and flags. Change one cause. Report linked app,
RAM/POOL/RAMTEXT/NOINIT/stack, draw/signature/raster work, windows/bytes/DMA waits,
longest service slice and input-to-visible latency. Preserve PCM, future state and
note timing. Distinguish target static/host results from FM-1 measurements. A negative
result is valid; no speed, RAM or flash gain has been measured in this intake.

### Design direction

The useful qualities are a dominant readout, compact persistent transport,
action-specific performance diagrams and short eased transitions. #840 will compare
a small confirmation/feedback refinement against an optional performance panel
using existing FX. Retain the native 240×240 four-knob grid, M8Stealth roles,
palette/contrast/state-by-form, transport/pattern/REC and actual control hints.
Use the existing native C host renderer and browser replay; require physical
readability and responsiveness before a default visual change.

Donor popup timing (140 ms enter, 800 ms hold, 110 ms exit) is a starting reference.
Compare immediate/static feedback and reduced motion. Native focused values and
curves (#572/#610), HOME TRACKS and #813 remain their own owners. A donor 3×5 font,
new phosphor theme, boot animation or editor redesign is not necessary to capture
these qualities.

Donor rendering uses a full 160×80 RGB565 frame: 25,600 B. At native resolution a
full frame would be 115,200 B, before scratch/DMA ownership needs. Its two-bit
afterglow is 3,200 B at source resolution and would require 14,400 B at 240×240,
plus full-frame work. These are arithmetic bounds, not linked allocations or free
RAM. Keep native strip rendering; prototype small clipped regions instead.

## Platform, compatibility and licensing

The donor runs Artery AT32F405 ARM firmware; Felucca runs JieLi AC791N/pi32v2.
Donor bootloader addresses, flash/storage map, USB/DIN/SPI/timer code and GCC
flags are not a board port. FM-1 TRS is IN; external output is USB through a host,
router or computer. Two USB peripherals need a host; direct host support remains
#289. Reuse #828 device profiles/#34 CC decoding, #280 output clock/transport and
#281/#282 clock reception/timing owners. Stock Akai firmware and OPEN MPK4 output
mappings must be distinguished and verified.

[LICENSE](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/LICENSE)
licenses original work MIT, copyright 2026 Gius.Marci.
[NOTICE](https://github.com/giusmarci/open-mpk4/blob/14b01b408ba6fa1d45abb7dbbe321bd97b778b1d/NOTICE) distinguishes
TinyUSB MIT, Artery library notices and CMSIS Apache-2.0. The checked vendor SPI
source explicitly limits its permission to development with Artery microcontrollers.
Exclude that code and Akai firmware/bootloader data; root MIT is insufficient
permission for every transitive file/asset. Audit selected original core/UI/data
and its closure, preserve notices and document adaptations. No third-party source,
font, artwork or preset asset is copied by this plan.

All current tasks are firmware-host workflows, native UI or integration planning.
No portable audio engine exists here to route to Engines/Engines-GPL. A genuinely
portable collection deliverable needs its own justified boundary before filing.
WebApp-only changes belong in that repository; while Issues is disabled, use the
documented Felucca fallback with an explicit client implementation owner.

## Watch registration and completion

Add `giusmarci/open-mpk4` main as **pending initialization**, retaining repository ID,
immutable pin, two reachable commits and zero review credit. Registration changes
go through ordinary review to main. The existing watcher then reconciles the source
registry to `automation/firmware-watch`, verifies identity/canonical name/branch/pin,
fetches complete history and fresh tip, and initializes only after success.
No new automation, schedule change or completed-coverage entry is appropriate.

#837 remains open for review/registration and later verified remote initialization.
#838/#839/#840 each require a retain/revise/defer/reject outcome. Native implementation,
target fit, physical listening/latency and device compatibility remain pending.

README assessment: existing development direction already describes collecting
features/engines/optimizations and source watch; no available capability changes.
Changelog assessment: planning and pending registration, no merged runtime milestone.
Diagnostic-guide assessment: no command, protocol, capability or measurement change.
