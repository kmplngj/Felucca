<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO engine

The 48-model, 51-preset experiment has been rebased onto current main for issue
[#27](https://github.com/kmplngj/Felucca/issues/27). It is an **opt-in hardware-test
candidate**, not part of the standard profile or the hosted main demo.

```sh
FELUCCA_PROFILE=macro ./build.sh
FELUCCA_PROFILE=macro tests/run_tests.sh
```

Use the [exact-revision artifact and FM-1 checklist](macro-hardware-test.md) for
installation and hardware acceptance. The [rebase validation report](macro-rebase-validation.md)
records the current comparison and separates host, static target, browser and device
evidence. No hardware acceptance is claimed until that checklist is actually run.
The source collection/extraction decision remains separate: the existing firmware
wrapper and generators are GPL, while Braids/stmlib and the adapted DSP retain MIT.

The `macro` profile selects every standard engine plus stable MACRO ID **14**.
`standard` and `reduced-lofi` exclude its source, exclusive tables/generator work and
larger state allocation. Their current unavailable-engine handling preserves saved
ID14/parameters without selecting another instrument. Never use an ordinary
standard-profile package as the MACRO test artifact.

The original branch and dated measurements below are retained as historical evidence
from 2026-10-11. Their flash/RAM/timing figures and old-build downgrade statements are
not measurements or compatibility guarantees for the rebased candidate. Current
profile resources, compatibility and tests are authoritative in the report above.

## Playing

MACRO appears after DRUM in PRESETS and the EDIT engine map in the opt-in profile. Its stable
stored/protocol ID is **14**, with **48 models and 51 factory sounds**. The six
original sounds and WAVE/FOLD/FBFM IDs 0/1/2 retain eight-voice operation. The
45 appended models (IDs 3..47) use **one Felucca voice per part**, including in
POLY and UNISON modes, to fit the full Braids delay/state storage. PLUCKED retains
Braids' internal three-string history. The four parts have independent state.

| Control | Range | Function |
| --- | --- | --- |
| SHAPE | 48 models | Select the oscillator model; the full list and IDs are in [the cost table](braids-model-costs.csv) |
| TIMBRE | 0..127 | WAVE: scan 64 original WAV LINE waves; FOLD: folding gain; FBFM: modulation depth |
| COLOR | 0..127 | WAVE: stepped/smooth samples, wave interpolation, then coarser samples; FOLD: sine-to-triangle blend; FBFM: modulator pitch approximately ±64 semitones |
| TUNE | −24..24 semitones | Transpose the oscillator |
| CUT / RES | 0..127 | Felucca's low-pass filter and resonance |
| DRIVE | 0..127 | Soft clipping before the filter |
| FINE | −50..50 cents | Fine tuning |

HOME's knobs are the model's TIMBRE and COLOR controls, CUT and MODEL. OSC has
MODEL, the two model controls and TUNE; TONE has CUT, RES, DRIVE, FINE. The
existing envelopes, filter envelope, sends,
pitch bend, fine detuning and modulation matrix apply. The SHP modulation
destination changes TIMBRE; the E1..E8 destinations address the eight controls
in table order. Model changes correct the first sample to the previous sample, fading that
correction over 32 samples. The added bank resets its full oscillator on a model
change and fades any extra legacy voices out over one control block. Note events
strike the physical/percussion models. Sounding retriggers retain the oscillator
and filter history; a new note from silence resets the legacy note/filter state.

## Panel labels, hints and preview

The panel gives TIMBRE and COLOR model-specific names:

| Model | TIMBRE label | COLOR label | OSC guidance |
| --- | --- | --- | --- |
| WAVE | SCAN | TEXTURE | Move through 64 waves; step, smooth or crush the texture |
| FOLD | FOLD | BLEND | Add harmonics; blend sine into triangle |
| FBFM | DEPTH | MOD PIT | FM with carrier feedback; transpose the modulator |

SHAPE is labelled MODEL. FBFM's MOD PIT reads in semitones: −64 at stored value 0,
0 at 64, and +64 at 127 (rounded from +63.992). The last detent spans approximately
two semitones. MOD and AUTOMATION use the compact names TEX and MPIT where their
value cells need less text; automation and held locks retain the same pitch units.
DESC continues to expose SHAPE/TIMBRE/COLOR and COLOR's original 0..127 range.
Stored parameter IDs and modulation ranges are unchanged; SHAPE's maximum is
now 47. DESC returns all 48 complete model names, and NAMES returns 51 presets.

OSC shows two short hints even with MENU > HELP off. With HELP on, its temporary
footer hints and HOME's knob hints follow the selected model too. The preview fits
the existing graph panel and the smaller LARGE strip:

- WAVE shows a settled wavetable cycle and a marker for the scan position.
- FOLD shows the folded sine/triangle blend at a reference pitch of C4.
- FBFM shows modulator → carrier and carrier → modulator feedback.
- Added models show their full name, two compact model-specific controls and bars,
  the one-voice limit and note-trigger guidance. Control meanings are recorded in
  [models.json](../assets/braids/models.json).

These are control illustrations before envelopes, modulation, oversampling, drive,
filter and effects, not live output traces. High-note folding attenuation is also
absent from the illustration. HOME and TONE retain the live scope. The waveform
uses 129 bounded points and existing immutable DSP tables in the main loop, without
allocating a buffer or touching voices, oscillator phases or engine memory. OSC
redraws when its values change; an unchanged preview remains cached while silent.

## Factory and user presets

The six original starter sounds retain their indices and values. One starter
preset for each added model follows them, for 51 sounds total:

| Preset | Model | Starting point |
| --- | --- | --- |
| WAVE SCAN | WAVE | Polyphonic wavetable texture |
| WAVE BASS | WAVE | Low, filtered mono bass |
| FOLD LEAD | FOLD | Bright mono lead |
| FOLD PAD | FOLD | Slow attack and release, polyphonic pad |
| FBFM BELL | FBFM | Decaying metallic bell |
| FBFM BASS | FBFM | Filtered mono FM bass |

Turn PRESETS to audition sounds. Tap SAVE twice to open PRESETS: KNOB 1 browses
sounds, KNOB 2 changes engine, KNOB 3 marks a favorite, and KNOB 4 filters by
favorites or category. Factory presets remain available after editing a sound.

MACRO uses Felucca's **32 shared user preset slots**, alongside the other engines.
To keep an edited sound:

1. Stop playback, tap SAVE once for USER, and choose a slot with KNOB 1.
2. Press OCT+ to open NAME; a used slot asks for overwrite confirmation first.
3. Enter a name with the piano keys or KNOB 1/2, and choose a category with KNOB 3.
   EDIT on USER renames an existing slot. Names can contain up to 12 characters.
4. Press OCT+ to save, or OCT− to cancel. Saving includes the model, all eight
   MACRO controls, envelopes, effect sends and the other sound parameters.

To load it, select its USER slot, turn KNOB 2 to select LOAD, then press OCT+.
Saved sounds also appear in the combined PRESETS list and its category/favorite
filters. The browser emulator stores these slots in this browser's local storage;
the FM-1 stores them in flash. Clearing browser storage removes the emulator's saves.

On 2026-10-11, the local browser build at revision `9b2792e` played all six factory
sounds through AudioWorklet at 44.1 kHz. An edited FOLD LEAD was saved in U01,
renamed MY FOLD, then loaded after a full page reload: SHAPE FOLD, TIMBRE 65%,
COLOR 26% and CUT 4.2 kHz were retained, and the loaded sound produced audio.
The Wasm regression also saves, names and reloads edited WAVE/FOLD/FBFM sounds in
fresh instances, comparing all eight engine values and their categories.
These checks establish the emulator workflow; real-device flash and panel
validation remains outstanding.

## DSP and attribution

`firmware/src/macro_dsp.c` is a selected integer C adaptation of Mutable Instruments
Braids, by Emilie Gillet (MIT), pinned to eurorack revision
`08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4`. WAVE follows `RenderWaveLine`; FOLD blends
`RenderSineFold` and `RenderTriangleFold`; FBFM follows `RenderFeedbackFm`'s previous
carrier → modulator → carrier feedback topology. The wrapper is
`firmware/src/eng_macro.c`. Source links and table extraction details are in
[assets/braids/README.md](../assets/braids/README.md), and the full MIT notice is in
[LICENSES/MIT-Braids.txt](../LICENSES/MIT-Braids.txt). Firmware credits also name Braids.

The pinned original source is now bundled and translated offline by
`tools/gen_braids.py` into `build/gen/felucca_braids.h`. It includes every source
model and the full wave/resource bank. The legacy three models reuse those
immutable tables, retaining their previous hashes and interpolation behavior.
The other 45 models run the translated source with its full delay storage, with
explicit unsigned wrapping instead of undefined signed-overflow/shift behavior.
The only delay-bound correction clamps a negative comb-delay pitch to zero.

Added models render at 88.2 kHz, then average pairs into Felucca's 44.1 kHz audio.
The phase and delay tables are retuned offline from Braids' original 96 kHz.
Calls use 24/24/16 source-sample chunks for a 32-frame control block, preserving
the original 24-entry scratch bounds. The engine retains Felucca's envelopes,
filter, drive, modulation and control cadence. This does not claim sample identity
with Braids hardware or M8. The original-rate translated C core is bit-compared
against the pinned C++ separately from these rate/integration differences.
These models can alias at high notes, especially with strong folding/FM.

## Persistence and compatibility

Existing engine IDs and parameter IDs are unchanged: NENGINES is 15, P_COUNT 111,
P_E0 103 and projects remain FUN10 (3840 bytes). SLICE keeps reserved ID 13 even
with `FELUCCA_SLICE=0`; DIGITAL's ID 1 also stays reserved when disabled. MACRO
stays ID 14 in all four FM4/SLICE configurations. The editor discovers its names,
ranges and presets through the existing INFO/DESC commands; the repository's
editor mock and engine ordering are updated too.

PER4 used favorites row 14 for MIDI LEARN and row 15 for UI preferences. PER5
preserves that complete prefix and appends 32 bytes for MACRO favorites. Boot
import and backup restore migrate PER4, keeping the mappings, old stars and UI
preferences; PER1–PER3 still migrate at boot. A backup's old CRC and fields are
validated before the staged settings expand. There is no new save-on-boot or
immediate erase on a knob turn.

**Downgrading:** earlier firmware cannot load engine 14 or import PER5 settings.
The earlier three-model branch also cannot represent IDs 3..47: it clamps new
model values and cannot reproduce those sounds. Keep a pre-update backup to
restore settings and sounds after a downgrade. Existing-engine
projects retain their previous format and sound hashes.

## Full-bank expansion — 2026-10-11

The remaining **45 models** are implemented on the same `kori/macro-engine`
branch, bringing the bank to 48. This includes CSAW/MORPH, SUB/SYNC/triple
oscillators, ring/swarm/comb/toy, digital filters, VOSIM/vowels/harmonics/FM,
plucked/bowed/blown/flute, bell/drums, wavetable/map/chords, noise/cloud/particles,
QPSK and the source's hidden QUESTION model. The original six presets and model
IDs retain their values and hashes. All engines remain enabled as before;
[issue #28](https://github.com/kmplngj/Felucca/issues/28) tracks optional builds.

### Firmware and RAM

The unchanged baseline for this expansion is **`b767f1107517feba1cb0b9ffd0ffc2804ef29540`**,
built before source changes. Both builds use the default features/assets described
below: SLICE=1, FM4=0, JieLi Clang 4.0.1 `-Os` for interrupt/DSP paths and the
existing selective main-loop `minsize` pass. The final build has no compiler
warnings. Binaries, ELF, disassembly, source snapshots and logs are retained in
ignored `build/macro-full-before/` and `build/macro-full-after/`.

| Resource | Three-model branch | Full bank | Delta |
| --- | ---: | ---: | ---: |
| App image | 511,708 B | 580,360 B | **+68,652 B** |
| Regular RAM (.data + .bss) | 54,964 B | 54,964 B | 0 |
| POOL SRAM | 327,896 B | 345,656 B | **+17,760 B** |
| RAM code (.ram_text) | 2,924 B | 2,924 B | 0 |
| Retained RAM (.noinit) | 15,564 B | 15,564 B | 0 |
| Loader image | 6,930 B | 6,930 B | 0 |
| Padded .fwsc package | 610,086 B | 610,086 B | 0 |

The app has **1,204 B flash spare** out of 581,564 B. Regular RAM has 18,764 B
spare; POOL has 22,984 B spare. The 55 retained Braids immutable objects total
**55,056 B** in XIP, including the full 256-wave bank (33,024 B). They replace the
legacy duplicated extraction. None of the existing sample sets was removed.

The shared engine arena grows from 12,888 to **17,328 B per part** (four parts).
A MACRO part uses **17,324 B**: eight 40-byte legacy note/filter slots, a
**17,000-byte full Braids oscillator**, and flags/alignment. This fixed reserve
applies to every model, including when the legacy models are selected; choosing a
smaller model does not reduce static RAM. The full source's largest delay buffer
is retained. One full oscillator per part fits; eight full oscillators per part
would not fit this SRAM layout. Render scratch is on the existing interrupt stack;
static RAM figures do not establish its high-water usage.

### Per-model flash and CPU

[braids-model-costs.csv](braids-model-costs.csv) records all 45 added model IDs,
upstream IDs, isolated target DSP code/table bytes, fixed state bytes, polyphony
and repeated host CPU ranges.

Flash probes use the same pi32v2 compiler and `tools/build.py` CFLAGS (`-Os`,
`-ffunction-sections`, `-fno-builtin`). `tools/measure_braids.py` restricts the
macro/digital dispatch cases in an isolated copy of the generated header, then
sums the object's .text/.rodata/.data sections. The shared analog dispatcher stays
intact. The probes include their entry points and shared DSP helpers/tables,
exclude Felucca's mixer, presets, UI and shared memset implementation, and range
from **1,632 B (CSAW) to 35,783 B (WAVE CHORD)**. These numbers are **not additive**
and are not the marginal firmware bytes saved by disabling a model; that needs
separate modular firmware builds. The actual all-model firmware delta is the
68,652 B measured above.

CPU uses Apple Clang 21 arm64 `cc -O2` and macOS `ri_instructions`, over the real
Felucca mixer at 44.1 kHz. For each added model, `tests/braids_test.c` holds note 60
at velocity 100, with attack/release/filter-envelope zero and sustain 127, CUT
110, RES 8, DRIVE 127, CHOR/DLY/REV 20/20/35 and ROOM reverb (the host fixture). It tests all nine TIMBRE/COLOR
combinations from {0,64,127}, warms for 22,048 frames (~0.5 s), counts 44,096 frames
(~1 s), and reports the largest count. The CSV gives the range of those maxima
across three process runs. These are **total mixer instructions per output frame**;
idle is included, unlike the preset-specific increments printed by `regress`.

The added models range from **526.1 to 759.8 host instructions/frame** in these
runs. HARMONICS is the heaviest; four HARMONICS parts with one held note each
measure **2,120.0–2,120.6 instructions/frame**, versus idle **316.3**.
This grid is a repeatable workload, not an exhaustive worst case over pitches,
note strikes, model automation, effects and USB traffic. Host instruction counts
are not pi32v2 cycles or FM-1 CPU percentages.

Model-change reset is bounded: fresh ownership is already zeroed by
`eng_mem_claim`; later changes clear 4,250 aligned words. The target emits a
store plus decrement/branch per word: **8,500 reset-loop instructions per part**,
plus initialization and rendering. All non-inlined dispatchers and the wrapper
are covered by the static target budget. `macro_render`'s budget deliberately
changes from 119 to 19,591 because the compiler inlines many newly added model
loops into it; the heuristic sums mutually exclusive paths and does not estimate
one model's timing. Other existing target budgets are retained.

Reproduce after the normal build:

```sh
build/host/braids_test
python3 tests/braids_reference.py
python3 tools/measure_braids.py --out build/braids-cost
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
```

Repeat `braids_test` three times on the same host/compiler. The reference and
flash probes work offline from pinned inputs; the target probe needs the normal
`JIELI_TOOLCHAIN` environment. Generated binaries/probe headers remain under build.

### Validation and remaining device checks

The applicable full suite covers 143 golden renders, preserving all 98 earlier
hashes; 720 original and 192 legacy MACRO engine-switch sequences; all 45 added
models' bounds, resets, independent parts, retrigger/release and live voice-cap
changes; strict ASan/UBSan; stable engine IDs under all FM4/SLICE configurations;
DESC's complete 48 names and NAMES' 51 presets; existing storage/backup/fuzz tests.
Only the added 45 golden/host CPU entries and newly compiled bank target budgets
are added; older entries are retained.

The offline original-rate C++/C comparison covers 48 models at nine parameter
combinations, 200 x 24-sample blocks each, **2,059,200 samples with zero bit
mismatches**. Three comb cases with zero TIMBRE are excluded from this comparison
because the original negative-delay shift is deliberately clamped; the corrected
port is exercised at those corners under strict sanitizers.

Default and FM4 UI render sweeps cover all ten palettes and FLAT/LINE/LARGE with
**zero layout/alignment findings**, including the added model labels and panels.
Chromium runs AudioWorklet and shows the new controls at desktop and 390 px width
without horizontal overflow or console warnings/errors. BOWED was saved in empty
U32 as **MACRO 32X**, then loaded after a full page reload: model BOWED, friction
39%, position 50% and TUNE 0 st were retained. Automated fresh-instance save/load
checks additionally verify all eight edited controls, names and categories for
WAVE/FOLD/FBFM plus PLUCKED/WAVE MAP/QPSK.

Native/Wasm audio matches over **4,723,110 frames across all 51 MACRO presets**,
including attacks, control gestures and release tails; the existing 88,200-frame
heavy song also matches. The optional DaisySP reference and official V15 restore-image check are skipped
(the required checkout/image are absent).
No real FM-1 was flashed or measured. Remaining acceptance is real-device
listening, maximum audio-ISR timing/deadline misses (including strikes, rapid
model changes and four parts), interrupt stack guards/high-water usage, physical
panel/preset flash behavior, USB audio and USB/TRS MIDI under load. Keep issue #27
open for those checks; the small flash reserve makes issue #28 useful next work.

## Initial three-model measurements — 2026-10-11

The following measurements are historical, before the full-bank expansion.
Current expansion costs are recorded above in the full-bank section.

The unchanged base was built first, then the implementation with identical default
features and assets: SLICE enabled, DIGITAL disabled, five sample sets / eleven
zones / 126,244 bytes of ADPCM. Target: JieLi Clang **4.0.1**, pi32v2, package
`jieli-linux-toolchains-20260730.1` via Docker linux/amd64; AC79 SDK revision
`d179b4484759423312073f5fbb232501aa491047`. The normal selective size pass applies
`minsize` to main-loop functions; engine, DSP and interrupt paths retain `-Os`.
No build flags, sample quality or existing engines were removed to make room.

| Resource | Before | After | Delta | After spare |
| --- | ---: | ---: | ---: | ---: |
| App image (`felucca.bin`, capacity 581,564 B) | 495,580 B | 511,708 B | **+16,128 B** | 69,856 B |
| XIP `.text` | 492,240 B | 508,368 B | +16,128 B | Included above |
| `.ram_text` | 2,924 B | 2,924 B | 0 | Separate RAM execution region |
| `.data` + `.bss` (capacity 73,728 B) | 54,964 B | 54,964 B | **0** | 18,764 B |
| `.pool` (capacity 368,640 B) | 327,800 B | 327,896 B | **+96 B** | 40,744 B |
| `.noinit` (capacity 15,696 B) | 15,564 B | 15,564 B | 0 | 132 B |

The 96 bytes are three 32-byte settings/favorites copies. Each MACRO voice needs
40 bytes, or **320 bytes per part**, inside the existing 12,888-byte-per-part shared
engine arena. `ENG_MEM_PART` and its four-part allocation do not grow.

Stack is separate from this static accounting. The target prologues reserve 128
local bytes for `macro_render` and 76 / 88 / 36 for WAVE / FOLD / FBFM, plus their
register saves. The 64-byte scratch audio block is included in the renderer's
frame. Full nested audio/scan interrupt stack high-water usage has not been
measured on hardware.

App SHA-256 before:
`badced1770fabc99ede44a31039e696fa3d51670eb1ee8af3687412d96ccdfde`;
after: `1461849b7a2aaf1371685fc03c72c00752e9c5c45ec3fa279dcfa20eb8a6608e`.
The loader remains 6,930 bytes. Package size (610,086 B) is not app-slot usage.

The model labels, hints and preview add **2,520 B of app flash** over the previous
MACRO implementation at `9b2792e7450e19647faad22f240c85e84c374275` (509,188 B).
Every static RAM region remains unchanged. That revision was rebuilt before this
UI change with the same toolchain and assets; its app hash matches the earlier
measurement. Baseline and final UI-change artifacts are in ignored
`build/macro-ui-before/` and `build/macro-ui-after/`.

### CPU

Host compiler: Apple Clang 21.0.0, arm64 macOS, `cc -O2`; the kernel's
`proc_pid_rusage` instruction counter is available. `tests/regress.c` holds eight
notes per MACRO preset, warms for approximately 0.5 seconds of audio, then counts
44,096 frames (approximately one second). Counts include the four-part mixer,
idle work, filter, envelopes and preset sends. All old budgets remain unchanged.

| Factory preset | Host instructions / frame |
| --- | ---: |
| WAVE SCAN | 1,995 |
| WAVE BASS | **2,219** |
| FOLD LEAD | 1,807 |
| FOLD PAD | 1,800 |
| FBFM BELL | 1,276 |
| FBFM BASS | 1,374 |

The unchanged base's heaviest preset was ANALOG RAVE at about 1,610 instructions
per frame; idle was about 310. Thus the heaviest new factory workload is roughly
38% more host instructions than that old workload, not 38% device CPU usage.

`tests/macro_test.c` separately measures 1 / 2 / 4 / 8 voices with TIMBRE 127,
COLOR's eight branch endpoints, DRIVE 127, CUT 110, RES 8 and sends 20 / 20 / 35.
It uses the same warm/count interval. Three consecutive runs gave:

| Workload | Host instructions / frame | Net / voice after subtracting idle |
| --- | ---: | ---: |
| Idle | 314.1–314.8 | — |
| WAVE, eight voices | 2,210.5–2,210.7 | 237.0–237.1 |
| FOLD, eight voices | 1,948.6–1,950.6 | 204.2–204.6 |
| FBFM, eight voices | 1,373.8–1,384.2 | 132.4–133.8 |
| Four WAVE + two PHYS SYMP + two FM6 PAD | 2,161.6–2,163.6 | — |

The host corner budget is 2,600 instructions per frame, with margin above these
observed loads. Timing in host nanoseconds is informational and depends on machine
load. No host-to-pi32v2 CPU percentage conversion is used.

The fresh target disassembly's weighted static loop costs are 119 for the MACRO
wrapper, 975 for WAVE, 302 for FOLD and 43 for FBFM. There are no divides or calls
inside these sample loops; model dispatch calls occur outside the wrapper's loop.
These are the existing `target_budget.py` estimates (nested loops weighted ×4),
not cycles or a proof of meeting the 2.902 ms DMA deadline. Each function has a
new budget; all existing target budget entries are retained.

The UI follow-up leaves DSP source and sample-loop costs unchanged. Its final
full-suite corner run measured eight voices at 2,230.2 / 1,953.0 / 1,373.2 host
instructions per frame for WAVE / FOLD / FBFM, and 2,160.3 for the mixed load;
all remain inside the existing budgets. Counts vary slightly between runs; the
three-run DSP table above records the earlier implementation measurements.

The same extended `tests/ui_render.c` harness was compiled with Apple Clang
`cc -O1` against an archive of `9b2792e` and the final sources. In consecutive
runs after the suite finished, its process-clock averages were:

| OSC model | Old scope: forced panel draw | New preview: forced panel draw | New cached frame |
| --- | ---: | ---: | ---: |
| WAVE | 47.2 µs | 36.6 µs | 0.08 µs |
| FOLD | 47.1 µs | 33.7 µs | 0.07 µs |
| FBFM | 47.3 µs | 33.7 µs | 0.08 µs |

The harness averages 800 calls for each panel measurement. With unchanged
parameters, the old animated scope still redrew every other frame (23.3–23.7 µs
per call); the new preview only checks its signature. LARGE full-screen redraws,
including its richer new strip, measured 67.7 / 72.8 / 78.4 µs versus
74.8 / 65.3 / 65.3 µs previously, averaging 200 forced redraws per model.
These host times are informational, depend on machine load and exclude actual
LCD transfer and interrupt timing. They do not establish FM-1 CPU utilization.
Reports and the archived baseline harness are retained under the UI-change
artifact directories above, including their `ui-cost/` subdirectories.

## Validation and reproduction

Fresh target build, the full applicable `tests/run_tests.sh` suite and target
resource checks are required. Use [BUILDING.md](../BUILDING.md) for toolchain and
host environment setup. For focused checks after rebuilding the harnesses:

```sh
build/host/regress tests/golden.txt tests/cpu_baseline.txt
build/host/macro_test
build/host/union_test tests/union_golden.txt
build/host/asan/macro_core_test
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
```

Coverage includes all six preset goldens and health checks; all 92 old hashes and
720 old switch hashes retained; 192 added switches to/from MACRO with release
tails and notes inside the switch fade; tuning and control response, phase/filter
retention on sounding retriggers, independent part state and exact release silence;
eight-voice filter/resonance/drive corners; stable IDs across four FM4/SLICE
configurations; MACRO user preset and FUN10 backup round trips; PER4/PER5 favorites
and MIDI LEARN isolation; malformed/CRC backup checks and persistence fuzzing.

The isolated core runs strict ASan and UBSan, including signed arithmetic and
shifts: wide-reference interpolation checks, all 128 TIMBRE values, COLOR branch
endpoints and low/high pitches, endpoint guards and model-change continuity. The
other DSP's historical signed-wrap exclusions remain confined to its existing
sanitizer suite.

UI validation renders default and DIGITAL-enabled builds, all palettes, FLAT,
LINE and LARGE, with zero layout findings. The generated engine-map image and
MACRO's HOME/OSC/TONE controls were inspected. Chromium's actual emulated panel
selects MACRO through EDIT's B4 key, changes WAVE/FOLD/FBFM and shows the controls
without overlap. Native and WebAssembly produce identical output for 476,280
frames covering all six MACRO presets, key chords, TIMBRE/COLOR gestures and
release tails; the existing heavy-song parity check is preserved.

The new UI tests compare all 128 timbres at eight texture/blend corners with the
settled DSP tables, check labels and pitch formatting, preserve generic DESC,
and prove cached idle draws leave track and engine state untouched. Chromium
exercises model changes and control endpoints in normal and LARGE layouts. A FOLD
sound saved as MACRO01X reloads after a full page refresh with FOLD 43%, BLEND 35%
and TUNE 0 st retained; its preview and hints are restored too. AudioWorklet is
running at 44.1 kHz, and the 390 px viewport has no horizontal overflow. These are
browser observations, not real-device observations.

Local baseline/after ELF, binary, disassembly, section reports, hashes and logs
are under ignored `build/macro-before/` and `build/macro-after/`; the UI follow-up
is captured separately in `build/macro-ui-before/` and `build/macro-ui-after/`.
Generated UI images are under `build/ui_new/` and `build/ui_fm4/`. The optional DaisySP float
reference is skipped because no DaisySP checkout is configured. The host suite's
five pre-existing unsequenced `host_now` warnings in `input_test.c` remain; the
fresh target build has no compiler warnings.

### Remaining real-device checks

No FM-1 was flashed or measured. Before a hardware-validated release, listen to
all models and extreme controls, check live preset/model changes and panel/MIDI
behavior, and record audio ISR min/max/average time, overloads and stack guards
with eight voices, four-part mixed loads, all effects, modulation, USB audio/MIDI,
TRS MIDI and nested TIMER5 scanning. Compare the unchanged base on the same device.
Record these in issue #27; the local and browser checks do not close that gate.
