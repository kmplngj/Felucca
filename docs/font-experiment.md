<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Pixel font experiment

Branch experiment for [issue #37](https://github.com/kmplngj/Felucca/issues/37),
on `kori/pixel-font-test`, based on `9b2792e7450e19647faad22f240c85e84c374275`.
Measured on 2026-10-11 with Inter Tight as the control. Following the comparison,
M8Stealth is the user-selected default; Inter Tight and Tamzen remain selectable
with `FELUCCA_FONT`. The saving is in firmware flash, with unchanged RAM use.
No firmware was flashed or released.

## Latest MACRO integration (2026-10-12)

The font branch now includes the latest remote `kori/macro-engine` at
`c2d91aa4c71b4294e44d8fcbddc4f0ec28956ccc`: 48 models and 51 factory presets.
The tested combined source revision is `4a6901d60234068db4503c6f57222237ad0e6e3f`.
Inter Tight and unset/default M8Stealth were freshly built on that identical tree.
A separate untouched source snapshot of `c2d91aa` was rebuilt as the base comparison.

All builds use the default features (SLICE=1, FM4=0), five sample sets / eleven
zones / 126,244 B ADPCM, JieLi Clang 4.0.1 / pi32v2, `-Os -ffunction-sections
-fno-builtin`, the existing selective main-loop `minsize` pass and hash-checked
AC79NN SDK packaging inputs. The repaired isolated Python environment uses
Python 3.13.16, Pillow 12.3.0, FontTools 4.66.1 and Brotli 1.2.0. Host tests use
Apple Clang 21.0.0; the browser build uses Emscripten 6.0.12-git.

| Resource | Untouched MACRO base, Inter | Combined Inter control | Combined M8Stealth |
| --- | ---: | ---: | ---: |
| Application .bin | 580,360 B | 580,324 B | **541,240 B** |
| App-slot spare (581,564 B) | 1,204 B | 1,240 B | **40,324 B** |
| RAM .data + .bss | 54,964 B | 54,964 B | 54,964 B |
| POOL | 345,656 B | 345,656 B | 345,656 B |
| .ram_text | 2,924 B | 2,924 B | 2,924 B |
| .noinit | 15,564 B | 15,564 B | 15,564 B |
| UI font symbols + descriptors | 42,904 B | 42,904 B | 3,340 B |

The combined M8 build saves **39,120 B (6.74%)** versus the untouched latest
MACRO base, or **39,084 B (6.73%)** versus the combined Inter control. The 36 B
control reduction comes from the font integration's metric-based placement.
Regular RAM has 18,764 B spare and POOL has 22,984 B spare in every configuration.
Font selection changes neither RAM region. The full MACRO bank's extra POOL
storage remains present. Both packaged font builds retain the identical 6,930 B
loader and the same 610,086 B padded installer size. Target builds have no warnings,
pass HAL boundaries, and keep the 916-instruction no-call RAMTEXT check.

### Combined validation

Fresh **full applicable suites pass for both Inter Tight and M8Stealth** on this
combined revision, with `GOLDEN_UPDATE` and `BUDGET_UPDATE` absent. Golden,
CPU, target-cost and engine-switch baseline files are byte-identical to Git.

- 143 audio golden renders: no changed/missing hashes, health failures or CPU
  budget overruns; all 98 earlier goldens remain represented.
- 9,540 independent text-reference cases per font; M8's 231 source glyph checks
  match upstream 1x/2x ink and all extra marks fit.
- Normal/FM4 sweeps: 225/235 screens x ten palettes, styles/LARGE and page/value
  sweeps; zero layout lint/alignment findings. M8 has 3,281,926 / 3,543,123 alignment
  measurements; Inter has 3,268,133 / 3,528,768.
- Full-bank bounds/reset/parts/transition tests, engine-switch regressions,
  strict MACRO/Braids ASan/UBSan, storage/protocol/loader and fuzz tests pass.
  The offline original-rate C++/C Braids comparison reports zero failures.
- Native/Wasm samples match bit for bit across all **51 MACRO presets over
  4,723,110 frames**, plus the existing 88,200-frame heavy song.
- Host instruction budgets and static target loop estimates pass. These are
  regression checks, not actual FM-1 timing or a claim of faster redraws.

DaisySP PHYS reference is skipped (checkout unavailable); the official V15
restore-image check is skipped (image unavailable). Legacy editor mock checks
also report capability skips for MENU settings, FM6 bank sender and MIDI Learn.
Both full runs retain the same five pre-existing `host_now` sequencing warnings;
there are no new target compiler warnings.

The first test attempt mistakenly set both update variables to `0`, which still
enables regeneration in these checkers. Those generated changes were archived,
the original files restored, and **both complete suites rerun with the variables
unset**. Only the final unchanged-baseline runs support the validation above.
The earlier missing-Pillow pre-compilation attempt is also retained separately.

### Browser and reproduction

The default M8 emulator was rebuilt to **813,566 B Wasm**, opened and visually
inspected while running. Browser warning/error logs are empty. A stable copy
serves the preview during control builds; its hash matches the final M8 suite's
Wasm. This verifies browser behavior; physical FM-1 readability, LCD redraw,
audio/USB/MIDI under panel load and interrupt stack/deadline checks remain open.
No hardware was flashed and no firmware release was published.

Use BUILDING.md's Python/toolchain/SDK setup, ensuring update variables are unset:

```sh
FELUCCA_FONT=inter-tight ./build.sh
env -u GOLDEN_UPDATE -u BUDGET_UPDATE tests/run_tests.sh
env -u FELUCCA_FONT ./build.sh
env -u GOLDEN_UPDATE -u BUDGET_UPDATE tests/run_tests.sh
```

Application SHA-256:

```text
MACRO base  084be69a7f21b55359b773dbd08959d0a6ec34ae483bc784fe5993aeea386fc1
Inter       c36488034555c9c7cf1237a691a4c5a2fe69a69fd2dbdd0b4faed3b1bd4bb4fa
M8Stealth   40c877d7c6ee328ce49f8dac22007825f64c9772334af16a97438a44ef1b4eca
```

Wasm SHA-256:
`842aa47258580d70fb48ced971661ca94ae0cda75998bfbb19421b4becac0a7f`.
Raw source snapshots, build/test logs, binaries, headers, metrics, hashes and UI
renders are under ignored `build/font-macro-2026-10-12/`. `browser-m8stealth.jpg`
records the live preview. Tamzen remains selectable, but was not rebuilt/retested
on this latest full-bank integration; its earlier measurements follow below.

The remaining sections record the historical three-model comparison from 2026-10-11.

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
