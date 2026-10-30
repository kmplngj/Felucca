<!-- SPDX-License-Identifier: GPL-3.0-only -->
# External MIDI key ranges (#796)

Each part has inclusive LOW and HIGH source-note bounds. The boot default is
0..127, preserving the existing MIDI layers and separate-channel behavior.
Example: assign T1 and T2 to channel 1 in MIDI IN TRACK, set T1 to 0..59 and
T2 to 60..127 for a split. T1 0..64 and T2 55..127 layer the sounds on 55..64.
Note 0 is valid. Note On with velocity 0 always releases.

Ranges are **session-only controller setup**, not project, preset, backup,
retained-cache or flash data. There is no new parameter ID or saved byte;
P_COUNT stays 111. Reapply setup after reboot/project load. The batch integration
owns project-load reset and the NRPN configuration bridge; this issue's focused
commit provides the runtime helpers and filtering. Old saved formats are unchanged;
older firmware has no range filtering and plays the complete existing channel layer.

The incoming raw note selects destinations after channel/OMNI/OFF routing and
before CHRD or ARP expansion. Every admitted source note plays its complete
per-part chord, including tones outside the range. Generated notes never route
themselves into another part's range. Existing transpose behavior is preserved:
external source pitch is not remapped by the local keyboard's TRN setting.
Built-in keys and sequencer playback bypass these ranges. Filtering does not
change controller, Program Change, channel-priority or first-OMNI fallback rules;
an exact-channel match rejected by its range does not trigger an OMNI fallback.
USB and TRS continue sharing channel/note ownership and part configuration.

Range edits affect future attacks. Held and pedal-held notes retain the destinations
captured at their attacks; releases, sustain-up and panic follow those owners.
A repeated note replaces previous owners before applying current bounds, even
when the new attack has no admitted destination. Sound loads retain the zone
setup while their existing panic discards that part's old owners. Routing changes
retain the existing cleanup rules for destinations removed by channel edits.
CC120/121/123 and input-overflow recovery preserve zone setup.

## Configuration contract

Internal helpers use zero-based part indexes 0..3:

- `midi_key_range_set(track, high, value)`: `high=0` selects LOW, `high=1`
  selects HIGH; value is 0..127. Returns 1 on success, 0 on invalid part,
  selector, value, or LOW>HIGH. Rejection preserves the previous bounds.
- `midi_key_range_get(track, high)`: bound, or -1 for invalid part/selector.
- `midi_key_mask(mask, note)`: removes destinations outside their inclusive
  range; invalid note >127 returns 0. Input masks come from `midi_route_mask`.
- `midi_key_reset()`: restores full ranges without discarding note ownership.
  The project-load caller also performs the normal project panic.

To move a narrow range past its current bounds, widen it first. For example,
60..60 → 72..72 requires HIGH=72 before LOW=72. Setting LOW=72 first rejects.

The batch NRPN bridge uses manufacturer-specific absolute track addresses
`0x3000 + track*0x10 + field`, field 0 LOW / 1 HIGH. It accepts seven-bit CC6
Data Entry MSB. Send CC99 address MSB, CC98 address LSB, then CC6 bound.
Configuration is independent of the sounding parts selected by channel routing.
The bridge and its actual wire tests are integrated separately; this commit's
host tests call the real setters and send notes through production input queues.
There is no new SysEx command, native menu row, editor descriptor or persistence.

## Exact MIDI and audio checks (pending batch/browser/FM-1 validation)

Use the exact integrated candidate's emulator or `.fwsc`, never a hosted default
build. The coordinator supplies the commit, package provenance and installation
procedure from [BUILDING](../BUILDING.md#install). Physical USB/TRS and audio
deadline behavior remain pending. No device was flashed for this change.

1. Stop transport and use CPU2 OFF. Choose contrasting sustained sounds on T1/T2
   with ALGORITHM and PRESETS. Tap HOME to MIXER, select each part with ALGORITHM,
   start LEVEL quietly with KNOB 1. Hold HOME for MENU, choose MIDI with ALGORITHM
   and MIDI IN with PRESETS, set TRACK with KNOB 1. Select T1 CHANNEL then T2
   CHANNEL with PRESETS and set each to 1 with KNOB 1. Leave T3/T4 on channels 3/4.
   Tap HOME to close MENU. No panel gesture configures LOW/HIGH; use MIDI below.
2. Send the following hex bytes as separate channel-1 messages to configure the
   split (shown one NRPN write per line):

   ```text
   B0 63 60  B0 62 01  B0 06 3B   # T1 HIGH = 59
   B0 63 60  B0 62 10  B0 06 3C   # T2 LOW = 60
   ```

   Send `90 3B 64`, then `80 3B 00`: only T1 attacks/releases. Send `90 3C 64`,
   then `90 3C 00`: only T2 attacks/releases. Repeat at notes 0 and 127. Isolate
   the parts using their MIXER LEVEL or capture each stereo part separately.
3. For overlap send `B0 63 60 B0 62 01 B0 06 40` (T1 HIGH=64), then
   `B0 63 60 B0 62 10 B0 06 37` (T2 LOW=55). Notes 54 and 65 sound only T1 and
   T2 respectively; notes 55 and 64 sound both. Capture actual stereo PCM for
   each isolated part and the overlap in browser tests.
4. Send `90 3C 64 B0 40 7F 80 3C 00` (hold note 60 with sustain).
   Send `B0 63 60 B0 62 01 B0 06 3B` (T1 HIGH=59), then
   `B0 63 60 B0 62 10 B0 06 3D` (T2 LOW=61). Both sounds remain held.
   Send `B0 40 00`: both release. Repeating note 60 now attacks neither part.
   Repeat without sustain, changing the ranges between attack and note-off.
5. Attempt `B0 63 60 B0 62 00 B0 06 7F` (T1 LOW=127 while HIGH=59): reject.
   Note 59 still sounds T1. Restore all bounds with T1 LOW=0, HIGH=127 and T2
   LOW=0, HIGH=127: NRPN LSBs 00/01/10/11, CC6 values 00/7F/00/7F.
   Both sounds now attack every note. Load a disposable project or reboot and
   confirm full ranges again; ranges are not saved. Restore separate channels
   1/2 to disable layering. Repeat on USB and TRS and report package, device/host,
   transport, scenario and observed versus expected result.

## Validation and resource limits

`tests/midi_key_range_test.c` compiles the production routing, queues, UART parser,
voice gates, chord/ARP, sound installation, panic and overflow paths. It checks all
128 notes in default, split and overlap configurations on both queue sources;
both exact bounds, invalid/reversed updates, independent channel owners, sustain,
repeat, velocity-zero, sound panic, route edits, OMNI/OFF, local/sequence bypass,
UART running status and reset ownership. The existing MIDI control harness is a
separate compatibility check. These tests establish control behavior and voice
gates, not audible PCM, device transport/timing or complete CI acceptance.

Runtime zone state is eight BSS bytes (LOW and 127-HIGH per part); no allocation,
DSP stage or voice reservation is added. A positive external note attack checks
four destination bounds. Overlap admits the same extra voices as the existing
layer mask; split filtering can reduce that load. Target app/RAM/POOL/RAMTEXT/
NOINIT/stack and active/inactive timing deltas require the coordinator's integrated
build/measurements; none are claimed here.

README assessment: the existing native-MIDI-layer overview remains accurate; the
batch can link this focused setup guide from that overview. Changelog assessment:
the integrated PR should add one grouped MIDI key/velocity-zone capability entry,
with session-only and pending-hardware limits. Diagnostic assessment: no command,
field, build flag or diagnostic capability changes; existing guides still apply.
