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

- **Optional MACRO engine:** the `macro` profile adds 48 Braids-derived models and
  51 factory sounds alongside all thirteen standard engines, using stable engine
  ID 14. WAVE/FOLD/FBFM retain eight voices; the added models use one voice per part.
  Full-bank parts use distinct deterministic random streams, and optional
  second-core scheduling accounts for their model costs.
  The standard profile is unchanged. User reports cover models, controls and
  switching during held notes; the raised-key symptom was a corrected QNT setting.
  Specific FM-1 listening, persistence, USB/TRS transport and timing checks remain
  pending. See the [engine guide](macro-engine.md),
  [device procedure](macro-hardware-test.md) and [results](macro-device-results.md),
  including the remaining model-rate qualification.
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
  A read-only raw store export (editor commands 82/83) downloads every stored
  object byte for byte, including projects, presets and settings the firmware
  cannot load, as the first step of moving legacy conversion to the web editor;
  a reference reader is included, with browser migration still pending. See [persistence contracts](extending.md#4-persistence-and-protocol)
  and the [stored-format inventory](legacy-formats.md).
- **Build identification and diagnostics:** startup, ABOUT and INFO identify the
  release, commit or PR; ABOUT includes the fork source. USB serial diagnostics,
  retained crash reporting, opt-in crash register context and interrupt-context
  assertions support investigation. See the [diagnostics guide](diagnostics.md).
- **Testing and installation tools:** deterministic interaction replay, native/WASM
  partition comparisons, host stress scenarios and a Chromium UI/audio gate.
  PR installation supports isolated source worktrees, exact-revision artifacts and
  the Python USB-MIDI updater with dependency checks before firmware CI.
- **Fork distribution and tracking:** a hosted browser demo, editor and installer
  with source revisions, complete reproducible source archives with dependency pins
  and checksums, and a repository-backed firmware-watch ledger for reviewing other forks.

### Fixed

- **Editor SysEx replies:** a request arriving between the Editor and updater's
  main-loop checks is retained for the correct consumer instead of silently
  discarded. The wire format and one-request-at-a-time contract are unchanged;
  see [the ownership regression and device evidence](sysex-dispatch-race.md).

- **MIDI timing and arithmetic:** TRS packets keep timely timestamps during audio
  renders, UART counts require a receive event, and external sequencer/ARP phase
  retains fractional progress through tempo and SONG changes. Signed DSP scaling
  is defined and invalid tempo has a bounded default. Normal PCM and valid-tempo
  behavior remain covered by regressions. The [device results](midi-dsp-device-results-2026-10-21.md)
  pass USB pulse-count phase with CPU2 OFF; physical TRS and CPU2 ON clock-phase checks remain pending.
  See [implementation evidence and test procedure](midi-dsp-reliability.md).

- **LED brightness feedback:** the DISPLAY menu now redraws INV, INV LO and INV HI
  immediately when their brightness is changed without leaving the row. Physical
  brightness/readability checks remain pending; see [display controls](display-idle.md).
- **Early rescue entry:** enable the shared key/LED power rail before reading
  OCT− at startup, allow it to settle and use the normal input scan cadence.
  Both-OCT calibration remains available; corrected entry awaits FM-1 retesting
  ([evidence and procedure](usb-rescue.md#physical-entry-evidence-and-related-firmware)).
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
  retried. A bounded in-RAM idle-poll pause mitigates observed BAD_JOB read faults
  in [matched tests on one FM-1](cpu2-idle-polling.md), while preserving all guards
  and default OFF. Broader unit/engine, TRS and reset/flash checks remain pending; see
  [second-core behavior and recovery](fork-features.md#optional-second-core).

### Changed

- **Display inactivity:** AUTO OFF combines the existing screen timeout with LED-only
  and combined darkness, retaining NEVER as default and the existing screen-only
  values. Timed LED darkness includes a quiet rotating key-LED pulse every 30 seconds;
  audio and input scanning continue. The LCD backlight remains on. See
  [controls, downgrade behavior and pending FM-1 checks](display-idle.md).
- **Python tooling setup:** locked uv dependency groups separate build/font tooling
  from MIDI installation. Build and PR handoff commands synchronize their environment
  automatically, including on macOS without manual pip setup; see
  [Python environments](../BUILDING.md#python-environments).

- **PR installation:** the CLI uses the maintained Python updater again. Native Rust
  updater setup, cached artifacts and backend selection have been removed; the locked
  `midi` group supplies `mido`/`python-rtmidi` in the trusted caller checkout. See [BUILDING](../BUILDING.md#test-a-pull-request-on-hardware).

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
