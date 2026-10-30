<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI performance controls

These controls use existing parts, sounds and MIDI note ownership. They add no
synthesis engine. The built-in keys and sequencer keep their existing routing.
All examples below use MIDI channel 1; hexadecimal bytes include a status byte
for every message so they can be sent directly by a MIDI utility.

## What can be played

| Feature | Musical use | Setup / controls |
| --- | --- | --- |
| Pair mix [#795](midi-795.md) | Blend a lead and pad with one fader | Assigned CC, configured by NRPN `0x3100..0x3102` |
| Key ranges [#796](midi-796.md) | Left-hand bass, right-hand lead; overlap layers | Inclusive incoming note bounds per part |
| Velocity zones [#797](midi-797.md) | Soft/hard articulations | Inclusive raw positive velocity bounds per part |
| Articulation [#798](midi-798.md) | Foot-controlled glide and connected mono phrases | CC5 time, CC65 portamento, CC68 mono/legato |
| Channel tuning [#799](midi-799.md) | Fine tuning and octave transposition | Standard RPN1 fine / RPN2 coarse |
| Soft Pedal [#800](midi-800.md) | Gentler new attacks | CC67; positive velocity becomes `ceil(v/2)` |
| Bank recall [#801](midi-801.md) | Recall saved sounds from a DAW/keyboard | CC0/32 then Program Change; bank1 is U01..U32 |
| Parameter control [#530](midi-530.md) | Automate common/engine parameters without Learn slots | Stable seven-bit NRPN registry |

Key/velocity zones and the pair assignment are **session-only**. They reset at
boot and when a project is loaded, and are not saved in projects, presets or
backups. This keeps the existing fixed-size project format and retained RAM
unchanged. Ordinary LEVEL edits made by the pair mix are saved as normal track
levels. Reapply routing setup after loading a project when needed.

Project load also clears Soft Pedal, live articulation overrides, bank selectors,
pending Program Changes and NRPN/RPN selections. Registered fine/coarse tuning
values and bend sensitivity are retained as channel state; they are not project
parameters. A bare Data Entry after loading a project has no selected parameter.
Power-on starts at neutral registered tuning.

## Configuration over MIDI

Send CC99/98 for the NRPN address, then CC6 for its seven-bit value. Both selector
bytes must be known. Sound NRPNs follow the receiving channel's routed parts;
configuration addresses below explicitly identify the target part. An unheard
channel cannot change the configuration. USB/TRS NRPN selectors are independent;
note/expression/controller state otherwise retains the existing shared model.

| Address | Meaning | Values / default |
| --- | --- | --- |
| `0x3000 + 0x10*part` | Key LOW | 0..127, default0 |
| `0x3001 + 0x10*part` | Key HIGH | 0..127, default127 |
| `0x3002 + 0x10*part` | Velocity LOW | 1..127, default1 |
| `0x3003 + 0x10*part` | Velocity HIGH | 1..127, default127 |
| `0x3100` | Pair's assigned CC | 0 disabled; available CC1..119 |
| `0x3101` | Pair A | part0..3, default0 |
| `0x3102` | Pair B | part0..3, default1 |

Here part0 means T1. Reversed ranges, identical pair members, invalid targets and
reserved CC assignments leave the previous setup unchanged. Parameter NRPN
values are scaled through the target descriptor; the configuration values in
this table are literal bounds/part numbers. MIDI Learn has priority over the
pair assignment. CC65/67/68 are reserved controller functions, so they no longer
serve as Learn or pair assignments. Existing stored data is retained.

Example: T1/T2 already assigned channel1 in MIDI IN TRACK, T1 plays notes0..59,
T2 plays60..127:

```text
B0 63 60  B0 62 01  B0 06 3B
B0 63 60  B0 62 10  B0 06 3C
```

Example: T1 responds to velocities1..79 and T2 to80..127:

```text
B0 63 60  B0 62 03  B0 06 4F
B0 63 60  B0 62 12  B0 06 50
```

Raw note and velocity choose destinations before CHRD/ARP and before Soft Pedal
scaling. A raw100 attack can therefore select T2's hard zone and sound at velocity50
with CC67 ON. Note-on velocity0 is always a release. Bounds/controller edits never
reroute an existing note's release away from its captured owners.

Pair CC20 for the default T1/T2 pair (disable the emulator's optional CC20..27
panel-knob mapping if testing this assignment there):

```text
B0 63 62  B0 62 00  B0 06 14
B0 14 00
B0 14 40
B0 14 7F
```

The endpoints are LEVEL112/0 and0/112. The midpoint rounds to LEVEL100 on each
part using the existing amplitude table. This is complementary linear gain,
not equal-power compensation or a promise of constant loudness for all patches.

## Testing and limits

Use the rebuilt browser emulator for software-MIDI/PCM tests; it does not validate
physical USB/TRS transport or FM-1 deadlines. The focused host tests cover each
feature and combinations, including project-reset and bank snapshot ordering.
The feature guides above give exact MIDI and later hardware procedures.

For testing tones, finish the deferred Program Change before sending dry effect
and envelope CC/NRPN setup; loading a preset can restore those sound parameters.
In MIXER, ALGORITHM selects a part and KNOB1 edits its LEVEL. KNOB2 edits PAN of
the selected part. This matters when isolating layered sounds in actual audio.

CC68 initially changes MONO/LEG parts only; POLY, UNISON and one-shot behavior is
documented in its guide. The existing ARP path supplies its own velocity, so CC67
retains that ARP behavior instead of changing the arpeggiator in this batch.
Fine-tuning input retains 14-bit state, with audible resolution limited by each
engine's existing pitch preparation. Bank0 preserves factory Program Change;
bank1 addresses exact user slots, while empty/unsupported/unavailable loads do
nothing. Bank Select alone never changes sound or retargets an already queued PC.

Layer/overlap regions can consume additional voices from the existing pool.
Resource and timing conclusions must come from the actual target build and
workload; small MIDI handlers do not make a second sound or an enabled effect free.
No physical FM-1 acceptance is established by these software controls/tests.
