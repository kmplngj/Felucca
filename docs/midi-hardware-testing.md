<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Run the MIDI performance scenarios on an FM-1

Use the standard-profile firmware from [PR803](https://github.com/kmplngj/Felucca/pull/803),
validated firmware head `bc395cc967361b1b82c9138fa7fa67f905dfda2d`.
The Python sender runs on the computer physically connected to the device. A
cloud workspace without USB/MIDI forwarding cannot reach a locally plugged-in FM-1.
The sender needs no new firmware API and uses ordinary MIDI channel messages.

## Prepare once

1. Install that candidate using the PR's hardware instructions if it is not
   already installed. Record the package/commit. Back up, load a disposable
   project, stop the transport and start with 2ND CORE OFF. Testing does not
   require reinstalling between cases. The sender never installs firmware or
   saves a user-preset slot, but does change current sound/controller parameters.
2. Connect USB directly, or connect a computer MIDI interface to the FM-1's
   correctly wired TRS MIDI input. Connect headphones or stereo line outputs
   to an audio interface. USB MIDI is control traffic; sending MIDI does not
   provide an audio recording. Optionally record the FM-1's USB audio with your
   existing recording application to test that transport as well.
3. ALGORITHM selects a part, PRESETS its sound. Give T1 an ANALOG sound and T2
   a clearly contrasting sustained pitched sound. Hold/release HOME for MENU;
   ALGORITHM selects MIDI, PRESETS selects MIDI IN, KNOB1 sets TRACK. On T1/T2
   CHANNEL rows, use KNOB1 to assign channel1 to both; keep T3/T4 on other channels.
   Close with HOME. Tap HOME to MIXER; ALGORITHM selects T1/T2, KNOB1 sets LEVEL100,
   KNOB2 sets T1 PAN left and T2 PAN right. Set ARP off and sound effects dry.
4. For articulation, use an audible attack and a sustained sound. For precise
   tuning, use a stable, unmodulated test patch, global TUNE0, and listen to or
   record T1 alone; a modulated lead is unsuitable for precision measurement.
   Before the `banks` case, save a recognizable disposable sound in U01 using
   the panel procedure in [the bank guide](midi-801.md). Empty U01 cannot prove recall.

## Python runner

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). From a checkout
containing the sender, on the device-connected macOS/Windows/Linux computer:

```sh
uv run --locked --group midi tools/fm1_midi_performance.py --list
# Copy the exact output name printed above, including any suffix.
uv run --locked --group midi tools/fm1_midi_performance.py --case mix --port "EXACT MIDI OUTPUT NAME" --firmware-label bc395cc9
```

Cases: `nrpn`, `mix`, `keys`, `velocity`, `articulation`, `tuning`, `soft`, `banks`.
Run one at a time while listening/recording and observing the panel. Each sequence
prints phase labels and writes a timestamped message log in `build/midi-hardware/`.
`--report path.json` selects the log location. `--channel 2` etc. changes all message
channels; match the device setup. Omitting `--port` prints the complete dry-run plan
without opening a MIDI port. Port selection is exact, with no automatic fallback.

| Case | Expected physical result |
| --- | --- |
| nrpn | Held note mutes and returns; ANALOG cutoff changes darkness/brightness |
| mix | CC20 positions0/64/127 give T1 only/both/T2 only |
| keys | Note59 sounds T1;60 sounds T2; a held59 releases after its range is edited |
| velocity | Velocity79 selects T1;80/100 select T2; Soft Pedal keeps raw100 on T2 |
| articulation | Compare retriggered MONO, connected LEGATO, then audible glide on C4/E4 overlap |
| tuning | Held A4 changes440→452.893→880→440Hz with a stable440Hz starting patch |
| soft | Soft100 should resemble normal50 and be quieter than normal100; soft1 remains positive |
| banks | Factory PC2, U01 recall, then unsupported bank2 leaves U01 unchanged |

Both normal completion and Ctrl-C attempt All Sound Off and a known baseline:
pedals off, neutral registered tuning, bank0, full T1/T2 zones, pair assignment off,
LEVEL100 and expression127. This does **not** restore the original project or
sound: cutoff, VCE/GLD edits and the last recalled sound may remain. Reload your
original project when finished. A disconnected cable can prevent cleanup; reconnect
and send a fresh case baseline or use the device's normal panic procedure.

`sent` means that the host MIDI API accepted the messages, not a hardware pass.
The script does not read back parameters, detect the installed firmware, record
audio or verify audible behavior. `--firmware-label` records your supplied identity
without verifying it. Retain the JSON, stereo recording and pass/fail observations
for each phase. Repeat through USB and TRS separately, then under the PR's loaded
audio/second-core procedure; one transport's result does not establish the other.

## Browser or MIDI-player alternative

Export exactly the same timed channel messages as a standard MIDI file:

```sh
uv run --locked --group midi tools/fm1_midi_performance.py --case mix --export-midi build/midi-hardware/mix.mid
```

Play it through a MIDI application that can send a file to a selected physical
MIDI output. Disable tempo changes, looping, transpose and channel remapping.
The file contains phase markers and cleanup. Stop playback with All Notes/Sound
Off if the player does not play the cleanup tail. This does not use a browser's
internal synthesizer: choose the actual FM-1 or connected MIDI interface as output.

A browser MIDI sender also works in Chrome/Edge over HTTPS or localhost with
Web MIDI permission. These CC/NRPN/RPN messages do not require SysEx permission.
For a quick pair-mix check after the common setup, send the hex packets from
[the configuration guide](midi-performance.md#configuration-over-midi), followed
by `90 3C 64`, `B0 14 00`, `B0 14 40`, `B0 14 7F`, and `80 3C 00`, pausing between
mix values. Finish by disabling the pair assignment with
`B0 63 62 B0 62 00 B0 06 00`. The hosted
emulator's MIDI input plays its simulated instrument; it does not send these
commands to physical hardware.

## Validation status

Hardware acceptance is pending. Sender tests use an injected MIDI sink/clock and
round-trip all eight MIDI files, including channel16, scheduling and interruption/
disconnect cleanup. The firmware itself has separate native/Wasm/browser evidence
in PR803. No new firmware behavior or device diagnostic command is introduced.
