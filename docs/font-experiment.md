<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Pixel font experiment

## Main-only integration — 2026-10-12

The font-only commits from PR #151 were extracted onto unchanged main
`b04f4fa720a4550c00f042a9eb67f26965784ae3`. No MACRO engine, engine IDs,
presets or Braids credits are included. The historical stacked-branch measurements
below remain explicitly separate from this current main-based comparison.

Fresh local builds use JieLi Clang 4.0.1/pi32v2 via Linux amd64 Docker, default
features and the same checked-in samples/verified SDK inputs, `-Os`,
`-ffunction-sections`, `-fno-builtin` and the selective minsize pass. Local image
inputs use Python 3.12, Pillow 12.3.0, fontTools 4.66.1 and Brotli 1.2.0;
hosted CI retains its pinned Pillow 11.1.0 and reports separate provenance.

| Resource | Unchanged main | Inter Tight control | Tamzen | M8Stealth default |
| --- | ---: | ---: | ---: | ---: |
| App | 495,620 B | 495,584 B | 456,372 B | 456,464 B |
| Font symbols + descriptors | 42,904 B | 42,904 B | 3,288 B | 3,340 B |
| RAM data+bss | 54,964 B | 54,964 B | 54,964 B | 54,964 B |
| POOL | 327,800 B | 327,800 B | 327,800 B | 327,800 B |
| RAMTEXT | 2,924 B | 2,924 B | 2,924 B | 2,924 B |
| NOINIT | 15,564 B | 15,564 B | 15,564 B | 15,564 B |
| Loader / padded FWSC | 6,930 / 610,086 B | 6,930 / 610,086 B | 6,930 / 610,086 B | 6,930 / 610,086 B |

M8 saves **39,156 B against unchanged main**, or **39,120 B against the
metric-adjusted Inter Tight control**. Tamzen is 92 B smaller than M8 in this
main-based tree. The font-only change claims no RAM, stack or installer download-size
saving; the separate cache follow-up below records its additional POOL saving.
Main-loop layout changes account for the control's 36 B reduction. M8 leaves
125,100 B in the app slot; RAM/POOL spare is 18,764/40,840 B. Stack windows and
NOINIT reservation are unchanged. RAMTEXT retains 916 instructions and no calls.

All three font configurations receive fresh target builds and complete applicable
host suites: 92 unchanged audio goldens at O2 and Os/no-SIMD, 720 unchanged engine
switches, independent text-reference cases, normal/FM4 layout/alignment sweeps,
persistence/protocol/loader, sanitizers/fuzz and rebuilt native/Wasm equality.
M8 source-atlas checks cover 231 glyphs, including 1x/2x and extra-mark fit.
No baseline was regenerated and no new target compiler warnings occur. The first Tamzen
runner reported one transient O2 PHYS counter overrun; a repeat moved it to another preset,
then three focused retries and a fresh complete runner passed. Preprocessed DSP harness
inputs are byte-identical between unchanged main and Tamzen, so font selection does not
enter that workload. Failed and repeat logs are retained; no CPU speedup is claimed.
Local DaisySP reference and unmodified official V15 are unavailable; absent legacy
editor capabilities are explicitly skipped. Hosted CI covers pinned DaisySP;
physical FM-1 LCD readability, redraw and audio/USB/panel load remain deferred.

Native-size before/after/diff sheets use the real renderer with PR #84's capture
tooling in an isolated local integration checkout. Both captures retain exact
revision/input/binary provenance; the production baseline is main, and the candidate
production files match this font-only branch. HOME/STEP/MENU examples include
FLAT/LINE/LARGE and palette variants. The fresh M8 browser emulator was opened;
splash, HOME and STEP displays were inspected with no browser console errors.
Host images do not establish physical LCD readability or device deadlines.

Evidence stays under ignored `build/pr-review/font-main-{baseline,m8,inter,tamzen}/`
and per-variant build/test logs. Capture reports are in the attached
`foundation-ui-followup` worktree under `build/pr-review/font-main-*`.

## Huffman cache follow-up — 2026-10-12 (#148, PR #233)

The font-only table above is the baseline before this separate cache change.
The font generators now report their emitted Huffman book count; the renderer
reserves one additional slot for the shared icon book. Pixel fonts retain one
slot, while Inter Tight retains its two font books plus icons.

Fresh local A/B uses the same toolchain, flags and input versions listed above.
The font-only baseline is `ce87a32` (the `5f829e3` review fix preserves generated
font bytes); the cache candidate is `e417066`. Main integration adds host tooling
and documentation; later main PR #237 adds explicit package-product selection.
The refreshed default build keeps product `FM-1_900` and the same production inputs.

