<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI Soft Pedal (CC67)

CC67 is a session controller switch for MIDI input, shared by USB and TRS on
one MIDI channel. Values 0..63 turn it OFF; 64..127 turn it ON. OFF is the
power-on default and preserves the previous note-input path exactly. CC67 is
reserved from MIDI Learn, including previously stored assignments.

When ON, each new positive velocity is replaced by `(velocity + 1) >> 1`:
1 becomes 1, 2 becomes 1, 63 becomes 32, 64 becomes 32, 126 becomes 63 and
127 becomes 64. The integer map is monotonic and never turns a positive attack
into a release. Note On velocity zero remains a release. Repeating a CC67 value
has no additional effect. There is no response table, sound parameter edit,
extra voice, persistent setting, flash operation or per-sample processing.

Destination selection uses the original source note and velocity, including
key and velocity zones. Each selected part receives the softened velocity once,
then its existing `input_on` / recording / matrix velocity / engine response
runs normally. The future response-curve feature (#123) must keep raw articulation
selection ahead of response processing and define curve/soft composition at this
same stage. No new response curve is introduced here. Existing ARP input stores
pitches through `arp_add` without input velocity; CC67 does not change that ARP
behavior. Local panel notes and sequencer playback are not separately softened;
recording a direct MIDI attack records the softened performance velocity.

Held voices retain their original velocity, pitch and ownership when the pedal
moves. A repeated pitch follows the existing replacement policy. Every part of a
shared-channel layer receives the same once-scaled input velocity; each engine
can respond differently. USB CC67 affects subsequent TRS notes on the same channel
and vice versa. Other channels keep their own switch states, even when routed to
the same part. Note release follows captured owners after controller or zone edits.

CC64 sustain is independent. CC120 All Sound Off and CC123 All Notes Off preserve
the soft switch, as does a sound/preset/engine-change panic. CC121 resets it OFF
and retains the existing sustain-release behavior. A routing change clears the
switch for channels that are no longer heard, together with their other controller
state. A still-heard channel retains it across routing, selected-part and layer
changes. Lost input/queue overflow clears all channel state, including CC67.
Project replacement must call `midi_soft_reset()` to start OFF; the batch coordinator
wires that project lifecycle hook. Neither projects nor presets store this state.

This is velocity response, not piano una-corda modeling. Engines using the common
amplitude response primarily change loudness. DIGITAL also changes FM modulation
index with velocity; FM6 uses the patch's operator velocity sensitivities and can
change brightness as well as level. DRUM changes hit level and its velocity-based
accent. A patch's modulation matrix can modify or reverse the audible response,
so use a known velocity-responsive patch and neutral matrix for comparison.

## Focused host validation

Rebuild against generated headers and the pinned Engines submodule:

```sh
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi_soft_test tests/midi_soft_test.c -lm
build/midi_soft_test
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi_control_test tests/midi_control_test.c -lm
build/midi_control_test
```

The focused test exercises all 128 CC67 values against all 128 velocities through
the production event queue and voice path. It checks zero release, mapping bounds,
thresholds, repeated CCs, USB/TRS sharing, channel independence, held/repeated
notes, sustain, layers, CC120/121/123, preset panic, overflow, routing and the project
reset helper. A matrix VEL test pins soft-before-existing-response ordering.
Integrated zone selection and actual project-load hook checks belong to the batch.

The implementation adds one byte field to each of 16 channel records; padding and
final target RAM/app/stack deltas require the integrated target build. OFF adds a
flag check per selected positive note destination; ON adds an unsigned add and
shift. CC67 takes one bounded channel store, not a track scan. These are source
operation counts, not measured target cycles or interrupt-load claims. Target
resource measurements, browser PCM and physical USB/TRS tests remain pending.

## Browser MIDI/audio procedure

Use the exact candidate emulator build, transport stopped, T1 selected, CH1-4
routing, a known velocity-responsive sustained patch, neutral matrix, ARP OFF
and a fixed master level. Capture actual PCM after MIDI traverses AudioWorklet
input. The following are raw hexadecimal channel-1 messages, with a 300 ms note
and at least 500 ms release gap (extend for the selected patch's release):

1. `B0 79 00`, `B0 40 00`, `B0 43 00`, `90 3C 7F`, `80 3C 00`.
   Capture the normal attack and tail.
2. `B0 43 40`, `90 3C 7F`, `80 3C 00`. New attack is velocity 64.
   Compare it with a reference after `B0 43 00`, `90 3C 40`, `80 3C 00`.
   With reproducible/reset patch state those inputs should produce matching PCM.
3. `B0 43 3F`, `90 3C 7F`, `80 3C 00`: normal threshold; then
   `B0 43 7F`, `90 3C 01`, `80 3C 00`: nonzero velocity-1 attack.
   All samples must be finite; allow a quiet but nonzero attack.
4. `B0 43 00`, `90 3C 65`, wait 200 ms, `B0 43 7F`, wait 200 ms,
   `90 40 65`: held C is unchanged; new E uses velocity 51. Send
   `80 3C 00`, `80 40 00` to finish.
5. `B0 40 7F`, `90 3C 7F`, `90 3C 00`, `B0 43 00`: sustain holds
   the soft note despite the soft switch change. `B0 40 00` releases it.
6. Finish with `B0 79 00`, `B0 7B 00`, `B0 40 00`, `B0 43 00` and
   wait for the release tail. Require quiet PCM after the patch's normal tail.

A static threshold/mapping test does not establish browser PCM behavior. Seed or
reset deterministic sound state for exact PCM comparisons; otherwise compare
attack energy using repeated strikes and record patch/engine identity.

## Pending FM-1 checks and documentation assessment

The coordinator supplies the exact candidate `.fwsc`, source commit and installation
procedure. After installation, start with stopped transport and a known sustained
velocity-responsive T1 patch with ARP OFF and neutral matrix. Select CH1-4 via the
verified MENU > MIDI > MIDI IN route. Connect MIDI source channel 1 and monitor
headphones/audio recording. Perform the browser sequences over USB, then TRS, then
USB controller with TRS notes and TRS controller with USB notes. Confirm softer new
attacks, held-note stability, independent sustain and a quiet final release.
Repeat with shared-channel layer routing, a preset change, project replacement
(expected OFF), and a route that excludes/re-enables channel 1 (expected OFF).
Record artifact/commit, engine/patch, transport, host, route and observed result.
Loaded audio deadline measurements and physical transport remain pending.

README's existing MIDI/layer overview remains accurate; no overview milestone edit
is needed in this isolated issue. The integrated changelog should add CC67 soft
response with hardware acceptance pending and link this guide. No diagnostic
commands, protocol parameter IDs or saved layouts change. The coordinator owns
shared changelog/protocol edits and test-runner registration.
