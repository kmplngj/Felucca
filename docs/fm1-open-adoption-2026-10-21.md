<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM1 Open adoption review — 2026-10-21

Selectively adopt FM1 Open's visible source techniques and sound designs through
Felucca's native contracts. The strongest immediate candidates are exact FM6
control-work caching and the existing LCD optimization experiments. Audition
instruments before selecting new ports. The native vendor engine remains a
separately licensed binary SDK, so a whole-firmware merge is unsuitable.

Coordination: [#370](https://github.com/kmplngj/Felucca/issues/370).
This refreshes the earlier V12 issue research; it changes no firmware and claims
no benchmark, measured device improvement or completed instrument port.

## Review provenance

| Input | Revision / observation |
| --- | --- |
| FM1 Open, README V14 | `4c7496daac04a95ff10d1afdcc8f9ead2dbabc41` |
| GitHub repository identity | `m-vave/fm1_open`, ID `1416743005`, default branch `main` |
| Complete donor graph at pin | Eight reachable commits; non-shallow clone; Git connectivity check passed |
| Felucca main | `3b165bae93e0d2ebb74ae9863f05eac93b0af036` |
| Firmware's MIT Engines pin | `9630426f5c4a34a209ca851356fbe8ba3c4c6d19` |
| Native issue inventory | Open/closed issues and comments paginated in Felucca and both engine collections; PR collections paginated in all four repositories |
| WebApp setting | Issues disabled; client work uses the documented firmware fallback |

This is a pinned source snapshot review, not a commit-by-commit historical audit:
**zero completed assessments** are added to the watch journal. Existing V12
roadmap #370, instrument selection #368, feedback specialization #366 and SAMPLE
interior-span #367 remain their owners. Historical intake text stays dated.

## Integration reconciliation — 2026-10-23

The original snapshot evidence and pinned native links below remain dated to the
intake. Reconciliation with Felucca main `f8ed365d845af789ce7237e3bd531f6d0c67fff9`
confirms that FM6 still computes frequency/AM work per operator and the native
canvas remains 240×124 RGB565. No new donor audit or device measurement is claimed.
This handoff also retains the [Clipper](clipper-adoption-2026-10-19.md) and
[Araminta v2.8](araminta-v2.8-review-2026-10-21.md) plans. All are experimental
selection/measurement work; they do not enable engines or change defaults.

## Delivery plan

| Order | Deliverable | Owner and decision gate |
| --- | --- | --- |
| 1 | Lazy exact FM6 AM attenuation cache per sensitivity within one note/block | [#498](https://github.com/kmplngj/Felucca/issues/498): native PCM/future-state equality and measured target benefit |
| 2 | Exact FM6 frequency reuse keyed by the full effective integer input | [#499](https://github.com/kmplngj/Felucca/issues/499): independent experiment; include per-note/arena growth and miss overhead |
| 3 | Feedback add/store loop and SAMPLE no-decode interior spans | Existing [#366](https://github.com/kmplngj/Felucca/issues/366)/[#367](https://github.com/kmplngj/Felucca/issues/367); first check whether the target compiler already provides the win |
| Parallel | Establish transfer/pixel baseline; compare smaller bands and incremental DMA service | Existing #59/#18/#99/#102; one renderer, separate measured causes |
| 4 | Small native content auditions, then one optional mono 303 if justified | Existing [#368](https://github.com/kmplngj/Felucca/issues/368); compare ANALOG and GPL Engines #7 before selecting a source |
| 5 | Distinct 808 voice/kit, then AY/YM PSG and Pluck if worthwhile | Same selection issue; collection tickets follow a chosen source/license boundary |
| Later | One live part survives accompaniment project changes | [#500](https://github.com/kmplngj/Felucca/issues/500): default-off workflow, dormant project data and explicit note/FX/load-gap policy |

Optimization experiments can begin independently of instruments. Keep AM caching,
frequency caching and loop specialization separately measurable. After isolated
results, two accepted FM6 changes could share one bounded hardware-handoff PR,
with a combined resource report and no addition of overlapping savings.

## Optimization fit

The donor's [DX7 note renderer](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/web/synth/dx7note.c#L188-L231)
demonstrates frequency-valid masks and modulation-input/sensitivity attenuation
reuse. Native [fm6_note_compute](https://github.com/kmplngj/Felucca/blob/3b165bae93e0d2ebb74ae9863f05eac93b0af036/firmware/src/fm6_core.c#L519-L544)
still recomputes these values per operator. Use Felucca's expressions and full
effective inputs. Do not copy the donor's gain representation, controller policy,
frequency keys or 64-frame FM quantum into native CTL=32 rendering.

Ordinary native FM6 operators already specialize modulation/add modes outside
their sample loops. The remaining feedback add/store question is #366, not a new
ticket. Gain/send caching #160, idle-track work #161, coefficients #180 and
output work #7 already own other overlapping techniques. Hot-code residency
#459/#6 and FPU #82 are independent experiments; the donor SDK's SRAM-required
symbol list is not source or proof that the same placement fits our linker.

For every retained optimization, establish an unchanged baseline and one-cause
A/B comparison with exact source, dependency, toolchain, profile, flags and asset
provenance. Check PCM and future state, target code/stack, app, RAM, POOL, RAMTEXT
and NOINIT. Test steady hits, continuously changing inputs and transitions under
both worker configurations/fallback. Keep host counts, static target estimates,
browser replay and actual FM-1 deadlines distinct. No speedup is established here.

## GUI rendering: concrete references and existing owners

[app/screen.c](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/app/screen.c#L30-L69)
uses one 240×16 RGB565 composition buffer, per-band left/right damage bounds,
captured display inputs and clipped final-pixel rendering. Its
[flush service](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/app/screen.c#L1650-L1691)
rotates through priority bands, merges new damage into unfinished work and checks
DMA completion before buffer reuse. Input changes can request drawing before the
33 ms animation tick; pending transfer work continues on intermediate polls.

| Concern | Native owner | Comparison |
| --- | --- | --- |
| Bytes/windows/waits and pixel equivalence | [#59](https://github.com/kmplngj/Felucca/issues/59) | Baseline unchanged, small-change, page-change and mixed-load replay before changing transport |
| Smaller canvas | [#18](https://github.com/kmplngj/Felucca/issues/18) | Compare current 124 rows with bounded bands; snapshot logical state once and account for every canvas caller |
| Busy/completion and latest-state coalescing | [#99](https://github.com/kmplngj/Felucca/issues/99) | Compare bounded idle/in-flight/pending service; preserve source-buffer lifetime and avoid starvation |
| Damage representation and strip budget | [#102](https://github.com/kmplngj/Felucca/issues/102) | Horizontal per-band spans versus finite rectangles, including command overhead and full-redraw fallback |
| Unnecessary semantic redraw | #95/#98 | Narrow pixel dependencies; retain required scope/playhead/readiness cadence |
| Transport failures | [#191](https://github.com/kmplngj/Felucca/issues/191) | Stop/retry safely; verify actual DMA abort before releasing borrowed memory |

Native [cv_px](https://github.com/kmplngj/Felucca/blob/3b165bae93e0d2ebb74ae9863f05eac93b0af036/firmware/src/gfx.c#L75-L82)
is 240×124×2 = 59,520 B. The donor band is 7,680 B: **51,840 B gross
buffer difference**, before metadata, snapshots, code and alignment. This is
arithmetic, not a linked net saving. Repeated glyph decode/composition can cost
CPU; splitting unchanged areas alone does not reduce their RGB565 payload.
Preserve native fonts/styles/LARGE, overlays, scroll, animation and sample-wave
readiness; do not multiply a frame's decoder budget by its number of bands.

The donor's 4 ms flush check occurs after a submit. Command/window transfers in
[the LCD adapter](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/app/board/lcd.inc)
still wait: this is not a proved hard 4 ms service bound. The adapter byte-swaps
the submitted buffer in place; native pixels are already swapped. Its timeout,
register reset and CS handling do not prove that our DMA has stopped borrowing
memory. Retain native HAL ownership and independently qualify recovery/SPI timing.

## Instrument experiment and license routing

[#368](https://github.com/kmplngj/Felucca/issues/368) remains the mixed-source
selection/host owner, as required by [the routing review](instrument-issue-routing.md).

| Donor family | Native audition first | Port decision |
| --- | --- | --- |
| DX7 | Existing FM6; recipes and direct SysEx #61/library #318 | No duplicate six-op engine; preserve own-patch semantics and native arithmetic |
| Open303 | ANALOG acid sounds; compare GPL Engines #7 | Optional mono model only after audible benefit, explicit accent/slide/drive and control mapping |
| 808 | DRUM kits and #71/#72; compare GPL Engines #5/#7 | One distinctive voice first; explicit donor part/variant to native lane mapping |
| AY/YM PSG | LOFI | Select only for distinct chip/shared-noise behavior; MIT core and GPL wrapper require separate provenance |
| Pluck | PHYS string models | Eight 1,024-float delays alone cost 32,768 B per instance; native part arenas are 12,888 B. Bound voices/state before a port |
| SEA sampler | SAMPLE/SLICE articulation | Choke/variation/filter behavior first; codec and storage migration remain separate later decisions |

[LICENSE.md](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/LICENSE.md)
licenses the public APP under GPLv3 with an SDK linking exception.
[THIRD_PARTY.md](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/THIRD_PARTY.md)
gives the proprietary binary engine a separate FM1-only grant. Keep it outside
this native integration; browser source is not proof of device-engine parity.

Visible Open303/808/Pluck/emu2149 kernels carry MIT notices; MSFA carries
Apache-2.0. However, their selected include closures reach GPL-with-exception
headers such as `app/synth/fm1_param.h` and `sdk/include/fm1_block.h`.
An MIT source filename does not make that copied closure MIT-compatible.
Before implementation, select exact files and transitive dependencies, retain
individual notices, and decide native ABI replacements versus GPL-derived code.
Then create a linked portable owner in Felucca-Engines or Felucca-Engines-GPL as
appropriate; reuse existing selected engine owners. No new collection ticket is
justified before this boundary and musical selection are resolved. GPL collection
consumption itself remains gated by #360.

V14 explicitly notices Apache-2.0 recovery resources and the extracted original
V15 voice bank. This is useful new provenance, not blanket SDK or asset clearance.
Verify selected bytes, extraction/hash and retained notices before importing
content. No donor source/assets are copied by this review, so LICENSING's current
no-vendor-material statement remains factual; an import PR must revise it.

Felucca owns global IDs, optional profiles, exact pins, shared voices/arenas,
services, persistence/producer protocol and FM-1 qualification. WebApp client
implementation follows a concrete firmware contract. No engine ID is reserved
here. New sounds need declared fidelity criteria; exact optimizations need exact
existing PCM/state. Neither browser timing nor reduced polyphony proves a target
speedup. Maintain six voices maximum per FM6 part and eight shared native voices.

## Features and limits

- V14 PLAY roles are a useful live/accompaniment idea. #500 starts with one of
  four native parts and session-only opt-in state. Project restore currently
  stops sequencing, panics all tracks and installs every sound; dormant project
  data, save/export/undo, note ownership, FX and storage gaps all need a design.
  Keeping one timbre does not imply gapless audio during a flash operation.
- Eight donor tracks remain the existing feasibility study #369. Do not double
  native arenas or reinterpret stored track masks. More lanes, more synth parts
  and pattern banks #62/#319 are different product/capacity decisions.
- DX7 SysEx/library #61/#318, Instrument/Rhythm workflows #203/#205/#215, radio
  #431 and USB input #287 already own related work. The binary SDK's BLE hooks
  are not a bare-metal radio implementation. Storage allocation remains #213.
- Step recording, MIDI routing/clock, tempo delay, mute/solo and sixteen demo
  recipes contain substantial overlap. Select concrete missing behavior after
  comparing native source; sixteen FX demos do not mean sixteen FX processors.

## Watch registration and completion

Register `m-vave/fm1_open` main as **pending initialization**, repository identity
1416743005, immutable historical/recent target at the reviewed pin, eight
historical commits and zero reviews. Preserve every existing pending source and
the canonical state/journal. This PR only changes registration and documentation.

After merge, the existing watcher workflow merges main into its
isolated `automation/firmware-watch` worktree. Its normal sync then verifies
identity, branch, pin and complete DAG, freezes queues and initializes the source.
The requested schedule remains daily 09:00 Europe/Berlin; this reconciliation
does not verify the external scheduler. No second automation or schedule change
is needed. Registration pending review
is not active coverage; snapshot research never advances historical frontiers.

Completion of the proposed work requires measured retain/reject results, a selected
instrument's source/license closure and collection-before-host pin integration,
compatible IDs/data/protocol, full applicable tests/build budgets and real FM-1
listening/deadline/panel/MIDI/USB qualification. Those implementation and device
checks remain pending. This review's README assessment: existing integration-fork
and watcher direction already covers this planning change; no shipped capability
changed. Changelog assessment: no entry for unimplemented plans or registrations.
