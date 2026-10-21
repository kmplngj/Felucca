<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Display and LED idle controls

## Controls and behavior

Hold **HOME** for more than 0.7 seconds until MENU appears, then release it.
Turn **ALGORITHM** to DISPLAY and **PRESETS** to the desired row. Any of
**KNOB 1–4**, or **OCT− / OCT+**, changes its value; **HOME** closes MENU.

**LEDS** keeps its existing six choices, in this order:
`OFF`, `DIM LO`, `DIM HI`, `INV`, `INV LO`, `INV HI`. DIM HI is the default.
OFF removes the idle glow while active indicators remain available. INV lights
inactive LEDs and darkens active ones; INV LO and INV HI lower the inactive
level. Their menu values now redraw immediately, including when only the inverse
brightness changes. This is distinct from timed LED blanking below.

**AUTO OFF** replaces the SCREEN OFF label and combines target and delay in one
row. The `m` suffix means minutes. Values stop at the ends rather than wrapping:

| Values | After the selected time without qualifying input |
| --- | --- |
| `NEVER` (default) | No timed blanking |
| `SCREEN 5m`, `SCREEN 15m`, `SCREEN 30m`, `SCREEN 60m` | Screen dark; normal LED behavior continues |
| `LEDS 5m`, `LEDS 15m`, `LEDS 30m`, `LEDS 60m` | LEDs dark except the alive signal; screen remains visible |
| `BOTH 5m`, `BOTH 15m`, `BOTH 30m`, `BOTH 60m` | Screen and LEDs dark except the alive signal |

Changing AUTO OFF restarts its timer. Panel buttons/keys pressed or held and
encoder turns restart it; the analogue MASTER pot and ordinary editor messages
do not. Playback continues and does not by itself prevent the timeout. Sound,
sequencer, MIDI, USB and input scanning continue. Dialogs, count-in and the UPDATE
MODE countdown prevent blanking. Crash/update/recovery screens retain their
immediate wake paths. The LCD backlight stays on: this is a visibility control,
with no measured power-saving claim.

When timed LED blanking applies, a single piano-key LED briefly lights every
30 seconds, starting 30 seconds after blanking. Each nominal 120 ms pulse uses
the low mid-level (about 8.3% scan duty); successive pulses rotate through the
27 keys. PLAY and REC are never used. It is an alive signal, not a note or beat.
It is always enabled for LEDS/BOTH; there is no additional preference.

**ANIM IDLE** retains its existing one-minute, stopped/idle animation. Timed LED
blanking takes priority and stops it; SCREEN-only timeout leaves LED behavior
unchanged. Existing ANIM OFF/ON/IDLE meanings remain unchanged.

## Waking the controls

For **LEDS**, the screen was never asleep: the first panel action restores LEDs
and acts normally. A played key sounds, a PLAY tap changes transport, and a knob
turn edits its value. For **SCREEN/BOTH**, the panel action that wakes the screen
is consumed: it must not play a key, start transport or edit a value. Release all
controls and let the knobs rest for 0.3 seconds before trying the action again.

The existing **MENU > MIDI > SCREEN WAKE** preference applies to all targets.
Reach it by holding HOME, turning ALGORITHM to MIDI and PRESETS to SCREEN WAKE.
With **+MIDI** (default), an incoming USB/TRS note-on routed to a track resets the
timer and wakes the selected outputs; the note still plays. **PANEL** leaves the
outputs asleep during MIDI input. MIDI clock, CC and SysEx do not wake them.

## Storage and editor compatibility

MENU setting ID **17** remains the same setting. Descriptor values 0–4 retain
NEVER and screen-only delays; 5–8 add LED-only delays and 9–12 add both-output
delays. Compact names fit the existing descriptor string limit. Firmware produces
these descriptors; live editor compatibility is a separate client check.

Settings still use `settings_dev[27]`, with no new record bytes or setting IDs.
Bits 0–2 retain the historical delay codes `0, 2, 1, 4, 7` for NEVER/5/15/30/60;
bits 3–4 select SCREEN=0, LEDS=1 or BOTH=2. Old screen settings keep their meaning.
Older firmware rejects LEDS/BOTH bytes above 7 and resets this preference to
NEVER. Downgrading therefore loses those timeout selections; it does not resize
the settings record or change project data.

## Design and validation status

The implementation keeps DISPLAY's existing eight rows on the 240 × 240 screen.
One AUTO OFF value carries target and duration instead of adding rows, a tab or
a submenu. Existing colors, selected-row styling, encoders and key hints remain.
The inverse-brightness fix adds its saved level to menu redraw detection.
LED blanking is applied in the main loop across the normal, dim, mid and breathing
maps, ahead of the idle animation; the scanner continues running.

