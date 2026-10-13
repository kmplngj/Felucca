<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Timestamped interaction replay

Replay panel gestures and channel MIDI through Felucca's real integrated emulator,
capturing the DAC audio and LCD on a declared timeline. This is the native capture
slice of the shared scenario matrix in #46, and the tooling requested in #112.
It measures host/emulator behavior; it does not measure CPU instructions, target
deadlines, or real FM-1 timing.

After the normal asset build, on Linux or macOS with Python 3 and a C compiler:

```sh
./build.sh
python3 tools/fm1_replay.py tests/scenarios/interaction.json --out build/replay/interaction-a
python3 tools/fm1_replay.py tests/scenarios/interaction.json --out build/replay/interaction-b
python3 tests/ui_compare.py build/replay/interaction-a build/replay/interaction-b --out build/replay/compare --strict
python3 tools/fm1_replay.py tests/scenarios/metronome-fixed.json --out build/replay/metronome
python3 tests/replay_test.py
```

CI runs the parser fixtures alone with `python3 tests/replay_validation_test.py`
in the portable Python suite, and the native fixtures with
`python3 tests/replay_test.py NativeReplayTests` after generated assets exist.
Changes to replay tools, native harnesses or scenarios conservatively select full
CI; emulator changes also run the native replay fixtures because the adapter
includes the emulator source.

Use a new output directory for every capture. Outputs must stay under this
checkout's ignored `build/`. No hardware, Emscripten, browser or Pillow is required
for replay. The native adapter is rebuilt when the compiler, flags, source or
generated-asset hashes change; its binary and exact inputs are recorded. `CC`
selects the host compiler, as for the other host tests. A failed run exits 2;
partial outputs have no completed `manifest.json` and should be discarded.

Each output directory contains streamed stereo signed PCM24 `audio.wav`, numbered
240 x 240 RGB PPM frames, the exact input `scenario.json`, and `manifest.json` with
PCM/frame hashes, event order, requested/actual times, state observations, compiler
flags, revision/diff hash, source/font/generated-asset hashes and initial state.
PCM is recovered exactly from the emulator's 24-bit DAC words; there is no dither.
The PPM conversion matches `tests/ui_render.c`'s RGB565 expansion. Frames come from
the firmware's real `lcd_fill`/`lcd_blit` drawing paths. Reading them never draws
or advances time. The test suite verifies that adding captures leaves both PCM
and final firmware state unchanged.

## Shared scenario schema 1

`tests/scenarios/` is the shared location for versioned scenario data. #46 currently
defines workloads without an existing parser or wire schema; this establishes its
sample timeline without adding a second benchmark model. Future host, browser and
device adapters should consume this format and declare their own delivery/tap
contracts. Unsupported events must fail, rather than silently becoming stubs.

The JSON object contains `schema: 1`, `sample_rate: 44100`, optional `name`,
`initial`, and ordered `events`. Unknown fields and duplicate JSON keys are refused.
`initial` has all these fields:

| Field | Meaning |
| --- | --- |
| `state` | `"factory"`: newly erased simulated NOR; no saved projects or user samples |
| `seed` | Nonzero uint32 shared firmware RNG seed, set before boot |
| `warmup_samples` | 22050–220500 frames consumed before timeline zero, allowing the 430 ms boot splash to finish |
| `master` | MASTER ADC value, 0–1023; default example 700 |
| `click` | Initial MENU CLICK value: 0 OFF, 1 REC, 2 ON |
| `usb_level` | Initial MENU USB LEVEL: 0 MASTER, 1 FIXED |

The initial click/USB preference uses the firmware's `menu_put` path after boot;
all other settings, presets and panel mapping start with the emulator's factory
defaults. Factory preset selection and engine switching during the scenario use
panel gestures, not direct test presets. Built-in sample availability follows the
generated assets and is recorded by their hashes.

Each event has a nonnegative integer `sample`, the stereo frame position relative
to the consumer after warmup, and `type`:

| Type | Additional fields |
| --- | --- |
| `key` | `id`: 0–26 (F3–G5); boolean `down` |
| `button` | `id`: FX, SCL, ENV, LFO, EDIT, GLO, HOME, SAVE, ARP, SEQ, PLAY, REC, OCT-, OCT+; boolean `down` |
| `encoder` | `id`: SELECT, ALGORITHM, PRESETS, KNOB 1–4; signed `delta`: −1024–1024 detents |
| `midi` | Channel `status`: 128–239; `data1`/`data2`: 0–127; Program Change/Channel Pressure require `data2: 0` |
| `master` | `value`: 0–1023 |
| `capture` | No additional fields; observe the current framebuffer |
| `end` | No additional fields; must be the final event, at a positive duration |

