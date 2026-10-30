<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI bank and user-preset recall (#801)

CC0 is Bank Select MSB; CC32 is Bank Select LSB. Their seven-bit values are
retained independently per MIDI channel, shared by USB and TRS. Either order
works; changing either selector alone never loads a sound. A Program Change
captures both selectors and its program at arrival. All numbers below are raw
zero-based MIDI data bytes; controllers displaying programs 1..128 need +1.

| CC0 | CC32 | Program | Result |
| --- | --- | --- | --- |
| 0 | 0 | 0..127 | Existing per-engine Program Change numbering, unchanged |
| 0 | 1 | 0..31 | Exact existing user slots U01..U32, independent of engine |
| 0 | 1 | 32..127 | Ignored |
| any other pair | | any | Ignored |

Bank 0 remains the default after boot. Factory numbering skips preset aliases;
DRUM programs select its existing kit list, and FM6's existing factory/voice-bank
numbering is unchanged. Bank 1 is a Felucca manufacturer-specific address, not
GM/GS. Empty, malformed or unavailable-engine user records leave the destination
sound unchanged. Legacy DIGITAL records use the existing conversion only when
FM6 is available. There is no fallback, compacted used-slot numbering or wrap.

The storage audit found 32 user records in the existing two 16-record UPB1
objects (`upreset.c`, `UP_SLOTS` in `core.h`, editor UP_LIST/GET/PUT/LOAD). The
physical storage object's bank boundary is unrelated to MIDI bank 1. FM6's voice
bank remains accessible only through legacy bank-0 FM6 program numbering.
Factory patterns and user phrases remain separate; no pattern bank is mapped.
No storage records, engine IDs, parameter IDs, flash addresses, or SysEx change.
MIDI recall reads the RAM mirror and never saves, erases or writes flash.

Each routed destination gets one pending packed bank/program word. The last PC
before that track's main-loop service wins, including an unsupported request
which replaces a pending valid one. A later Bank Select cannot alter a pending
request. Layered tracks receive the same snapshot. The route and selected track
at PC arrival choose destinations; later routing/selection edits do not move or
cancel those requests. Each track services its request separately, so a new PC
between services may coalesce differently across tracks. This follows existing
per-track main-loop coalescing rather than an atomic all-layer transaction.

CC120/123 and CC121 leave bank selectors and pending requests intact; MIDI Reset
All Controllers excludes Bank Select. Route changes retain bank selectors.
Input-queue overflow clears selectors and cancels pending requests. The
`midi_bank_reset()` helper does the same for the coordinator's boot/project-reset
integration; this issue's isolated branch supplies the helper and overflow call.
Project wiring is part of the integrated MIDI batch.

Main-loop bank-1 service calls the existing user-preset sound path with an
explicit destination track. It keeps mix, steps and other `param_kept` values,
uses sound undo and motion pause/rebase, drops engine-specific motion when the
engine changes, and runs normal sound panic/install/fade. It never substitutes
the selected track for a captured destination. UI/editor `up_load()` still targets
the selected track and retains its existing unavailable-engine policy.

Selector fields add 32 bytes (two bytes × 16 channels); pending words add 12 bytes
(four bytes replacing one × four tracks), before integrated linker effects.
There is no allocation, rendering stage or per-sample bank work. Target RAM,
stack, code size and loading-cycle measurements remain the coordinator's checks.
No main-loop cost or hardware deadline claim is made here.

## Focused validation

From this checkout after coordinator-provided submodule/generated setup:

```sh
mkdir -p build/midi-801
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi-801/midi_control_test tests/midi_control_test.c -lm
build/midi-801/midi_control_test
cc -O1 -g -w -fsanitize=address,undefined -fno-sanitize-recover=all -Ibuild/gen -Ifirmware/src -o build/midi-801/midi_control_san tests/midi_control_test.c -lm
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 build/midi-801/midi_control_san
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi-801/upreset_test tests/upreset_test.c -lm
build/midi-801/upreset_test
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi-801/sound_install_test tests/sound_install_test.c -lm
build/midi-801/sound_install_test
```

The existing MIDI harness compiles real input queues/parsers, channel dispatch,
UI service, sound installation, preset storage and ownership paths. The #801
cases cover retained/order-independent selectors, all 16 channels, shared ports,
no selector-only load, bank snapshot before later changes, exact slot bounds,
coalescing including an empty last request, invalid/absent-engine records,
CC121, captured layer destinations, normal undo, steps/mix/common-motion retention,
engine-motion cleanup, held-note panic cleanup and overflow/reset. Existing
bank-0 tests exercise all available engines, DRUM kits and FM6 voice-bank slots.

## Browser and FM-1 test procedure — pending

Use the integrated candidate's exact artifact/SHA and standard profile, a USB
cable, MIDI source, headphones at low volume, and a TRS MIDI interface for the
second pass. Coordinator owns build/install commands; do not test the hosted
release in place of this candidate. Back up existing user presets before saving
disposable U01/U32 fixtures. Recall itself writes nothing.

1. Stop playback. Tap HOME. Turn ALGORITHM left to T1. Choose a contrasting
   factory sound with PRESETS. Tap SAVE from HOME to enter USER. Turn KNOB 1 to
   a disposable slot U01; turn KNOB 4 to select SAVE and tap OCT+. If OVERWRITE
   appears, tap OCT+ to proceed only for the disposable fixture. At NAME, tap
   OCT+ to save the default name. Tap HOME. Choose a contrasting engine/sound
   with ALGORITHM/PRESETS and repeat for U32. Note both sounds and engines.
2. Hold HOME to open MENU, release, turn ALGORITHM to MIDI, PRESETS to MIDI IN,
   and KNOB 1 to CH1-4. Tap HOME to close. Send channel-1 bytes
   `B0 00 00`, `B0 20 01` only: sound must stay unchanged. Send `C0 00`: hear U01;
   send `C0 1F`: hear U32, with the correct engine/parameters and contrasting PCM.
   Hold SAVE after a recall to check normal sound undo. Keep transport stopped
   for the first pass, then repeat while a disposable pattern/motion plays:
   steps and common motion stay, engine-specific motion follows normal cleanup.
3. Hold a channel-1 note, recall the other sound, then release the old note.
   Hear the normal sound-change panic/fade and no stuck note. Play a fresh note;
   its engine and PCM must match the recalled sound. Record actual audio.
4. Send `B0 20 00`, `C0 02`: expect legacy bank-0 program 2 for the current
   engine. Send `B0 00 01`, `B0 20 01`, `C0 00`: unsupported bank 129 changes
   nothing. Send `B0 00 00`, `C0 20`: user program 32 changes nothing. Try an
   empty user slot: it must not load the next used slot. Send `B0 79 00`, then
   `C0 00`: CC121 retains bank 1, recalling U01.
5. In MENU > MIDI set MIDI IN to TRACK; set T1 CHANNEL and T2 CHANNEL to 1 using
   PRESETS to pick the row and KNOB 1 to set each value. Leave T3/T4 at 3/4.
   Tap HOME. Repeat bank-1 recalls: both T1/T2 change, T3/T4 stay. Test independent
   channel-3 recall. Change routing after a queued PC in the deterministic host
   test; a human cannot guarantee the pre-main-loop window.
6. Repeat selectors/PC through TRS, including USB CC0 followed by TRS CC32/PC
   on the same channel. On another channel choose another bank: channel 1 keeps
   its prior selectors. Return CC0/32 to zero when finished. Restore disposable
   preset backups if needed; report SHA/profile, transport, bytes and observations.

For automated browser MIDI-to-AudioWorklet testing, send the same raw packets
through the actual browser input path after creating U01/U32 through existing
preset APIs. Compare PCM of both recalls, not only editor state. The deterministic
host case queues bank1/PC31 then bank0 before main-loop service to establish
snapshot ordering; browser timing alone does not reliably force that window.
Malformed storage and missing-engine profiles are host/profile checks, not a
reason to corrupt physical flash.

README/changelog/protocol integration belongs to the coordinator's combined PR:
link this guide and summarize external user-preset recall. This focused capability
does not alter the fork purpose, installation or diagnostic commands. The diagnostic
capability guide needs no new command entry. Browser, target/resource, full-suite
and physical USB/TRS/audio/deadline checks are not performed by this worker.
