<!-- SPDX-License-Identifier: GPL-3.0-only -->
# NRPN sound control (#530)

NRPN uses CC99 (address MSB), CC98 (address LSB), then **seven-bit CC6** (value
0..127). Address = MSB * 128 + LSB. Each USB/TRS source and each of its sixteen
channels has its own selector. Both halves must have arrived since reset before
CC6 applies. Selecting an address alone never replays old data. Subsequent CC99
or CC98 updates retain the other half, as ordinary MIDI selectors do; send both
halves when changing destinations. CC38 and CC96/97 do not edit NRPN values.
127:127 cancels selection; partial, unknown and reserved addresses have no effect.
No FM6 operator pages are mapped.

Common controls and current-engine E1..E8 follow the same channel routing as
notes, including TRACK layers. Bounds come from current native descriptors:
`min + (value * (max - min) + 63) / 127`. PAN is -64..63 (CC6=64 gives zero),
not the donor's historical range. Engine edits resolve the requested sound at
data-entry time, so a new engine uses its own bounds. Missing engines and
zero-width E slots ignore engine NRPNs. Common controls still work on unavailable
engines. Mutations use the normal knob/motion-capture path, consume no MIDI Learn
slots and introduce no flash write or persistent format.

RPN remains shared between USB/TRS on a channel, like existing bend and note
ownership. Either RPN selector CC101/100 cancels both NRPN selectors on that
channel; NRPN selection cancels shared RPN. CC121 cancels both NRPN selectors;
input-queue overflow cancels every selector. Routing a channel out of the heard
block cancels its selectors; a still-heard channel's selection follows current
routing. Notes keep their existing captured ownership across edits. Fixed CCs
and learned mappings retain their existing priority.

## Registry provenance and extensions

