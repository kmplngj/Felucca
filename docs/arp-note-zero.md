<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Existing ARP modes and MIDI note 0

The existing UP, REPEAT and CHORD paths now track release identities separately
from raw MIDI pitches. Note 0 receives the same gate expiry and cleanup as notes
1–127. This corrects existing modes; it adds no DRONE mode, parameter or voice.
Physical FM-1 listening, MIDI transport and deadline qualification remain pending.

## Runtime contract

`track_t.arp_mask` uses bit 0 for `arp_note` and bits 1–3 for `arp_ch[0..2]`.
Every pitch remains an ordinary MIDI value, including 0. A clear bit means the
corresponding release slot is unused; it does not mean that pitch cannot sound
from another source. The mask records ARP-emitted release identities, not a new
admitted-voice or input-owner ledger. Voice limits, stealing and the existing
panel/MIDI same-pitch behavior characterized by #307 are unchanged.

The byte occupies natural padding before `arp_off`; a compile-time assertion
keeps that field eight bytes after `arp_note`, and the existing track-size
alignment assertion remains. Actual linked target layout, app/RAM/stack deltas
and static costs must be checked on the candidate, not inferred from padding.
The field is runtime-only: project/preset parameters, steps, IDs and wire formats
are unchanged. Project capture uses its separate saved-track record.

The audio ISR owns updates. Gate expiry, retrigger, empty lists, external Stop,
mode/HOLD cleanup and panic use explicit validity. CHORD retains its original
indexed slots, maximum four notes and clamped-127 deduplication, including a
skipped slot followed by another emitted pitch. Panic/overflow and MIDI silence
clear the mask through `arp_forget`; sound/project loads use their existing
panic path. No new reset is added to the engine fade or voice allocator.

On the target, the main-loop LED reader saves interrupt state, masks interrupts,
copies the mask and four pitches, then restores the prior state. Mapping and LED
work remain outside that short window. This protects the ARP snapshot only;
it does not promise an atomic snapshot of sequencer and MIDI state together.
Host fixtures use their existing hardware stubs; they do not measure the target
critical-section duration or prove physical LED timing.

## Regressions and evidence boundaries

`tests/midi_control_test.c` drives the real MIDI queue, ARP and voice handlers.
At nominal 44,100 Hz/internal 120 BPM, RATE 1/16 is 5,512 samples and raw GATE 64
is 2,756 samples. The test independently expects no gated voice after 87 further
32-sample blocks (2,784 samples), before the next step. It observes actual voice
gates and retrigger age, rather than treating the new mask as the gate oracle.

Coverage includes notes 0/1/60/127, UP/REPEAT, HOLD release/refire/disable, sorted
and as-played CHORD with primary/secondary zero, four-note limits and upper
clamping, mode OFF, panic/overflow, probability/RNG, empty remapped lists,
sustain/shared MIDI ownership, recording NOTE/TIE closure, external
Start/Stop/Continue/loss, preset/engine and project cleanup. Existing scale,
clock and panel LED fixtures also check the revised runtime contract.
This does not add new source-ownership policy or qualify all engine/voice modes.

After generating assets with a successful build, focused host checks are:

```sh
cc -O2 -w -Ibuild/gen -Ifirmware/src tests/midi_control_test.c -lm -o build/host/midi_control_test
build/host/midi_control_test
cc -O2 -w -Ibuild/gen -Ifirmware/src tests/scale_test.c -lm -o build/host/scale_test
build/host/scale_test
cc -O2 -w -Ibuild/gen -Ifirmware/src tests/midi_drift_test.c -lm -o build/host/midi_drift_test
build/host/midi_drift_test
```

Repeat with `-Os -fno-vectorize -fno-slp-vectorize` in place of `-O2`.
`-w` follows these harnesses' existing convention; it is not warning-free build
evidence. The full applicable suite additionally runs the UI/LED fixtures.
Unchanged-source negatives are retained with the local issue evidence; no sound
or cost baseline is rewritten. Full target/resource, full-suite and fresh
native/Wasm/browser acceptance are separate gates. No CPU improvement is claimed.

## Pending FM-1 checks

Use only the reviewed candidate's identified installable package and the
[PR installation procedure](../BUILDING.md#test-a-pull-request-on-hardware).
The focused local implementation stage does not supply an installable package.
Keep a backup, use a disposable project and record exact build/variant, device,
MIDI source/channel and output recording. These actions are user instructions,
not evidence of an agent device run.

1. Back up and use a disposable project. If playing, tap PLAY to stop. Tap
   HOME until HOME is shown, then turn ALGORITHM to select track 1. Hold EDIT
   until [EDIT] SET appears; while holding it turn KNOB 1 ENG to ANALOG and
   KNOB 2 No. to an ANALOG factory sound, then release EDIT. Tap EDIT until
   VOICE is shown and set KNOB 1 to POLY. Tap ENV until
   ENV is shown, set KNOB 3 SUS to 100% and KNOB 4 REL to its shortest value so
   release gaps are easy to distinguish from tails.
   Hold HOME for more than 0.7 s to open MENU, turn ALGORITHM to the MIDI tab,
   PRESETS to MIDI IN and KNOB 1 to CH1–4. Select AUTO SELECT with PRESETS and
   set it OFF with KNOB 1 so multi-channel tests cannot change the selected part.
   Tap HOME until HOME is shown. Use a MIDI
   sender on channel 1 that can send numeric pitches 0, 1, 60 and 127 (octave
   names vary between programs); release all other inputs and the sustain pedal.
2. From HOME tap HOME twice to CLOCK; set KNOB 1 BPM to 120 and KNOB 3 to INT.
   Tap ARP until the page title is ARP. Set KNOB 1 MODE UP, KNOB 2 RATE 1/16,
   KNOB 3 OCT 1 and KNOB 4 GATE 50% (approximately half the step). Displayed
   50% can represent raw63 or64; the host regression specifically uses raw64. Tap ARP again for ARP 2: KNOB 1
   SWG 0, KNOB 2 PROB 100%, KNOB 3 HOLD OFF and KNOB 4 ORD NOTE (sorted). Do not start
   transport for this initial internal-clock check.
3. Send/hold each pitch separately at velocity100, then send its note-off.
   Expect periodic attacks separated by release gaps for every pitch, including
   0; ordinary note-off releases it. Repeat with REPEAT, then CHORD using
   [0,60] and ORD PLAY (as-played) [60,0]. Both chord pitches must release at each gate.
   The very low pitch may be difficult to hear directly: compare its envelope
   and recorded output with the nonzero controls, rather than relying on a
   note-name convention or declaring a silent low fundamental a failure.
4. On ARP 2 turn HOLD ON. Tap pitch0 and release it, wait for a latched retrigger,
   then turn HOLD OFF with no physical input down. Expect the generated sound
   to release; repeat with pitch60. On ARP set MODE OFF during a held zero and
   expect cleanup. Confirm panic/All Sound Off also releases the sound.
5. In separate runs repeat the external-clock Stop/Continue/loss, sustain,
   recording, preset/engine/project and shared-input cases, with USB and TRS
   distinguished. Check note/LED agreement when the selected keyboard mapping
   includes the pitch. Repeat under normal dense audio/panel/USB load using the
   [performance procedure](performance.md#device-timing-and-stress-procedure);
   host gate tests alone establish neither deadlines nor wire behavior.

Release inputs, disable HOLD/ARP, stop playback and restore the previous project
and settings. Report the exact scenario and expected versus observed gate/tail,
recording, LED and transport behavior. Physical checks above remain pending.