The PR's **Validation performed** section is the evidence record for its exact
revision, build flags, host checks, target budgets and browser captures. This
guide describes the intended controls and the acceptance procedure; it does not
claim that a test has passed. Physical LCD/LED visibility, pulse timing, input
wake behavior and MIDI/audio operation remain **Pending hardware validation**.
Separate heartbeat controls, extra timeout durations and new menu pages are
outside this implementation.

## User test instructions — pending FM-1 validation

Use one combined candidate for all checks. Use the PR number,
40-character head commit and exact standard-profile `.fwsc` artifact/run link
recorded in the PR handoff.
Retain its provenance, package checksum and flags. Do not use a raw `.bin` or
assume the hosted demo contains this revision.

1. Back up the device with a compatible editor's Backup export and keep the
   previous firmware package. Connect one FM-1 with a USB data cable and headphones;
   close other MIDI applications and unplug TRS MIDI for the initial checks.
   From a trusted reviewed checkout with [uv and GitHub CLI set up](../BUILDING.md#test-a-pull-request-on-hardware),
   install once with `uv run --locked --group midi tools/fm1_pr.py NUMBER --profile standard`,
   substituting the PR number from that handoff. The helper records the selected head.
   Alternatively install the verified package linked in the PR handoff using the
   [documented installer](../BUILDING.md#install).
2. Tap HOME to reach HOME; stop transport with PLAY if running. Set MASTER low,
   release all keys and controls, and record the current project, track, engine
   and preset. Hold HOME, select SYSTEM with ALGORITHM, select INFO with PRESETS,
   and tap OCT+. Record the commit/PR identity; OCT− returns. Select RESTORE LAST
   with PRESETS, record its original value and set OFF to avoid autosaving test
   project changes. Record the original
   DISPLAY LEDS/ANIM/AUTO OFF and MIDI SCREEN WAKE values before changing them.
3. In DISPLAY, select LEDS. Step through all six choices with OCT−/OCT+ or KNOB 1.
   Every label must update immediately; INV LO and INV HI must produce different
   steady inactive brightness from INV. OFF must still show active indicators.
   Select AUTO OFF and step from NEVER through all 13 choices and back: no
   clipping, missing labels or wrap at either end. Repeat with LARGE enabled.
4. Select ANIM IDLE, LEDS DIM HI, MIDI SCREEN WAKE PANEL and AUTO OFF LEDS 5m;
   close MENU with HOME and start a stopwatch after releasing it. Leave controls
   alone. Idle animation may start after one minute; at five minutes it must stop
   and LEDs go dark while HOME remains visible. At 5:30 and 6:00, expect a brief
   dim pulse on different piano keys. Press/release one piano key: LEDs return
   and this first key sounds. Release it and confirm its sound ends.
5. Select AUTO OFF SCREEN 5m and close MENU. After five untouched minutes the
   screen must darken while LEDs retain their normal behavior. Tap PLAY once:
   the screen wakes and transport stays stopped. Release it, wait 0.3 seconds,
   then tap PLAY again: transport starts. Stop it with another PLAY tap.
6. For a shared playback check, load a known saved looping project: from HOME
   tap SAVE four times (USER → PRESETS → PHRASES → PROJECT), select its slot with
   KNOB 1, select LOAD with KNOB 3 and tap OCT+. Record slot, project name,
   track engines/presets and FX sends. Set AUTO OFF BOTH 5m, close MENU and tap
   PLAY. Listen without touching controls for six minutes. Screen/LEDs must
   blank at five minutes; the two subsequent alive pulses must not sound notes
   or interrupt playback. The first PLAY tap wakes only; the second, after release
   and 0.3 seconds, stops transport. If no suitable project exists, leave this
   playback scenario pending and report the missing setup.
7. Before the MIDI check, select MIDI IN CH1-4 in MENU's MIDI tab; record its old
   value. With PANEL and BOTH 5m selected, close MENU and wait five minutes.
   Open a USB MIDI sender on the connected host; send note 60 on channel 1 at
   velocity 64, followed by note-off after one second. With PANEL, T1 must play
   while outputs stay asleep. Wake by tapping HOME, then select SCREEN WAKE
   +MIDI; after a fresh five-minute timeout send the same note: outputs wake and
   T1 sounds. Repeat through TRS MIDI if available; record untested
   paths as pending. Do not leave MIDI notes held.
8. Restore MIDI IN and RESTORE LAST as well as the original menu values, stop
   transport and release all notes. For
   a persistence check first select BOTH 5m while stopped, close MENU and allow
   two seconds for the stopped settings save before a normal restart; verify BOTH 5m
   was retained, then restore the original setting. Report artifact/commit,
   device version, host/MIDI setup, timed observations and expected versus actual
   results. Retain pre-update backup for a downgrade; note the NEVER fallback.
