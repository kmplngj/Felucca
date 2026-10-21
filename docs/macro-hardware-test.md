<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO hardware acceptance

All device checks below are **Pending hardware validation**. No FM-1 is exposed in
this cloud workspace. Native/Wasm parity and browser persistence exercise simulated
hardware; they do not establish device deadlines, physical input/display behavior,
real NOR timing, USB audio/MIDI or TRS MIDI.

## Candidate and installation

Use the firmware producer repository, `kmplngj/Felucca`, and the final issue #27 PR
head. Record the full commit, build flags, resolved profile, artifact checksum and
`provenance.json`. Replace `PR_NUMBER` and `FULL_SHA` with the published handoff's
values. Check out the published PR branch before using these commands: until this
PR is merged, main's helper does not accept `--profile`. A development ABOUT
version alone cannot identify the artifact.

MACRO is opt-in: the candidate must use **`FELUCCA_PROFILE=macro`**. The default
`standard` artifact does not contain MACRO. Do not install a standard artifact to
perform this procedure. The PR handoff must identify the macro-profile Actions run
and its installable `felucca-macro.fwsc`; a raw `.bin` is not an installation package.
See [BUILDING](../BUILDING.md) for toolchain/SDK prerequisites and checksums. A local
build from the exact source revision uses:

```sh
FELUCCA_PROFILE=macro ./build.sh
python3 tools/fm1_install.py build/felucca-macro.fwsc
python3 tools/fm1_install.py --info
```

The PR helper requests or reuses an exact-commit **macro-profile** run. The
workflow reference selects the PR branch's profile-aware workflow; it is separate
from the pinned firmware source revision. Prepare/download without a connected FM-1:

```sh
python3 tools/fm1_pr.py PR_NUMBER --commit FULL_SHA --profile macro \
  --workflow-ref feat/macro27-current-main --download-only
```

On the host connected to the normally running FM-1, close applications using its
MIDI ports and omit `--download-only` to verify and install the same package:

```sh
python3 tools/fm1_pr.py PR_NUMBER --commit FULL_SHA --profile macro \
  --workflow-ref feat/macro27-current-main
```

Keep downloaded provenance and checksums. The helper asks before flashing. Do not
enter ROM download mode. Automatic/default standard-profile builds cannot replace
this explicitly selected artifact.

Before installation, retain a full backup using the compatible editor's Backup
export, and retain the previous firmware package. Use unused USER/project slots;
record their numbers. Earlier firmware cannot reproduce engine 14 sounds or all
new settings. A firmware downgrade is not a data rollback: restore the matching
pre-update backup if downgrading. See [MACRO compatibility](macro-engine.md).

Required setup: FM-1, USB data cable, headphones or recorded line output, a Mac/Linux
host, a MIDI source able to address channels 1–4, and a TRS MIDI source/cable for the
transport checks. Record host OS, audio application, USB sample rate and routing.

## Start and identify

1. Close editor, DAW, MIDI senders and serial monitors; unplug TRS MIDI. Restart with
   no keys/buttons held. Transport starts stopped; the green PLAY light is off.
   Existing RESTORE LAST settings can restore a project, so record which project
   appears. Tap HOME from another page to reach HOME. Turn ALGORITHM left until T1
   is selected. Set MASTER to a comfortable low listening level.
2. Hold HOME more than 0.7 seconds until MENU appears, then release. ALGORITHM
   selects the SYSTEM tab; PRESETS selects ABOUT; OCT+ opens it. Record version,
   then OCT− returns. Tap HOME to close MENU.
3. From HOME tap SAVE once for USER and again for PRESETS. Turn KNOB 2 until MACRO
   appears, after DRUM in this profile. KNOB 1 or PRESETS browses its factory sounds;
   select WAVE SCAN. Tap HOME. This route follows the profile's engine order rather
   than assuming a fixed EDIT-map keyboard key.

## Models, controls and live changes

1. On MACRO HOME, KNOB 1/2 edit the model-specific TIMBRE/COLOR controls, KNOB 3 CUT,
   KNOB 4 MODEL. Tap EDIT for OSC: KNOB 1 MODEL, 2 TIMBRE, 3 COLOR, 4 TUNE. Wait at
   least 0.5 seconds between EDIT taps to avoid the double-tap layer lock. Next EDIT
   opens TONE: CUT, RES, DRIVE, FINE on KNOB 1–4. Follow visible model-specific labels.
2. On OSC, turn KNOB 1 fully left to WAVE, then visit all 48 model positions through
   QUESTION. For each, play C4, a low note and a high note; sweep TIMBRE/COLOR through
   low/mid/high, release and retrigger. Record silent, stuck, unexpectedly clipped or
   discontinuous sounds, the model and exact values. Percussion can decay while held;
   strike again when checking it. High-note aliasing is a documented limitation.