Notes on/off, sustain, pitch bend and other channel messages travel through
`midi`; note velocity zero has the firmware's normal note-off semantics. System
realtime, SysEx, TRS byte streams and arbitrary parameter injection are unsupported.

Input is limited to 1 MiB, 4096 events, 256 captures, 60 s after warmup and 65536
total absolute encoder detents. The accumulation limit prevents overflow while
several detents wait for a UI read. MIDI queue overflow aborts with the offending
event number. The conservative output estimate includes PCM, PPMs and metadata;
`--max-output-bytes` can reduce the default 96 MiB budget, but cannot enlarge it.
Parsing and output-budget checks happen before compilation or artifact creation.

## Timing and audio tap

`tests/hostsim.c` integrates the real DSP but lacks the complete panel, main-loop
and LCD behavior. `tests/ui_render.c` uses the real drawing code for independently
constructed static scenes. The selected `web/emu/felucca_web.c` already integrates
DSP, audio ISR, UI, panel events, clock and simulated persistence. The small native
adapter includes that existing source; it maintains no separate firmware copy.

The emulator advances its 1 ms clock only to produce the output requested by
`web_render`. It always renders the actual 128-frame DMA half with four CTL=32
blocks. UI input runs every simulated millisecond after the splash and the frame
loop every 15 ms. The runner splits **consumption**, never a DSP/control block, at
each requested event/capture position. A final partial WAV duration still leaves
the complete final DMA half synthesized.

The producer can be ahead of the consumer because rendered audio is queued.
An event is published at the requested consumer position; queued audio is retained,
and firmware observes it at its normal subsequent audio/UI opportunities. It does
not retroactively affect the already rendered portion of a half. The manifest
records the absolute `actual_device_ms` and relative `first_unsynthesized_sample`
alongside every requested sample, plus absolute produced/consumed positions and
the warmup origin. These are publication observations, not a promise that the
note becomes audible at that sample. Physical codec playback and DMA latency are
not simulated. Native/Wasm/browser parity remains covered separately by the existing
emulator suite and the transport-partition tests in #87.

Equal timestamps execute in file order, without intervening rendering. A capture
between two events therefore observes only state published so far; the LCD can
still show the previous 15 ms redraw. Immediate press/release at one timestamp
does not promise a visible or audible gesture. Give a gesture time to reach its
normal service path, as the checked-in sequences do.

Audio is the **DAC tap after MASTER/fixed-level attenuation and the metronome**,
before the hardware codec. USB audio's `uac_tap` is before the click and is disabled
in this adapter. The fixed-level/metronome sequence exercises the real DAC-side
preference and click code; it does not capture a USB device or prove 48 kHz UAC
behavior. Overload shedding and CPU counters do not measure host wall-clock work:
the fake TIMER4 follows emulator time. Hardware observations remain separate.

## Workloads and visual review

`interaction.json` captures held key → octave change → release, overlapping channel
MIDI/key input, retrigger/release, ENV's graph with a tempo edit irrelevant to that
graph and an attack edit relevant to it, then SAVE > PRESETS and an engine switch
while a key is held. It finishes with a release tail and an explicit partial-half
end. The fixtures check the engine really changes, all input is released and no
voice remains active. `metronome-fixed.json` exercises PLAY, click, MASTER and FIXED.

The existing #58 `tests/ui_compare.py` also accepts these replay manifests and
uses the same exact RGB pixel comparison, bounds and comparison sheets as for
static scenes. It pairs frames by requested sample and event order, validates
their hashes and paths, and rejects captures with different scenario hashes,
initial state, timing contracts or build feature settings. Use the same exact
input file for comparisons. Replay manifests retain their distinct timeline and
adapter provenance; they cannot be paired with static-scene captures. Pillow is
needed only for comparison. PPMs can also be opened directly in an image viewer.
The ordinary UI lint/comparison and DSP golden suites remain required; replay
captures complement them. Optional video encoding is an export step (for example,
convert selected PPMs to PNG and encode at their explicitly recorded timestamps),
not a compiler/runtime dependency. Native/Wasm replay parity and browser replay
export can be separate follow-ups.

Unavailable: physical panel debounce/scan interrupts, real USB/UAC/TRS transport,
editor/updates, real NOR timings, battery/crash paths, target CPU/deadlines and
physical screen readability. The adapter's software NOR is simulated, not evidence
of hardware flash timing or wear. No firmware source or device behavior is changed.
