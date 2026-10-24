<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Constant-advance font metadata experiment

The #150 candidate reduces the linked app by **576 B** in controlled standard,
CPU2-off and MACRO builds. It preserves all five M8Stealth roles, original
glyph metrics, lookup behavior and rendered pixels. It adds 8 B to the local
`text_run` and track-cushion frames. This remains a draft experiment: full
delivery validation and physical FM-1 latency/stack qualification are pending.
No device speed improvement is claimed.

## Representation and compatibility

The current repertoire has 397 records: 105 each in S/M/N and 41 each in L/X.
Only S/M/N have constant advances, 96/144/288 in 1/16 px. Their records become
six-byte `aag_fixed_t` values: uint16 byte offset, signed int8 left bearing,
then uint8 top bearing, ink width and height. The original eight-byte `aag_t`
also contains uint16 advance; it remains the format for L/X and generic alpha
fonts, including phased glyph arrays.

L/X keep all their original records. In particular, their points retain
128/192 advances while other glyphs retain 272/416. No bitmap byte, sparse
lookup, character order, local mark, capital metric, scale, fallback or stored
preference is changed. L/N/X continue to share M's raster. Keycaps, icon data,
Huffman/ramp caches and raster decoding are unchanged. #149 renderer changes
and PR #605 icon reuse are separate experiments; their savings are not included.

The descriptor has one uint16 `fixed_adv` in previously unused padding.
Zero selects the original record layout; a positive value selects phase-free
compact bitmap records and supplies their advance. The glyph pointer is
`const void *`. The only production layout readers are `glyph_metrics`, which
returns the original record or fills a caller-owned eight-byte scratch record,
and `glyph_advance`, used when only a pen advance is needed. No eight-byte
array cast is made over six-byte storage. Text rendering, track-cushion ink
boxes and ABOUT/credits wrapping all use this seam. The UI test's alignment
hook does too; its conditional work, layout rules and tolerances are unchanged.

The generator computes and validates full original metrics before serializing
compact S/M/N. Compact emission is explicit, requires a positive constant
advance and bitmap scale, and retains all prior narrowing checks. Offset and
advance units are not narrowed. Original generic alpha probes remain supported.

Production compile assertions pin record sizes, alignments and every field
offset, plus descriptor offsets and size. Native pi32v2/Wasm32 use a 36 B
descriptor with `fixed_adv` at 30 and `hc` at 32; a 64-bit host uses 64 B with
those fields at 50/56. Actual JieLi Clang 4.0.1, host arm64 and Wasm32 draft
layout checks pass. The linked target confirms all five 36 B descriptors and
every compact/original record byte. Full rebuilt Wasm/browser qualification
remains separate.

## Controlled measurements, 2026-10-24

