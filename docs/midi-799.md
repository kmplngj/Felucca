<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Channel fine and coarse tuning (#799)

Registered tuning is runtime channel state shared by USB and TRS, like bend.
It does not edit sound parameters or saved projects. Startup is fine value 8192
(unison) and coarse value 64 (zero semitones). CC 121 preserves both tunings and
RPN 0 bend sensitivity, following RP-015; it centers bend, cancels selection and
releases sustain as before. Route changes preserve registered tuning but clear
abandoned part expression, and new notes reapply their channel's state. Sound
installation clears part performance expression; the next note or tuning/bend
message applies the channel's registered values again. Project/session reset
policy is coordinated by the batch integration.

Select RPN with CC 101=0 and CC 100=1 (fine), or CC 100=2 (coarse). Fine is
`(CC6 << 7) | CC38`, centered at 8192, with offset `(value-8192)/8192`
semitones: -100 through +99.9878 cents. Either byte updates immediately and
preserves its other byte. Coarse uses CC 6 only: value 0..127 means -64..+63
semitones; CC 38 is ignored. RPN 0 retains the existing 0..24 semitones/0..99
cents sensitivity. Null 127/127 and unknown registered selectors ignore data;
NRPN selection cancels registered selection. Data increment/decrement is not
added here. Selector source isolation belongs to #530; tuning itself is shared.

Updates affect every pitched voice currently routed to or owned by that channel
at its next render block, including held notes, release tails, CHRD and ARP.
A part has one expression state: the latest channel note or expression message
wins when several channels target it. Layers sharing a channel receive identical
tuning. Use distinct channels for independently detuned layers. Raw MIDI note
identity, chord ownership, sustain and note-off matching remain unchanged.
DRUM ignores channel tuning. Other engines receive the existing pitch-preparation
output (sampled/unpitched material retains its engine's pitch behavior).

Coarse and fine combine with smoothed bend before the existing pitch16/fine
split; negative division floors, preserving a positive residual. Global TUNE and
voice detune then retain their existing preparation. The base pitch clamps to
0..2047 sixteenths of a semitone, with residual correction as before. Fine input
is retained at full 14-bit precision, while the existing 1/4096 oscillator factor
limits effective fractional resolution to about 0.42 cents. No new oscillator,
saved parameter, allocation or per-sample conversion is introduced. State adds
fine 14 plus coarse to each of 16 channels and one Q 14 int 32 per part; exact target
layout, flash and deadline deltas need the coordinator's fresh target build.

## Validation and user test procedure

The focused `tests/midi_tuning_test.c` includes the real MIDI queue, dispatcher,
ownership and renderer fixture. It checks fine/coarse extremes and center
neighbors, partial entries, USB/TRS sharing, independent channels, cancellation,
CC 121, clipping and raw sustain release. ANALOG, PHASE and FORMANT oscillator
phase advances establish tuning within 0.6 cents of the ideal reference and
composition with negative global tuning and bend within 0.9 cents. Actual PCM
neutral equality and nonzero rendered audio are checked. Existing MIDI control
integration tests remain applicable. Browser PCM/pitch tests, full host tests,
target budgets and physical FM-1 checks remain coordinator/hardware gates.

Use the exact integrated candidate emulator/package, stopped transport, track 1
ANALOG with no pitch modulation, channel 1, note 69 (A 4), global TUNE 0. For every
sequence below bytes are hexadecimal; keep the original note 69 held throughout:

1. Send `B 0 65 00 B 0 64 01 B 0 06 40 B 0 26 00`, then `90 45 64`.
   Expect 440 Hz at normal tuning.
2. Send `B 0 06 60 B 0 26 00` (fine 12288). Expect approximately 452.893 Hz
   (+50 cents), while note identity stays 69.
3. Send `B 0 06 40 B 0 26 00 B 0 64 02 B 0 06 4C`.
   Expect 880 Hz (+12 semitones).
4. Send `80 45 00`: the original note releases. Repeat while holding sustain
   (`B 0 40 7F`), then send `B 0 79 00`: sustain releases but +12 remains.
5. Send `B 0 65 00 B 0 64 02 B 0 06 40` to restore coarse zero, fine center
   from step 3 remains. Null selection with `B 0 65 7F B 0 64 7F`.

For a two-layer unison/detune check, assign track 1 and track 2 distinct MIDI
channels 1 and 2, use the same ANALOG patch and send note 69 to both. Send the fine
sequence on channel 2 (`B 1`) only: expect beating and separate channel tuning;
release with original `80 45 00` and `81 45 00`. Run the same procedure over
USB and TRS on FM-1 with the exact candidate `.fwsc`, record audible cleanup and
loaded deadlines. Physical transport, listening and timing remain pending.

README/changelog: coordinator should add one combined batch entry; no competing
edits here. Diagnostics guide: no diagnostic command or field changed.

Focused checks on this issue branch: optimized MIDI control integration and
optimized tuning tests passed. ASan/UBSan tuning execution stops at the existing
FORMANT negative left shift in `eng_formant.c:186`; a neutral FORMANT probe with
no tuning messages reproduces the same failure. No sanitizer exclusions or
unrelated DSP changes were added. Host channel layout is 18 bytes (288 total),
versus 14 bytes before (224 total), plus 16 bytes for part tuning: 80 added static
bytes on this host ABI. Target layout and cost remain unmeasured here.
