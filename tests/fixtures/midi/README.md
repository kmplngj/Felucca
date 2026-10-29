<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Open MIDI music for FM-1 tests

Three unmodified, original CC0 MIDI assets published on OpenGameArt in 2025–2026.
The music remains **CC0-1.0**, separate from the GPL test documentation and tools.
See the [license text](../../../LICENSES/CC0-1.0.txt) and
[manifest](manifest.json) for authors, source/download URLs, publication evidence,
retrieval dates, SHA-256 hashes and measured file properties. Publication dates
do not establish when a piece was composed or first released elsewhere.

| MIDI / creator | OGA publication | Style and suggested use | File properties |
| --- | --- | --- | --- |
| [Empacotatron](https://opengameart.org/content/empacotatron) / Fupi | 2025-09-28 | Energetic techno/arcade melody; start here for repeated attacks and chords. This MIDI contains the main melody, not the complete audio arrangement. | 80.001 s; encoded tempo 84 BPM; channel 1; peak 4 held notes |
| [Elytra](https://opengameart.org/content/elytra) / continuum.mid | 2025-05-24 | Layered electronic/video-game music; sustained parts and allocation stress. Only the MIDI is included, without the source preview's soundfont. | 242 s; 120 BPM; note channels 1, 2, 5, 8, 10; peak 13 held notes |
| [Xenon Phoenix](https://opengameart.org/content/xenon-phoenix) / continuum.mid | 2026-10-10 | Energetic electro-rock inspired by Doom WAD music; rhythmic multitimbral and drum workloads. The separate audio arrangement credits Bloo too. | 124.8 s; 100 BPM; note channels 1, 2, 3, 4, 10; peak 11 held notes |

The peaks count overlapping MIDI note-on/off pairs, not FM-1 voice usage; sustain,
release tails and engine behavior affect load. All three parse with mido 1.3.3 and finish
with matched note releases. None contains SysEx. These are musical workloads,
not yet automated regression scenarios or hardware-qualified arrangements.

## Play on an FM-1

Use a DAW/sequencer that imports Standard MIDI Files and sends MIDI to the FM-1.
Felucca has four parts sharing eight voices; it is not a General MIDI sound bank.
Keep the original files unchanged and record any DAW routing, filtering or edits
alongside the tested firmware revision and project/preset settings.

1. Start with transport stopped and a backed-up, disposable working project.
   Hold HOME for more than 0.7 seconds and release in MENU. Select MIDI with
   ALGORITHM, MIDI IN with PRESETS, choose CH1–4 with OCT−/OCT+, then tap HOME.
   On HOME select T1 with ALGORITHM. Tap SAVE twice to reach PRESETS; use KNOB 2
   to select FM6 and KNOB 1 to choose a factory sound, then HOME. Record the sound.
   Use a recorded POLY sound/mode for the chord test, with CHORD and ARP disabled;
   those settings can otherwise expand or rearrange incoming notes. QNT governs
   the local keyboard path and is not a filter for these incoming MIDI notes.
2. Import `empacotatron.mid` into the DAW, retain its tempo map, and route only
   channel 1 to the FM-1 USB MIDI output. For this first pass send notes and their
   velocities only; disable automatic program/bank selection, controllers,
   SysEx and transport/clock transmission. Leave Felucca's internal transport
   stopped. Play once, allow release tails to end, then repeat. Check for missed
   attacks, stuck notes, dropouts and resets; record audio at fixed levels.
3. For Elytra or Xenon Phoenix, choose and document at most four source parts,
   remap their channels to 1–4, and choose each Felucca sound explicitly. GM
   program changes select Felucca sound slots rather than equivalent GM sounds;
   filter them and bank changes. Start with notes only, then enable specific
   controllers deliberately in a separate recorded run.
4. Channel 10 percussion is ignored by CH1–4 routing. Remap it to a part using
   DRUM, or use TRACK routing with that part assigned channel 10. DRUM has
   GM-note mappings but is not the source soundfont. Including drums means
   choosing at most three other parts. Full Elytra/Xenon arrangements exceed
   eight held notes even before release tails; reduce them for a listening test
   or label the unchanged density as intentional allocation stress. Actual voice
   stealing depends on the chosen mapping and engines; several GM drum notes
   can share a single DRUM lane rather than occupy separate sounding voices.
5. After playback, release all notes using the DAW's panic function if needed.
   Restore the original project/settings. Repeat over a physical TRS connection
   as a separate transport test. USB playback cannot establish TRS behavior.

For measurements use the existing [diagnostics](../../../docs/diagnostics.md) and
[performance](../../../docs/performance.md) procedures with the same arrangement,
sound settings and routing before/after a change. Listening, USB/TRS timing and
target deadline qualification remain pending until run on real hardware.

## Repository integration

These three files total 40,653 bytes. Vendoring keeps offline tests and source
archives reproducible without another submodule checkout or unrelated audio
assets. They are host-side test inputs and are not compiled into firmware.
Updates should explicitly review provenance and replace the manifest hashes.

`tools/fm1_replay.py` accepts timestamped JSON scenarios, not `.mid` files; these
files cannot be passed directly to it. A future adapter can use the existing
locked `midi` dependency group and preserve the MIDI tempo map, select/remap
parts, and record its transformations. Existing replay limits (60 seconds and
4,096 events) require bounded excerpts; conversion and automated replay are not
implemented by this asset addition.

Other verified sources, not bundled: [Warning! by davidpanda](https://davidpanda.itch.io/warning/devlog/967174/launched-into-public-domain-cc0-chiptune-music)
(CC0, 140 BPM chiptune; MIDI published June 2025) and
[HydroGene's 16-bit RPG collection](https://hydrogene.itch.io/high-quality-16-bit-music)
(CC0; MIDI archive published October 2025, composition dates unverified).

Validation for this addition: parsed all files using the locked mido 1.3.3,
checked channel/event statistics and balanced note releases, and verified hashes
and byte sizes. No firmware change, build or hardware playback is claimed.
Documentation assessment: the root README and changelog need no entry for this
small fixture collection; diagnostic commands and their guides are unchanged.
