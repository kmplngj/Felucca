<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Fork features and testing

This guide describes the controls, compatibility limits and testing tools summarized in
the [README](../README.md). The [upstream manual](https://github.com/hugelton/Felucca/wiki/Home)
covers the shared controls and engines. The [fork site](https://kmplngj.github.io/Felucca/)
publishes tested main builds and a pinned WebApp fork; its
[source revisions](https://kmplngj.github.io/Felucca/sources.html) may differ from this checkout.

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

## MIDI timing and arithmetic hardening

TRS input is polled at 2 kHz even while audio renders. Packets and timestamps are
published by TIMER5; sequencers and synth state remain owned by the audio consumer.
Only receive/overtime events consume UART DMA counts. USB MIDI remains deferred.
External USB/TRS clock uses fixed musical units with separate fractional carries
for each sequencer and arpeggiator, including tempo changes and SONG sections.
An extreme live ARP rate reduction can create a temporary backlog: at most eight
notes are generated per control block and remaining phase is retained for later
blocks. Stop freezes that backlog; a new key tapped while stopped still sounds
once and its gate ends in real time. Internal-clock timing and stored IDs are unchanged.

Invalid internal tempo uses the declared 120 BPM default locally; valid 40–240 BPM
and a measured external beat retain their timing. This guard does not establish
the cause of the previously reported intermittent zero tempo. Signed DC/low-cut,
FM6 and PHYS scaling is defined without changing the normal vectors/PCM.
See [evidence and combined device procedure](midi-dsp-reliability.md).

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

### Retained exclusion after a failed worker (#410)

A worker that failed must not start again just because the unit reset before the OFF
preference was saved. While the worker answers, the firmware keeps an 8-byte guard in
retained RAM (`.noinit`, present only in `FELUCCA_CPU2=1` builds). A failure records
the reason in it **before** the worker is held or the chip resets:

| Reason (console `cpu2_excl`) | Meaning |
| --- | --- |
| 1 `BAD JOB` | the worker refused a job whose check word did not match |
| 2 `TIMEOUT` | it did not finish a block within 4 ms (it stalled or faulted) |
| 3 `FAULT` | core 0 itself faulted while the worker answered |
| 4 `HANG` | the watchdog reset the chip while the worker answered (found at the next boot) |
| 5 `CORRUPT` | the guard's magic matched but its contents did not; refused, never trusted |

While an exclusion is held, a saved **2ND CORE ON** is not honoured: at startup the
worker is not started, the preference is cleared again (a normal deferred save from
the main loop), and the screen shows `2ND CORE HELD: <reason>`. A failure during the
session shows the same notice. The unit runs on one core, as with the setting OFF.

**Recovery.** Open **MENU > SYSTEM > 2ND CORE**, set it to **OFF**, then back to **ON
(BETA)**. The screen shows `2ND CORE RETRY: RESTART`, which clears the exclusion; the
worker is tried again at the next power-on or restart. Leaving it OFF keeps the unit on one core and
the exclusion in place. The editor's MENU_SET of the same item has the same effect.
A restart alone, a firmware update or the saved ON never clears the exclusion.

Limits: the guard is judged by what the firmware wrote, not by proof that the worker
caused a fault. Whether `.noinit` survives a given reset class or a short power-off on
a real FM-1 has not been established, so the policy does not rely on it: a valid
exclusion is kept through every reset class including power-on, and if the RAM was in
fact lost the guard is simply absent (then only the saved preference decides, which a
normal failure has already cleared unless power was lost before that deferred save).
Real-device warm-reset and power-cycle checks are pending. `FELUCCA_CPU2=0` builds have
none of this. The design adapts the idea and record of
[fm1-x0x ed35a452](https://github.com/charlesvestal/fm1-x0x/commit/ed35a45235d506564440b707bb7cf5f491d4e2b8)
(GPL-3.0) to this HAL.

## Project compatibility

Projects with conditional steps do not open on 1.5 or 1.5.1; projects saved by
1.4 or later do not open on 1.1.5.x. Review the upstream
[release notes](https://github.com/hugelton/Felucca/wiki/Release-Notes) and
[upgrade guide](https://github.com/hugelton/Felucca/wiki/Upgrading-from-1.1.5)
before downgrading, alongside the fork-specific limitations above.

## Identify the installed build

The startup screen uses your saved colors, including CUSTOM, with the same minimal
layout in FLAT and LINE. Beneath the name it shows one identity line at the normal
version size (very long release labels use the smaller font, then explicit ellipsis
if still too wide; the full version remains in build provenance):

- Clean, identified `--release` builds show their version.
- Verified CI PR builds show `PR #123 merge` or `PR #123 head`.
- Development builds show the compiled commit (eight hexadecimal characters).
  `-dirty` marks modified local sources, including dirty `--release` builds;
  `unknown` means the source has no verified revision.

Every build keeps the same 430 ms automatic deadline from the input scanner's start;
required initialization and session restoration can take longer. Press any button or
piano key to skip the splash once initialization is ready. The dismissal is consumed
through release, so it cannot also play a note, start playback or open a menu. Release
all held controls, then press again for normal input. Knob turns do not dismiss the
splash and are discarded during it; MASTER remains live. The existing LED sweep adds
no startup delay. Startup calibration/recovery gestures retain precedence.

**MENU > SYSTEM > ABOUT** retains the full version, compiled commit and optional PR
label, along with maker and community credits. It remains available after the short splash.
Hold **HOME** until MENU appears, release it, turn **ALGORITHM** to SYSTEM, turn
**PRESETS** to ABOUT and tap **OCT+**. Turn PRESETS to scroll; OCT− returns to the
menu and HOME closes it. Keep the full artifact provenance with test reports.
See [build identity](../BUILDING.md#build-revision-and-pr-identity) for local/archive behavior.

ABOUT also shows this build's source repository (`github.com/kmplngj/Felucca` in
this fork). It follows the GitHub Actions repository or local GitHub `origin` at
build time, so another fork displays its own source after rebuilding. Turn PRESETS
to read wrapped links and the preserved upstream and third-party credits.

**MENU > SYSTEM > INFO** identifies the installed build using
a verified PR label, otherwise a clean identified
release's version, otherwise the compiled commit (including `-dirty` or `unknown`
when applicable). PR builds also show a **COMMIT** row with the compiled revision;
normal PR checks show the test merge's commit, exact-PR builds the selected head.
From HOME, hold **HOME** until MENU appears, release it, turn **ALGORITHM** to
SYSTEM, turn **PRESETS** to INFO and tap **OCT+**. USB state and CPU load remain
below the identity. Tap **OCT−** to return to SYSTEM or **HOME** to close MENU.

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
