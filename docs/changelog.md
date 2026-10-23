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

- **Build metadata contracts:** canonical supported-profile exports include stable IDs,
  exact engine pins, dependencies, assets, licences and defaults. Successful target builds
  emit artifact-bound resource/stack reports, with stale-evidence verification using the
  existing build guards. This is the first stage of #465; cost prediction and a browser
  builder remain pending. See [build evidence](build-profiles.md#machine-readable-build-evidence).
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
  release, commit or PR; ABOUT includes the fork source. USB serial health/input
  counters and consistent main/worker crash snapshots support device investigation.
  A read-only host collector retains raw replies, JSONL samples and a summary with
  counter deltas and supplied build provenance. Opt-in crash-register context,
  interrupt-misuse counters and a bounded 64-bit multiply/16-bit-load reproducer
  support targeted debugging; normal FM-1 builds leave these probes disabled.
  The synthetic reproducer adds a test workload, not an audio fix. See the
  [capability overview and activation requirements](diagnostics.md#diagnostic-capabilities).
- **Rendered-screen screenshots:** an opt-in development build exports bounded
  RGB565 HOME/menu captures over USB SERIAL, with full device build identity and a
  host PNG/JSON tool. Explicit `--wake` silently wakes the current stopped view,
  waits for redraw and holds it awake for the bounded capture; default capture
  still rejects sleep. Unsupported or changed scenes fail explicitly;
  normal builds leave capture disabled. Digital captures do not qualify physical
  panel colours or backlight behaviour; the new explicit wake path awaits FM-1
  validation. See [scope and device checks](screen-capture.md).
- **Testing and installation tools:** deterministic interaction replay, native/WASM
  partition comparisons, host stress scenarios and a Chromium UI/audio gate.
  PR installation supports isolated source worktrees, exact-revision artifacts and
  the Python USB-MIDI updater with dependency checks before firmware CI.
- **Fork distribution and tracking:** a hosted browser demo, editor and installer
  with source revisions, complete reproducible source archives with dependency pins
  and checksums, and a repository-backed firmware-watch ledger for reviewing other forks.

### Fixed

- **LCD state readability:** muted track names/settings, mixer annotations,
  piano-roll pitch labels and MOD text/units retain readable contrast across
  built-in palettes. Mute marks and inactive graphics keep their distinct state.
  Control hints, calibration prompts and the emulator panel use the printed SEL
  button name, distinct from the SELECT encoder and musical SCL page. See
  [roles and validation scope](lcd-typography.md#readable-inactive-information);
  physical FM-1 readability and loaded-panel checks remain pending.
- **Hosted editor settings:** applied RAM-only and deferred-save settings retain
  the device's returned value; rejected edits restore the confirmed value while
  preserving newer picker drafts. Saved edits replace earlier warnings with
  "Saved" while retaining the message history. The pinned editor discovers AUTO OFF,
  WAKE and ALL DARK from firmware descriptors, including builds without CPU2. See
  [WebApp PR #7](https://github.com/kmplngj/Felucca-WebApp/pull/7),
  [feedback fix #8](https://github.com/kmplngj/Felucca-WebApp/pull/8) and
  [site deployment and source revisions](../.github/CI.md#fork-site-deployment).
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

- **LCD typography:** control hints and state badges now use native M8Stealth57
  lettering alongside the default M8 text. Numeric card and MOD units stay in a
  fixed slot, and small-value fallbacks share a consistent vertical band.
  Track digits center on their cushion, removing the old extra shift for “1”.
  Rounded pill edges, icons, text-font comparison builds and LARGE mode remain
  available. See [roles, fit rules and validation scope](lcd-typography.md);
  physical readability and loaded-panel qualification remain pending.
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