3. Sustain a note and change models in both directions, especially WAVE/FBFM → an
   added model → WAVE. Expect responsive labels/control hints and clean release, with
   no reset or stuck note. Release all input before changing the next test.
4. Continue tapping EDIT until VOICE. KNOB 1 selects POLY/MONO/LEG/UNI. Play an
   eight-note chord from MIDI in POLY and UNI: WAVE/FOLD/FBFM allow eight voices;
   models 3–47 allow one Felucca voice per part. PLUCKED retains internal string
   history. Compare the audible allocation while changing between legacy/added models.
5. Load a different factory preset with PRESETS. Hold SAVE >0.7 seconds and release:
   the previous loaded sound returns. Hold again to swap back. Verify notes release.

## Save, cancel, restart and load

1. Select an added model, note all eight control values and change each control on
   OSC/TONE. Tap HOME then SAVE for USER. KNOB 1 chooses the recorded unused slot;
   KNOB 4 selects SAVE; OCT+ opens NAME. KNOB 1 moves the cursor, KNOB 2 changes a
   character, KNOB 3 changes category. Record the name/category. OCT− cancels: no
   preset should have been written.
2. Repeat SAVE selection, then OCT+ to NAME and OCT+ to write. If the slot is used,
   OCT+ first confirms OVERWRITE; use only a disposable slot. Keep transport stopped.
3. HOME, then PRESETS loads another sound. SAVE → USER, KNOB 1 same slot, KNOB 2
   selects LOAD, OCT+ loads. Inspect OSC/TONE: model and all eight values must match,
   with the saved name/category, and the sound must play.
4. Restart normally; repeat USER LOAD from the same slot. Verify the same values and
   audio. Repeat for WAVE and QUESTION to cover the legacy and highest stored model.
5. For four-part project persistence, tap SAVE four times from HOME (USER → PRESETS
   → PHRASES → PROJECT). KNOB 1 selects a disposable project slot, KNOB 4 SAVE,
   OCT+ NAME, OCT+ writes (used slots add overwrite confirmation). Restart, return to
   PROJECT, select the same slot, KNOB 3 LOAD and OCT+. Verify all four parts.

## Four parts, effects and transports

1. Select T1–T4 with ALGORITHM and set MACRO on each via SAVE twice → PRESETS → KNOB 2.
   First use HARMONICS on all four parts; then repeat with WAVE, FOLD, PLUCKED and
   QPSK. Record each part's preset, voice mode, control values and envelopes. Tap FX:
   KNOB 2 CHOR, 3 DLY, 4 REV; use matching displayed amounts on every part. Record
   global delay/reverb/chorus settings too (subsequent FX page taps reach them).
2. Hold HOME to MENU, ALGORITHM → MIDI, PRESETS → MIDI IN, OCT± → CH1-4. Close HOME.
   Send a fixed repeating chord/note sequence on channels 1–4 at a recorded tempo,
   velocity and duration. Include strikes, overlapping notes, sustain and note-offs.
   Play for at least 60 seconds while editing TIMBRE/COLOR and changing models. Expect
   responsive controls, no resets or stuck notes, and usable audio without dropouts.
3. Repeat the identical sequence while capturing USB audio at the host's recorded
   supported rate. Repeat with USB MIDI and TRS MIDI separately and together, documenting
   which source drives each channel to avoid unintended duplicate notes. Record audio,
   panel responsiveness and any stream or note failures. Stop transport with PLAY if
   running; send note-offs/sustain-off and release keys before saving.

## Diagnostics and report

Follow [diagnostics](diagnostics.md#idle-baseline-setup) for the quiet baseline. To
expose CDC: hold HOME, SYSTEM tab with ALGORITHM, USB SERIAL row with PRESETS,
OCT+ ON, HOME closes MENU; wait for re-enumeration. Select the explicit device tty
and close competing serial clients. On macOS use its `/dev/cu.usbmodem…` name;
on Linux use the matching `/dev/ttyACM…`.

```sh
python3 tools/fm1_diagnostics.py --port /dev/ttyACM0 \
  --scenario 'MACRO four-part; recorded project/MIDI/FX/USB workload' \
  --duration 60 --interval 5 --firmware-revision FULL_SHA
```

The label does not generate the workload. Run the stated MIDI/audio workload during
collection. Keep `summary.json`, `samples.jsonl` and `console.raw`; check VALID
continuity and counter deltas for audio lateness, voice shedding/given-up, USB errors,
stalls and UART drops. Missing fields are unavailable, not measured zero. Retain
crash/guard information; static stack allocations do not establish high-water use.
Repeat the same workload on the baseline and candidate, and with/without polling to
observe collector overhead. Host timing or static budgets do not prove FM-1 deadlines.

Report commit/package/profile, device version, host and transport setup, slot/project,
model/control values, steps performed, expected versus observed results, audio and
logs. Restore USB SERIAL and host/MIDI settings after collection. Mark every unrun
scenario pending; a successful installation is not completion of this checklist.
