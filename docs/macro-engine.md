<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO engine

Implemented on `kori/macro-engine`, based on revision
`ef1f561b6b105f20350f6b1eac0dc0789a357f00`.
Tracking: [MACRO implementation #27](https://github.com/kmplngj/Felucca/issues/27).
[Build-time engine selection #28](https://github.com/kmplngj/Felucca/issues/28) is separate work.
Every existing engine remains in the default build.

## Playing

MACRO appears between PHYS and NOISE in PRESETS and the EDIT engine map. Its stable
stored/protocol ID is **14**, with six factory sounds: WAVE SCAN, WAVE BASS, FOLD LEAD,
FOLD PAD, FBFM BELL and FBFM BASS. It shares the existing eight-voice budget across
the four parts, including POLY, MONO, LEGATO and UNISON.

| Control | Range | Function |
| --- | --- | --- |
| SHAPE | WAVE / FOLD / FBFM | Select the oscillator model |
| TIMBRE | 0..127 | WAVE: scan 64 original WAV LINE waves; FOLD: folding gain; FBFM: modulation depth |
| COLOR | 0..127 | WAVE: stepped/smooth samples, wave interpolation, then coarser samples; FOLD: sine-to-triangle blend; FBFM: modulator pitch approximately ±64 semitones |
| TUNE | −24..24 semitones | Transpose the oscillator |
| CUT / RES | 0..127 | Felucca's low-pass filter and resonance |
| DRIVE | 0..127 | Soft clipping before the filter |
| FINE | −50..50 cents | Fine tuning |

HOME's knobs are TIMBRE, COLOR, CUT and SHAPE. OSC has SHAPE, TIMBRE, COLOR, TUNE;
TONE has CUT, RES, DRIVE, FINE. The existing envelopes, filter envelope, sends,
pitch bend, fine detuning and modulation matrix apply. The SHP modulation
destination changes TIMBRE; the E1..E8 destinations address the eight controls
in table order. SHAPE changes retain phase and correct the first sample to the
previous sample, fading that correction over 32 samples. Sounding retriggers
retain oscillator, feedback and filter state; a new note from silence resets them.

## DSP and attribution

`firmware/src/macro_dsp.c` is a selected integer C adaptation of Mutable Instruments
Braids, by Emilie Gillet (MIT), pinned to eurorack revision
`08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4`. WAVE follows `RenderWaveLine`; FOLD blends
`RenderSineFold` and `RenderTriangleFold`; FBFM follows `RenderFeedbackFm`'s previous
carrier → modulator → carrier feedback topology. The wrapper is
`firmware/src/eng_macro.c`. Source links and table extraction details are in
[assets/braids/README.md](../assets/braids/README.md), and the full MIT notice is in
[LICENSES/MIT-Braids.txt](../LICENSES/MIT-Braids.txt). Firmware credits also name Braids.

The tables are original data, generated offline from the bundled JSON. WAVE's 64
waves plus a duplicate endpoint guard, the sine and two folding tables occupy
**9,927 bytes** of immutable XIP data. No delay line or full Braids wave/resource
bank is allocated. Wave interpolation uses split products to avoid signed
overflow; feedback phase modulation wraps in unsigned arithmetic.

Felucca supplies its 44.1 kHz tuning instead of Braids' 96 kHz tables. WAVE and
FOLD average two subsamples. Scan smoothing is adjusted to the 32-sample control
cadence; FOLD and FBFM attenuate high-pitch modulation/folding as in Braids.
Carrier pitch is clamped to Felucca's tuning range; the modulator extends below
note 0 by octave shifts and clamps at the top of the same table. Parameter
ramps, averaging order and Felucca's filter/envelopes differ from the original.
This is a three-model adaptation, not a sample-identical M8 or full Braids port.
These models can alias, particularly on high notes with strong folding/FM.

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
Keep a pre-update backup to restore settings after a downgrade. Existing-engine
projects retain their previous format and sound hashes.

## Measured resources — 2026-10-11

The unchanged base was built first, then the implementation with identical default
features and assets: SLICE enabled, DIGITAL disabled, five sample sets / eleven
zones / 126,244 bytes of ADPCM. Target: JieLi Clang **4.0.1**, pi32v2, package
`jieli-linux-toolchains-20260730.1` via Docker linux/amd64; AC79 SDK revision
`d179b4484759423312073f5fbb232501aa491047`. The normal selective size pass applies
`minsize` to main-loop functions; engine, DSP and interrupt paths retain `-Os`.
No build flags, sample quality or existing engines were removed to make room.

| Resource | Before | After | Delta | After spare |
| --- | ---: | ---: | ---: | ---: |
| App image (`felucca.bin`, capacity 581,564 B) | 495,580 B | 509,188 B | **+13,608 B** | 72,376 B |
| XIP `.text` | 492,240 B | 505,848 B | +13,608 B | Included above |
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
after: `683f17351a1cc55559cdedcbe382a74a034859bf32821928bdbeb80c23d92254`.
The loader remains 6,930 bytes. Package size (610,086 B) is not app-slot usage.

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

Local baseline/after ELF, binary, disassembly, section reports, hashes and logs
are under ignored `build/macro-before/` and `build/macro-after/`. Generated UI
images are under `build/ui_new/` and `build/ui_fm4/`. The optional DaisySP float
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
