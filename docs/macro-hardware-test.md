<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO hardware acceptance

The [device results record](macro-device-results.md) contains the user's model/control
and held-note switching reports. The raised/black-key symptom, including on FM6,
was resolved by correcting QNT. The specific checks below remain **Pending hardware
validation** except where that record identifies user-reported coverage. No FM-1 is exposed in
this cloud workspace. Native/Wasm parity and browser persistence exercise simulated
hardware; they do not establish device deadlines, physical input/display behavior,
real NOR timing, USB audio/MIDI or TRS MIDI.

## Candidate and installation

Use the firmware producer repository, `kmplngj/Felucca`, and the final issue #27 PR
head. Record the full commit, build flags, resolved profile, artifact checksum and
`provenance.json`. Replace `PR_NUMBER` and `FULL_SHA` with the published handoff's
values. Run installation tools from a trusted reviewed caller checkout with the
profile-aware helper; the downloaded PR sources must not supply the installer.
A development ABOUT version alone cannot identify the artifact.

MACRO is opt-in: the candidate must use **`FELUCCA_PROFILE=macro`**. The default
`standard` artifact does not contain MACRO. Do not install a standard artifact to
perform this procedure. The PR handoff must identify the macro-profile Actions run
and its installable `felucca-macro.fwsc`; a raw `.bin` is not an installation package.
See [BUILDING](../BUILDING.md) for toolchain/SDK prerequisites and checksums. A local
build from the exact source revision uses:

```sh
FELUCCA_PROFILE=macro uv run --locked --group build ./build.sh
uv run --locked --group midi tools/fm1_install.py build/felucca-macro.fwsc
uv run --locked --group midi tools/fm1_install.py --info
```

The PR helper requests or reuses an exact-commit **macro-profile** run. The
workflow reference selects the PR branch's profile-aware workflow; it is separate
from the pinned firmware source revision. Prepare/download without a connected FM-1:

```sh
uv run --locked --group midi tools/fm1_pr.py PR_NUMBER --commit FULL_SHA --profile macro \
  --workflow-ref feat/macro27-current-main --download-only
```

On the host connected to the normally running FM-1, close applications using its
MIDI ports and omit `--download-only` to verify and install the same package:

```sh
uv run --locked --group midi tools/fm1_pr.py PR_NUMBER --commit FULL_SHA --profile macro \
  --workflow-ref feat/macro27-current-main
```

