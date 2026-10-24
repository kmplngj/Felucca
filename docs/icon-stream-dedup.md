<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Exact icon-stream reuse experiment

Candidate for [#96](https://github.com/kmplngj/Felucca/issues/96), based on clean
`a7a1f5eb9de7decffbff4ef7aeb4e734b00eb33b`, 2026-10-24. Only identical complete
12 px icon streams share storage. The shared Huffman codebook is still computed
from **all** unchanged cells of every size before deduplication. No decoder,
renderer, icon identity, input font, typography, phase count or protocol changes.

Focused export and independent C pixel checks pass. The candidate remains an
experiment with a measured 208 B net app reduction in both matched target variants;
the full applicable suite, screen/emulator comparison and FM-1 qualification
remain pending. No device speed gain is claimed.
No alternative codec or font representation was trialed.

## Baseline and chosen class

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
payload is 208 B. There are no duplicate streams in the current 16/24 px sets.
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

## Export, independent rendering and causal checks

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

## Bounded host draw-cost comparison

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
| Measured class and complete cost | Exact inventory, clean matched target variants: app -208 B each; static regions/stacks unchanged, budgets/resource verification pass | Final CI identity and remaining behavior/device acceptance |
| Identical decoded alpha and metrics | All exported icon cells, IDs, ink boxes and book checked; normal/strict C pixel and boundary checks | Full UI screens, palettes including user CUSTOM, styles, LARGE, clipping/scrolling/rolling digits and supported free text; font data remains unchanged |
| Determinism and provenance | Two exports match; exact baseline/candidate header hashes, unchanged input assets and notices | Final revision/toolchain/profile/asset evidence attached to retained candidate |
| Runtime/resource cost | No added runtime state/decoder; linked regions unchanged, bounded cold/hot/clipped host samples | Actual device display/load cost |
| Host/browser/audio | Focused Python and real C checks, strict ASan/UBSan, causal negative controls | Full applicable host suite, audio/engine-switch goldens and fresh browser/emulator gate |
| FM-1 | No device access, flash or observations | Readability/panel activity under dense audio; USB audio 44.1/48 kHz and USB/TRS MIDI, lateness/shedding/scan/stream counters, supported CPU2 variants |

Unperformed checks remain pending. No installation, merge, release or publication
is authorized by this experiment record.

README assessment: no change is needed; the existing purpose, display capability
and measurement/validation overview already cover this internal representation
experiment. Changelog assessment: no entry for this small internal representation adjustment;
the existing “Memory and display work” overview remains accurate. Detailed
208 B net target evidence belongs here, with qualification still pending; this
is not a new user-facing capability or a development milestone.

The Fukiai font and generated icon data retain the existing MIT notices; firmware,
generator and test changes retain GPL-3.0-only. No artwork, font data or licences
were replaced. See [LICENSING.md](../LICENSING.md).
