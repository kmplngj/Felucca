<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Display and LED idle controls

This candidate retains the accepted two-stage menu under
[#555](https://github.com/kmplngj/Felucca/issues/555) with the pre-probe LCD driver.
The owner reports correct colours and readable text immediately after rebooting
the rollback A/B `cfbcb596`; see [the A/B evidence](lcd-colour-ab-2026-10-22.md).

**ALL DARK blanks the LCD image and every LED; it does not turn off the physical
backlight.** The backlight rail remains powered with PA2 and input scanning
enabled. Independent backlight-off under [#546](https://github.com/kmplngj/Felucca/issues/546)
remains unresolved. The current driver sends no controller `0x51`/`0x53` commands;
there is no CPU sleep or power-saving claim. The withdrawn experiment is recorded
in the [historical probe guide](lcd-backlight-probe.md).

## Panel controls

Hold **HOME** for more than 0.7 seconds until MENU appears, then release it.
Turn **ALGORITHM** to DISPLAY, **PRESETS** to AUTO OFF and tap **OCT+** to open
its detail page. PRESETS selects a row; any **KNOB 1–4** or **OCT− / OCT+**
changes a value. Select BACK and tap OCT+ to return to DISPLAY. HOME closes MENU
from either page. Returning keeps AUTO OFF selected.

| Detail row | Values | Behavior |
| --- | --- | --- |
| IDLE AFTER | NEVER, 5 MIN, 15 MIN, 30 MIN, 60 MIN | First-stage delay; default NEVER |
| IDLE MODE | SCREEN, LEDS, BOTH | Outputs affected by the first stage; remembered while IDLE AFTER is NEVER |
| ALL DARK | NEVER, 5 MIN, 15 MIN, 30 MIN, 60 MIN | Independent image/all-LED blanking threshold; default NEVER; backlight stays powered |
| WAKE | +MIDI, PANEL | Existing wake preference, moved here from MIDI / SCREEN WAKE |
| BACK | Open action | Return to DISPLAY |

Both times count **total time since the same last qualifying interaction**.
For IDLE AFTER 5 MIN, IDLE MODE LEDS, ALL DARK 30 MIN, first-stage LED blanking
starts at minute 5 and LCD image/all-LED blanking at minute 30, not 35.
If both stages are enabled, ALL DARK must be later than IDLE AFTER. Panel value
steps skip conflicting choices without moving the other timer: with IDLE AFTER
5 MIN, ALL DARK steps directly from NEVER to 15 MIN. Direct conflicting editor
writes are rejected. Either stage may independently be NEVER. Changing a timer/mode restarts inactivity and restores visibility.

SCREEN sleeps the LCD image while the backlight remains powered; ordinary LEDs keep
working. LEDS blanks the normal/dim/mid/breath maps while leaving the LCD awake.
BOTH combines these first-stage effects. Timed LED blanking stops ANIM IDLE and
leaves one low-level piano-key pulse every 30 seconds, starting 30 seconds after
blanking. Each nominal 120 ms pulse rotates among the 27 keys; PLAY/REC are never
used. ALL DARK takes precedence over either target, sleeps the LCD image and
blanks **every LED with no heartbeat or animation**. If SCREEN/BOTH already slept
the LCD in the first stage, ALL DARK adds complete LED suppression. Neither stage
disables PA2 or independently switches off the physical backlight, so the retained
ALL DARK label does not promise complete physical darkness.

The normal DISPLAY / LEDS setting remains separate: OFF, DIM LO, DIM HI, INV,
INV LO, INV HI. DIM HI is the default. OFF removes idle glow but keeps active
indicators. INV lights inactive LEDs; INV LO/HI reduce that level. All labels
redraw immediately when changed. These normal levels return after timed wake.

## Activity and wake

Panel buttons/keys pressed or held and encoder turns reset both timers. The
analogue MASTER pot, ordinary editor traffic and internal playback do not. With
WAKE +MIDI (default), accepted USB/TRS note-ons routed to a track also reset the
timers and wake outputs; the note plays normally. PANEL ignores MIDI for wake.
Clock, CC, note-offs and SysEx do not count as wake activity.

A first-stage LEDS-only wake acts normally on its first gesture. When the LCD is
asleep, including ALL DARK, panel wake is consumed: release every control and let
encoders rest for 0.3 seconds before playing or editing again. The first PLAY tap
must wake without starting/stopping transport; the following tap acts normally.
Sound, sequencing, MIDI, USB and input scanning continue. Dialogs, count-in and the
UPDATE MODE countdown prevent blanking; crash/update/recovery restore visibility.

## MIDI, editor and stored-data compatibility

Firmware-produced MENU_DESC/MENU_SET descriptors expose every persistent setting:

- **ID 17 AUTO OFF:** unchanged values 0 NEVER; 1–4 SCREEN 5/15/30/60m;
  5–8 LEDS 5/15/30/60m; 9–12 BOTH 5/15/30/60m. The native detail page splits its
  time and mode for easier editing; existing clients can retain the combined row.
- **ID 31 WAKE:** unchanged values 0 +MIDI, 1 PANEL, now grouped under DISPLAY.
- **ID 33 ALL DARK:** 0 NEVER; 1–4 5/15/30/60 MIN. ID 32 stays reserved for
  2ND CORE even in builds that omit it. Discover items by descriptor index and
  use their returned IDs; do not assume index equals ID in CPU2-off builds.

MENU_SET returns actual values. An inconsistent timer order returns rc 2 and
changes nothing; applied settings retain the existing durability results:
0 saved, 3 in RAM only, 4 pending STOP. See the [wire reference](../web/EDITOR_PROTOCOL.md#menu-settings-72-73-104).
The generic WebApp can discover the additional row; its companion reply-handling
fix [#556](https://github.com/kmplngj/Felucca/issues/556), delivered for review in
[WebApp PR #7](https://github.com/kmplngj/Felucca-WebApp/pull/7), keeps deferred/rejected
changes visible accurately. Use that PR's current reviewed checkout for browser
testing. The hosted site still uses its existing client pin; updating and
deploying that pin is separate from this firmware candidate. Direct MIDI settings
are available independently of the hosted client. PR builds do not publish the site.

No setting-record or backup-size growth: settings_dev[27] retains bits 0–2 for
historic timer codes 0,2,1,4,7 and bits 3–4 for SCREEN/LEDS/BOTH. Bits 5–7 hold the
new ALL DARK index 0–4. settings_dev[13] remains reserved for #204. Invalid stored
targets/timers normalize safely; an invalid or conflicting ALL DARK is disabled.
Historical bytes 0–7 retain their interpretation. Older firmware without ALL DARK
rejects bytes containing its high bits and falls back to NEVER; older firmware
also rejects LEDS/BOTH selections. Keep a backup before downgrade.

## Combined user test procedure — remaining FM-1 checks

The rollback A/B is already installed with the owner's authorization. Immediate
colour/text recovery and unchanged settings readbacks are recorded in the
[A/B evidence](lcd-colour-ab-2026-10-22.md). The timed LED transitions, repeated
wake and audio/MIDI scenarios below remain **pending** unless separately reported.

1. Keep the installed candidate's exact revision, standard-profile `.fwsc`,
   checksum, flags, preflash backup and previous package with the test report.
   Continue remaining checks on that installed candidate; a new flash is not
   needed for each scenario. For a subsequent artifact within the owner's test
   scope, use the PR handoff's exact `FULL_SHA` and verified package with the
   [documented installer](../BUILDING.md#test-a-pull-request-on-hardware).
2. Tap HOME to reach HOME; stop transport if running and release all controls.
   Record the current project, track, engine/preset, LEDS, ANIM, AUTO OFF, WAKE,
   MIDI IN and RESTORE LAST settings. Hold HOME, select SYSTEM with ALGORITHM,
   INFO with PRESETS and tap OCT+. Record the compiled revision; OCT− returns.
3. Follow the panel route above. Check all rows, both value directions and BACK;
   reopen AUTO OFF and close with HOME. Set IDLE AFTER 5 MIN, IDLE MODE LEDS,
   ALL DARK 15 MIN and WAKE PANEL. From NEVER, ALL DARK must step directly to
   15 MIN; one downward step must return to NEVER, skipping the conflicting
   5 MIN. IDLE MODE and IDLE AFTER must not change. Restore 15 MIN. Repeat with
   LARGE enabled. Verify every INV brightness label separately in DISPLAY / LEDS.
4. Set ANIM IDLE and LEDS DIM HI, close MENU and leave untouched. At five minutes,
   animation stops and ordinary LEDs blank while LCD stays awake. At 5:30 expect
   one dim piano-key pulse; later pulses rotate. At minute 15, the LCD image
   blanks and all LEDs stay dark, including at later 30-second pulse boundaries.
   The physical backlight remains powered; do not count image blanking as a
   successful independent backlight-off test.
5. Tap PLAY once: the image and normal LED mode return, transport remains
   stopped. Release and wait 0.3 seconds, then PLAY acts. Repeat a fresh timeout
   and wake with a key/encoder: first gesture must be consumed, subsequent
   gestures work without stuck notes or parameter jumps. Repeat at least three
   sleep/wake cycles; stop and restore the verified package on input/colour
   failure. Do not try a PA2-off workaround.
6. Test SCREEN 5 MIN with ALL DARK NEVER: the image blanks, the backlight stays
   powered and normal LEDs stay available. Test LEDS 5 MIN / ALL DARK NEVER to retain the
   heartbeat indefinitely. Test IDLE AFTER NEVER / ALL DARK 5 MIN for the
   independent second stage. Changing settings must safely restart inactivity.
7. Load one known looping project: from HOME tap SAVE four times to PROJECT,
   KNOB 1 selects slot, KNOB 3 LOAD, OCT+ loads. Record slot/name/engines/FX.
   Set the two thresholds as in step 3 and start PLAY. Audio must continue through
   both transitions. If no known project exists, mark this scenario pending.
8. Select MIDI / MIDI IN CH1-4, then DISPLAY / AUTO OFF / WAKE +MIDI. After a
   fresh dark timeout, send USB note 60, channel 1, velocity 64, with note-off one
   second later. T1 plays and lights wake. With PANEL, the same note plays while
   outputs remain dark; panel wake still works. Repeat via TRS if available.
   MIDI clock, CC and SysEx must not reset the interval. Mark untested paths pending.
9. With transport stopped and notes released, read back IDs 17/31/33 from MIDI,
   set valid values and reject an invalid order; confirm actual returned values
   and durability status. Close MENU and allow the stopped save to finish, restart
   normally and verify retention and readable boot. Restore the original settings.
   Report exact artifact/revision, unit/host/MIDI setup, brightness comparison,
   timing and wake results; keep software, transfer and physical observations separate.