Unchanged baseline: `29ad24fdc33617b623c8506cc1283c0208d76cce`, exact Engines pin
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. All three complete baseline builds,
artifact-bound resource verifications and target budgets were archived before
tracked edits. Relative to the older 1523 inventory, only agent/workflow
documents changed; font/build inputs are identical. The live issue's historical
251-record premise is corrected in its [current inventory comment](https://github.com/kmplngj/Felucca/issues/150#issuecomment-6389169311).

Both sides use the same actual JieLi Clang 4.0.1 binary, SHA-256
`c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f`, normal
macOS Docker path, verified AC79NN_SDK_V1.2.1 inputs, product FM-1_900,
`-Os -ffunction-sections -fno-builtin -Wall -Wno-unused-function`, selective
minsize, M8Stealth and no diagnostic flags. Standard/MACRO compile CPU2 support
with its runtime default OFF; CPU2-off explicitly omits it.

Candidate apps were compiled/linked with each baseline's frozen generated
inputs and build identity, changing only `ui_fonts.h` plus the scoped native
schema/accessor/generator sources. No identity-frozen candidate package was
made. These measurement apps must not be installed. A truthful clean candidate
build/package after commit is a distinct delivery gate.

| Profile | App before -> candidate | Net delta | Candidate app spare |
| --- | ---: | ---: | ---: |
| Standard, CPU2 compiled | 496,316 -> 495,740 B | -576 B | 85,824 B |
| Standard, CPU2 omitted | 492,768 -> 492,192 B | -576 B | 89,372 B |
| MACRO, CPU2 compiled | 580,368 -> 579,792 B | -576 B | 1,772 B |

App capacity is 581,564 B. All 397 glyph records, lookup/payload bytes and
descriptors are checked against native ELF symbols. Named font symbols shrink
4,630 -> 4,000 B: 3,176 -> 2,546 B metadata, unchanged 110 B lookups, 1,164 B
unique S/M rasters and 180 B descriptors. The **630 B gross fields** therefore
become 576 B net app reduction after all other linked code/alignment changes.
The remaining 54 B is not attributed solely to one helper. Standard named
helpers include new 44 B `glyph_metrics` and 16 B `glyph_advance`, with other
callers shrinking or growing.

All static regions are unchanged within each pair:

| Region, used / spare | Standard CPU2 compiled | CPU2 omitted | MACRO CPU2 compiled |
| --- | ---: | ---: | ---: |
| Main RAM | 62,392 / 11,336 B | 55,764 / 17,964 B | 62,392 / 11,336 B |
| POOL | 336,440 / 32,200 B | 336,440 / 32,200 B | 354,200 / 14,440 B |
| RAMTEXT | 3,152 / 21,424 B | 2,924 / 21,652 B | 3,152 / 21,424 B |
| NOINIT | 15,576 / 120 B | 15,564 / 132 B | 15,576 / 120 B |

The original floors remain 4,096 B RAM, 8,192 B POOL and 100 B NOINIT. Flash-busy
RAM code and enabled worker machine bytes are byte-identical. Existing guards
retain 916 flash instructions/no calls and 84 worker instructions/its job-only
call policy. Protected ISR/callback closures and their linked static-cost
tuples are unchanged across all profiles; all six target budgets pass without
updating baselines. This does not establish device deadlines.

Main user/supervisor reservations remain 24,320/7,936 B, each with a separate
256 B guard. Compiled worker reservations remain 4,096 B user including guard
and 256 B supervisor, already accounted in RAM; CPU2-off has no worker.
Local prologues change consistently across profiles: `text_run` 164 -> 172 B
and `cv_trk` 60 -> 68 B; `text_w` 24 -> 20, `menu_text` 120 -> 116, `ink_w` 24 -> 16,
`ink_in`/`kh_ink` 28 -> 24 B. These are local allocations, not cumulative stack
high-water marks or live remaining margins.

## Equivalence and host cost

- An independent exported-data probe reconstructed all 397 original eight-byte
  records exactly from the proposed format. Twelve negative controls corrupt
  offsets/bearings or replace L/X point advances; every corruption is rejected.
- The normal `text` suite now includes a checked-in original-format reference
  fixture, frozen from the unchanged header, with retained M8Stealth ancestry
  and CC BY-SA 3.0 data notices. The reference renderer reads those original
  records directly; it does not call either production accessor. All five
  roles and a generic alpha phase-array fixture are covered. All 397 native
  and four alpha-phase records match; 19,440 pen/pixel cases pass normally and
  under strict ASan/UBSan, including missing codes, clipping and point spacing.
- Four generator storage tests pass, including compact constant-advance
  rejection and signed-bearing/u16-offset edges. Upstream atlas checks cover
  367 glyphs at 1x/2x/3x; 190 direct doubled ASCII raster/metric checks, extra
  marks, sharing and spacing pass. Theme, LCD typography and 1,056 track-cushion
  cases pass.
- Matched normal/FM4 UI sweeps have zero lint, contrast/neutral and alignment
  findings. All 3,084 normal + 3,204 FM4 screen PPMs and 12 rolling PPMs are
  byte-identical, with no missing/extra images. Selected HOME, filter, NAME,
  ABOUT/credits and FM6 output was inspected. Legacy stored STYLE/LARGE bits
  are exercised without restoring retired native controls.
- The only target compiler warning is the inherited unused `x` at
  `ui_draw.c:728` on both sides; no new compiler warning is observed.

A separate host Clang 21 `-O2` workload renders 120,000 240x96 frames with all
five text roles, keycap alpha and a Huffman icon, after 200 warmup frames. Four
baseline/candidate samples each use ABBAABBA order under the shared exclusive
host-validation lock. Warm, explicitly cold text/keycap/icon-cache and
theme-changing medians are 0.6578 -> 0.6606 s (+0.4%), 0.6685 -> 0.6821 s (+2.0%)
and 0.6549 -> 0.6632 s (+1.3%); checksums agree. A cold candidate sample reaches
0.8158 s. These noisy host elapsed times establish no speed benefit or target
service bound. An initial 12,000-frame probe appeared faster but is retained
as short preliminary evidence, not used for a speed claim. Whole native UI
render reports retain their own instrumented host timings separately.

Full applicable suite, fresh committed-revision target packages for every
profile, native/Wasm comparison, emulator/browser, service reviews and physical
FM-1 acceptance remain pending. No audio golden, CPU budget or hardware result
is claimed from these focused checks. No golden or resource floor was relaxed.

## Reproduce the comparison

Use a clean recursive checkout, the pinned assets and [build setup](../BUILDING.md).
Select baseline 29ad above and record `git diff`, exact pin, compiler/SDK hashes
and effective flags as described in the [baseline procedure](performance.md#establish-a-comparable-baseline).
For each unchanged profile, run a complete build and archive the root build
files, `build/gen`, loader, matching listing sidecar, identity and resource report:

```sh
rtk proxy env FELUCCA_CPU2=1 FELUCCA_PROFILE=standard uv run --locked --group build ./build.sh
rtk proxy python3 tools/build_report.py --verify build/resource-report.json
rtk proxy python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
```

Repeat with CPU2=0/standard and CPU2=1/macro, retaining separate complete
archives before changing source. Resource verification uses the same explicit
profile/CPU2 environment and SDK/toolchain paths as its corresponding build.
Preserve the full generated directory, not just the font header.

Apply the candidate change in that same baseline checkout. For each profile,
restore its frozen `build/gen` and regenerate only the font header with
`uv run --locked --group build python tools/gen_bitmap_font.py build/gen/ui_fonts.h`.
Require every other generated file to match byte-for-byte. With the same
feature environment set **before importing build**, the controlled compile is:

```python
import sys
sys.path.insert(0, 'tools')
import build as B
import build_report as R
evidence = B.build_app()
errors, notes = B.check(*evidence)
if errors:
    raise RuntimeError(errors)
regions, stacks = R.resources(B, evidence)
```

Archive the returned listing/section/symbol/RAM evidence, raw/annotated IR,
app/ELF and resources. Run its target budget using the matching sidecar. Compare
every original/compact glyph symbol, original L/X periods, five descriptors,
lookup/payload bytes, code, all regions/stacks and protected paths. Do not
package an identity-frozen measurement app.

For reproducible normal-suite correctness after a **fresh** build:

```sh
rtk proxy uv run --locked --group build tests/run_tests.sh --unit text --ai-output
rtk proxy uv run --locked --group build tests/run_tests.sh --unit ui_render --ai-output
rtk proxy uv run --locked --group build tests/run_tests.sh --unit ui_fm4 --ai-output
```

The original-format fixture is in `tests/font_metadata_reference.h`; no ignored
archive is required by the normal text test. Preserve its metrics separately
when evaluating a new representation. Strict sanitizer reproduction compiles
`tests/text_ref_test.c` with `-O1 -fsanitize=address,undefined
-fno-sanitize-recover=all -fno-omit-frame-pointer`, normal generated/source
include paths and `-lm`. Run full applicable checks and the fresh emulator
[browser gate](cloud-testing.md) before handoff. Serialize host benchmarks and
full CPU runs through `/tmp/felucca-backlog-validation.lock`.

The executed capture/trial/probe/analysis/benchmark scripts, exact source and
artifact hashes, logs, original/encoded records, complete UI outputs and
comparison JSONs are retained under ignored `build/issue150/` in the experiment
worktree. These private artifacts supplement the commands and checked-in
oracles; they are not a firmware distribution.

## Remaining acceptance and documentation assessment

Retain or reject this candidate separately from other font/UI work. Before
acceptance, compare the same exact baseline/candidate profile, settings and
runtime CPU2 choice on an FM-1. Check text-heavy NAME, ABOUT/credits wrapping,
large L/X values and decimal points, every palette and track cushions; then
exercise dense redraw/control traffic during four-part audio with USB at 44.1
and 48 kHz plus MIDI. Follow the [performance workload](performance.md#device-timing-and-stress-procedure)
and [diagnostic interpretation](diagnostics.md): compare lateness, render maxima,
nested scan cost, shedding and USB/MIDI errors separately. The additional local
frames need nested-interrupt stack qualification. Equal host pixels do not
prove physical LCD behavior, runtime latency or live stack margin. No device
flash, listening, timing, panel or stack measurement has been performed.

README assessment: its introduction and Development direction/process already
cover CPU/RAM/size experiments, sound/compatibility preservation and pending
hardware checks. There is no new engine, display behavior, installation or
product-overview change, so no README edit is required. The changelog adds one
grouped Optimized metadata entry linking this measured result and qualification
limits. The typography guide links the representation evidence. Diagnostic
activation/defaults, transport and fields do not change, so no diagnostic guide
inventory update is needed. Original fonts/atlases, existing notices and license
terms remain untouched; the test-only metrics fixture retains its data notice.