The common MSB0 registry and engine MSB1 registry below are adapted from
[ordenador/Felucca #255, pinned source](https://github.com/ordenador/Felucca/blob/3348c2eb6aa4ba175f5e746a7e42d7670f74a498/firmware/src/midi_nrpn_map.h),
commit `3348c2eb6aa4ba175f5e746a7e42d7670f74a498`, GPL-3.0-only.
The donor selector/reset implementation is adapted with native layer routing and
MIDI Learn preserved. No donor engine gitlink or unrelated changes are imported.
Addresses do not depend on enum insertion. Common holes 8 and 61..80 remain
reserved; every unlisted address stays unassigned.

Collision audit: donor assigns only 0:0..102 (with holes) and 1:0..7.
Native session extensions therefore reserve 0x3000 + track*0x10 + field
(track 0..3, field 0 key low, 1 key high, 2 velocity low, 3 velocity high),
0x3100 MIX_CC, 0x3101 MIX_A, 0x3102 MIX_B. These absolute track configuration
addresses are dispatched once per heard event through `midi_nrpn_extra`, whose
stub returns zero until batch integration wires the feature helpers. They do
not follow destination fanout and are not saved. No new SysEx is added.

## Controller and browser test sequence

Use the exact batch artifact and rebuilt emulator, selected part 1 with ANALOG
(id 0), ROUT CH1-4, stopped transport. With the browser MIDI handler ready,
choose the part using the part-1 button, and use an attached controller on channel
1 (USB source 1). Bytes below are hexadecimal; CC values in brackets are decimal.
Browser testing must exercise the real Web MIDI handler/AudioWorklet and inspect
both applied values and captured PCM.

1. Send `90 3C 64` (hold middle C). Select Level with `B0 63 00`, `B0 62 00`;
   send `B0 06 00`, `B0 06 40`, `B0 06 7F` [0,64,127]. Expect LVL0/64/127
   and audible level change. Restore `B0 06 68` [104].
2. Select ANALOG E5 (cutoff) with `B0 63 01`, `B0 62 04`; send the same three
   CC6 messages. Expect current E5 descriptor endpoints/midpoint and audible
   brightness changes. Inspect actual ANALOG descriptors in this revision rather
   than assuming a donor range. Release with `80 3C 00`; expect quiet release.
3. On USB select PAN with `B0 63 00`, `B0 62 27`; independently select LEVEL on
   TRS with `B0 63 00`, `B0 62 00`. USB `B0 06 40` must set PAN0; TRS
   `B0 06 40` must set LVL64. On channel2, use B1 to select another parameter;
   neither source/channel may overwrite the others' selectors.
4. Send USB `B0 65 00`, `B0 64 00`, `B0 06 0C` (RPN0 range12); CC6 must
   update bend sensitivity only and invalidate both source selectors on channel1.
   Reselect NRPN, then `B0 79 00` (CC121), followed by CC6: no NRPN edit.
   Cancel explicitly with `B0 63 7F`, `B0 62 7F`. Try unknown0:8 and partial
   selection after reset; no parameter edit. Fixed CC7 and a learned CC retain
   their behavior while NRPN is selected.
5. Repeat held/released notes with clock traffic, sustain CC64, velocity-zero
   note-off and route/engine changes. Check finite/nonzero held PCM, quiet release,
   stable clock and no stuck note. Browser cannot establish physical TRS behavior.

**Pending FM-1 validation:** build the frozen integration revision using
`uv run --locked --group build ./build.sh` and the normal BUILDING.md prerequisites;
use that exact `.fwsc` package and record its SHA256/commit/profile. From a trusted
caller checkout install only when authorized using the documented installer. On
FM-1 HOME select part1, choose ANALOG with the engine selector, open MENU > MIDI
and set ROUT CH1-4, then repeat steps1..5 over physical USB and TRS with output
connected to headphones/interface. Stop notes and send CC121 when finished.
Record device/package identity, host/controller, both transports and audible
results. Input deadlines, CPU/RAM/stack cost and physical timing remain pending.

## Validation and documentation assessment

The focused host harness compiles actual queue, routing, descriptor, parameter,
Learn and motion sources. Run a freshly built `tests/midi_nrpn_test.c` fixture,
then `python3 tests/midi_nrpn_registry_test.py build/midi_nrpn_test` to freeze the
audited donor registry and the generated native public bounds below. Strict
ASan/UBSan uses no sanitizer exclusions. Coordinator owns full-suite, target,
reduced/MACRO profile rebuilds and browser validation; host results are not device
or target-cost evidence. Session configuration bridge/reset wiring belongs to batch
integration. README/fork-guide/changelog should link this guide and describe stable
NRPN sound control in the combined batch PR; root owns shared documentation edits.
Diagnostic commands are unchanged, so no diagnostic-guide change is required.

Focused worker validation at the issue commit: GCC14.2.0 host optimized NRPN
fixture passed, fatal ASan/UBSan NRPN fixture passed without exclusions, frozen
registry/public-map check passed, and existing MIDI control/clock integration
fixture passed. A `-DFELUCCA_ENG_OMIT=3` sparse host simulation also passed; it is
not a generated reduced-profile build. Target resource deltas remain unmeasured;
selector storage is statically 96 bytes and the common lookup table 256 bytes of
constant data before target linker effects. No per-sample dispatch is added.

Reproduce from the prepared worktree (generated includes supplied by coordinator):

```sh
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi_nrpn_test tests/midi_nrpn_test.c -lm
build/midi_nrpn_test
python3 tests/midi_nrpn_registry_test.py build/midi_nrpn_test
cc -O1 -g -w -fsanitize=address,undefined -fno-sanitize-recover=all -Ibuild/gen -Ifirmware/src -o build/midi_nrpn_test_san tests/midi_nrpn_test.c -lm
ASAN_OPTIONS=halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 build/midi_nrpn_test_san
```

## Generated native common address map

<!-- NRPN_MAP_BEGIN -->
| Address | Parameter | Native bounds |
| --- | --- | --- |
| 0:0 | Level | 0..127 |
| 0:1 | ENV Attack | 0..127 |
| 0:2 | ENV Decay | 0..127 |
| 0:3 | ENV Sustain | 0..127 |
| 0:4 | ENV Release | 0..127 |
| 0:5 | ENV Filter | -64..63 |
| 0:6 | ENV Pitch | -64..63 |
| 0:7 | ENV Shape | -64..63 |
| 0:9 | LFO Rate | 0..127 |
| 0:10 | LFO Wave | 0..4 |
| 0:11 | LFO Phase | 0..127 |
| 0:12 | LFO Fade | 0..127 |
| 0:13 | LFO Pitch | -64..63 |
| 0:14 | LFO Filter | -64..63 |
| 0:15 | LFO Shape | -64..63 |
| 0:16 | LFO Amplitude | 0..127 |
| 0:17 | Arp Mode | 0..14 |
| 0:18 | Arp Rate | 0..9 |
| 0:19 | Arp Octaves | 1..4 |
| 0:20 | Arp Gate | 1..127 |
| 0:21 | Arp Swing | 0..100 |
| 0:22 | Arp Probability | 0..127 |
| 0:23 | Arp Hold | 0..1 |
| 0:24 | Arp Order | 0..1 |
| 0:25 | Scale Root | 0..11 |
| 0:26 | Scale | 0..15 |
| 0:27 | Quantize | 0..4 |
| 0:28 | Transpose | -24..24 |
| 0:29 | Sequence Length | 1..64 |
| 0:30 | Sequence Division | 0..9 |
| 0:31 | Sequence Swing | 0..100 |
| 0:32 | Sequence Gate | 1..127 |
| 0:33 | Distortion | 0..127 |
| 0:34 | Chorus Send | 0..127 |
| 0:35 | Delay Send | 0..127 |
| 0:36 | Reverb Send | 0..127 |
| 0:37 | Voice Mode | 0..3 |
| 0:38 | Glide | 0..127 |
| 0:39 | Pan | -64..63 |
| 0:40 | Mute | 0..1 |
| 0:41 | Glide Mode | 0..1 |
| 0:42 | Voice Priority | 0..2 |
| 0:43 | Voice Allocation | 0..1 |
| 0:44 | Detune | 0..127 |
| 0:45 | Slicer Mode | 0..2 |
| 0:46 | Slicer Pattern | 1..16 |
| 0:47 | Slicer Rate | 0..5 |
| 0:48 | Slicer Depth | 0..127 |
| 0:49 | Matrix1 Source | 0..10 |
| 0:50 | Matrix1 Destination | 0..22 |
| 0:51 | Matrix1 Amount | -64..63 |
| 0:52 | Matrix2 Source | 0..10 |
| 0:53 | Matrix2 Destination | 0..22 |
| 0:54 | Matrix2 Amount | -64..63 |
| 0:55 | Matrix3 Source | 0..10 |
| 0:56 | Matrix3 Destination | 0..22 |
| 0:57 | Matrix3 Amount | -64..63 |
| 0:58 | Matrix4 Source | 0..10 |
| 0:59 | Matrix4 Destination | 0..22 |
| 0:60 | Matrix4 Amount | -64..63 |
| 0:81 | Chord | 0..9 |
| 0:82 | Chord Voicing | 0..4 |
| 0:83 | Drum Kick | 0..127 |
| 0:84 | Drum Snare | 0..127 |
| 0:85 | Drum Clap | 0..127 |
| 0:86 | Drum Closed Hat | 0..127 |
| 0:87 | Drum Open Hat | 0..127 |
| 0:88 | Drum Tom | 0..127 |
| 0:89 | Drum Rim | 0..127 |
| 0:90 | Drum Bell | 0..127 |
| 0:91 | LFO Sync | 0..10 |
| 0:92 | LFO Trigger | 0..1 |
| 0:93 | LFO Polarity | 0..1 |
| 0:94 | Sequence Quantize | 0..1 |
| 0:95 | Spread | 0..127 |
| 0:96 | Insert Type | 0..8 |
| 0:97 | Insert A | 0..127 |
| 0:98 | Insert B | 0..127 |
| 0:99 | Insert C | 0..127 |
| 0:100 | Insert Mix | 0..127 |
| 0:101 | Analog Filter Type | 0..2 |
| 0:102 | ENV Sync | 0..1 |
| 1:0..7 | Current engine E1..E8 | Current native engine descriptor |
<!-- NRPN_MAP_END -->
