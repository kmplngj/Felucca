# Felucca — personal fork

[![License: GPL-3.0-only](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)

![Felucca on the M-VAVE FM-1](docs/felucca-1.0.png)

This is my personal fork of [Hügelton's Felucca](https://github.com/hugelton/Felucca),
multi-engine synthesizer firmware for the **M-VAVE FM-1**. The goal is to bring together
recent features and optimizations from upstream and other forks, collect and integrate
additional synthesis engines, and improve CPU efficiency, RAM use and firmware size.

This is ongoing integration and experimentation. Features are adopted as they are
reviewed and tested; the fork does not automatically include every upstream or fork change.

## What it offers

Felucca combines thirteen engines with factory presets, four tracks sharing eight voices,
a 64-step sequencer, songs, effects, a modulation matrix, USB/TRS MIDI and USB audio.
See the upstream [feature overview](https://github.com/hugelton/Felucca/wiki/Features)
and [manual](https://github.com/hugelton/Felucca/wiki/Home) for the shared instrument.

This fork builds on upstream 1.6.1 with workflow improvements, deferred project autosave,
pixel-font options, performance diagnostics and broader host/emulator regression coverage.
Five portable engines live in the pinned
[Felucca-Engines fork](https://github.com/kmplngj/Felucca-Engines); initial standard/reduced
engine build profiles are implemented. Broader engine selection and startup usage modes
remain planned. The optional second-core worker is beta, off by default, and still needs
real-device reliability validation in this fork. Shared effect-control smoothing
experiments are implemented, with FM-1 listening and timing qualification pending.

[Detailed fork features and testing](docs/fork-features.md) covers controls, defaults,
compatibility limits and build identification.

## Development direction and process

- **Gather and review:** follow upstream and related forks for useful features, engines
  and optimizations, preserving attribution and checking licences and compatibility.
- **Integrate engines:** use the shared engine library where appropriate and build profiles
  to fit the FM-1's limits. Keep sound IDs, saved projects and editor behavior compatible.
- **Measure and optimize:** compare CPU cost, RAM use and firmware size against a baseline,
  while preserving sound, responsive controls and audio deadlines.
- **Validate and document:** use host tests, target builds and emulator replay, then check
  hardware-dependent behavior on an FM-1. Keep planned work and pending device checks explicit.

The [modularity roadmap](docs/modularity.md) and [capacity plan](docs/flash-capacity.md)
track the larger work. The [performance guide](docs/performance.md) explains measurements;
[engine extension contracts](docs/extending.md) describe integration boundaries.
This README summarizes the overall direction and meaningful milestones. Detailed changes
belong in focused guides, issues, PRs and release notes.

## Try, install or build

- **Fork builds:** download this fork's [Releases](https://github.com/kmplngj/Felucca/releases)
  or [CI artifacts](https://github.com/kmplngj/Felucca/actions), following the
  [download and checksum guide](.github/CI.md#downloads-and-checksums).
- **Install:** use the fork's **`.fwsc` package** with the
  [web installer](https://hugelton.github.io/Felucca/) in Chrome or Edge, or follow the
  [command-line instructions](BUILDING.md#install). Raw `.bin` files are build material.
  Installation is at your own risk; M-VAVE's updater or the installer's
  **Return to official V15** restores stock firmware.
- **Explore:** try the [browser demo](https://hugelton.github.io/Felucca/webapp/try/)
  or [web editor](https://hugelton.github.io/Felucca/webapp/editor/).
- **Build and test:** start with [BUILDING.md](BUILDING.md), including
  [engine profiles](BUILDING.md#engine-build-profiles) and
  [testing a PR on hardware](BUILDING.md#test-a-pull-request-on-hardware).
  For device reports, use the [diagnostics guide](docs/diagnostics.md).

```sh
git clone --recurse-submodules https://github.com/kmplngj/Felucca.git
cd Felucca
# Install the prerequisites in BUILDING.md, then:
./build.sh
```

The hosted installer, demo, editor and wiki are **upstream services**, updated independently
of this fork. Use a fork package to install this fork, and its local emulator to test this
checkout. Review [project compatibility](docs/fork-features.md#project-compatibility)
before downgrading.

## Feedback and contributing

Report fork-specific bugs and integration ideas in
[this fork's Issues](https://github.com/kmplngj/Felucca/issues), with the build commit,
reproduction steps and any relevant diagnostics. Shared upstream discussion lives in
[Hügelton's Discussions](https://github.com/hugelton/Felucca/discussions).
See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for development guidance.

Felucca uses AI coding assistance for code, tests, documentation and maintenance.
Design, sound design and direction remain the maintainer's or community's; generative AI
is not used for music, icons or artwork. See the upstream
[AI development statement](https://github.com/hugelton/Felucca/discussions/166).

## Credits and licence

Based on the work of Leo Kuroshita (@kurogedelic), Hügelton Instruments and the
contributors credited in [CREDITS.md](CREDITS.md). Contributions from upstream and
other forks retain their attribution and licences.

Felucca is [GPL-3.0-only](LICENSE), including the Hügelton Sample Pack. Bundled fonts,
ported DSP and the five MIT-licensed engines in `firmware/engines/` retain their own
licences; see [LICENSING.md](LICENSING.md) and [LICENSES/](LICENSES/).
M-VAVE and FM-1 are trademarks of their owners; this project is not affiliated with them.

Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