| Configuration | App before -> after | POOL before -> after |
| --- | ---: | ---: |
| M8Stealth | 456,464 -> 456,416 B (-48 B) | 327,800 -> 326,768 B (-1,032 B) |
| Tamzen | 456,372 -> 456,328 B (-44 B) | 327,800 -> 326,768 B (-1,032 B) |
| Inter Tight | 495,584 -> 495,584 B (byte-identical) | 327,800 -> 327,800 B |

For both bitmap profiles, `hc_tab` shrinks from 1,548 to 516 B entirely in
`.pool`; its free margin increases from 40,840 to 41,872 B. RAM data+bss remains
54,964 B, RAMTEXT 2,924 B/916 instructions/no calls, NOINIT 15,564 B, loader
6,930 B and padded FWSC 610,086 B. User/supervisor stack reservations remain
24,320/7,936 B at unchanged addresses. No CPU speedup is claimed.

All three fresh target builds and complete applicable host suites pass without
new warnings or baseline updates. Each profile retains byte-identical output
across 2,580 normal and 2,700 FM4 PPM renders; independent provenance captures
compare all 2,586 scenes including six filmstrips exactly. Compiled text-reference
checks cover 9,540 cases per profile. A deliberately wrong Inter Tight book count
fails the consumer-contract check. M8 browser HOME/STEP work without console
warnings/errors; physical FM-1 display, panel, audio and USB tests remain deferred.
Local DaisySP/V15 and absent legacy editor checks have the same limits as above;
hosted firmware CI covers its pinned DaisySP setup.

Evidence: ignored `build/pr-review/cache-{m8,inter,tamzen}/`, associated build/test
logs, raw PPM and font-header comparison JSON, consumer-contract rejection and
`cache-final-default/` production-artifact parity. PR #233 records the final
main-based integration revision and hosted CI results separately.

## Historical stacked-branch experiment

