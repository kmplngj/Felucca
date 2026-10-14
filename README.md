# Felucca

[![License: GPL-3.0-only](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)

![Felucca 1.0](docs/felucca-1.0.png)

Multi-engine synthesizer firmware for the M-VAVE FM-1, **version 1.6**. Connect the FM-1 to a computer by USB, open the
[web installer](https://hugelton.github.io/Felucca/) in Chrome or Edge and press Install; no extra hardware is needed.
Installing is at your own risk: M-VAVE's updater or the installer's **Return to official V15** takes you back.
Want to look around first? [Try it in your browser](https://hugelton.github.io/Felucca/webapp/try/), no FM-1 needed.

- Install: [web installer](https://hugelton.github.io/Felucca/), or `tools/fm1_install.py` from a terminal
- Edit: [web editor](https://hugelton.github.io/Felucca/webapp/editor/) (developed in [Felucca-WebApp](https://github.com/hugelton/Felucca-WebApp))
- Read: the manual is in the [wiki](https://github.com/hugelton/Felucca/wiki/Home): [Installation](https://github.com/hugelton/Felucca/wiki/Installation) ·
  [Controls](https://github.com/hugelton/Felucca/wiki/Controls) · [Menu](https://github.com/hugelton/Felucca/wiki/Menu) ·
  [Engines](https://github.com/hugelton/Felucca/wiki/Engines) · [Release notes](https://github.com/hugelton/Felucca/wiki/Release-Notes) ·
  [Troubleshooting](https://github.com/hugelton/Felucca/wiki/Troubleshooting)
- Build: [BUILDING.md](BUILDING.md), including [UI font choices](BUILDING.md#build)
- Test a PR on your FM-1: [one-command PR build and install](BUILDING.md#test-a-pull-request-on-hardware), without a local target toolchain; then follow the PR's hardware test instructions (CI does not validate the hardware)
- Download: this fork's [Releases](https://github.com/kmplngj/Felucca/releases) and successful [Actions](https://github.com/kmplngj/Felucca/actions) artifacts; follow the [download and checksum guide](.github/CI.md#downloads-and-checksums)
- Diagnostics: [collect CDC console reports](docs/diagnostics.md) with USB SERIAL on and an explicitly selected port

<a href="https://hugelton.itch.io/felucca"><img src="https://static.itch.io/images/badge-color.svg" alt="Available on itch.io" width="74"></a>

## What it is

Thirteen engines with factory presets, four tracks (8 voices shared), a 64-step sequencer (chords, ties, chance, conditions,
ratchets, nudge, locks, automation, live and step recording), SEQ TOOLS, songs, effects, a MOD matrix, MIDI (USB and TRS,
per-track channels, MIDI LEARN) and USB audio. More: [Features](https://github.com/hugelton/Felucca/wiki/Features).

## New in 1.6

- **Your own UI colours:** COLOR has an eleventh value, CUSTOM, set in the web editor with a live preview on the FM-1
- **The SEQ piano roll follows the play position** when the pattern is longer than one screen
- **Conditional steps** (1:2 … 4:4, FILL), **EUCLID, DOUBLE and HALF**, **a MIDI channel per track**, PHASE FOLD, three more drum kits and humanize in the MOD matrix (1.5.5 and 1.5.6 were never released: 1.6 carries them)
- ⚠ A project with conditional steps does not open on 1.5 or 1.5.1; projects saved by 1.4 or later do not open on 1.1.5.x

All changes and what to know before going back: [Release notes](https://github.com/hugelton/Felucca/wiki/Release-Notes) · [Upgrading from 1.1.5](https://github.com/hugelton/Felucca/wiki/Upgrading-from-1.1.5).

## This fork

The web installer, browser demo, editor and wiki linked above are upstream Hügelton services.
Their hosted versions are updated independently of this fork's builds and releases.
Use this fork's `.fwsc` package with the installer for a fork build; raw `.bin` files and
CI diagnostics are build material. The command-line installer validates package structure
and CRCs before opening MIDI ports; see [package validation and file-error recovery](BUILDING.md#package-validation-and-file-errors).

- **UI fonts:** source builds use M8Stealth57/89 by default. `FELUCCA_FONT` selects
  `m8stealth`, `tamzen` or `inter-tight` at build time; keycaps retain Inter Tight.
  The [controlled font comparison](docs/font-experiment.md) records about 39 KB less
  firmware flash and 1,032 B less POOL RAM for pixel-font decode caches than Inter Tight.
  Physical FM-1 readability and redraw checks remain pending. [Compare real renderer captures](docs/ui-comparison.md).
- **RECENT sounds:** on SAVE > PRESETS, turn KNOB 4 (LIST) past OTHER to RECENT for
  the last eight loaded sounds, newest first. PRESETS browses them; loading from RECENT
  keeps the list order, and SAVE held undoes the audition. Deleted or replaced user
  sounds are skipped. The list is per session, excludes patterns/projects, and is not
  stored in a project or backup.
- **MOMENTARY status:** hold LFO and turn a knob on HOME or a sound/FX page; releasing
  LFO restores the value, or OCT+ while holding keeps it. The header shows MOMENTARY
  TURN, how many values will restore, or KEPT until LFO is released. Messages and
  quick-layer labels take priority.
- **Previous page:** on a family's page, hold OCT− and tap its family button to go
  back one page, wrapping from first to last. It consumes the octave modifier and
  preserves sounding notes' pitch. Press OCT− first for FX, GLO, SCL, EDIT and SEQ;
  their quick layers use OCT− pressed afterward for UNDO. Other-family buttons,
  dialogs and MIDI LEARN retain their normal behavior.

For the new playback transpose, select **SCL > QNT SEQ+T**: melodic sequencer notes
apply TRN before scale snap, without rewriting stored steps. Existing QNT modes keep
their behavior; engines with their own key maps (DRUM and SLICE) are exempt. Older
firmware reads SEQ+T as SEQ. **SEQ TOOLS > EUCLID** exposes HITS, STEPS and ROT and
one undo and a live, reversible preview (OCT+ applies; OCT− cancels); seeded drop
remains future work.

The [emulator partition regression](BUILDING.md#emulator-partition-regression) checks
that equivalent scheduled MIDI/panel input produces exactly the same audio and state
through the browser bridge with different render partitions, without an FM-1.

The [interaction replay guide](docs/interaction-replay.md) shows how to run a
timestamped key, button, encoder and MIDI sequence through the native emulator,
with synchronized WAV audio, LCD frames and a provenance manifest under `build/`.
It works without hardware on Linux/macOS; its audio captures the DAC output after
MASTER and the metronome, and its manifest records the emulator's delivery timing.

The [host stress matrix](tests/stress_matrix.md) replays fixed voice-load, effect and
engine-switch workloads and retains exact PCM, WAVs and health results without an FM-1.

## Support and contributing

Please report what you find in [Issues](https://github.com/hugelton/Felucca/issues) (reproducible bugs, one per issue). Ideas and
requests go to [Discussions](https://github.com/hugelton/Felucca/discussions). Pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
Felucca is GPLv3 and you are free to fork it; before starting yet another fork, please consider whether a PR would do.

## AI disclaimer

Felucca is developed with the assistance of AI coding agents (code, tests, documentation, translation, maintenance). The
design, features, sound design and direction are the maintainer's or the community's, and no generative AI is used for music,
icons or artwork. See [On AI-Assisted Development and Responsibility](https://github.com/hugelton/Felucca/discussions/166).

## Credits and licence

Free software: [GPL-3.0-only](LICENSE), the Hügelton Sample Pack included; the bundled fonts and ported DSP keep their own licences
([LICENSES/](LICENSES/), [LICENSING.md](LICENSING.md)). Thanks to everyone whose work and contributions are in it: [CREDITS.md](CREDITS.md).

M-VAVE and FM-1 are trademarks of their respective owners. Felucca is not affiliated with or endorsed by them.

Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
