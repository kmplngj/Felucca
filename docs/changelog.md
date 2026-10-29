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

## For firmware developers

The links below collect implemented work that may help other FM-1 firmware
projects and embedded-audio developers. Follow each change's source, attribution
and [licence requirements](../LICENSING.md); host-specific code and hardware
assumptions need adaptation. Evidence applies to the revisions and workloads
recorded in the linked reports, rather than every current build or device.

| Area | Reusable implementation and evidence | Limits and remaining hardware checks |
| --- | --- | --- |
| **DSP and CPU cost** | Silent-effect shortcuts in [fx.c](../firmware/src/fx.c), with [forced-off audio/state comparisons, skip assertions and negative controls](../tests/fx_rest_test.md); broader [DSP integration evidence](https://github.com/kmplngj/Felucca/pull/349). | Tested equivalence and target estimates do not establish FM-1 timing gains. Recheck tails, wake-up, transitions and loaded audio deadlines on the adopting firmware. |
| **RAM, flash and display work** | [Aligned copies/fills](../firmware/src/libc.c) and [host checks](../tests/libc_test.c); [bitmap font generation](../tools/gen_bitmap_font.py) and [controlled font/cache comparisons](font-experiment.md), including a separate 1,032 B POOL reduction. | Savings are dated A/B results, not current totals or additive estimates. Font-only flash savings do not imply RAM or CPU savings; physical readability and loaded redraw/audio checks remain separate. |
| **MIDI and arithmetic fixes** | [Timestamp, UART event/count, clock-phase and signed-scaling fixes](midi-dsp-reliability.md#changes-and-provenance), with focused regressions, SDK evidence and [device results](midi-dsp-device-results-2026-10-21.md). | USB pulse-count phase passed with CPU2 OFF in the recorded setup. Physical TRS and CPU2 ON clock-phase checks remain pending; UART register widths and event semantics are JieLi-specific. |
| **Request ownership and worker reliability** | [Editor/updater SysEx race](sysex-dispatch-race.md), including causal device reproduction, [boundary-injection regression](../tests/sysex_dispatch_test.py) and resource deltas; [CPU2 idle-poll mitigation and matched device tests](cpu2-idle-polling.md). | Serialized requests remain required. Bounded USB observations do not qualify every host/load or physical TRS. CPU2 evidence is from one FM-1; broader engine/unit and reset/flash qualification remains pending, with the worker beta and default OFF. |
| **Build and resource safeguards** | [Profile contracts and artifact-bound resource/stack reports](build-profiles.md#machine-readable-build-evidence), [report generation](../tools/build_report.py), [report regressions](../tests/build_report_test.py) and [ISR-aware size selection](../tools/size_fns.py). | Linked region sizes and reserved stacks are static evidence, not live RAM/stack watermarks or deadline measurements. Re-establish the memory map, ISR reachability and compiler behavior for another target. |
| **Diagnostics and reproducible testing** | [Read-only USB collector](diagnostics.md), [rendered-screen capture](screen-capture.md), [interaction replay](interaction-replay.md) and [real browser UI/audio gate](cloud-testing.md), with their setup, provenance and validation scope. | Collection continuity is not a firmware pass. Host/WASM replay does not qualify FM-1 I/O or deadlines; digital screenshots do not qualify physical colours/backlight. Capture flags are development-only, and explicit capture wake awaits device validation. |
| **CI and AI workflows** | [Selective CI, caches and exact-revision artifacts](../.github/CI.md); [AI workflow guide](ai-workflows.md) linking summary-first evidence, the firmware-watch ledger/skill, PR-testing instructions and firmware-specific AI review configuration. | Context filtering preserves full relevant diff and history coverage. AI/static review complements target and device checks. Text reduction is a context-size proxy until actual token usage and task quality are measured. |

## Fork development

### Fixed

- USB control recovery discards a deferred device address when the host abandons
  or stalls its status stage. Failed EP0 selection/status reads no longer count
  as completion. Host regressions cover replacement requests, address zero and
  reset; physical host/controller abort timing remains pending.

- The [CDC diagnostics collector](diagnostics.md#interpreting-a-report) requires a
  complete, valid key-latency group before reporting measured latency. Missing
  older-firmware metrics remain unmeasured; malformed present known numeric fields,
  including empty or colon-containing values, invalidate collection while retaining
  raw evidence. USB audio packet deltas also require
  unchanged supported sample-rate and setter evidence: observed rate boundaries
  invalidate collection even when a reset count overtakes its old value. Missing
  legacy rate evidence leaves packet deltas unavailable. No firmware or protocol
  change.

### Added

- Two [release channels](releases.md): one rolling **Latest Dev** prerelease identifies
  the latest validated main-branch PR merge; tagged packages require exact-commit device
  test attestation and a linked report before publication. Both ship risk/recovery
  guidance; tagged versions include the complete commit changelog since the previous
  stable release. Dev notes stay short, and superseded Dev releases/tags are removed.


- Default-off [raw render-stage evidence](render-stage-evidence.md) adds one
  inclusive CPU0 mix-stage observer, empty controls and coherent optional `status`
  snapshots with explicit rejection/error semantics. Release builds refuse the
  diagnostic flag; target cost accounting and matched FM-1 acceptance remain
  pending. This delivers instrumentation, without a DSP speedup claim.

- **Standalone RAM-loader status:** waiting and package validation, verified
  application-sector progress, native completion/restart and host retry guidance
  work without an intact application. Bounded RAM-owned scanlines contain missing
  or slow LCD completion while retaining in-flight sources and servicing USB and
  the watchdog. Package, protocol and protected-storage policy are unchanged.
  Physical FM-1 update/display/retry qualification remains pending; see
  [screen meanings and limits](usb-rescue.md#standalone-ram-loader-screen).
- **Native audio-window evidence:** optional developer tooling discovers and
  qualifies a bounded held-key renderer window, repeats trace/PCM and compares
  silent controls and the original native replay basis. See the
  [capture guide](native-audio-window.md); no physical timing or optimization
  result is supplied.

- **Native guest hotspot attribution:** optional developer tooling revalidates
  saved replay evidence and counts bounded windows by target function range and
  emulator instruction class. See the [report guide](native-hotspots.md); no
  firmware execution, physical timing or optimization result is supplied.

- **Native emulator replay evidence:** optional developer tooling verifies matched
  artifacts, repeated held-key/modeled-UART traces and PCM, and silent controls.
  See the [bounded replay guide](native-emulator-replay.md); this supplies no
  hotspot attribution, physical timing result or device qualification.

- **Read-only boot clock evidence:** normal USB SERIAL diagnostics report seven
  saved startup clock-register words without changing clock configuration.
  The collector retains raw values and supports older firmware that omits them.
  Real bootloader/reset-path readings and any correction decision remain pending;
  see [diagnostic scope and setup](diagnostics.md#boot-clock-evidence).

- [Offline update-record survey](update-record-survey.md) reports native-loader
  CRC/marker matches and coverage in saved raw flash bytes. It accesses no device
  and changes no storage policy; external SPL behavior remains unverified.

- Optional [target entry-frame inventory](stack-frame-evidence.md) reuses verified
  artifact evidence. Unsupported stack/ASM forms and unresolved calls stay explicit;
  stack reservations and runtime behavior are unchanged. It is not a live watermark
  or whole-stack fit result.

- [Offline boot-area survey](boot-area-survey.md) checks saved dump/package
  boot records, SPL CRCs, chip key and declared clock fields with bounded input
  parsing. It accesses no device and changes no installer policy; live clocks,
  bootloader compatibility and backup-first hardware survey remain pending.

- [Offline factory-level audit tooling](loudness-audit.md) captures selected native
  sounds, reports stereo loudness/headroom and retains fixed-scale audition WAVs.
  It changes no factory levels; role assignment, listening decisions and physical
  DAC/USB qualification remain separate.

- Maintainer-only [immutable build bundles](build-bundles.md) bind an existing profile's
  exact package/resource/source/reproduction evidence and optional build-time Wasm receipt.
  A separate manual main-only workflow now orchestrates canonical builds, Git-free
  reproduction and a mandatory matching simulator before uploading a verified bundle;
  the same recipe has an explicit local maintainer mode for pre-merge evidence.
  Offline verification checks artifact correspondence; full host/browser/device acceptance,
  public build service and deployment remain separate.
  Native target builds now refuse unsupported compiler search/configuration variables
  such as `CPATH`, `LIBRARY_PATH` and `SDKROOT`; Docker target builds ignore these
  unforwarded host values. Host loader injection (`LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`,
  `DYLD_LIBRARY_PATH`) is refused for both backends. `LD_LIBRARY_PATH` remains allowed
  and is recorded only as a value hash; see [build-input identity](build-bundles.md#identity-and-immutability).

- **Build metadata contracts:** canonical supported-profile exports include stable IDs,
  exact engine pins, dependencies, assets, licences and defaults. Successful target builds
  emit artifact-bound resource/stack reports, with stale-evidence verification using the
  existing build guards. This is the first stage of #465; cost prediction and a browser
  builder remain pending. A reviewed native font policy pins M8 inputs, metrics and shared
  bitmap storage; target reports verify the 4,630 B text-font bound and separate named
  keycap, icon, decoder and cache costs. This changes no font pixels or runtime behavior.
  See [build evidence](build-profiles.md#machine-readable-build-evidence).
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

- **USB controller retry:** local restart clears stale configuration and pending
  control/stream state before reattachment, so bulk/audio endpoints wait for fresh host
  configuration. Existing host-reset queue policy is preserved. Software-model
  checks pass; physical USB recovery qualification remains pending. See
  [test scope](../BUILDING.md#tests) and [counter interpretation](diagnostics.md#interpreting-a-report).

- The offline USB tone checker rejects recordings without synchronized tone data,
  unsupported rates and incomplete PCM, and reports matched frames accurately.
  [Recording interpretation](diagnostics.md#usb-test-tone-recordings) keeps device
  qualification separate from the offline result.

- PR-source cleanup protects reflog-only detached commits and refuses removal with
  deinitialized or orphan private submodule repositories. It preserves history
  without automatic metadata repair. See the
  [worktree preservation and cleanup procedure](../BUILDING.md#optional-isolated-pr-sources).

- Latest Dev uses a compact commit-based firmware version that fits ABOUT. PR and
  full commit provenance remain in release metadata; the UI regression gate now
  exercises the generated Dev version before merge. This fixes the initial Dev
  release's layout-test failure; no publication gate is relaxed.
- Native replay source-change guards include consumed portable Engines sources
  and generated include files, so changes during compilation cannot publish an
  adapter or completed capture with stale input provenance. See
  [interaction replay](interaction-replay.md).

- **Python installer liveness:** unrelated or malformed SysEx no longer keeps a
  stalled update waiting indefinitely or hides a disconnected MIDI port. Valid
  update requests still renew the existing staging and writing idle budgets.
  See [installer errors](../BUILDING.md#package-validation-and-file-errors).

- **Native attribution:** ABOUT credits and the retained installer template now
  distinguish PHASE/DRUM GPL-3.0-only from the author's Sample Pack CC0 1.0
  dedication. The PHASE source comment agrees; synthesis and generated sounds
  are unchanged. Native host rendering and scroll checks qualify this text change;
  no physical display observation is claimed.
  See [licensing scope](../LICENSING.md#sample-pack-dedication-and-scope).

- **LCD state readability:** muted track names/settings, mixer annotations,
  piano-roll pitch labels and MOD text/units retain readable contrast across
  built-in palettes. Mute marks and inactive graphics keep their distinct state.
  Control hints, calibration prompts and the emulator panel use the printed SEL
  button name, distinct from the SELECT encoder and musical SCL page. See
  [roles and validation scope](lcd-typography.md#readable-inactive-information);
  physical FM-1 readability and loaded-panel checks remain pending.
- **Firmware CI coverage:** required host work and nested checks now use a
  source/configuration-bound structured report instead of success banners and
  recognized skip wording. Missing dependencies, child completion or stale evidence
  fail strict verification; documented CPU/V15 and profile exceptions stay explicit.
  See the [runner contract](../BUILDING.md#tests). Firmware/device behavior is unchanged.

- **Browser emulator readability:** keyboard hints, footer links, build version and
  small-print text meet a 4.5:1 contrast floor against the neutral page background.

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

- Backport the remaining signed DSP arithmetic fixes from upstream 1.7.0:
  ANALOG, LOFI, TRIO, WHEEL, NOISE and native PHASE retain their output while
  avoiding undefined signed shifts and overflow. The fork's engine API,
  zero-mix ANALOG path and per-part PHASE scratch remain intact. See the
  [arithmetic follow-up](midi-dsp-reliability.md#upstream-170-arithmetic-follow-up)
  for provenance and validation limits; FM-1 listening remains pending.

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

- **Return to official firmware across bootloaders:** Felucca's update staging and
  the Python installer accept M-VAVE's official V16 as well as V15, each only as the
  exact reviewed file (whole-file SHA-256 on the host; flash image size and CRC16,
  boot-area SHA-256 and chip key on the device), over whichever boot area the unit has. Before, V15 was
  refused on a unit with V16's bootloader or m-bootloader, and V16 everywhere. M-VAVE's
  FM1 Open firmware and m-bootloader's installer now get explicit explanations instead
  of generic failures. The [offline boot-area survey](boot-area-survey.md), hardened
  separately in #712 and retained here, checks saved dump/package CRCs and bounded
  fields; declared clocks (V16's: 320 MHz, #618) are not live measurements. V16
  return and crossed-bootloader transitions await FM-1 qualification; the browser installer keeps V15 until its
  client update. See [return to official firmware](usb-rescue.md#return-to-official-firmware-and-the-boot-area-619)
  and [compatible bootloaders](usb-rescue.md#boot-areas-and-other-firmware).
- **Unified native reading:** value pages use a shared four-knob parameter bank
  and a stable larger current value while keeping full native graphs. Explicit
  scope feedback covers held-step locks, motion and temporary/kept edits; focus
  remains after turn feedback expires. Names have a larger reading role above five
  list rows. Settings use seven uniform 9 px rows and explicit ON/OFF; single
  values, including COLOR/LEDS, edit directly. AUTO OFF groups related values on
  a detail page with the same typography. NORMAL/LARGE is consolidated;
  the old settings bit and editor id remain reserved for compatible rollback.
  Physical FM-1 readability and loaded-panel
  qualification remain pending. See the [reading contract](lcd-typography.md#focused-parameter-bank).
- **One native look (direction A, #572):** rules instead of boxes in every palette.
  Value pages show the focused knob as a 27 px numeral where the graph leaves room, the
  four knob columns under rules whose form names the editing state (solid, dashed
  automation, doubled lock, dotted MOMENTARY), and the accent only while a knob turns. The header
  reads `T1 ▶ 124 BPM` flush left with the REC mark after the tempo.
  Compact knob rows, MENU tabs, settings rows and the footer share the same type system.
  MENU > STYLE is retired with its value and editor id kept for rollback. New
  MENU > DISPLAY > **GRAPH** (default TURN): the turned knob's filter response or
  envelope replaces the live waveform while it turns, then the waveform returns; SCOPE,
  CURVE and STILL keep the waveform, add a small one, or stop animating. Physical FM-1
  readability and redraw checks remain pending. See the [feature guide](fork-features.md).
- **LCD typography:** control hints and state badges now use native M8Stealth57
  lettering alongside the default M8 text. Numeric card and MOD units stay in a
  fixed slot, and small-value fallbacks share a consistent vertical band.
  Track digits center on their cushion, removing the old extra shift for “1”.
  One M8Stealth family now supplies two native bitmap grids and exact 2× reading
  roles. No additional 14 px role is emitted. Tamzen and Inter Tight firmware variants
  are retired; rounded pill edges and icons retain antialiasing.
  See [roles, fit rules and validation scope](lcd-typography.md);
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

- **PR installation:** the CLI uses the maintained Python updater. The locked
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
- **Display and startup:** M8Stealth supplies native text. The minimal startup
  identity follows saved colors and can be
  dismissed by a button or key without triggering its normal action.
- **Effect controls:** shared chorus Depth and per-track chorus/delay/reverb sends
  glide during sound. These smoothing experiments are implemented; FM-1 listening
  and timing qualification remain pending. See [effect control smoothing](fork-features.md#effect-control-smoothing).
- **Optional second core:** upstream worker support replaces the separate fork
  experiment. The device preference stays off by default and enabling it is beta;
  a `FELUCCA_CPU2=0` build removes the worker entirely.

### Optimized

- Native icons share identical complete 12 px compressed streams while preserving
  icon IDs and decoded pixels. Decoder and cache code are unchanged. See the
  [icon-stream evidence](icon-stream-dedup.md) for dated measurements and scope.

- Docker target builds share one invocation-owned toolchain container across loader,
  application and resource checks, reducing repeated container startup overhead.
  Compiler arguments and firmware behavior are unchanged; the benefit depends on
  host load and compiler time. Native Linux builds keep their existing path. See
  [builder lifetime and fallback](../BUILDING.md#prerequisites-macos) and
  [the controlled measurements](https://github.com/kmplngj/Felucca/pull/661).
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
  reduce repeated validation/build work. Classified draft changes use explicit
  focused feedback, including matching test entry points, graphics and selected
  DSP helpers; shared or unfamiliar files retain full validation. AI guidance uses
  draft PRs and affected local units during iteration, with complete applicable
  CI on the final ready candidate before merge and no identical local rerun
  without a changed input or unresolved concern. Selector/helper-contract-only
  changes use workflow/coverage checks without firmware or audio builds; workflow
  YAML and shared test execution changes retain full validation. Full host work
  runs across two runners with a source-derived aggregate rejecting missing,
  duplicate or stale evidence. Standalone backup fixtures can reuse matching
  verified receipts; firmware identity and releases stay fresh. Required checks
  still gate merges; see [CI stages and artifacts](../.github/CI.md#feedback-and-merge-stages).
  These are CI scheduling changes, not firmware CPU or hardware performance claims.
  The host suite's opt-in
  [`--ai-output` mode](../BUILDING.md#tests) condenses console output while retaining
  full logs, failure exit codes and warning/skip hints; test coverage is unchanged.
