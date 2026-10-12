<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Firmware CI and releases

`CI` runs on pull requests, pushes to `main` and manual dispatch. Its reusable
`Firmware validation` job runs natively on Ubuntu 24.04 x86-64 with Clang for the
host harness and JieLi Clang 4.0.1 for pi32v2. No repository secrets are required.
Build jobs have `contents: read`, checkout does not retain credentials, Actions
are pinned to commit SHAs, jobs time out after 60 minutes, and superseded PR runs
are canceled. Fork PRs use `pull_request`; there is no `pull_request_target` job.
Repository Actions policy may require maintainer approval for first-time fork
contributors. This change does not alter branch protection or repository settings.

## Required checks and evidence

| Check | Required evidence |
| --- | --- |
| Target build | Fresh FWSC, app and disassembly; existing HAL, flash-safe loader/RAMTEXT, app/RAM/POOL guards |
| Host regression | Sound goldens, release tails, engine switches, persistence, MIDI, USB and UI checks; both existing O2 and Os/no-SIMD harnesses |
| Robustness | ASan/UBSan and fixed-seed parser/storage/sample fuzz runs |
| References | Pinned DaisySP comparison and checked-in CC0 samples |
| Web/emulator | Node tests and Emscripten build, followed by native/WASM song equality and emulator checks |
| Delivery | Package byte equality from a second clean checkout; no tracked changes or baseline updates |
| Release | Required files, attribution and every license, SHA-256 coverage of every bundle file, archive checksum |

`tools/ci.py verify-tests` rejects skipped local optional suites, absent test
outputs and missing target-budget entries even if the runner prints success.
Linux has no `proc_pid_rusage` instruction counter: both host CPU budgets remain
unavailable and their explicit messages are retained. Host wall time is
informational; pi32v2 disassembly cost is a static heuristic. Real FM-1 audio
deadlines, scanning, USB/MIDI, listening and update/recovery remain device checks.
This infrastructure change does not change firmware, flags or test baselines.
The only permitted fixture skip is the official V15 restore comparison: that
requires the vendor firmware, which is deliberately not redistributed here.

## Dependencies and provenance

Python 3.12 and Node 22 are selected explicitly. Pillow and fontTools versions
are in `tools/ci-requirements.txt`; Raqm is mandatory. Emscripten 6.0.11 and DaisySP
are fetched from fixed source commits. The target cache contains only JieLi's
`jieli-linux-toolchains-20260730.1` and the three AC79 SDK files. Cache keys include
runner OS/architecture and setup/checker sources. Every cache hit rechecks the
compiler/package identity and SDK SHA-256 values from `tools/build.py`.

The SDK downloader first tries JieLi's pinned Gitee SDK commit, then a pinned
[ChoralRoot mirror](https://github.com/Quixotic7/ChoralRootFM1/tree/d09c687d8ee1850fc1360c080aca41763be998ca/tools/sdk)
of the same three Apache-2.0 files. Both sources must match Felucca's reference
hashes. Downloaded files are verified before replacement. No SDK binary is added
to this repository. The existing toolchain downloader uses a moving vendor URL:
CI rejects a different package/compiler identity, but no vendor archive checksum
is available here. Provenance includes the downloaded compiler's SHA-256; this
does not establish an independently authenticated vendor archive.

`build/ci/provenance.json` records the actual checkout revision/date, runner,
Python/font dependencies, compiler/hash, SDK hashes, default flags, Emscripten,
Node, DaisySP and sample hashes. Action inputs pin Python/Node minor versions,
not every runner OS package or patch update. Reproducibility is checked between
two checkouts in one run; cross-runner byte identity is not promised. Updates to
these pins must pass the same goldens and package checks without blanket updates.

## Debug artifacts and cost

Each run uploads available diagnostics with `if: always()`, including failures:
setup/build/test/reproduction logs, provenance, target ELF/map/disassembly,
loader ELF/disassembly, UI PNGs, host WAVs and selected FM6/reverb examples.
Setup failures may have only checkout details; the complete Actions step logs
remain on the run page. A canceled job can upload available diagnostics while
its runner remains alive; a killed runner cannot guarantee an upload.

Diagnostics expire after 14 days; successful firmware/release artifacts after
30 days (subject to repository policy). Download them from the Actions run's
Artifacts section. Artifact access follows repository permissions and may
require sign-in. Only explicit build paths are uploaded, never an environment
dump, credentials or dependency caches. Public GitHub-hosted runner use follows
GitHub's plan; private forks can consume minutes and artifact storage. There is
one target/test job per run and no recurring nightly schedule.

## Releasing

Push a `vX.Y`, `vX.Y.Z`, `vX.Y.Z.W` or `vX.Y-suffix` tag; each numeric component
must be one digit because the existing package product identity has that limit.
The workflow validates the version, builds the versioned target, exercises that
exact FWSC with the existing loader/update tests, reproduces the package, then
verifies the complete release directory. No tag is created by CI.

A separate job downloads and checks the validated bundle before receiving
`contents: write` publication privileges. It publishes the FWSC, app,
`SHA256SUMS`, provenance, attribution, license documents and a tar.gz containing
all files and third-party license texts. The archive has its own `.sha256` file.
Suffix versions become prereleases; an existing release is preserved without
replacing its assets. Nothing flashes a device or publishes an installer/Pages.

To rehearse, manually dispatch `Release` with a version such as `1.6-rc1` from
the desired source branch. It runs all checks and produces release artifacts
without executing the publisher. Do not push a tag merely to test CI.

## Sources of the design

- [Jangada](https://github.com/zednaked/jangada/blob/db41fd9845af6c8ebfbc348dafc33d98ef83a27d/.github/workflows/ci.yml): native target CI, full suite and second-checkout byte comparison.
- [ChoralRoot](https://github.com/Quixotic7/ChoralRootFM1/blob/d09c687d8ee1850fc1360c080aca41763be998ca/.github/workflows/release.yml): dependency/layout checks, licensing and separate read-only build/write publisher.
- [Melodee](https://github.com/keremimo/melodee/blob/1673b244fe1dbd2cb771b828da230d09a6db6fb9/.github/workflows/nightly.yml): downloadable artifacts and source/compiler provenance.
- [Ghoulbox](https://github.com/jasonpersinger/ghoulbox-fm1-dungeon-synth/blob/8081206b951353b8d04886eeae615feb18123ef5/.github/workflows/host-tests.yml): bounded/read-only CI. Felucca retains target/image checks instead of host-only omissions.

Failure diagnostics and strict optional-suite coverage improve on these examples.
Nightlies, extra firmware variants, Linux instruction counting and Pages
deployment are separate follow-ups rather than prerequisites for this gate.
