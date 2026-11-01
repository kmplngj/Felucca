<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Upstream 1.8.0 integration

The donor is [hugelton/Felucca v1.8.0](https://github.com/hugelton/Felucca/releases/tag/v1.8.0),
commit `9f62297c2db627bbcb20d7ce896683a17318674c`. The fork baseline is
`f0fea3c5fce7a0134f84543e09b64001c2991b33`. This is a feature backport,
not an upstream binary or a new tagged fork release. The default development
version now reflects the accepted upstream base, v1.8.0.

The integration branch records the peeled release commit as a Git ancestor while
retaining the adapted fork tree. Merge this PR with a merge commit: squashing or
rebasing would discard that upstream ancestry and make GitHub report the same
release commits as missing again. Newer upstream commits remain visible.

## Coverage and adaptations

| Upstream change | Integration |
| --- | --- |
| CLEAR ALL, undo for hand-edited steps, contextual dialogs and longer messages | Copied behavior into the fork's native UI and project paths; preserves Direction A, M8 typography, gestures and external menu IDs. |
| Dirty-project LOAD and MIDI LEARN CLEAR confirmations; modal PLAY stop; NO CLOCK | Ported with upstream regressions. LOAD compares against the last saved/loaded project, separately from deferred autosave. |
| Six-letter value names, SLOT A–D, HELP and QUANTIZE hint | Ported in the existing parameter/knob/page owners. |
| FM6 AMS correction (`79ece4f`) | Copied correction and operator regression; AMS-zero factory voices retain their sound. |
| AFTERTOUCH (`1d431e4`) | Copied pressure math, three appended common parameters and dedicated modulation route. FM-1 analog scanner helpers are adapted from BSP `5942e68b89ab9ccd23f2c541d712ca38fe635f11`. Physical sensing is FM-1-only; MIDI channel pressure remains available on other adapters. |
| Five-colour palettes (`19dfe41`, `5ff74b8`, `6ecba52`) | Copied five stored colours, one-time CUSTOM migration, red/blue signal colours and green USB battery; retained native layout. Fixed inherited alpha-ramp greyscaling of coloured icons. |
| ADPCM (`5d9694d0475a74c63c71b9aab4edff408f48cd5f`) | Copied BRR decoder, synthesis, generated original waves and reference tests. Optional profile uses ID 15, preserving MACRO 14. Host-owned post-render hook preserves the pinned MIT engine interface. Disabled in standard builds. |
| SDL2 desktop (`1350697`) | Copied `platforms/common` and `platforms/linux`, adapted to fork profiles and HAL. Source-only beta; see [desktop instructions](../platforms/linux/README.md). |
| Loop-span target-budget correction (`7fe8937`) | Copied joining of partially overlapping backward spans; retained nested-loop distinction and regression fixtures. Existing thresholds were not globally regenerated. |
| Upstream 1.7 reliability and licence fixes | Already present in the baseline; see [existing provenance](midi-dsp-reliability.md). |
| BSP extraction and portable PHASE relocation | Retained the fork HAL, SMK targets, recovery safeguards and native PHASE state. Required pressure-scanner behavior is ported without replacing these diverged implementations or the pinned MIT interface. |
| CoreS3, proposed SMK and other prospective ports | Upstream release describes future work; no missing published implementation is claimed as supported. The fork's existing experimental SMK implementation remains separate. |

Necessary native safety adaptations preserve held-track pressure when selection changes,
keep the ADC owned by its pending scan until completion, and retain MASTER gain
until the first valid scanned pot reading. ADPCM echo participates in the existing
engine-switch fade; these changes leave steady-state DSP/reference output intact.

Original notices remain with copied files. [Licensing](../LICENSING.md#upstream-180-copied-components)
records the MPL pressure helpers and LGPL BRR decoder. No restricted factory sample
bank is included. Sol subagents performed implementation and independent review.

## Compatibility and limits

Aftertouch defaults to OFF. On EDIT > VOICE 3, AT selects sensitivity 1–10,
ATDST the destination and ATAMT its depth. Enabling AT with no route selects
CUT +32 (DRUM: DIST). Only physical F3–C5 sense pressure; the top seven keys do not.
Pressure goes to the held key's original track and USB MIDI OUT as channel pressure.
Incoming MIDI channel pressure uses the same route with physical sensing off.
The three parameters precede engine values using the existing count-based storage
mapping; older projects/presets import with aftertouch off. Newer aftertouch data
has the usual older-firmware downgrade limitations.

CLEAR ALL resets live tracks, steps, automation and song order to a new project.
It leaves saved projects, user presets, samples, settings and MIDI LEARN intact.
OCT− cancels its confirmation; OCT+ executes it. Save a project first if its live
state must remain available; autosave is not a separate user project slot.

Palettes store background, identity, text, primary, secondary in that order.
Old CUSTOM values migrate once on import/load, using a private persistence bit;
legacy protocol packets retain their lengths and flags. New clients explicitly request
the new order, while legacy clients retain their earlier wire layout. The companion
Felucca-WebApp update selects the matching labels, previews and writes without
guessing from a version string. Older firmware
interprets a newly saved palette using the old order.

`FELUCCA_PROFILE=adpcm` adds the experimental engine alongside all standard engines.
An upstream opt-in ADPCM project uses donor ID 14 and needs an explicit source-aware
remap before import; that ID remains MACRO in this fork. Existing fork sounds are
never silently reinterpreted.
It is not enabled through a bare `FELUCCA_ADPCM=1` override: profile identity and
artifacts must agree. Its arena adds 1,824 bytes of POOL across four parts.
Upstream considers it too expensive for FM-1; host correctness is not device
performance qualification. Desktop MIDI/audio/controller behavior also needs
platform-specific physical checks.

## Known build limits

The standard, CPU2-off, ADPCM and SMK-37 Pro target builds pass their resource
checks. The full MACRO recipe currently fails the XIP linker limit: this working
candidate is 7,400 bytes over, while the unchanged baseline is already 1,320 bytes
over. These figures use default target flags and the working-tree build identity;
MACRO needs separate capacity work before this full recipe can be installed.

A clean validation snapshot passed Git versus verified Git-free native build and
bundle reproduction. Sealed native/WASM receipts remain unavailable because the
baseline mapper rejects its reported board selector. Actual browser behavior and
native/WASM song comparisons are separate checks; this pre-existing receipt gap
is not treated as a passing provenance check.

## Validation and device handoff

Fresh focused host checks cover UI/project formats/SMK UI, FM6 AMS, physical-scan
fakes, pressure/MIDI/modulation, palette migration and native renderer output.
The palette sweep covers 257 scenes in ten palettes with zero lint, colour or
alignment findings. ADPCM's sixteen DSP scenarios match snes_spc 0.9.0 exactly;
optimized and sanitizer tests cover presets, releases and arena switches.
Desktop checks cover compilation, both panel layouts, headless audio and a saved
preset restored by a new process. These are software checks, not device acceptance.
Integrated target/full-suite results and resources are recorded in the task handoff.

Pending FM-1 user checks (do not flash without the operator's installation scope):

1. Back up using the [build/install guide](../BUILDING.md#install). Use the exact
   candidate package, standard profile, CPU2 OFF; record ABOUT identity. From HOME,
   hold HOME over 0.7 seconds, release, select SYSTEM with ALGORITHM and ABOUT with
   PRESETS, then OCT+ to inspect identity; HOME closes the menu.
2. Tap EDIT, at least 0.5 seconds between taps to avoid layer locking, until VOICE 3.
   Start AT OFF and verify the sound is unchanged. Turn KNOB 2 to enable AT, check
   the F3–C5 hint/default route, then hold and press a middle key. KNOB 3 selects
   ATDST and KNOB 4 depth. Check smooth pressure response, release, track selection
   while held, unchanged MASTER response and MIDI OUT channel pressure. The top
   seven keys should not generate physical pressure. Test incoming USB and TRS
   channel pressure separately with AT OFF. SMK requires its own MIDI-only check.
3. With transport stopped, edit a sequencer step on STEP/NOTE/TIME/FLAG and through
   REC entry. Hold SAVE to undo, then again to redo; the message names track/STEPS.
   Load a sound and confirm its undo is labelled SOUND. Verify edited automation
   remains consistent with step undo.
4. Save project A, edit a value, then select LOAD of another project. Verify it asks;
   cancel with OCT− and keep the edit, then confirm with OCT+. Open MENU while
   playing and tap PLAY: playback stops and MENU stays open. Repeat in a dialog;
   PLAY while stopped must not start transport there.
5. Hold HOME, select MIDI with ALGORITHM and LEARN CLEAR with PRESETS. OCT+ opens
   the confirmation; OCT− preserves learned controls. Repeat and confirm. For
   SYSTEM > CLEAR ALL, cancel first, then confirm; verify the new project's tracks,
   empty steps/automation/song, and retained saved slots/presets/samples/settings.
6. Select USB or TRS clock, start from an external source, then remove its clock.
   Expect stopped transport and the matching NO CLOCK notice. Repeat both inputs.
   Inspect GREY/MONO red REC, blue active state and green battery on USB power;
   load an older CUSTOM palette and verify its colours persist after restart.
7. Import a known nonzero-AMS FM6 voice and compare AMD zero/nonzero behavior;
   verify factory AMS-zero voices. Check loaded four-track audio deadlines and
   pressure/USB/TRS activity, then separately repeat with CPU2 enabled if desired.
   ADPCM and each SMK target require separate qualification, not this standard pass.

README, changelog and palette design/product guidance are updated. Diagnostic
command changes belong in the console/capability guides. Physical key pressure,
LCD readability, analog ADC ownership/timing, MIDI cables and audio deadlines
remain pending until exercised on real hardware.
