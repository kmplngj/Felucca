<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Fork features and testing

This guide describes the controls, compatibility limits and testing tools summarized in
the [README](../README.md). The [upstream manual](https://github.com/hugelton/Felucca/wiki/Home)
covers the shared controls and engines; hosted upstream tools may differ from this checkout.

## Fork features

- **Automatic project saves:** with RESTORE LAST on, autosave waits for stopped transport,
  idle controls and voices, and ten seconds of quiet stereo output. Long effect tails
  keep postponing the save; USB LEVEL FIXED also protects the full-level USB signal with MASTER turned down. See the
  [autosave contract](extending.md#41-flash-map-and-deferred-save-example).
- **UI fonts:** source builds use M8Stealth57/89 by default. `FELUCCA_FONT` selects
  `m8stealth`, `tamzen` or `inter-tight` at build time; keycaps retain Inter Tight.
  The [controlled font comparison](font-experiment.md) records about 39 KB less
  firmware flash and 1,032 B less POOL RAM for pixel-font decode caches than Inter Tight.
  Physical FM-1 readability and redraw checks remain pending. [Compare real renderer captures](ui-comparison.md).
- **RECENT sounds:** on SAVE > PRESETS, turn KNOB 4 (LIST) past OTHER to RECENT for
  the last eight loaded sounds, newest first. PRESETS browses them; loading from RECENT
  keeps the list order, and SAVE held undoes the audition. Deleted or replaced user
  sounds are skipped. The list is per session, excludes patterns/projects, and is not
  stored in a project or backup.
- **MOMENTARY status:** hold LFO and turn a knob on HOME or a sound/FX page; releasing
  LFO restores the value, or OCT+ while holding keeps it. The header shows MOMENTARY
  TURN, how many values will restore, or KEPT until LFO is released. Messages and
  quick-layer labels take priority.
- **Previous page:** on a family's page, hold OCT− and tap its family button to go
  back one page, wrapping from first to last. It consumes the octave modifier and
  preserves sounding notes' pitch. Press OCT− first for FX, GLO, SCL, EDIT and SEQ;
  their quick layers use OCT− pressed afterward for UNDO. Other-family buttons,
  dialogs and MIDI LEARN retain their normal behavior.

For playback transpose, select **SCL > QNT SEQ+T**: melodic sequencer notes
apply TRN before scale snap, without rewriting stored steps. Existing QNT modes keep
their behavior; engines with their own key maps (DRUM and SLICE) are exempt. Older
firmware reads SEQ+T as SEQ. **SEQ TOOLS > EUCLID** exposes HITS, STEPS and ROT with
a single undo step and a live, reversible preview (OCT+ applies; OCT− cancels); seeded drop
remains future work. Cancelling retires the preview's undo entry without clearing
a later load's undo, and keeps earlier tools available to the layer's OCT− undo.
An early nudged first step uses the upcoming loop's condition, including at LEN 1.

## Effect control smoothing

Shared chorus Depth changes glide while the bus sounds: tap and release **FX**
repeatedly until **CHORUS**, then turn **KNOB2 (CDP)**. Cycle FX to the **FX** page
and turn **KNOB2 (CHO)** for each track's send. Depth edits use the same glide
regardless of control source (one detent takes about
0.36 ms, a full-range jump at most 46.1 ms). After the chorus tail drains, the next
sound starts at the selected Depth. Static settings and saved project/settings
formats are unchanged; INSERT CHOR retains its existing behavior.

On the **FX** page, **KNOB2 (CHO)**, **KNOB3 (DLY)** and **KNOB4 (REV)**
glide to their new send levels over one rendered control block while a track
sounds (normally 32 samples, about 0.73 ms). This also applies to modulation and
parameter locks. A new sound after silence starts at its current send levels.
While REV/ECHO THROW is active or fading, all three sends keep their existing
THROW behavior. Dry LEVEL/PAN and saved formats are unchanged. See the
[send experiment](../tests/send_gain_test.md) for measurements and pending hardware checks.


Real FM-1 listening and timing qualification remain pending for these experiments.

## Optional second core

The upstream 1.6.1 second-core worker is integrated, with its device preference off
by default. Set **MENU > SYSTEM > 2ND CORE > ON (BETA)** and restart to enable it;
unreliable units fall back to one core. Device reliability remains unverified in
this fork. The separate fork experiment is retired; see the
[modularity plan](modularity.md#combining-our-plan-with-felucca-161--2026-10-14).

## Project compatibility

Projects with conditional steps do not open on 1.5 or 1.5.1; projects saved by
1.4 or later do not open on 1.1.5.x. Review the upstream
[release notes](https://github.com/hugelton/Felucca/wiki/Release-Notes) and
[upgrade guide](https://github.com/hugelton/Felucca/wiki/Upgrading-from-1.1.5)
before downgrading, alongside the fork-specific limitations above.

## Identify the installed build

The startup screen and **MENU > SYSTEM > ABOUT** show the display version and
build commit (eight hexadecimal characters). `-dirty` marks modified local sources;
`unknown` means the source has no verified revision. Verified CI PR builds also show
`PR #123 merge` (the compiled test merge) or `PR #123 head` (the exact selected commit).
Hold **HOME** until MENU appears, release it, turn **ALGORITHM** to SYSTEM, turn
**PRESETS** to ABOUT and tap **OCT+**. Turn PRESETS to scroll; OCT− returns to the
menu and HOME closes it. Keep the full artifact provenance with test reports.
See [build identity](../BUILDING.md#build-revision-and-pr-identity) for local/archive behavior.

## Testing without hardware

The [emulator partition regression](../BUILDING.md#emulator-partition-regression) checks
that equivalent scheduled MIDI/panel input produces exactly the same audio and state
through the browser bridge with different render partitions, without an FM-1.

The [interaction replay guide](interaction-replay.md) shows how to run a
timestamped key, button, encoder and MIDI sequence through the native emulator,
with synchronized WAV audio, LCD frames and a provenance manifest under `build/`.
It works without hardware on Linux/macOS; its audio captures the DAC output after
MASTER and the metronome, and its manifest records the emulator's delivery timing.

The [cloud browser test](cloud-testing.md) drives this checkout's emulator in
Chromium and checks LCD updates, keyboard/pointer/encoder input, stereo audio,
portrait layout and browser saves. It runs without an FM-1 or model calls, writes a
compact report and retains screenshots/WAV on failure. GitHub Actions runs it for
emulator changes and full validation.

The [host stress matrix](../tests/stress_matrix.md) replays fixed voice-load, effect and
engine-switch, dense ratchet/modulation, throw and MIDI-parser workloads, plus real
emulator panel/save timelines. It retains exact PCM, WAVs, LCD captures and health
results without an FM-1, with a separate [FM-1 capture procedure](stress-device.md)
and result template for pending physical observations.
