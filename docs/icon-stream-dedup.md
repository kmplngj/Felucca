<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Exact icon-stream reuse

## Delivery and evidence scope

The stream-reuse implementation is carried with the native attribution correction
in [PR #596](https://github.com/kmplngj/Felucca/pull/596), preserving their separate
logical commits. Its current validation and exact build identities are recorded
in that PR. Standard full CI covers the real C icon oracle, strict sanitizers,
ABOUT navigation and scrolling, normal/FM4 native renders and the browser gate;
the optional MACRO profile needs its own target resource/budget check.

The sections below retain the **2026-10-24 experiment**, source pins and measured
208 B result. Those are not a new combined-build saving, and cannot simply be
added to another PR's size change. Identity, flags and generated inputs must be
reported with any later comparison. This bounded data representation changes no
decoder/cache code or decoded pixels; physical LCD and device-timing observations
remain separate and unperformed. No device speed gain is claimed.

Candidate for [#96](https://github.com/kmplngj/Felucca/issues/96), refreshed against
main `3fce9f9f4d63b56aecfdc0e7e2d35d4271878bcf`, 2026-10-24. Only identical complete
12 px icon streams share storage. The shared Huffman codebook is still computed
from **all** unchanged cells of every size before deduplication. No decoder,
renderer, icon identity, input font, typography, phase count or protocol changes.

Focused export and independent C pixel checks pass on the refreshed candidate.
Matched current-base target/resource checks and the controlled screen/header
comparison pass: both target variants retain 208 B less linked app with unchanged
static RAM regions. At signed `7736398b34bebbdd810fb8fd0d5feeaf00fb2bd7`, the full
macOS suite completed with 125 passed, four failed, one blocked and three explicit
not-applicable units; all four failure types reproduce on the clean `3fce9f9`
baseline. The fresh browser gate passed all ten checks, and native/Wasm emulator,
replay and partition checks passed. Hosted CI and FM-1 qualification remain
separate pending gates. No device speed gain is claimed.
No alternative codec or font representation was trialed.

## Recorded native UI integration (2026-10-24)

The normal merge of `3fce9f9` into the previous candidate `70b8794`
completed without conflicts and was signed as
`e1e7d4c969cc66334b5da897a60af1c37c33392a`. It retains
main's native UI, assets, font retirement and readability tests. The focused
Python test now imports the relocated Huffman helpers from
[ui_font_data.py](../tools/ui_font_data.py); the generator retains that module's
import and attribution. The helper implementations, icon rasterization, Fukiai
font, icon-name input and production icon consumers are unchanged from the prior
base. No source or generated output was taken from a donor.

The initial focused check regenerated only its four required UI headers.
That check records HEAD `70b8794f-dirty` and MERGE_HEAD `3fce9f9`; its initial
provenance is distinct from the subsequent clean target builds below. Evidence is under
`build/issue96/main3fce-focused/`, with `asset-provenance.json`,
`candidate-inventory.json` and `focused-results.json`.

The current candidate export SHA-256 is
`ea2e2a6165977b15655c0ecd5aa9f1b7e033229b8eab8e6ffd7d1474490dfd3e`.
It contains 105/39/6 cells at 12/16/24 px, respectively; DATA sizes are
3,486/2,311/508 B including two final zero lookahead bytes per size. The shared
book remains 57 B and all named icon arrays total 7,343 B before linking.
The 12 px cells have 99 distinct start offsets; every cell retains its IDX/OFF/INK
entry. These are exported-array counts, not a new linked saving or runtime claim.

The actual `icon_streams` runner unit passes all four Python tests without skips
and 48,000 real C raw-alpha/Huffman canvas comparisons plus boundary fixtures.
The actual `asan_icon_streams` unit repeats the C checks with strict ASan/UBSan
and passes. The same-host raw oracle is regenerated directly from unchanged raster
inputs, independently of candidate DATA/OFF. Logs retain the existing font
`post.stringData` diagnostic and Pillow's missing-Raqm fallback warning. These
focused units do not establish full-suite or CI coverage.

The preserved pre-change Mac raw-array oracle was also freshly rebuilt against
the current candidate source and headers: 48,000 comparisons pass normally and
under strict ASan/UBSan. `preserved-results.json` records commands, source hashes
and verification that the oracle differs from the original only in its harness
include path; its raw expected arrays were not regenerated from the candidate.

The coordinator separately captured a clean exact-`3fce9f9` baseline with header
SHA-256 `5332c159a635d6647080cd3555af110d51b735b9f90284dfa72c6b37e441faa2`.
Its inventory is 105/39/6 cells, DATA 3,694/2,311/508 B and a 57 B shared book.
The controlled A/B uses the same current source, generated assets and build
identity, replacing only the icon header in an isolated include directory.
All 3,084 screen PPMs and six rolling PPMs are byte-identical, with no missing or
extra files. The baseline covers 257 scenes in ten palettes plus the page/value
sweep: zero lint findings and zero off-center findings over 2,817,481 alignment
measurements. The clean-baseline worktree retains
`build/issue96-main3fce/controlled-ui-comparison.json`. This establishes that
header substitution preserves the current native screen pixels; it is not a
browser, full-suite, device or performance result.

Fresh clean target baselines are also complete under the coordinator's control:

| Current `3fce9f9` baseline | App | RAM | POOL | RAMTEXT | NOINIT |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default CPU2 support, runtime default OFF | 496,316 B | 62,392 B | 336,440 B | 3,152 B | 15,576 B |
| `FELUCCA_CPU2=0` | 492,768 B | 55,764 B | 336,440 B | 2,924 B | 15,564 B |

Fresh clean candidate `e1e7d4c969cc66334b5da897a60af1c37c33392a` passes target
instruction budgets, package validation and artifact-bound resource verification
in both matched variants:

| Current candidate | App | App delta | RAM | POOL | RAMTEXT | NOINIT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Default CPU2 support | 496,108 B | -208 B | 62,392 B | 336,440 B | 3,152 B | 15,576 B |
| `FELUCCA_CPU2=0` | 492,560 B | -208 B | 55,764 B | 336,440 B | 2,924 B | 15,564 B |

`build/issue96/main3fce-targets/comparison.json` records every region and stack
reservation, compiler/tool/SDK hashes, flags and effective defines. They match
within each pair except the explicitly recorded build/splash revision and
source-derived profile digest. The initial standard candidate explicitly set
CPU2 to 1; that successful artifact is retained separately, and the standard
candidate was rebuilt with the baseline's exact default invocation. Both produce
identical app bytes. The table uses the latter matched invocation.

Fresh ELF symbol bytes confirm 7,551 to 7,343 B of linked named icon arrays;
`cv_alpha_hc` is byte-identical within each variant and its 516 B Huffman cache
is unchanged. RAM, POOL, RAMTEXT, NOINIT and all stack reservations are unchanged.
The builds retain the same pre-existing `ui_draw.c` unused-variable `x` warning
as both clean baselines; no new target compiler warning was introduced. Existing
font-table diagnostics and Pillow's missing-Raqm fallback are retained in logs.
These are target/static and same-host pixel results, not FM-1 timings.

Native text is now M8Stealth only, with S/M bitmaps and shared integer-scaled
L/N/X roles. [DESIGN.md](../DESIGN.md), [PRODUCT.md](../PRODUCT.md) and
[lcd-typography.md](lcd-typography.md) remain authoritative. The two style values
in the low-level pixel oracle are retained internal compatibility coverage;
STYLE and LARGE are retired native choices, not extra menu routes to test.
Their reserved stored/wire values remain unchanged. Current screen acceptance
must use the unified native layout and preserve its graph, focus and rolling
behavior, without restoring old font or layout alternatives.

## Completed recorded integration checks (2026-10-24)

The final `7736398` standard target build is clean and retains app 496,108 B,
RAM 62,392 B, POOL 336,440 B, RAMTEXT 3,152 B and NOINIT 15,576 B. The preceding
matched two-variant comparison at `e1e7d4c9` is recorded above; the only subsequent
source change was this report's measurement update, not firmware behavior.

The full macOS invocation used the documented build dependency group, Node 22,
configured DaisySP, resolved macOS TMPDIR and Homebrew's library lookup path.
`build/host/test-run-s4ghyjhs/summary.json` records **125 passed, four failed,
one blocked, three explicit N/A, zero skipped/cancelled**. The original run
remains failed. `loader` and the firmware engine-contract fixture reject target
ELF section attributes under Mach-O; failed `loader` blocks `asan_loader`.
SPRING costs 119 versus ROOM 90 instructions/sample (30% limit). ANALOG has
three O2 CPU budget overruns in standard and CPU2-off, while Os has none.

All four failures were freshly reproduced by the corresponding units at clean
`3fce9f9`; their logs are retained in the unchanged baseline checkout under
`build/issue96-main3fce/failing-unit-baselines/`. The three ANALOG O2 counts
match each corresponding baseline run. All 98 audio goldens remain exact with
no health/voice/routing failure or crash. Portable Python, icon export/normal and
strict sanitizer checks, UI/readability/FM4, replay, configured DaisySP,
native/Wasm emulator and partition checks pass. No golden or budget was changed.

`build/browser/run-WeOU1o/summary.json` records **10/10 passed**, no errors,
clean exact `7736398`, Playwright 1.64.1 and Chromium 156.0.8078.4. It binds the
served Wasm/page/worklet hashes and checks actual stereo audio, release,
GRAPH TURN, responsive/contrast behavior and storage/reload. A separate direct
IAB check opened HOME then ENV and dragged KNOB 1: ATK changed 1.0 to 1.2 ms,
with clean native readout/curve. Its screenshot is retained. These are host and
browser observations, not physical FM-1 acceptance.

Current-head Codex completed without findings. The actual full CodeRabbit review
of `7736398` completed with one minor report-status correction, addressed here.
[Hosted CI40092901749](https://github.com/kmplngj/Felucca/actions/runs/40092901749)
is still running at the time of this record; no hosted acceptance is inferred.
Physical LCD/panel, USB/TRS, listening and timing checks remain pending.

## Historical baseline and chosen class

The baseline, linked and host-cost measurements below describe the previous
a7-based experiment through `70b8794`. They remain useful provenance, but do not
qualify the refreshed `3fce9f9` integration. New matched resource and full-check
results must be recorded separately before making current-main claims.

The initial [inventory](https://github.com/kmplngj/Felucca/issues/96#issuecomment-6383180973)
and [C reference](https://github.com/kmplngj/Felucca/issues/96#issuecomment-6383222917)
were made on `5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e`. The freshly generated,
unchanged `a7a1f5e` icon header has the same SHA-256:
`85947fe4a0307f806613870ad117c1fe4d4c7256786843ea88d14d104c7687aa`.
The default Fukiai inputs and generated codebook contain these named arrays:

| Size | Cells | Raw nibble bytes | Packed DATA including two lookahead bytes | OFF / IDX / INK bytes | Complete size group |
| --- | ---: | ---: | ---: | ---: | ---: |
| 12 px | 105 | 7,560 | 3,694 | 210 / 123 / 210 | 4,237 B |
| 16 px | 39 | 4,992 | 2,311 | 78 / 123 / 78 | 2,590 B |
| 24 px | 6 | 1,728 | 508 | 12 / 123 / 24 | 667 B |

The one shared `AI_HC` array is 57 B: 15 canonical-length counts plus 42 symbols.
Total named arrays are 7,551 B before linker alignment/reachability. Index arrays
retain all 123 names, including entries absent at a particular size. Icons have
one square alpha cell per selected size; text-font phases, advances and kerning
are separate inputs and remain unchanged.

Six complete 12 px streams are identical: cell pairs 9/67 (27 B), 11/71 (28 B),
29/101 (26 B), 37/80 (29 B), 44/95 (71 B), 57/89 (27 B). Their summed repeated
payload is 208 B. There were no duplicate streams in those 16/24 px sets.
The choice is confined to the measured 12 px opportunity; no other #93 storage
or numeric-table transformation is included.

The coordinator archived fresh clean baseline target builds before this source
change, using JieLi Clang 4.0.1, standard engine profile, M8Stealth and the selective
minsize pass, once with compiled CPU2 support and once with `FELUCCA_CPU2=0`:

| Clean baseline | App | RAM | POOL | RAMTEXT | NOINIT |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default CPU2 support, runtime default OFF | 491,876 B | 62,152 B | 336,440 B | 3,152 B | 15,576 B |
| `FELUCCA_CPU2=0` | 488,164 B | 55,556 B | 336,440 B | 2,924 B | 15,564 B |

Artifact-bound resource reports and profile/disassembly evidence are under
`build/issue96/baseline-standard/` and `build/issue96/baseline-cpu2-off/` in the
experiment checkout. Fresh clean candidate `da4b09b94f97016249f4aa07b59f728866394306`
builds pass both target instruction budgets and artifact-bound resource verification.
The compiler/tool/SDK hashes, flags, effective feature settings and stack reservations
match their baseline; only revision/splash identity and the source-derived profile
digest differ. Both variants have **208 B less linked app**, with RAM, POOL,
RAMTEXT and NOINIT unchanged. Historical totals are not this baseline.

| Candidate | App / spare | RAM / spare | POOL / spare | RAMTEXT / spare | NOINIT / spare |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default CPU2 support | 491,668 / 89,896 B | 62,152 / 11,576 B | 336,440 / 32,200 B | 3,152 / 21,424 B | 15,576 / 120 B |
| `FELUCCA_CPU2=0` | 487,956 / 93,608 B | 55,556 / 18,172 B | 336,440 / 32,200 B | 2,924 / 21,652 B | 15,564 / 132 B |

The standard target contains all 7,551 B of baseline named icon arrays and
7,343 B in the candidate; exact symbol sizes establish their linked cost before
inter-object padding. The 500 B `cv_alpha_hc` code is byte-identical within each
variant, and the shared 516 B target Huffman cache is unchanged. Source and
codebook/metadata checks retain existing shared decoder/ramp costs.
`target-comparison.json` and `linked-symbol-comparison.json` retain the full
region margins and symbol proof. Follow [performance.md](performance.md) and
[build evidence](build-profiles.md#machine-readable-build-evidence).

## Representation and consumer audit

[gen_aa_icons.py](../tools/gen_aa_icons.py) obtains the unchanged list of packed
cell streams from `huff_pack`, then builds one dictionary local to a single
size/codebook. A dictionary key is the **entire packed byte stream**, not a raw
substring or a prefix. Only the 12 px call enables reuse. A repeated stream takes
its first occurrence's byte offset. Every original cell still gets its own OFF
entry, IDX identity and INK box in the same order.

Offsets may now decrease. Current consumers decode from a start pointer with an
explicit pixel count; none uses the next offset to compute an end:

- [icons.c](../firmware/src/icons.c): `cv_icon_on` passes DATA + OFF[cell] and
  `size, size` to `cv_alpha_hc`; `icon_cell` and `icon_ink` retain their tables.
- [gfx.c](../firmware/src/gfx.c): `cv_alpha_hc` emits exactly the supplied width
  and height, including decoded/dropped clipped rows. The Huffman LUT and color
  ramp caches have unchanged keys, sizes and code.
- [ui_render.c](../tests/ui_render.c): the independent alignment/icon unpacker
  also starts at OFF[cell] and stops after size squared pixels.
- [text_ref_test.c](../tests/text_ref_test.c) uses the shared `AI_HC` identity;
  [engine_metadata_test.c](../tests/engine_metadata_test.c) consumes icon IDs.
  Neither computes stream length from neighboring offsets.

Each first occurrence remains byte-aligned. Two zero lookahead bytes remain at
the **end of each size's DATA**, including if the last cell references an earlier
stream. Intermediate lookahead may inspect following streams, as before; only
the declared pixel count is consumed. The generator explicitly rejects a blob
whose payload plus final lookahead would reach 65,536 B. No 16-bit offset is
narrowed or wrapped. There is no runtime dictionary or new allocation, ISR work,
flash access, retained state, LUT state or decoder code.

## Historical export, independent rendering and causal checks

The candidate header SHA-256 on the recorded host is
`f5d5c9a1872948776296d8efb12f68cd7267fb4648d5f05bc836698868a9a9a2`.
AI12_DATA changes from 3,694 to 3,486 B; total named arrays from 7,551 to 7,343 B.
Exact before/after comparison confirms AI_HC, all IDX/INK arrays and all 16/24 px
DATA/OFF arrays are unchanged. AI12_OFF references the stable first occurrences.

[icon_stream_test.py](../tests/icon_stream_test.py) verifies the actual generated
header and a second deterministic export against separately rasterized raw input
on the same host. It checks every named ID, cell count/index, ink box, shared
codebook, meaningful alpha pixel, first-occurrence offset, exported stream bytes,
final lookahead and 16-bit bound. Synthetic fixtures cover whole-stream versus
prefix identity, empty streams, odd pixel counts, long runs, 8/9/15-bit code
boundaries and exact capacity limits. Four unittest tests pass, with no skips.

For CI portability, expected raw pixels are produced from the input rasterizer
directly, never by decoding the candidate's DATA/OFF arrays. Pillow/fontTools
raster behavior is therefore matched on the executing host rather than pinning
Mac-specific raster bytes globally. The shared rasterizer is not a second
independent font rasterizer; independence here is raw source alpha versus the
packed export/decoder/offset path.

[icon_stream_test.c](../tests/icon_stream_test.c) invokes the actual unchanged
`cv_alpha_hc` and compares every resulting RGB565 canvas pixel with the separate
unpacked `cv_alpha` path. The portable raw oracle covers 150 cells x 10 built-in
palettes x two styles x four clip arrangements x mirrored/plain x cold/hot
Huffman cache = **48,000 comparisons**, passing normally and with strict
AddressSanitizer + UBSan. Separate C fixtures check zero/odd dimensions, every
code length 1..15 and exact heap allocations ending in the two lookahead bytes.

The preserved local pre-change Mac oracle supplies additional before/after
evidence: its original raw arrays were left untouched and only the include path
was redirected to the candidate checkout. It also passes all 48,000 comparisons
normally and with strict ASan/UBSan. That oracle is local evidence for the exact
baseline export; it is not a portable global pixel golden.

Two local negative controls establish sensitivity without modifying production
inputs: changing the first exported offset from 0 to 1 fails the C pixel
comparison at the first scene; omitting lookahead from a synthetic exact heap
allocation triggers an ASan `heap-buffer-overflow`. Logs and structured outcomes
are under `build/issue96/`, including `mutation-results.json` and
`focused-coverage-summary.json`. No sound or budget baseline was regenerated.

The real runner registers `icon_streams` with `assets pillow` prerequisites and
`asan_icon_streams` with `assets sanitizer`, dependent on the first unit's raw
reference header. Missing prerequisites remain visible to the existing strict
coverage contract. Focused structured evidence records four successful unittest
tests, the normal compiler/children, and the strict sanitizer compiler/child.
No asset-dependent test is placed in the portable asset-free unit.

## Historical bounded host draw-cost comparison

Apple Clang 21.0.0, macOS arm64, `-O1 -w`. The same C benchmark is compiled once
against the archived baseline header and once against the candidate. Seven
alternating process pairs measure `clock()` process CPU time, 12,000 draws per
cache/clip case: all 150 cells, mirrored/plain, 40 repeats. Canvas clear and
color-ramp lookup are included; LCD transfer, audio and device scheduling are
absent. Every resulting checksum agrees. Full samples and ranges are retained
in `build/issue96/host-cost.json`.

| Cache | Clip | Baseline median ns/draw | Candidate median ns/draw |
| --- | --- | ---: | ---: |
| Hot | Full | 392.083 | 392.417 |
| Hot | Left/top | 405.167 | 409.833 |
| Hot | Right/bottom | 396.167 | 390.083 |
| Hot | Vertical strip | 386.417 | 393.750 |
| Cold | Full | 488.167 | 479.583 |
| Cold | Left/top | 495.250 | 500.250 |
| Cold | Right/bottom | 491.167 | 494.917 |
| Cold | Vertical strip | 488.500 | 497.583 |

Median differences range from -1.76% to +1.90%, with overlapping baseline and
candidate sample ranges. This short host comparison establishes no meaningful
speed improvement or pi32v2 draw-cost claim. Runtime cache/data structures are
unchanged by source inspection and the matched linked reports above; device
timing remains required separately.

## Reproduction and remaining acceptance

Generate through the usual build workflow before running the full suite. For
the bounded asset-only check in an already generated checkout:

```sh
uv run --locked --group build python tools/gen_aa_icons.py build/gen/ui_icons.h
uv run --locked --group build tests/run_tests.sh --unit icon_streams
uv run --locked --group build tests/run_tests.sh --unit asan_icon_streams
build/host/icon_stream_test --bench
```

`--unit` is the runner's internal focused entry point; it does not produce full
suite acceptance. The normal required final invocation remains
`uv run --locked --group build tests/run_tests.sh --ai-output`, with the fresh
matching target build and [resource checks](performance.md). The local focused
run prints the existing font `post.stringData` diagnostic and Pillow's missing
Raqm fallback warning; equivalence is checked on that same host. Neither warning
was hidden or treated as a new visual qualification.

| #96 acceptance area | Current evidence | Still required |
| --- | --- | --- |
| Measured class and complete cost | Current matched clean target variants, symbols/resources and budgets pass: -208 B app each | Final committed build/CI identity and qualification |
| Identical decoded alpha and metrics | Current four Python tests and normal/strict C pixel and boundary checks pass; controlled current-base A/B preserves all 3,084 screen and six rolling images | User CUSTOM, historical stored style/size values and supported free text beyond the captured matrix; FM-1 legibility |
| Determinism and provenance | Current two exports match; current header/input hashes recorded, unchanged Fukiai inputs and notices | Final committed revision/toolchain/profile/asset evidence attached to retained candidate |
| Runtime/resource cost | No added runtime state or decoder code; prior host timing samples remain historical | Actual device display/load cost; no speed claim |
| Host/browser/audio | Current macOS suite completed 125 pass/4 fail/1 blocked; all 98 goldens exact, browser10 and native/Wasm checks pass; failures reproduce on clean baseline | Hosted CI acceptance and physical qualification |
| FM-1 | No device access, flash or observations | Readability/panel activity under dense audio; USB audio 44.1/48 kHz and USB/TRS MIDI, lateness/shedding/scan/stream counters, supported CPU2 variants |

Unperformed checks remain pending. No installation, merge, release or publication
is authorized by this experiment record.

For the current native screen comparison, cover HOME and MIXER, value pages and
their tall/ordinary focused banks, ENV/LFO/FX/engine graphs, MOD, PRESETS/USER/
PROJECT names and lists, NAME entry and dialogs, and MENU's uniform rows,
DISPLAY graph choices, COLOR/LEDS direct editing, AUTO OFF and INFO/ABOUT.
Include all built-in palettes, representative user CUSTOM pairs, dense/long
text, active/inactive states, compact/header rolling frames and both historical
stored size values. Expected candidate output is pixel-identical to the matched
`3fce9f9` baseline for the same inputs. Retired STYLE/LARGE values are compatibility
fixtures; the native menu must remain as main defines it. Host captures do not
establish FM-1 legibility, panel latency or audio deadlines.

README assessment: no change is needed; the existing purpose, display capability
and measurement/validation overview already cover this internal representation
experiment. Changelog assessment: no entry for this small internal representation adjustment;
the existing “Memory and display work” overview remains accurate. Detailed
historical target evidence and current requalification status belong here; this
is not a new user-facing capability or a development milestone.

The Fukiai font and generated icon data retain the existing MIT notices; firmware,
generator and test changes retain GPL-3.0-only. No artwork, font data or licences
were replaced. See [LICENSING.md](../LICENSING.md).