Install uv first (`brew install uv` on macOS; other hosts use
[uv installation](https://docs.astral.sh/uv/getting-started/installation/)). The
locked `midi` group supplies the Python USB-MIDI updater; no backend flag or manual
pip setup is needed. Keep downloaded provenance and checksums. The helper asks
before flashing. Do not
enter ROM download mode. Automatic/default standard-profile builds cannot replace
this explicitly selected artifact.

Before installation, retain a full backup using the compatible editor's Backup
export, verify that it contains all four project slots, and retain the previous
firmware package. The test pack uses **all four project slots A–D**, so mark all
four disposable only after preserving their original data; no project slot remains
outside this test. Reserve one disposable USER slot too and record its number.
The generator writes host files only; imports/saves are explicit user actions.
Never automatically overwrite device slots. Earlier firmware cannot reproduce
engine 14 sounds or all
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
   then OCT− returns. Turn PRESETS to RESTORE LAST, record its original setting,
   and use OCT− to select OFF. This prevents autosave from replacing the working
   music during controlled recall tests; A–D remain explicit project saves.
   Record 2ND CORE and leave it OFF for the primary run (changes apply after a
   restart). Tap HOME to close MENU. Restart normally if a core setting changed.
3. From HOME tap SAVE once for USER and again for PRESETS. Turn KNOB 2 until MACRO
   appears, after DRUM in this profile. KNOB 1 or PRESETS browses its factory sounds;
   select WAVE SCAN. Tap HOME. This route follows the profile's engine order rather
   than assuming a fixed EDIT-map keyboard key.
4. Tap the physical **SEL** button: the second button from the left in the upper
   six-button row, between **FX** and **ENV**. This is the firmware's SCL/scale
   function; use the printed SEL button, not the SELECT knob. If CHORD appears,
   tap SEL again to reach the SCL scale page. Use KNOB 3, labelled QNT, to select
   **OFF**. WHITE deliberately
   silences black keys; quantization is kept across engine changes and in projects.
   With transport stopped and no external MIDI input, tap HOME, press and release every
   physical piano key in the lower and upper rows, first with WAVE SCAN and then
   with an FM6 factory sound. Reach FM6 through HOME → SAVE twice → PRESETS,
   KNOB 2 FM6, KNOB 1 a factory sound, HOME. Each key should strike and release a
   note; record exact failing key positions, octave, engine, page and any held
   layer buttons. Repeat after a normal power cycle. The earlier raised-key report
   was resolved by correcting QNT; this step keeps that setup explicit. After the
   restart verify QNT OFF again. Return to MACRO WAVE SCAN with SAVE twice →
   PRESETS → KNOB 2 MACRO → KNOB 1 WAVE SCAN → HOME before the model checks.

## Prepare the project and song pack

1. From the reviewed candidate checkout, generate the pack on the host:

   ```sh
   uv run --locked --group build tools/macro_device_pack.py \
     --generate-headers --out build/macro-device-pack --candidate FULL_SHA
   ```

   This compiles the firmware's host serializer and writes files; it does not
   connect to, install or change an FM-1. Keep `manifest.json` with the tested
   firmware provenance. This command generates `macro` profile/UI assets and
   needs a host C compiler; it does not need the JieLi toolchain or a target build.
   Later runs can reuse those headers with `python3 tools/macro_device_pack.py
   --out build/macro-device-pack-another --candidate FULL_SHA`. Use a new output
   directory for each run: the generator refuses to replace an existing pack.
   Record the generator's source revision separately from the installed candidate.
2. Keep the full backup from before this procedure outside the generated pack
   directory. Also export each existing A–D project individually. Check that
   A, B, C and D are backed up and disposable before any
   import. In the compatible WebApp open PROJECT, find the PROJECTS card and click
   **Import** within the desired A/B/C/D slot. Select that slot's matching
   `*.felucca-project.json` file and confirm **Import → [letter] (overwrite)?**
   only for the intended disposable slot. Repeat individually for the other slots.
   Import updates slot storage; loading is a separate action.
   Do not import a fixture over a slot you still need. The `.fun10` files are
   the underlying firmware records, not installable packages or full backups.
3. Use this mapping and record the files' manifest hashes. Imported data must
   remain in A–D as specified because the song references those slots:

   | Slot | Import file | Expected setup |
   | --- | --- | --- |
   | A | `A-legacy-poly.felucca-project.json` | MAC LEGACY; four MACRO parts: WAVE/FOLD/FBFM/WAVE; polyphonic strike/tie/rest patterns |
   | B | `B-bank-heavy.felucca-project.json` | MAC HEAVY; four HARMONICS parts; repeated strikes |
   | C | `C-mixed.felucca-project.json` | MAC MIXED; PLUCKED/PHYS/FM6/ANALOG; mixed two-note patterns |
   | D | `D-song.felucca-project.json` | MAC SONG; WAVE/HARMONICS/PLUCKED/WAVETABLE; five song sections referencing A–C patterns |

   All use 120 BPM, internal clock and CH1-4 routing. The manifest records exact
   parameter values. MACRO controls start at model-specific ID, TIMBRE/COLOR 64,
   TUNE 0, CUT 110, RES 8, DRIVE 127, FINE 0. Each part has LEVEL 64, attack/decay 0,
   sustain 100, release 25, CHOR/DLY/REV sends 20/20/35 and ROOM reverb.
   Global FX start at delay time 1/8, feedback 60, color 70, delay mix 90,
   reverb size 90/damping 60, and chorus rate 40/depth 60. These are stored
   integer values; the manifest pairs its globals array with parameter labels.
   Display percentages/filter units differ from these stored integer values.
4. Close the editor after import so it cannot compete for MIDI ports. From HOME,
   tap SAVE four times for USER → PRESETS → PHRASES → PROJECT. KNOB 1 chooses A;
   KNOB 3 selects LOAD; OCT+ loads it. Confirm MAC LEGACY and the four sounds by
   tapping HOME and selecting T1–T4 with ALGORITHM. Repeat LOAD for B, C and D,
   confirming the names and engines/models above before playback. Any unexpected
   import destination, sound or value is a failure to resolve before load testing.
5. With D loaded and transport stopped, tap GLO for SONG. KNOB 1 selects a section,
   KNOB 2 a track; inspect KNOB 3's PAT and KNOB 4's REPS without changing them.
   The sections are `AAAA ×8`, `BCAB ×8`, `CABC ×8`, `BBBB ×8`, then `---- ×1`.
   Press PLAY (or OCT+ on SONG) to start. Expect about 66 seconds at 120 BPM,
   changing patterns while retaining D's sounds, followed by the silent ending
   and stopped transport. Press PLAY to stop early. Run twice and note any missed
   section, stuck note, reset, unresponsive control or dropout.

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
6. Reload A from the imported pack, record its four sounds and eight MACRO values,
   explicitly save it back to A with the route above, load B, then reload A and
   compare. Repeat for B, C and D in their own slots. Preserve the fixture names
   when confirming NAME. After a normal power cycle, load each A–D explicitly
   (RESTORE LAST remains OFF): names, engines/models, controls and patterns must
   match the manifest. With D loaded, tap GLO and compare its five song sections;
   start it with PLAY and verify the same approximately 66-second sequence and
   silent ending. Report any change separately from USER preset persistence.

## Four parts, effects and transports

1. Load A through HOME → SAVE four times → PROJECT → KNOB 1 A → KNOB 3 LOAD → OCT+.
   Tap HOME and PLAY to run its internal patterns for at least 60 seconds; PLAY
   stops. Repeat for B (four HARMONICS parts) and C (mixed engines), then D's song
   through GLO → PLAY. Before each run select T1–T4 with ALGORITHM to verify the
   engine/model, POLY mode, envelopes and manifest values. Tap FX for part sends:
   KNOB 2 CHOR, 3 DLY, 4 REV; later FX taps show global effect pages. Record the
   global values from the manifest and leave them identical in repeated runs.
   Expect repeated notes and ties to release, responsive controls and stable
   audio without resets/dropouts. B is a defined stress workload, not a proven
   worst case over every model, pitch and control.
2. Hold HOME to MENU, ALGORITHM → MIDI, PRESETS → MIDI IN, OCT± → CH1-4. Close HOME.
   Keep the internal transport stopped. Load A and play the pack's
   `macro-ch1-4.mid` at its saved 120 BPM through USB MIDI, routed to channels 1–4
   without channel remapping, looping or transposition. Each file run lasts
   64 seconds: eight-note chords on channels 1, 2 and 3 for eight seconds each;
   all four channels together at 24–56 seconds; rapid strikes at 56–60 seconds;
   note-offs/sustain-off and release tails at 60–64 seconds. Repeat unchanged
   with B and C. Retain the MIDI file's hash, event schedule and player settings.
   Repeat the defined load while editing TIMBRE/COLOR and changing models,
   recording the part, model, values and edit times so that this separate manual
   stress run can be reproduced. Expect
   responsive controls, no resets or stuck notes, and usable audio without dropouts.
3. Repeat the identical sequence while capturing USB audio at the host's recorded
   supported rate. Repeat with USB MIDI and TRS MIDI separately and together, documenting
   which source drives each channel to avoid unintended duplicate notes. Record audio,
   panel responsiveness and any stream or note failures. Stop transport with PLAY if
   running; send note-offs/sustain-off and release keys before saving.
4. After recording the primary run with 2ND CORE OFF, repeat A/B/C and the same
   MIDI/audio workload with the optional worker enabled. Hold HOME, select SYSTEM
   with ALGORITHM and 2ND CORE with PRESETS, choose ON with OCT+, then HOME and
   restart normally. Record worker status and errors alongside audio/controls;
   expect no dropouts, resets or worker failures. Compare the same setup with OFF,
   and restore the original setting after testing (restart to apply it). A host
   split estimate does not establish device deadline headroom.
5. Exercise repeated four-part model resets separately. Reload B, then on each
   T1–T4 tap LFO until the LFO page appears: KNOB 1 RATE fully clockwise (40 Hz),
   KNOB 2 WAVE SAW, KNOB 3 PHASE 0, KNOB 4 FADE 0. Tap LFO to LFO 2: KNOB 1 SYNC
   OFF, KNOB 2 TRIG NOTE, KNOB 3 POL BI. Continue tapping LFO to MOD: KNOB 1 slot 1,
   KNOB 2 SRC LFO, KNOB 3 DST MODEL (engine E1), KNOB 4 AMT +63. Leave B's base
   HARMONICS model intact. HOME → PLAY for 60 seconds sweeps all four model banks;
   expect rapid timbre changes without resets, stuck notes or audio dropouts.
   The matching host setup changes all four models in 475/1,000 control blocks,
   including 446 consecutive pairs; these are host workload counts, not device
   timing measurements. Record actual FM-1 render timing/lateness separately.
   Stop, reload B to remove this temporary modulation, then run its fixed four
   HARMONICS parts for another 60 seconds. Repeat the comparison with the same
   core setting and diagnostics; do not save the temporary stress edits over B.

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
logs in the [device results record](macro-device-results.md), using its run template.
Stop playback, send note-offs and sustain-off, and wait for effect tails before
any save or restore. Restore the pre-test backup if these A–D/USER test contents
are no longer needed; verify the restored project names before overwriting the
saved backup. Restore RESTORE LAST, USB SERIAL, 2ND CORE and host/MIDI settings to
their recorded original values. Returning to older firmware requires its matching
backup as described above. Mark every unrun scenario pending; a successful
installation is not completion of this checklist.
