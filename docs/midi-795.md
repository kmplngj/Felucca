<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI pair mix (#795)

One assigned CC edits the LEVEL of two existing parts. It adds no voices or
render stage; configure a same-channel layer separately. The assignment is
inactive at boot and resets at project load. CC and target assignment are
**session-only**, absent from project/preset/backup formats. The resulting native
LEVEL edits follow existing project-save and motion rules.

## Assignment and curve

The session configuration uses these absolute NRPN addresses, independent of the
receiving channel's note destination. Use CC99/98 to select and seven-bit CC6 to
write. USB and TRS share the assignment. Only channels heard by MIDI IN routing
can operate the mix. There is one pair across all channels, with last edit winning.

| Address | Field | Values | Default |
| --- | --- | --- | --- |
| `0x3100` | Mix CC | 0 off, otherwise an available CC | 0 |
| `0x3101` | Part A | 0..3 (tracks 1..4) | 0 |
| `0x3102` | Part B | 0..3 (tracks 1..4) | 1 |

Identical or out-of-range target updates and reserved/fixed CC assignments are
rejected, leaving the previous configuration intact. Disable before changing the
pair; updates do not apply a remembered fader position. Reversing A/B is supported:
use a spare part for one intermediate assignment, because every update must leave
a valid pair. CC20 is an example chosen by the user, **not a MIDI standard mix CC**.

The reserved set is CC1, 6, 11, 32, 38, 64, 65, 67, 68, 96..101 and 120..127,
plus the fixed sound map CC5, 7, 10, 71..75, 91, 93, 94. CC0 disables rather than
assigning Bank Select. A learned assignment may use the same available CC and
takes precedence; clearing that learned entry exposes the mix assignment again.
MIDI Learn waiting for a controller consumes the CC before mix editing.

For position `x` in 0..127, the ideal amplitudes are `A=(127-x)/127`, `B=x/127`.
Each ideal is rounded to Q12, then mapped to the nearest existing `LEVEL_Q12`
entry, with ties toward the quieter level. Endpoints are exactly LEVEL112 (0 dB,
Q12 4096) and LEVEL0 (zero). Positions 63 and 64 both map to LEVEL100 on each part
(Q12 2053, -6 dB). Native half-decibel quantization means repeated fader positions
can produce the same levels; this is a stepped control, using the existing mixer.

This is a complementary linear-amplitude blend, with no boost above unity for an
individual part. It adds no equal-power compensation: uncorrelated parts lose
roughly 3 dB of summed power around the midpoint. Table quantization can make the
sum slightly above unity (midpoint 4106/4096, about 0.02 dB). Different patches,
panning, envelopes, effects and phase can change perceived loudness and headroom;
equal loudness is not promised. Turning a part to LEVEL0 silences its dry signal,
while previously excited global effect tails may continue.

## Edit and lifecycle precedence

Each received position changes the two native `P_LEVEL` values and calls the
existing `motion_capture` path when a value changes, just as CC7 edits do. Only
the selected part, armed and playing, records motion. Its captured edit is
transient and restores its native base on stop; the other part's edit becomes
its new base. Without recording, both edits become base values. Existing motion
events can subsequently overwrite either LEVEL. A manual LEVEL edit or CC7 wins
until the next mix event; the next event computes both levels afresh.

Disabling, reassigning, resetting controllers with CC121, changing sounds or
engines, changing routing, disconnecting, or input-overflow recovery never
restores an earlier mix snapshot. The assignment holds part indices, with no
cached sound/engine pointers. Sound loads preserve LEVEL by the existing rules;
the next mix event edits whichever sounds occupy those parts. An absent engine
still receives the common LEVEL edit safely and stays silent. Project load/boot
disables the assignment. Disconnect/input loss retains the last deliberate
levels and the session assignment; normal note-ownership recovery still applies.
No fader position is replayed after reconnect or reconfiguration.

## Exact MIDI example

All bytes below are hexadecimal, each line is one complete message. These
configuration NRPNs require the integrated configuration bridge; the focused
host test calls the same configuration helpers directly.

From a stopped project with no learned CC20, route tracks 1 and 2 to channel 1 using
the existing editor MENU_SET protocol (value encoding is value+8192, low byte
first). Tracks 3/4 keep their existing channels:

```text
F0 7D 46 4C 49 1A 00 40 F7  ; T1 CHANNEL = 1 (zero-based value 0)
F0 7D 46 4C 49 1B 00 40 F7  ; T2 CHANNEL = 1
F0 7D 46 4C 49 15 05 40 F7  ; MIDI IN = TRACK (value 5)
B0 63 62                    ; NRPN MSB = 0x62
B0 62 00                    ; address 0x3100, mix assignment
B0 06 00                    ; disabled while configuring
B0 62 01                    ; address 0x3101, A
B0 06 00                    ; A = track 1
B0 62 02                    ; address 0x3102, B
B0 06 01                    ; B = track 2
B0 62 00                    ; address 0x3100
B0 06 14                    ; assign CC20
B0 63 7F                    ; release NRPN selector
B0 62 7F
90 3C 64                    ; C4 velocity100, both parts
B0 14 00                    ; A unity, B zero
B0 14 3F                    ; midpoint: both LEVEL100
B0 14 40                    ; same quantized midpoint
B0 14 7F                    ; A zero, B unity
B0 07 50                    ; manual CC7 sets both routed LEVELs to80
B0 14 00                    ; mix wins: A112, B0
B0 40 7F                    ; sustain on
80 3C 00                    ; release key (both held by pedal)
B0 14 7F                    ; fast sweep endpoint
B0 40 00                    ; release both pedal-held notes
B0 63 62
B0 62 00
B0 06 00                    ; disable, retaining last levels
```

To reverse the original pair while disabled, select/write B=2, A=1, B=0
(`B0 62 02`, `B0 06 02`, `B0 62 01`, `B0 06 01`, `B0 62 02`, `B0 06 00`,
with NRPN MSB still 0x62). Reenable by selecting low byte0 and writing 20.
Changing A directly to 1 while B remains 1 is rejected.

## Validation and FM-1 handoff

Focused production-source host checks:

```sh
mkdir -p build/midi-795
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi-795/midi_mix_test tests/midi_mix_test.c -lm
build/midi-795/midi_mix_test
```

This fixture exercises all 128 positions through the real queue, monotonic nearest
gains, invalid/reversed pairs, reserved/fixed/learned priorities, TRS running
status, motion recording/restoration, engine changes/absence, sustain, CC121 and
input overflow. The real voice/mixer fixture renders both same-channel parts
independently at every position and requires bounded PCM, nonzero contributions
and exactly zero dry PCM at muted endpoints. These checks do not measure audible
clicks, browser transport, physical transport, interrupt deadlines or target size.
The coordinator owns runner registration and integrated NRPN/project-reset tests.

**Pending hardware validation:** use the coordinator's final PR `.fwsc` artifact
and recorded commit, built with the standard profile; follow the trusted installer
in [BUILDING](../BUILDING.md#install). No firmware was flashed for this issue.
Connect headphones/line output and a channel 1 controller over USB, then repeat
over TRS MIDI IN. Use a stopped disposable project. Load two contrasting patches
through the editor (for example ANALOG lead on track 1, FM6 PAD on track 2), leave
both unmuted, and send the exact setup above. Listen at each endpoint to establish
each contribution independently; with effects disabled the muted contribution
must be silent. Hold C4 while sweeping 0..127 at one position/50 ms, then alternate
0/127 ten times at 20 ms intervals. Check stepping/clicks, useful blend and pedal
release. Repeat while recording automation on the selected track and observe the
native restore on stop; repeat CC7 and MIDI Learn precedence checks. Disable and
reconnect: levels must stay put until a new edit. Load a project: assignment must
be off. Finish with pedal-up, CC123 and CC120 on the active channel. Report the
artifact/commit, patches, transport, observed behavior and any clicks or stuck notes.

Target app/RAM/POOL/RAMTEXT/NOINIT/stack deltas, inactive and dense CC+clock+notes
cost, full CI, browser MIDI/audio and hardware listening/deadline checks remain
coordinator/integration gates. Implementation adds three session-state bytes and
bounded event-driven lookup; no measured resource or timing claim is made here.

README and changelog need a batch capability entry/link, owned by the coordinator.
No diagnostic commands or output fields change; diagnostics documentation needs
no new command description. Existing diagnostics can support later deadline tests.
