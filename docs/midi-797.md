<!-- SPDX-License-Identifier: GPL-3.0-only -->
# External MIDI velocity zones (#797)

Each part has inclusive velocity LOW/HIGH bounds, default 1..127. For example,
T1 1..79 and T2 80..127 select soft and hard articulations using the parts'
existing sounds. T1 1..95 and T2 64..127 deliberately layer both on 64..95.
Bounds are hard boundaries; there is no automatic crossfade or new sound bank.
Velocity-zero Note On always releases, including when LOW is 1.

This is **session-only controller setup**: no parameter IDs, project/preset/backup
bytes, retained records or flash writes change. P_COUNT stays 111. Reapply setup
after boot/project load. The batch integration owns project-load reset and the
NRPN bridge; this focused change supplies runtime helpers and filtering. Older
firmware plays the existing complete layer without velocity filtering.

Destination selection runs in this order: channel routing, raw source-key range,
raw positive velocity range, then destination response scaling and CHRD/ARP input.
A Soft Pedal or future #123 response curve must not change articulation selection.
The same raw incoming velocity selects every destination, independent of patch
velocity sensitivity. Built-in keys and sequencer steps bypass these external
zones. USB/TRS keep their existing shared channel/note ownership semantics.

Held and pedal-held notes retain captured owners through bound/response edits.
A repeated source note first releases its previous owners, then selects from the
new velocity and current bounds; an attack rejected by every zone still clears
old owners. CHRD/ARP expand only admitted parts and release captured tones.
Sound-install panic, route edits and input-overflow cleanup retain their existing
ownership behavior. CC120/121/123 and sound loads preserve velocity configuration;
explicit zone reset restores bounds without discarding captured owners.

## Configuration contract

- `midi_velocity_range_set(track, high, value)`: zero-based part 0..3,
  `high=0` LOW or `high=1` HIGH, inclusive value 1..127. Returns 1 on success;
  invalid part/selector/value or reversed bounds return 0 without mutation.
- `midi_velocity_range_get(track, high)`: bound, or -1 for invalid part/selector.
- `midi_velocity_mask(mask, raw_velocity)`: removes excluded part bits; zero
  and values above 127 return 0. Call after the source-key mask.
- `midi_velocity_reset()`: restores all parts to 1..127. Project load also
  performs the normal project panic through the batch integration.

Widen a range before moving it past its current bounds: 64..64 to 100..100
requires HIGH=100 before LOW=100. LOW=100 first rejects.

The batch's absolute NRPN configuration address is
`0x3000 + track*0x10 + field`, field 2 velocity LOW / 3 velocity HIGH. Send CC99
address MSB, CC98 address LSB, CC6 bound, with seven-bit Data Entry values.
Configuration selects an absolute part regardless of the channel's note routing.
This focused commit does not implement that bridge or a native menu/editor UI.
No SysEx or persistent format is added.

## Exact MIDI/audio procedure (pending integrated/browser/FM-1 validation)

Use the coordinator's exact integrated emulator or `.fwsc` candidate and recorded
commit/build flags. Obtain/install it using [BUILDING](../BUILDING.md#install);
the hosted default emulator is not evidence for this change. No device was flashed.
Physical USB/TRS, audible behavior and device deadlines remain pending.

1. Stop transport, CPU2 OFF. Use contrasting sustained T1/T2 sounds; follow the
   verified panel setup in [key-range checks](midi-796.md#exact-midi-and-audio-checks-pending-batchbrowserfm-1-validation)
   step 1 to put both parts on channel 1 in MIDI IN TRACK. Start at quiet MIXER
   levels. Leave T3/T4 on channels 3/4. Default key ranges must cover note 60.
2. Configure split velocities (hexadecimal MIDI bytes):

   ```text
   B0 63 60 B0 62 03 B0 06 4F   # T1 HIGH = 79
   B0 63 60 B0 62 12 B0 06 50   # T2 LOW = 80
   ```

   Play/release `90 3C 01 80 3C 00`, then velocity79 (`90 3C 4F`): T1 only.
   Release with `90 3C 00`. Play velocity80 (`90 3C 50`), then127 (`90 3C 7F`):
   T2 only; release after each. Repeating note60 at79 then80 without an intervening
   release replaces T1 with T2. Final velocity-zero releases T2. Isolate each part
   at MIXER and capture actual PCM separately to identify its sound.
3. Set overlap: `B0 63 60 B0 62 03 B0 06 5F` (T1 HIGH95), then
   `B0 63 60 B0 62 12 B0 06 40` (T2 LOW64). Velocity63 is T1 only,
   64 and95 sound both, 96 is T2 only. Release between tests and confirm final
   silence after normal patch release tails. Overlap may consume both parts'
   voices, just like existing layering.
4. Restore split79/80 using step2. Send `B0 43 7F` (Soft Pedal ON), then
   `90 3C 64`: raw100 must select T2, even if delivered velocity scales below80.
   Release `80 3C 00`, then `B0 43 00`. With sustain down (`B0 40 7F`), play
   soft79 and release; change T1 HIGH to50 (`B0 63 60 B0 62 03 B0 06 32`).
   The T1 note stays held until `B0 40 00`, then releases. Repeat while physically
   holding the note across edits. Key ranges still intersect these velocity zones;
   excluding note60 from a selected part must prevent its next attack.
5. Try T1 LOW100 while HIGH50 (`B0 63 60 B0 62 02 B0 06 64`): reject,
   leaving velocity50 admitted. Restore T1 LOW1 then HIGH127 (NRPN LSB02/03,
   CC6 values01/7F); restore T2 LOW1 then HIGH127 (LSB12/13, values01/7F).
   Reboot/load a disposable project and confirm defaults. Repeat on physical USB
   and TRS, including held notes, panic and sound/route edits; report exact package,
   host/device/transport and observed versus expected results.

## Validation and resource limits

`tests/midi_velocity_range_test.c` compiles actual queues, UART parser, routing,
voices, chord/ARP, sound-install, panic and overflow paths. It exhausts 0..127
velocities in default, split, overlap and shared-boundary configurations for both
queue sources; tests all 16,384 note/velocity pairs against intersecting key zones;
and checks single-value/invalid/reversed bounds, captured owners, sustain,
retrigger, independent channels, range/selection edits, CC120/121/123, sound panic,
input overflow, CHRD/ARP, local/sequence bypass, UART running status and reset.
These checks establish gate/control behavior, not audible PCM or hardware timing.
Raw-velocity versus Soft Pedal integration needs the combined batch fixture.

Additional static state is eight BSS bytes, two bounds per part. Work is bounded
by four part comparisons per positive external note event, with no allocation,
continuous DSP, persistent storage or extra voice reservation. Actual target
app/RAM/POOL/RAMTEXT/NOINIT/stack and note-event timing deltas require the
coordinator's integrated build and measurements; no timing figure is claimed.

README assessment: native layer behavior remains accurate; batch may link this
setup guide. Changelog assessment: add a grouped MIDI-zone entry in integration,
including session-only and pending hardware limits. Diagnostic assessment: no
new commands, fields, flags or diagnostics; existing guides remain applicable.
