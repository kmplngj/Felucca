<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Shared parameter metadata: consumers and a minimal proposal

Research for [#31](https://github.com/kmplngj/Felucca/issues/31), inspected
2026-10-24–25 at firmware `2579e55791df0ccc2d72f35177526248d75cbc79` and Engines
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. The live issue and its empty comment
list were checked. This report completes the requested consumer audit, proposal,
estimates and contract-test plan; it implements no metadata API or control mode.
No runtime, descriptor layout, wire field, stored value or baseline changes here.

Reuse `param_desc_t`, `track_desc`, `param_desc_of` and the existing knob resolver.
The useful missing piece is a small description of the **control in its current
panel context**, not another authoritative parameter database. Static wire
descriptions and dynamic panel presentation deliberately answer different questions.
Keep both. A numeric range alone cannot establish action behavior, interpolation
safety, editing focus or capture eligibility.

The merged [control contract and test plan](control-contract-and-test-plan.md)
from [PR #603](https://github.com/kmplngj/Felucca/pull/603) owns value lifetimes,
overlap policy and the broader regression plan. Its D1–D5 remain open. This report
chooses no A/B storage, scene/morph behavior, target-selection policy, simultaneous
writer precedence, KEEP semantics or new base/effective readback. Unmerged
[PR #597](https://github.com/kmplngj/Felucca/pull/597) is outside this baseline.

## Evidence and consumer/gap matrix

Commit-qualified source links below are evidence for this revision; relative links
are navigation. This is source inspection, not a run of those tests. The portable
[descriptor declaration][descriptor] already supplies label, format, min/max,
default, names and optional unit. `engine_t.edit[8]` owns canonical engine-slot
descriptors; the optional engine `desc` hook may change presentation while retaining
range/default. Common and global descriptors remain host-owned `TP` and `GP`.

| Consumer or context | Current source of truth / intentional behavior | Gap or constraint for shared metadata |
| --- | --- | --- |
| Ordinary panel cards, HOME and pages | [`home_param`][home], [`page_desc`][page] and [`track_desc`][lookup] resolve requested engine, selected track, HOME LEVELS and MOD slot; [drawing][cards] formats the resulting control | Reuse this resolution. A descriptor alone omits resolved scope/track/id and whether this cell is a value, selector or action |
| Knob editing and MOMENTARY availability | [`knob_here`, `mom_target`][knob] share target resolution; write/capture/LEARN stay in `knob_edit`/`mom_turn`. MIXER MUTE is direction-based permanently, numeric momentarily | Preserve these policies. Read queries must not call `knob_value`: its acceleration helper changes timing state even before a parameter write |
| Dynamic engine E slots | [`track_desc`][lookup] uses `eng_req`, not the old sounding engine during a fade. [ANALOG][analog] changes SYNC/SUB presentation; [PHYS][phys] selects model-dependent labels/names. [LOFI][lofi] and [NOISE][noise] have further descriptor hooks at the pinned Engines revision | Resolve with current mode; fall back to `edit[k]` on a null hook. Do not change raw IDs/ranges/defaults or cache only by slot number |
| MACRO display words and values | [`ui_param_label`, short labels and formatting][presentation] add model-specific words and FBFM COLOR semitone display. Canonical DESC remains SHAPE/TIMBRE/COLOR and raw COLOR 0..127 | Descriptor sharing does not erase this presentation adapter. Short labels and value transformations need explicit UI context |
| INSERT A/B/C | [`ins_desc`][insert] and `track_desc` select DRIVE/TONE/LEVEL, CRUSH names or swept-effect controls by TYPE. Static descriptors stay generic INS A/B/C | Invalidate panel descriptions when TYPE changes. Keep ids 97..99 and raw 0..127; editor generic metadata is deliberate |
| ENV SYNC | [25 named buckets][esync] replace TIME presentation for ATK/DEC/REL. These are **named F_INT**, with raw 0..127 and unchanged defaults; [turning][turn] lands at bucket starts | `fmt == F_ENUM` is insufficient to detect a stepped presentation. Never replace the raw value merely because its displayed bucket is read |
| Enum ordering, aliases and unavailable choices | [`enum_orig`, `enum_skip`, `enum_rank`, `param_turn`][turn] preserve retired values/aliases, skip empty FM6 bank slots and use explicit musical division order | Stored numbers, display rank and legal knob successors are different. Do not reorder IDs to match labels or infer turn semantics from a names pointer alone |
| Action, selector, empty and fixed cells | [`act_cols`][actions] plus [input routes][input] own action/selector behavior; fixed `min == max` and an empty page cell differ. LFO RATE with SYNC is additionally displayed dim while its stored range remains editable metadata | Classify the current control, not the parameter globally. N_GO or F_ENUM is not an action contract; display dim is not a universal write prohibition |
| Selected DRUM lane versus sounding note | Explicit [grid selection][grid] and [layer key selection][lane-layer] write `ui.lane`; [drum note-on][drum] maps each sounding note to its own lane. [Input notes][note] also update `last_note` for performance/display uses | Keep editing lane explicit. Neither the latest note nor a voice's lane is the selected parameter/drum focus; future descriptions must not make playback navigate the editor |
| Editor DESC and library/export tooling | [`ed_desc`/DESC][editor-desc] use static `param_desc_of`/GP; [`descdump`][descdump] emits host-side JSON from real descriptors. [Protocol][protocol-desc] bounds strings/enum counts and documents [INSERT][protocol-insert], [ENV SYNC][protocol-esync] and [MACRO][protocol-macro] differences | Reuse static descriptors and generation outside firmware. Dynamic semantics need a separately agreed, versioned protocol extension and client work; none is added here |
| Motion, MIDI and render constraints | [Motion validation][motion] and [absolute CC scaling][cc] use canonical descriptors; [render modulation][mod] uses the sounding engine and restores temporary values. Recording/LEARN support have their own allowlists | A UI description must not become a new render lookup or imply every numeric parameter can be recorded, learned or interpolated |

The audit covers firmware producers, native panel/input/drawing, descriptor export
and protocol documentation. It does **not** inspect the maintained
[Felucca-WebApp](https://github.com/kmplngj/Felucca-WebApp) implementation or establish
how its current sliders, libraries, caches or dynamic labels behave. The old `web/`
protocol document and `tests/descdump.c` are not a client audit. Any client change
belongs in that repository with its own fixtures and compatibility checks.

## Proposed read-only seam and ownership

The existing knob Module already has useful Depth: a small target Interface hides
HOME, MIXER and page resolution. Extend that existing ownership only when a concrete
consumer needs it. The proposed first Seam is a main-loop control-description query
alongside those resolvers, shared by **ordinary card drawing** and **MOMENTARY target
availability**. Their real caller paths are `draw_column_values → home_param/page_desc`
and `mom_status → mom_target → knob_here`. Special graph/gesture routes remain with
their existing owners; do not route every UI through a generic engine/plugin layer.

The proposal's logical schema is deliberately small; these are design concepts,
not new C declarations or wire fields:

| Description element | Meaning and owning source |
| --- | --- |
| Stable identity, when a parameter exists | Scope, explicit track index and numeric parameter id; resolve HOME LEVELS and MOD slot before returning it. Labels are presentation, never identity. Action/selector cells without a parameter return no parameter identity |
| Canonical descriptor | Borrowed `const param_desc_t *` from `param_desc_of` or GP. No copied strings/tables and no widening of the portable struct |
| Panel presentation | Borrowed dynamic descriptor plus the existing label/short-label/format adapter, resolved once for this context. Wire callers continue using their static path |
| Control role | Value, fixed value, selector, action or absent, derived from the page/gesture owners. This does not authorize execution, capture, LEARN or MOMENTARY; those policies stay with their current functions |
| Explicit focus input | Current track/page/knob and any selected lane/operator/MOD slot supplied by the owning UI context. Note-on/playback state is not a focus setter. No new stored focus is proposed |

Return metadata without a writable value pointer or an executor callback. A caller
that needs a value performs its existing, explicitly named control/base read; a
description query must not silently normalize, clamp or commit it. An editing
Adapter can keep the existing writable `knob_target_t` privately; it must retain
MIXER MUTE, acceleration, motion and LEARN rules. The read query supplies facts,
not an alternative write helper. The potential permanent-edit helper in #603 is
separate and still gated by D4.

This Seam is justified only if it removes duplicate context interpretation in the
two real consumers. A wrapper that simply forwards to `track_desc` adds little
Leverage: delete it and retain today's helpers instead. Prefer Locality in the UI
owner over another registry. Ordinary HOME/MIXER/page resolution and action/selector
classification are real variations already present; no hypothetical plugin Adapter
or runtime JSON parser is needed. Wire DESC is not forced through a UI context.

Keep grouping in the existing page/family tables. Keep portable numeric/enum
descriptors in the exact Engines source pin; a reusable layout change would need an
Engines PR/API review before the firmware pin changes. Felucca owns common/global
parameters, host presentation, control role/focus, stable IDs and protocol production.
Felucca-WebApp owns client consumption. No new schema version or runtime flags are
allocated by this report.

For possible performance controls, continuous raw range, discrete raw enum,
named/bucketed presentation, action and fixed value are useful distinctions, but
they do not decide morph eligibility. An enum could have an approved switch policy;
a numeric parameter could select a model or cross a discontinuity. Eligibility,
interpolation law, target binding across engine changes and A/B lifetime remain
unclassified until a concrete feature makes those product decisions. Do not add a
default “morphable” bit inferred from format or advertise unsupported controls.

## Observation, caching and compatibility rules

1. Resolve only on the main loop. No allocation, I/O, encoder consumption, timing
   reads with side effects, parameter writes, motion capture, LEARN picks or sound
   publication in the query. Existing [`param_format`][format] may write its output buffers
   and `fmt_named` presentation scratch; “read-only” here means no musical/focus/
   edit-timing mutation, not that drawing writes no pixels or scratch.
2. Make read cost explicit: at most four control queries for one four-card pass;
   MOMENTARY availability scans at most four targets per `ui_input`, as today.
   Reuse a result for that pass rather than re-resolving label/range/status at each
   subwidget. These are proposed caller budgets, not measured whole-frame totals.
   Formatting, graph drawing and today's additional label lookups need separate
   accounting. Engine descriptor hooks must remain bounded, immutable-table reads.
3. Start with pass-local descriptions and existing draw invalidation. A persistent
   cache would need keys for requested engine, mode selectors, INSERT TYPE, ESYNC,
   track, page/slot, HOME LEVELS, selected lane/operator and relevant load generation.
   Value formatting must see current values; pointer stability alone is not a cache
   key. Verify invalidation before adding caching; keep selectors out of interrupts.
4. Bound string/name reads. Current F_ENUM formatting indexes a validated value;
   named F_INT formatting scans a zero-terminated list. The concrete ENV list has
   25 names, INSERT lists 16 and LOFI DCY 32; do not turn that into an unbounded future callback.
   A follow-up must test termination/count contracts without extending the wire or
   portable struct merely to avoid a bounded scan. DESC keeps at most 24 enum names
   of width 8, except MACRO's 48 of width 12, inside its 664-byte reply.
5. Preserve numeric engine/parameter IDs, enum aliases, raw domains/defaults,
   parameter-count mapping and every existing wire reply. At this revision
   `P_E0=103`, `P_COUNT=111`, `G_COUNT=27`. [Native extension rules](extending.md#15-parameters)
   define count-based import; label changes must not redefine a stored ID.
   A new client-facing description needs an additive negotiated contract and old
   client tests, not a silent change to DESC, GET/WATCH or DUMP.

The static table approach costs no per-sample discovery and preserves a single
numeric authority. Host generation such as `descdump` can share those tables without
runtime parsing, but generated client data must carry provenance/profile and be
regenerated from the selected exact pin. It cannot infer native UI gestures,
momentary policy or engine-mode state solely from static JSON.

## Resource estimates, not target measurements

This patch changes Markdown only. No new compiled data, executable input or ISR
work is introduced; no target size, cycle or RAM delta was measured. The following
are planning arithmetic for a later candidate, not an optimization claim:

| Candidate choice | Estimate and limitation |
| --- | --- |
| Reuse existing descriptors | Zero new descriptor/string copies by design. Under 32-bit pointers and 4-byte alignment, today's fields imply 20 B per `param_desc_t`; ABI/ELF evidence is still needed before using that as a target measurement |
| One compact transient description | For example, two borrowed descriptor pointers (8 B), a 16-bit id, 8-bit scope/track/role and three padding bytes imply 16 B with 4-byte alignment. This omits separately passed focus/context and label/format scratch; it is not a committed struct layout |
| Four transient results | Four such 16 B descriptions imply 64 B of scratch if all are live together. Querying/consuming one at a time could avoid that array. Compiler saved registers, spills and the complete caller frame remain unknown; do not assume stack is reclaimed before a nonreturning caller ends |
| Dense semantic annotations, if later justified | One byte per 111 track plus 27 global parameter IDs is 138 B of logical const data, before alignment/relocations. This cannot represent page-dependent actions by itself; do not allocate it speculatively |
| Persistent per-track copies/cache | Not proposed. Four full 111-value int16 copies alone would be 888 B, with no resolution of #603's value-lifetime decisions. Cache keys and invalidation would add state |
| ISR/POOL/NOINIT and flash/RAM totals | Proposed query stays main-loop-only; add no render calls, retained state or publication object. Exact code bytes, linker padding, RAM versus POOL placement and stack/cost changes require unchanged/candidate target builds and protected-path checks |

A runtime follow-up must follow [performance.md](performance.md): fix one cause,
capture the unchanged revision/profile, inspect linker regions and full frames,
run focused/full applicable host checks and target budgets, then measure loaded
FM-1 redraw/knob/audio timing if behavior or workload changes. Host/static counts
do not prove hardware deadlines. No estimate here justifies a baseline update.

## Proposed contract cases and delivery gates

Existing tests already cover key behaviors: [#295 status inspection][status-test]
checks 480 no-turn frames without edit/capture/timing changes; [MACRO UI tests][macro-test]
check canonical versus panel words and read-only preview; [editor tests][editor-test]
check the 48-name descriptor and stored round trips. The #603 plan audits additional
motion, enums, CC, acceleration and combined-control coverage. Reuse those real-source
harnesses; do not present their existing assertions as missing or newly passing.

| Proposed case | Exercise and independent expected result | Likely harness / gate |
| --- | --- | --- |
| M1 identity and context | All four ordinary HOME/HOME LEVELS/MIXER/page cells, MOD slots and two tracks: description resolves the same numeric owner as actual editing. Changing display text never changes ID; MUTE's two edit policies remain characterized | `ui_test.c`; compare to actual turn/write destination, not a second copy of the proposed resolver |
| M2 dynamic modes and cache invalidation | ANALOG SYNC/SUB, LOFI/NOISE modes, PHYS models, INSERT's nine TYPEs, ENV SYNC OFF/ON, optional MACRO model changes, track switch and load. Panel text/format follows new context; canonical ranges/defaults/raw values and DESC bytes stay unchanged | UI + editor harnesses; include profiles with optional engine absent and unknown engine fallback |
| M3 stepped presentation | All 128 ENV raw values map to `v * 25 / 128`; one turn uses the independent bucket-start formula `(k * 128 + 24) / 25`. Query/format preserves raw values. Division display rank, retired aliases and empty FM6 slots preserve established order/normalization | Extend existing enum/ENV tests, reuse #603 P5; do not require raw numeric monotonicity of musical order |
| M4 role versus execution | Every ordinary/action/selector/empty/fixed page class: repeated describe/status/draw calls execute no action and consume no delta. Turn/OCT execution still takes the original route; fixed-page/MOMENTARY refusal does not invent a new fixed-HOME policy | UI input/action counters and #603 P6; #597 behavior remains conditional on adoption |
| M5 observation and read budget | Snapshot parameters, engine memory, selection/lane/operator/MOD focus, motion, LEARN and acceleration state; query all four cells repeatedly. Those remain unchanged; instrument at most four resolutions per proposed card pass and four per availability scan | Extend existing status/preview fixtures; allow output buffers, draw caches and `fmt_named` scratch to change |
| M6 explicit drum focus | Select one editing lane, play/sequence different GM drum notes and describe/redraw repeatedly. Selected lane/parameter identity remains fixed; explicit lane navigation changes it. Sounding notes still map to their own voice lanes | `ui_test.c` plus note/sequence paths; `last_note` updates are allowed and must not become focus setters |
| M7 static editor compatibility | Request DESC before/after each panel-mode change, GET/WATCH versus DUMP/base, invalid scope/id and fixed controls. Preserve existing command-specific behavior, bounded name/string replies, stable raw IDs and old count mapping | `editor_test.c`, `descdump.c`, existing project/preset tests; no new fields or broad wire rewrite |
| M8 performance-control semantics | When a concrete feature is approved, distinguish continuous/discrete/action/fixed/unsupported targets; test interpolation law and engine/track rebinding against its explicit product contract | Future feature owner; no eligibility oracle, A/B behavior or D1–D5 policy is invented in this report |

First implement only the missing characterization/integration cases needed by a
chosen consumer, then evaluate whether sharing the resolver removes enough duplicate
logic. A runtime change needs exact-revision validation. Native generated images,
browser replay and physical panel/display/audio/MIDI qualification apply **if an
implementation follows**, with routes written against that candidate. They are not
gates for accepting this proposal and were not performed for this documentation.

For this report, verify source anchors, local links, arithmetic, issue-criterion
coverage and `git diff --check`. No firmware build, host suite, browser run or FM-1
flash/test is required: executable inputs and user behavior are unchanged.

README assessment: “Development direction and process” already describes reviewing,
compatible integration and measured follow-up; no capability, engine, install path
or compatibility behavior changes. No README edit. Changelog assessment: no entry;
this research delivers no implemented control capability or optimization. The small
link in the native parameter guide makes the research discoverable without listing
planned semantics as shipped features. Runtime/protocol usage guides should change
with their eventual implementation, not with this proposal.

[descriptor]: https://github.com/kmplngj/Felucca-Engines/blob/9630426f5c4a34a209ca851356fbe8ba3c4c6d19/src/felucca_engine.h#L100-L114
[home]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui.c#L1908-L1915
[page]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/params.c#L503-L522
[lookup]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/params.c#L223-L243
[cards]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui_draw.c#L866-L886
[knob]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui_knob.c#L29-L164
[analog]: https://github.com/kmplngj/Felucca-Engines/blob/9630426f5c4a34a209ca851356fbe8ba3c4c6d19/src/eng_analog.c#L35-L42
[lofi]: https://github.com/kmplngj/Felucca-Engines/blob/9630426f5c4a34a209ca851356fbe8ba3c4c6d19/src/eng_lofi.c#L44-L57
[noise]: https://github.com/kmplngj/Felucca-Engines/blob/9630426f5c4a34a209ca851356fbe8ba3c4c6d19/src/eng_noise.c#L20-L53
[phys]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/eng_phys.c#L62-L77
[presentation]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui.c#L1917-L1959
[insert]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/params.c#L157-L183
[esync]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/params.c#L23-L37
[turn]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/params.c#L245-L317
[format]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/params.c#L319-L429
[actions]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui.c#L1981-L2010
[input]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui_input.c#L970-L1008
[grid]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui_input.c#L615-L668
[lane-layer]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/ui_layer.c#L666-L681
[drum]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/eng_drum.c#L201-L226
[note]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/seq.c#L673-L685
[editor-desc]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/editor.c#L283-L296
[descdump]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/tests/descdump.c#L36-L94
[protocol-desc]: ../web/EDITOR_PROTOCOL.md#5-desc
[protocol-insert]: ../web/EDITOR_PROTOCOL.md#insert-effect-parameters
[protocol-esync]: ../web/EDITOR_PROTOCOL.md#filter-type-and-env-sync-parameters
[protocol-macro]: ../web/EDITOR_PROTOCOL.md#optional-macro-profile-27
[motion]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/motion.c#L166-L180
[cc]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/midi_control.c#L225-L235
[mod]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/mod.c#L209-L245
[status-test]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/tests/ui_test.c#L10668-L10680
[macro-test]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/tests/ui_test.c#L11683-L11708
[editor-test]: https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/tests/editor_test.c#L1443-L1495