Branch experiment for [issue #37](https://github.com/kmplngj/Felucca/issues/37),
on `kori/pixel-font-test`, based on `9b2792e7450e19647faad22f240c85e84c374275`.
Measured on 2026-10-11 with Inter Tight as the control. Following the comparison,
M8Stealth is the user-selected default; Inter Tight and Tamzen remain selectable
with `FELUCCA_FONT`. The saving is in firmware flash, with unchanged RAM use.
No firmware was flashed or released.

## Configurations

| Role | Inter Tight | Tamzen regular | M8Stealth |
| --- | --- | --- | --- |
| S: labels, units, hints | 12 px / 400 | 6×12 BDF; 6 px advance | Stealth57, native 5×7 ink; 6 px advance |
| M: values, names | 15 px / 500 | 8×16 BDF; 8 px advance | Stealth89, native 8×9 ink; 9 px advance |
| L: large readouts | 28 px / 600 | shared M ink at 2×; 16 px advance | shared M ink at 2×; 17 px advance |
| Visible capital heights S/M/L | 9 / 11 / 21 px | 7 / 9 / 18 px | 7 / 9 / 18 px |

All variants keep the existing 15/19/35 px line boxes and 12/15/28 baselines.
Inter Tight uses 4/4/2 horizontal raster phases and compressed 4-bit alpha.
The pixel variants use packed 1-bit glyphs, with no extra framebuffer or glyph
scratch. Keycap legends retain Inter Tight in every variant.

Tamzen is the same regular 6×12 / 8×16 candidate previously tested, from
Tamzen-1.11.6. Its input BDFs remain unmodified; middle dot and ellipsis are
local generated marks. Fonts and licence are in `assets/fonts/tamzen/`.

M8Stealth uses the actual unmodified `m8stealth57.woff2` and
`m8stealth89.woff2` from Dirtywave/M8WebDisplay commit
`eabcc3da605b38f8fbe113c610c84122a17eb5ed`. They are decoded only at build time
with FontTools/Brotli and rasterised without antialiasing at 8/12 ppem.
All ASCII ink matches the independent m8gd 5×7 / 8×9 reference atlases exactly.
Copyright, degree, middle dot, six umlauts and ellipsis are explicit local
bitmap adaptations; both S/M faces retain the same 105 supported characters,
and L retains the same 41-character sparse subset. The WOFF2 files and source
attribution remain unmodified, including the embedded Matthias Tellen ancestry
credit. Font data/adaptations retain CC BY-SA 3.0. Provenance, hashes and full
terms are in `assets/fonts/m8stealth/README.md` and
`LICENSES/CC-BY-SA-3.0-M8Stealth.txt`.

The M8's own text-cell grid is not used as Felucca's advance. Its glyph ink is
preserved; the large face uses 17 px pen strides to keep a 1 px gap after doubled
8 px ink and fit three-digit readouts within the 51 px card area.

The other supplied WOFF2 faces were also inspected: native Stealth99 is 9×9
with 12 px advances, Stealth1010 is 10×10 with 12 px advances, and Stealth1212 is
12×12 with 14 px advances. They are wider than the tested label/value faces and
would need a separate role/layout experiment. They were not included in these
firmware builds or measured as additional firmware configurations.

## Target measurements

Fresh builds used identical default features and samples, JieLi Clang 4.0.1 /
pi32v2, the hash-checked AC79NN_SDK_V1.2.1_2023-12-13 packaging files,
`-Os -ffunction-sections -fno-builtin` and the existing selective main-loop
`minsize` pass. Python 3.13, Pillow 12.3.0, FontTools 4.66.1 and Brotli 1.2.0
were used in the ignored local `build/venv`. No golden or resource baselines
were rewritten.

| Resource | Inter Tight control | Tamzen | M8Stealth57/89 |
| --- | ---: | ---: | ---: |
| Application .bin | 509,152 B | 469,944 B | 470,032 B |
| ELF font symbols + descriptors | 42,904 B | 3,288 B | 3,340 B |
| RAM .data + .bss | 54,964 B | 54,964 B | 54,964 B |
| POOL | 327,896 B | 327,896 B | 327,896 B |
| Loader ota.bin | 6,930 B | 6,930 B | 6,930 B |
| Installer .fwsc | 610,086 B | 610,086 B | 610,086 B |

Against the branch's control, Tamzen saves **39,208 B (7.70%)** and M8Stealth
saves **39,120 B (7.68%)**. M8Stealth is **88 B larger than Tamzen**; flash size
is effectively tied. Font symbols/descriptors are all in XIP `.text`.
The font-only symbol saving is 39,616 B for Tamzen and 39,564 B for M8Stealth;
rendering, placement and attribution offset 408/444 B of those savings.

The unchanged source revision previously built to 509,188 B. The branch's
metric-based layout expressions account for the control's 36 B reduction.
Thus total savings against that unchanged revision are 39,244 B (7.71%) for
Tamzen and 39,156 B (7.69%) for M8Stealth. The current main checkout's font
sources were checked and still use the same Inter Tight configuration.

RAM has 18,764 B spare within the build's 73,728 B `.data+.bss` budget, and
POOL has 40,744 B spare within 368,640 B, unchanged for all three. `.ram_text`
is unchanged at 2,924 B / 916 instructions, with no calls; `.noinit` is
15,564 B. HAL register-boundary checks pass and there are no new target warnings.
The installer stays 610,086 B because the app is padded to the fixed 581,564 B
`APP_SLOT`; the smaller apps provide internal firmware headroom rather than a
smaller installer download. Loader bytes are identical.

SHA-256 of application binaries:

```text
inter-tight  ee817a44e4b0f37dfd22654ddb018552c5ac86ce0d58e7a827690d49748ffb70
tamzen       ce231aead541d75be3dc54fdeeb417d33edfd0d65c0089de133013d1676154ec
m8stealth    b8b5207d2f0698abf339439ab5491ce1175482fb687d4d5ad761cd8d24476d08
```

## Validation

- Fresh full applicable suites pass for Inter Tight, Tamzen and final M8Stealth.
  The Inter Tight/Tamzen apps were rebuilt against the final C sources using
  archived variant headers; both are byte-identical to the measured, tested apps.
- The follow-up default build with `FELUCCA_FONT` unset selects M8Stealth and is
  byte-identical to the validated explicit M8 selection above, including the loader.
  Its fresh full applicable suite passes. The 718,325 B browser emulator was
  rebuilt, switched on and visually inspected; the displayed Wasm binary matches
  the final suite's binary. This establishes browser startup, not physical LCD behavior.
- Each variant passes the independent text renderer's 9,540 pen/pixel cases,
  including edge/negative clipping, themes and supported extra marks. M8Stealth
  also passes these cases under ASan/UBSan. Its additional source test pins 231
  glyphs at 1×/2× to the upstream bitmap atlases and checks every added mark fits.
- Each passes UI behavior and normal/FM4 render sweeps: 215/225 screens × 10
  palettes, FLAT/LINE/LARGE, plus page/value sweeps. All final runs have zero
  layout lint and alignment failures. M8Stealth has 3,270,868/3,532,065 alignment
  measurements; Tamzen has 3,278,367/3,539,976; Inter Tight has
  3,256,908/3,517,543. Existing clipping/alignment tolerances are unchanged.
- All 98 audio golden renders are unchanged. Host instruction and target static
  budgets pass, along with persistence/protocol/loader, engine-memory, sanitizer,
  fuzz and web checks. All six MACRO presets match native/Wasm bit for bit over
  476,280 frames. No timing improvement on the FM-1 is claimed.
- DaisySP-dependent PHYS reference checks remain skipped (dependency unavailable).
  All variants emit the same five pre-existing `host_now` sequencing warnings in
  `tests/input_test.c`. Real LCD readability, redraw timing and audio under panel
  load remain unmeasured.

The first M8 run exposed two integration issues, both corrected without relaxing
tests: an 18 px large advance forced three-digit BPM into M, and the maker name
clipped the splash square. L now keeps the exact 2× glyph ink with 17 px advances;
the two maker lines use S with the original baseline placement and full text.
The corrected target is 48 B larger than the first 469,984 B M8 build. That failed
run is preserved under `build/font-m8/m8stealth-first-attempt/`.

The earlier Tamzen changes make card/unit/hint/piano-roll placement follow font
metrics. Its lowercase ascenders require an actual-ink splash inset. A previous
animation test required 20 changed pixels, rejecting Tamzen's thin `1` (18 pixels);
it now requires visible motion inside the strip and zero change outside, keeping
exact final-frame, duration, direction and retargeting checks. The LARGE test's
message now describes the font-independent requirement; its assertions are kept.

## Readability assessment

Native 240×240 renders and nearest-neighbor 2× views were inspected for HOME,
LARGE HOME, MENU, FM6 OPERATOR, automation, naming, chords, details, drum grid,
presets and splash across GREY/PAPER/MONO. Separate glyph specimens cover signed
numbers, fractions, `0/O`, `1/I/l`, `5/S`, `8/B` and every extra mark.

M8Stealth89 gives the heaviest, clearest pixel strokes of the two tested pixel
options for values and names. Its distinctive zero and crisp digits are useful
in the previews. Tamzen is thinner, narrower and more open. Inter Tight retains
larger small labels and a smoother mixed-case appearance; both pixel candidates
reduce S/M capitals by 2 px. M8 also needs a smaller splash credit face to fit.
These are visual observations from renders, not human reading tests on an LCD.

Both pixel options display HOME's LARGE `355` in L at 18 px capital height;
Inter Tight falls back to M there. M8's medium 9 px advance is wider than Tamzen's
8 px, so longer values such as `ENV ATK` still use S. Font saving is demonstrated;
a universal readability win is not. The render review recommended retaining
Inter Tight as default until a real FM-1 comparison, with M8Stealth as the stronger
bold-digit candidate. The user subsequently chose M8Stealth as the build default
for its flash saving. Physical LCD readability and redraw checks remain open.

Artifacts under ignored `build/font-m8/`:

- `font-comparison.png`: matched native HOME/LARGE/FM6/naming screens, three columns.
- `font-comparison-details.png`: eight further screen/theme comparisons.
- `font-comparison-2x.png`, `glyph-comparison*.png`: nearest-neighbor/detail specimens.
- `selected-font-audit.json`: actual chosen faces and ink boxes for selected values.
- `inter-tight/`, `tamzen/`, `m8stealth/`: app/ELF/disassembly/package, font headers,
  section/symbol measurements, screenshots, full build/test logs and checksums.
- `control-confirm.log`: final-source target rebuilds proving both controls identical.
- `default-build.log`, `default-tests.log`, `default-emu-build.log`: fresh default
  selection verification; `default-emulator-proof.json` records binary hashes and
  `m8stealth-emulator.jpg` shows the running local emulator.

## Reproduce

Use [BUILDING.md](../BUILDING.md), including Pillow and `fonttools[woff]`:

```sh
FELUCCA_FONT=inter-tight ./build.sh
tests/run_tests.sh
FELUCCA_FONT=tamzen ./build.sh
tests/run_tests.sh
FELUCCA_FONT=m8stealth ./build.sh
tests/run_tests.sh
```

Always rebuild before switching variants; tests and the browser emulator use the
preceding build's generated header. Raw evidence from the original Tamzen run
remains under `build/font-{before,default,after}/`. Compare labels, long names,
signed/fractional numbers, glyph confusion, dark/light/mono and redraw/audio under
load on an actual FM-1 before adopting a font.
