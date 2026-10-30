<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI portamento and legato switches (#798)

CC65 (portamento) and CC68 (legato) use the existing voice paths. Values 0..63
mean OFF/normal; 64..127 mean ON/legato. Until either switch is received, the
part's authored GLD and VCE behavior is unchanged. The switches are live state,
not parameters: they do not alter project/preset bytes, report a parameter edit,
record motion, or add a synthesis path.

CC65 OFF suppresses GLD and ends an in-progress pitch glide immediately, without
retriggering the envelope or changing the mono stack. ON permits the authored
GLD time; zero still means no glide. CC5 retains its existing 0..127 GLD parameter
mapping, edit and motion-capture behavior. CC5 while OFF still edits/remembers the
time; ON uses that latest value. CC65 works with existing pitched POLY, MONO,
LEG and UNI glide paths. One-shot/drum engines ignore its pitch effect.
Sequencer slide retains its existing independent request and default slide time.

CC68 overrides VCE only when the authored mode is MONO or LEG on a pitched
engine. OFF uses MONO's attack retrigger on each winning note-on; ON uses LEG's
connected-note envelope, retriggering the first note of a new phrase. Releasing
the winning note falls back to another held note without an attack, as before
in both mono modes. Releasing either key first empties the same stack correctly.
A held-note switch changes later transitions without immediately retriggering or
reallocating voices. POLY, UNI, one-shot and drum allocation remain unchanged;
CC68 is inert in those modes. The received state can become effective if VCE is
subsequently edited to MONO/LEG, until reset or sound change.

USB and TRS share channel state. Each part has one effective switch state;
the latest applicable channel event or note-on wins, as for existing channel
expression. Receiving a switch binds it to the current routed destinations plus
parts retaining notes owned by that channel. Every destination in a layer gets
the event. Later notes on a bound destination reapply that channel's state.
Releases always follow captured note owners, including sustain, repeated notes,
selection changes and route edits. A newly selected or newly routed destination
has no inherited switch binding until a switch is sent there.

Reset behavior:

| Event | Result |
| --- | --- |
| CC121 Reset All Controllers | Both switches OFF/normal for current and retained destinations; preserve CC5 GLD time; release sustain as usual |
| CC123 All Notes Off | Release normally, honoring sustain; keep switches |
| CC120 All Sound Off | Silence destinations and discard their overlays/bindings, restoring authored behavior |
| Part panic or preset/sound install with panic | Discard that part's overlays and all channel bindings to it; a later note cannot restore an old sound's switches/time |
| Lost-input queue recovery | Panic every part and clear channel state; return to authored behavior |
| TRACK route edits / entering or leaving TRACK | Release removed destinations and discard their bindings; preserve still-routed bindings; new destinations use authored behavior |
| Entering a channel block | Forget excluded channels; heard channels retain their original note owners under the legacy SEL-to-block rule |
| Entering SEL / changing selected part | Existing part state remains; new destinations receive switches only after another controller event |
| Boot/project load | Authored defaults; root integration resets channel state and panics parts on project load |

CC65/68 are reserved fixed controllers, including when older MIDI LEARN settings
contain those CCs. Switch reception takes precedence over those old assignments.
No controller setting is persisted. Saving a preset/project saves the authored
VCE/GLD values, including any GLD edit previously made by CC5.

## Focused author checks

From this checkout, with the coordinator-prepared Engines submodule and generated
headers:

```sh
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi_glide_test tests/midi_glide_test.c -lm
build/midi_glide_test
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/midi_control_798_test tests/midi_control_test.c -lm
build/midi_control_798_test
```

The new test compiles actual queues, routing, sound install, ownership, voice
allocation and renderer. It checks 0/63/64/127, zero/max CC5, repeated switch values,
supported/unsupported modes, envelope age/stage preservation, rendered pitch
movement, both release orders, sustain, repeated notes, CC121/120, panic,
route removal, layers, sound loads, overflow and USB/TRS shared state. The older
MIDI control fixture covers the pre-existing CC map and controller/clock paths.
The coordinator registers the new fixture in the integrated runner. Both commands
passed in the issue worktree. The new fixture also passed with
`-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all` (and the same include
paths/`-lm`). No sanitizer diagnostics were emitted. Target, full-suite, browser,
physical transport, saved-project reset integration and hardware checks are pending.

Source accounting adds two bytes per part and four bytes per channel (72 bytes
with four parts and sixteen channels, before final target layout verification).
Each positive note-on adds bounded destination-state copying. Switch events visit
at most four parts; CC65 OFF visits at most eight voices per part. Rendering reads
the effective glide time once per control block, with no new per-sample controller
polling. These are bounds, not measured event cycles or deadline claims. Target
app/RAM/POOL/RAMTEXT/NOINIT/stack deltas and matched inactive/active traffic timing
remain coordinator checks.

## Browser and FM-1 MIDI/audio procedure (pending)

Use the exact integrated candidate, not the hosted release. The coordinator builds
a fresh emulator and captures actual browser MIDI-to-AudioWorklet PCM. Hardware
qualification later needs the same candidate's `.fwsc`, USB MIDI and TRS source,
stereo recording/headphones and a stopped transport. No device flash or hardware
observation was performed for this issue commit.

The following setup uses the editor protocol (decimal command/parameter IDs), so
no unverified panel navigation is required. `sx(cmd,...args)` sends
`F0 7D 46 4C cmd args F7`; wait for each reply. `v14(v)` is
`[(v+8192)&127, (v+8192)>>7]`. `param(track,id,v)` sends
`sx(31,track,id,...v14(v))`. `cc(n,v)` is `[0xB0,n,v]`,
`on(n)` is `[0x90,n,100]`, `off(n)` is `[0x80,n,0]`.
All notes below use channel 1, C4=60 and E4=64. Use 250 ms between MIDI steps
unless a different interval is stated; retain PCM and candidate identity.

1. Stop the transport. Set global routing CH1-4:
   `sx(3,1,14,...v14(0))`. Select part 1 with `sx(27,0)` and load ANALOG
   factory preset 0 with `sx(8,0,0)`. Set part 1 VCE MONO `param(0,37,1)`,
   GLD 100 `param(0,38,100)`, glide TIME `param(0,41,1)`, attack 80
   `param(0,1,80)`, sustain 100 `param(0,3,100)`, release 40
   `param(0,4,40)`, PRIO LAST `param(0,42,0)`, ARP OFF
   `param(0,17,0)`, and quantize OFF `param(0,27,0)`. Turn sound effects off
   with `param(0,33,0), param(0,34,0), param(0,35,0), param(0,36,0)`
   so stereo layer captures can distinguish each part.
2. Detached baseline: `cc(65,0), cc(68,0), on(60)`, wait 500 ms,
   `on(64), off(64), off(60)`. E4 should immediately take pitch and retrigger
   attack; releasing E4 returns to C4; final release ends the phrase. Repeat
   releasing C4 first; E4 stays until released. Save PCM for both.
3. Connected phrase: `cc(68,64), on(60)`, wait 500 ms, `on(64), off(64),
   off(60)`. E4 pitch changes immediately (CC65 remains OFF) and preserves the
   envelope instead of a new attack. Repeat `cc(68,127)` and the older-first
   release. Compare the attack envelope against step 2.
4. Glide phrase: `cc(65,64), on(60)`, wait 500 ms, `on(64)`. Record at least
   500 ms; the pitch trajectory approaches E4 rather than jumping. While held,
   send `cc(65,63)`; the remainder lands immediately without a fresh attack.
   Release both notes. Repeat `cc(65,127)` and `cc(65,0)` to check both edges.
5. Remembered time: `cc(65,0), cc(5,127), on(60)`, wait 500 ms, `on(64)`;
   no glide. Release both; `cc(65,127)` and repeat should glide using GLD 127.
   Repeat with `cc(5,0)`; no glide even when ON. Read GLD using `sx(31,0,38)`
   to confirm actual authored parameter changes. Set GLD 100 again.
6. Sustain/repeat/reset: `cc(68,127), cc(65,127), on(60), cc(64,127),
   off(60), on(64), on(64), off(64), cc(121,0)`. Sustain releases and the next
   C4/E4 overlap behaves MONO/no glide, while GLD still reads 100. Send
   `cc(120,0)`; there must be no stuck notes. This panic returns authored MONO
   and GLD 100; explicitly send switches again for subsequent comparisons.
7. Layer: select part 2 `sx(27,1)`, load the same factory sound, apply the same
   parameters with `track=1`. Set PAN left/right with `param(0,39,-64)` and
   `param(1,39,63)`. Set routing TRACK `sx(3,1,14,...v14(5))` and assign both
   tracks channel 1 using `sx(73,26,...v14(0))` and
   `sx(73,27,...v14(0))` (MENU channel values are zero based). Repeat steps
   2–6. Capture each stereo side: both should have detached/legato/glide changes.
   While held, change part 2 to channel 2 with `sx(73,27,...v14(1))`;
   its held note releases, part 1 remains owned and releases normally.
8. Unsupported allocation: set VCE POLY `param(0,37,0)`, send `cc(68,127)`
   then overlapping notes; they remain polyphonic. Repeat VCE UNI value 3;
   its authored unison remains. Select DRUM via `sx(27,0), sx(8,10,0)`;
   CC65/68 must not turn its independent hits into a mono stack. Reload the
   ANALOG sound to prove old overrides are gone, then reapply the mono setup.
9. Repeat switches over USB and TRS on physical FM-1, including USB ON then TRS
   OFF on the same channel. Check shared state, retained-note cleanup and loaded
   audio deadlines using the existing diagnostics procedure. This establishes
   physical transport/audio behavior only when performed and recorded.

Project-load reset must also be exercised on the integrated candidate, because
that shared reset hook belongs to the coordinator. Browser evidence cannot
qualify physical MIDI transport, device audio deadlines or USB streaming.

Documentation assessment: the coordinator should add a short README MIDI-in
mention, a changelog capability entry and the CC65/68 live-state semantics to
`web/EDITOR_PROTOCOL.md`, linking this guide. No new diagnostic command or field
is introduced; the existing performance/diagnostics guides cover resource and
hardware checks. These shared documentation edits are intentionally centralized
for the batch.
