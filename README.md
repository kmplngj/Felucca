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

The standard profile combines thirteen engines with factory presets, four tracks sharing eight voices,
a 64-step sequencer, songs, effects, a modulation matrix, USB/TRS MIDI and USB audio.
Eight is the shared allocation pool; deadline headroom depends on the sound and USB load
([measured PHYS example](docs/audio-deadline-investigation-2026-10-21.md)).
The [fork feature guide](docs/fork-features.md) covers controls, defaults,
compatibility limits and build identification. The
[upstream manual](https://github.com/hugelton/Felucca/wiki/Home) documents the shared
instrument; some details may differ in this fork.

This fork builds on upstream 1.6.1 with workflow improvements, deferred project autosave,
pixel-font options, performance diagnostics and broader host/emulator regression coverage.
The default M8Stealth display uses native pixel lettering for both regular text
and control/status badges, with stable number/unit placement
([LCD typography](docs/lcd-typography.md)).
The [diagnostic capability overview](docs/diagnostics.md#diagnostic-capabilities) distinguishes
the normal USB console and read-only host collector from opt-in assertion, crash-register,
arithmetic-reproducer and screenshot builds, with their activation and evidence limits.
An opt-in [device-screen capture diagnostic](docs/screen-capture.md) exports
firmware-rendered static HOME/menu pixels with device build provenance over USB SERIAL.
Its explicit `--wake` option silently wakes and holds the current view for capture.
It is disabled in normal builds and does not measure physical LCD colours or backlight glow.
[MIDI timing and DSP hardening](docs/midi-dsp-reliability.md) retains external-clock
phase, timestamps TRS input during rendering, and guards invalid tempo.
[Device results](docs/midi-dsp-device-results-2026-10-21.md) qualify USB pulse-count
phase with CPU2 OFF; physical TRS and CPU2 ON clock-phase checks remain pending.
Five portable engines live in the pinned
[Felucca-Engines fork](https://github.com/kmplngj/Felucca-Engines); initial standard/reduced
engine build profiles are implemented. Broader engine selection and startup usage modes
remain planned. The optional second-core worker is beta and off by default.
[Bounded FM-1 comparisons](docs/cpu2-idle-polling.md) cover an idle-poll mitigation
for observed BAD_JOB failures on one unit; broader unit, engine/profile and TRS
qualification remains pending. After a recorded worker failure it is held off
across resets until the player retries it ([guide](docs/fork-features.md#retained-exclusion-after-a-failed-worker-410)). Shared effect-control smoothing
experiments are implemented, with FM-1 listening and timing qualification pending.

The opt-in [MACRO/Braids profile](docs/macro-engine.md) adds a fourteenth engine with
48 oscillator models and 51 factory sounds while keeping every standard engine. WAVE,
FOLD and FBFM support eight voices; the 45 added models use one voice per part.
This firmware-native integration is experimental and
requires `FELUCCA_PROFILE=macro`; the normal build and hosted demo do not include it.
The [FM-1 test procedure](docs/macro-hardware-test.md) includes reproducible projects
and songs. The [device results record](docs/macro-device-results.md) separates
user-reported model/control and held-note checks from pending persistence, transport and timing
qualification under [#27](https://github.com/kmplngj/Felucca/issues/27).
Early USB rescue and explicit update-loader compatibility are implemented;
the [recovery guide](docs/usb-rescue.md) describes OCT− entry, existing installers
and the combined FM-1 checks that remain pending.

## Development direction and process

- **Gather and review:** follow upstream and related forks for useful features, engines
  and optimizations, preserving attribution and checking licences and compatibility.
  The [firmware watch](docs/firmware-watch.md) keeps the source registry, commit reviews
  and historical backfill in a queryable repository ledger.
  The [FM Lab adoption review](docs/fm-lab-adoption-2026-10-21.md) plans optional FM6
  sound-design features, original voice content and exact optimization experiments.
- **Integrate engines:** use the shared engine library where appropriate and build profiles
  to fit the FM-1's limits. Keep sound IDs, saved projects and editor behavior compatible.
- **Measure and optimize:** compare CPU cost, RAM use and firmware size against a baseline,
  while preserving sound, responsive controls and audio deadlines.
- **Validate and document:** use host tests, target builds and emulator replay, then check
  hardware-dependent behavior on an FM-1. Keep planned work and pending device checks explicit.

The [engine collection plan](docs/modularity.md#gpl-collection-and-mixed-engine-builds--agreed-2026-10-16)
describes selecting MIT, GPL and native engines in one firmware build. The GPL collection
is initialized; WAVE implementation and mixed-build integration remain pending.

The [modularity roadmap](docs/modularity.md) and [capacity plan](docs/flash-capacity.md)
track the larger work. The [performance guide](docs/performance.md) explains measurements;
[engine extension contracts](docs/extending.md) describe integration boundaries.
The [stored-format inventory](docs/legacy-formats.md) documents the first recovery stage:
a read-only raw export, with historical firmware readers retained while browser migration is pending.
This README summarizes the overall direction and meaningful milestones. The
[changelog](docs/changelog.md) gives a curated overview of additions, fixes, changes
and optimizations. Detailed controls and evidence belong in focused guides, issues,
PRs and release notes.

## Try, install or build

- **Fork builds:** download this fork's [Releases](https://github.com/kmplngj/Felucca/releases)
  or [CI artifacts](https://github.com/kmplngj/Felucca/actions), following the
  [download and checksum guide](.github/CI.md#downloads-and-checksums).
- **Install:** use the fork's **`.fwsc` package** with the
  [fork web installer](https://kmplngj.github.io/Felucca/webapp/installer/) in Chrome or Edge, or follow the
  [command-line instructions](BUILDING.md#install). Raw `.bin` files are build material.
  Installation is at your own risk; M-VAVE's updater or the installer's
  **Return to official V15** restores stock firmware.
- **Explore:** try the [fork browser demo](https://kmplngj.github.io/Felucca/webapp/try/)
  or [fork web editor](https://kmplngj.github.io/Felucca/webapp/editor/).
- **Build and test:** start with [BUILDING.md](BUILDING.md), including
  [engine profiles](BUILDING.md#engine-build-profiles) and
  [testing a PR on hardware](BUILDING.md#test-a-pull-request-on-hardware).
  For device reports, use the [diagnostics guide](docs/diagnostics.md).

```sh
git clone --recurse-submodules https://github.com/kmplngj/Felucca.git
cd Felucca
# Install the prerequisites in BUILDING.md (macOS: brew install uv), then:
uv run --locked --group build ./build.sh
```

The command-line PR testing helper uses the Python USB-MIDI updater with locked
dependencies: `uv run --locked --group midi tools/fm1_pr.py NUMBER`. See
[its setup and usage](BUILDING.md#test-a-pull-request-on-hardware).

The fork site follows successful full builds of `main`: the demo and installer use
that firmware revision, and the editor comes from a pinned revision of
[our WebApp fork](https://github.com/kmplngj/Felucca-WebApp). Check the site's
[source revisions](https://kmplngj.github.io/Felucca/sources.html) before testing;
the live site can lag behind this checkout.
See [site deployment](.github/CI.md#fork-site-deployment) and review
[project compatibility](docs/fork-features.md#project-compatibility) before downgrading.

## Development status

For now, I manage this fork's development and issues on my own, following my own
priorities and wishes. This could change once the larger tasks I want to complete
are done, with more room for community input and contributions.

This fork uses AI coding assistance for code, tests, documentation and maintenance.
Design, sound design and direction remain mine; generative AI is not used for music,
icons or artwork.

## Credits and licence

Based on the work of Leo Kuroshita (@kurogedelic), Hügelton Instruments and the
contributors credited in [CREDITS.md](CREDITS.md). Contributions from upstream and
other forks retain their attribution and licences.

Felucca is [GPL-3.0-only](LICENSE), including the Hügelton Sample Pack. Bundled fonts,
ported DSP and the five MIT-licensed engines in `firmware/engines/` retain their own
licences; see [LICENSING.md](LICENSING.md) and [LICENSES/](LICENSES/).
M-VAVE and FM-1 are trademarks of their owners; this project is not affiliated with them.

Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
