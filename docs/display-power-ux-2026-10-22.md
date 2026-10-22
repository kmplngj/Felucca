<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Display and LED idle settings — proposed UX, 2026-10-22

Status: the owner accepted this design on 2026-10-22; implementation is in draft
PR #549. Physical backlight-off and full-dark wake remain unqualified. The current
[control guide](display-idle.md) describes the candidate. Companion evidence:
[FM-1 display-power research](display-power-research-2026-10-22.md).
Source baseline: `d9c307265f6012d4df4b74128bb038580956f595`, verified against
remote `main` on 2026-10-22. Existing implementation: [#547](https://github.com/kmplngj/Felucca/pull/547).
The independent-controller probe [#549](https://github.com/kmplngj/Felucca/pull/549)
remains a separate draft; this proposal does not qualify it.

## Job and agreed behavior

The player should be able to reduce panel lighting after a short idle period,
then make the FM-1 completely dark after a separately chosen period. The user
specified that the second stage means **LCD image, physical backlight and all
LEDs off**, and that both thresholds count the **total time since the last
qualifying interaction**. No CPU standby, audio stop or USB disconnection is
requested. Audio, sequencer and MIDI continue.

The 30-second rotating LED heartbeat belongs only to the first LED-off stage.
Completely dark means no heartbeat, including PLAY/REC indicators and animations.

## Recommended direction

Keep the current eight-row DISPLAY tab and its existing visual language. Turn
its `AUTO OFF` row into an action opening a small detail page. Keep `LEDS` in
DISPLAY for the normal illumination mode and INV brightness. Do not add a ninth
row, introduce scrolling, or multiply the current 13 combined values by another
timer.

Proposed detail-page content, using illustrative values:

| Row | Example | Meaning |
| --- | --- | --- |
| IDLE AFTER | 5 MIN | First-stage threshold; NEVER disables this stage. |
| IDLE MODE | LEDS | SCREEN, LEDS or BOTH; preserves the existing first-stage targets. |
| ALL DARK | 30 MIN | Independent threshold for backlight and every LED off; default NEVER. |
| WAKE | +MIDI | Existing PANEL / +MIDI preference, grouped with the timers. |
| BACK | OPEN | Return to DISPLAY with AUTO OFF selected. |

Show a persistent short caption, `TIMES SINCE INPUT`. In documentation and the
WebApp use the fuller wording “Both times are measured from the last interaction.”
For the example, the first transition occurs at minute 5 and complete darkness at
minute 30, not minute 35. These are example settings, not new defaults.

Use `ALL DARK`, rather than `DEEP SLEEP`, because only the lighting changes.
The current SCREEN target blanks the LCD image while its backlight remains on;
describe that limitation explicitly until independent backlight control is
verified. Never present the desired behavior as already available.

Move the existing MIDI-tab SCREEN WAKE presentation into this page as WAKE,
preserving its stored preference and wire ID; do not create a duplicate setting.
Its full-dark behavior remains conditional on the verified wake path. The detail
page has room for these five rows. Client descriptor grouping and old-client
compatibility need review alongside that relocation.

## Interaction and alternatives

Recommended navigation preserves PRESETS for row selection, KNOB 1–4 and OCT−/OCT+
for decreasing/increasing values, and HOME for closing the menu. Open AUTO OFF
with OCT+, following the existing menu action convention. On the detail page,
an explicit BACK action avoids making OCT− mean both “decrease” and “back”. BACK
uses OCT+; its action affordance follows the existing INFO/ABOUT entries. These
are proposed routes requiring implementation and panel verification, not current
instructions for the device.

Alternatives considered:

- **Two extra rows in DISPLAY:** exceeds its fixed eight-row layout or displaces
  unrelated controls. Rejected for this bounded change.
- **One longer combined value:** hides the independent thresholds and increases
  the number of knob detents. Rejected.
- **OCT− always goes back in the detail page:** saves the BACK row but changes
  the familiar value-decrement gesture. Prefer the explicit row while space is
  available.

The main AUTO OFF row should clearly signal that it opens a page. Prefer a short
summary such as `5m / 30m >`, consistently ordered first-stage / ALL DARK. Use
`5m / - >` or `- / 30m >` when one stage is disabled, and `NEVER >` when both are
disabled; the detail page spells out NEVER. Assess the summary against all three
fonts rather than squeezing it into the existing value area. If it cannot fit,
use `OPEN` with the established action cue. This summary is a proposed layout,
not a verified native render.

## States, timing and wake contract

- Preserve existing saved first-stage settings and defaults. ALL DARK defaults
  to NEVER on upgrade, missing data, or unsupported hardware.
- Initially reuse NEVER / 5 / 15 / 30 / 60 MIN rather than introduce a minute
  editor. If both stages are enabled, allow only ALL DARK thresholds later than
  IDLE AFTER. A disabled first stage may have an independently enabled ALL DARK.
  Never silently adjust another timer while editing one field. Imports and
  protocol writes need the same deterministic validation policy; define their
  error response before implementation.
- Reuse the existing definition of activity: panel buttons/keys/encoders and,
  when enabled, accepted MIDI note-ons. Master-pot movement, editor traffic,
  MIDI clock/CC/SysEx and internal playback do not currently reset the timer.
  Preserve this policy; document the exclusions rather than promise “any input”.
- Keep dialogs, count-in, update/recovery and crash behavior explicit. Critical
  screens must restore visibility; lighting changes must not interrupt audio.
- An input that wakes a dark screen is consumed until release/rest, preserving
  the current protection against accidental notes and edits. MIDI notes keep
  sounding normally. Any extension to the LED-only wake policy needs explicit
  acceptance checks.
- On wake, restore the selected normal LED/INV mode and a fully redrawn screen,
  then restart both timers. Changing/importing timer settings resets inactivity
  and restores visibility. No timer transition performs an immediate flash erase.

**Hardware gate:** ALL DARK must not ship as a normal panel setting until a
reliable wake path is proven. Controller-only backlight-off with PA2 low is the
preferred experiment because it may retain scanning. PA2 high disables matrix
input in reported FM-1 measurements; ordinary panel wake must not be advertised
for that path. Periodically enabling PA2 to scan is unqualified and may visibly
flash the backlight or miss input. An external-MIDI-only wake would be a different
product contract, not a transparent fallback.

## Implementation boundaries and acceptance plan

This proposal changes no firmware, protocol, storage or client code. Firmware
owns the lighting state machine, HAL, saved settings and descriptors; any editor
presentation work belongs in Felucca-WebApp. Keep menu ID 17 and its existing
values compatible. A native split into time/target controls can map to that
existing value; it must not renumber protocol rows. Allocate any new persisted
timer under the capacity plan: byte `settings_dev[13]` is reserved for #204 and
must not be borrowed. Assess old-client behavior and downgrade semantics before
choosing storage or a new descriptor ID.

After the hardware result, implementation should cover:

1. Native detail navigation and correct values under all fonts, palettes,
   styles and large-type settings; exact menu return and HOME-close behavior.
2. Both absolute thresholds, NEVER combinations, rejected invalid ordering,
   timer edits/imports, wraparound, and complete-dark precedence over heartbeat.
3. Restore/wake gestures, held inputs, all LED maps/animations, emergencies,
   continued audio/MIDI/sequencer operation and deferred settings saves.
4. Old settings, backup round trips, malformed values and client descriptors;
   WebApp desktop/mobile controls and keyboard behavior if client changes follow.
5. A real FM-1 check of physical darkness and wake reliability with the exact
   candidate revision, followed by the normal integrated regression/build gates.

No emulator can establish electrical backlight darkness or wake while PA2 is
disabled. No firmware build, browser test or device test was run for this
documentation-only proposal. No measured resource or power-saving claim is made.

README assessment: no change to implemented capabilities, installation or fork
status, so no README update is warranted. Changelog assessment: this is an
unimplemented proposal; do not add it to the shipped-feature changelog.
