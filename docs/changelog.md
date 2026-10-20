<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Changelog

A curated overview of meaningful additions, fixes, behavior changes and optimizations
in this personal fork. Related work is grouped by outcome rather than by commit;
small maintenance changes are omitted. The initial backfill covers merged fork work
from 2026-10-11 through 2026-10-19, not a new tagged release.

See the [fork feature guide](fork-features.md) for controls and compatibility,
the [performance guide](performance.md) for measurement scope, and
[upstream release notes](https://github.com/hugelton/Felucca/wiki/Release-Notes)
for the shared instrument's earlier history. Plans and unmerged experiments belong
in issues and roadmaps, not among implemented changes below.

## Fork development

### Added

- **Early USB rescue:** holding OCT− at power-on or repeated incomplete warm boots
  selects a MIDI-only installer before settings, projects and audio initialize;
  another warm reset in rescue escalates to ROM USB. FM-1 hardware qualification
  remains pending; see the [recovery guide](usb-rescue.md).
- **Playing and editing workflows:** a session-local RECENT sound browser,
  MOMENTARY edit status, previous-page navigation, playback transpose before scale
  quantization (`SEQ+T`), and reversible EUCLID sequencer previews.
- **Project recovery and backup:** deferred automatic project saves that wait for
  stopped, idle operation and quiet stereo output, including effect tails and
  fixed-level USB audio; full backups now include the FM6 voice bank and SLICE records.
  See [persistence contracts](extending.md#4-persistence-and-protocol).
- **Build identification and diagnostics:** startup, ABOUT and INFO identify the
  release, commit or PR; ABOUT includes the fork source. USB serial diagnostics,
  retained crash reporting, opt-in crash register context and interrupt-context
  assertions support investigation. See the [diagnostics guide](diagnostics.md).
- **Testing and installation tools:** deterministic interaction replay, native/WASM
  partition comparisons, host stress scenarios and a Chromium UI/audio gate.
  PR installation supports isolated source worktrees, exact-revision artifacts and
  a pinned native MIDI updater, including its macOS reconnect fix.
- **Fork distribution and tracking:** a hosted browser demo, editor and installer
  with source revisions, complete reproducible source archives with dependency pins
  and checksums, and a repository-backed firmware-watch ledger for reviewing other forks.

### Fixed

- **Sequencer state and timing:** early nudged steps use the upcoming loop's
  condition; EUCLID cancellation preserves the correct undo ownership, and
  stop/cursor state is covered by focused regressions
  ([PR #392](https://github.com/kmplngj/Felucca/pull/392)).
- **Sound and effect transitions:** sound installation now uses one publication
  path for UI, storage and editor loads, including FM6 factory patches. Leaving
  FM6 drops its effective audio-side patch; enabling FX LATCH during a hold
  correctly releases the held effect.
- **Update and storage safety:** loader cleanup preserves autosave and voice-bank
  sectors. Firmware updates reject mismatched image sizes before erasing; build
  guards check package/app limits, interrupt-reachable size optimizations and
  reserved-memory headroom.
- **Second-core failure handling:** parallel rendering uses per-part state where
  required, and failed work falls back to serial rendering. A retained exclusion
  prevents automatic retries after a recorded worker failure until explicitly
  retried. Real FM-1 reset and reliability checks remain pending; see
  [second-core behavior and recovery](fork-features.md#optional-second-core).

### Changed

- **Update-loader compatibility:** installers bind current Felucca packages to loader
  `900`, with the digest-pinned original V15 using loader `015` through Python/the
  maintained browser. Unknown package families fail Python file preflight before
  MIDI access; its legacy `--force` option has no effect. The [recovery guide](usb-rescue.md)
  records supported clients and pending hardware checks.
- **Upstream foundation and engine ownership:** integrated upstream 1.6 and 1.6.1
  while retaining fork work. ANALOG, LOFI, TRIO, WHEEL and NOISE use the pinned MIT
  Engines collection with an explicit API contract; standard/reduced build profiles
  and firmware engine metadata preserve stable IDs. GPL collection integration and
  broader usage modes remain planned; see the [modularity roadmap](modularity.md).
- **Display and startup:** M8Stealth is the default font, with Tamzen and Inter Tight
  build options. The minimal startup identity follows saved colors and can be
  dismissed by a button or key without triggering its normal action.
- **Effect controls:** shared chorus Depth and per-track chorus/delay/reverb sends
  glide during sound. These smoothing experiments are implemented; FM-1 listening
  and timing qualification remain pending. See [effect control smoothing](fork-features.md#effect-control-smoothing).
- **Optional second core:** upstream worker support replaces the separate fork
  experiment. The device preference stays off by default and enabling it is beta;
  a `FELUCCA_CPU2=0` build removes the worker entirely.

### Optimized

- **DSP and effects:** reorganized the PHYS modal resonator and integrated ANALOG,
  TOM and INSERT processing optimizations. Silent chorus, delay, HALL and SPRING
  paths skip work while preserving the tested audio/state behavior. See
  [combined integration evidence](https://github.com/kmplngj/Felucca/pull/349)
  and [silent-FX regressions](../tests/fx_rest_test.md); host equivalence and target
  estimates do not establish FM-1 timing gains.
- **Memory and display work:** aligned memory copies/fills, paired-pixel canvas
  clears, cached project readiness, scope/LCD submission improvements and smaller
  font decode caches. The [controlled font comparison](font-experiment.md) records
  about 39 KB less app flash for pixel fonts and a separate 1,032 B POOL saving;
  these are dated comparisons, not current whole-firmware totals.
- **Development turnaround:** change-based CI selection, dependency caches,
  parallel independent host tests and reuse of automatic PR firmware artifacts
  reduce repeated validation/build work. Required checks still gate merges;
  see [CI scope and artifacts](../.github/CI.md).
