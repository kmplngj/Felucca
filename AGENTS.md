<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Felucca development guide

Felucca is bare-metal synth firmware for the M-VAVE FM-1 (JieLi AC791N / pi32v2).
Develop for the actual JieLi Clang 4.0.1 toolchain, its memory map, and audio deadlines.
Host tests and the browser emulator compile the real DSP sources against simulated hardware.

## Start here

1. Check the branch and working tree; preserve changes belonging to other work.
2. Read the relevant sources and the documents below before changing behavior.
3. For an optimization, capture a baseline from the unchanged revision, change one cause,
   and repeat the same measurements. Report bytes and timing with their provenance.

| Before you… | Read |
| --- | --- |
| Build, generate assets, or run tests | [BUILDING.md](BUILDING.md) |
| Collect diagnostics from a connected FM-1 | [docs/diagnostics.md](docs/diagnostics.md), [docs/performance.md](docs/performance.md) |
| Change DSP, interrupt scheduling, buffers, compiler options, or resource use | [docs/performance.md](docs/performance.md) |
| Change MIDI, saved parameters, backup, or editor messages | [web/EDITOR_PROTOCOL.md](web/EDITOR_PROTOCOL.md), the affected serializers and their tests |
| Contribute or package third-party code/data | [CONTRIBUTING.md](CONTRIBUTING.md), [LICENSING.md](LICENSING.md) |
| Add an engine, effect or platform/persistence hook | [docs/extending.md](docs/extending.md) |
| Evaluate an idea from another FM-1 firmware | [The dated development review](docs/development-review-2026-10-11.md), then that project's current source |
| Plan build profiles, usage modes, new engine IDs or new persistent data | [docs/modularity.md](docs/modularity.md) and the issues it maps; for flash sectors, saved bytes or retained RAM, the [capacity plan](docs/flash-capacity.md) |
| Create or update a PR, or hand off a change for user testing | [PR testing skill](.agents/skills/pr-testing/SKILL.md) |

If this checkout has a `.codegraph/` index, use CodeGraph first to locate code and trace
callers. Otherwise use normal source search; indexing is the owner's choice.

## Batch related issues for one hardware handoff

Prefer one bounded PR for two or three related issues that share a subsystem and
device test setup. Extend an existing relevant draft PR when appropriate. The goal
is fewer firmware builds, installations and repeated hardware setups, while keeping
each change reviewable and diagnosable.

- Check current source, merged PRs and existing tests before selecting work: an open
  issue may already be implemented. Complete missing evidence instead of rewriting it.
- Declare the batch's issue list, scope and acceptance checks before implementation.
  Keep changes in separate logical commits and map each issue to its focused tests.
  Leave unrelated features, large experiments and independent storage/protocol/boot
  migrations for another batch. Freeze scope before final validation; new ideas go
  into the next round rather than continually invalidating a hardware candidate.
- Capture one clean shared baseline. Reuse existing artifacts only when revision,
  relevant source/asset hashes, engine pins, toolchain, profile and flags match; retain
  their provenance. Preserve per-issue isolated comparisons when measuring one cause,
  and report the integrated resource delta separately. Do not add overlapping savings.
- During implementation, rebuild and run focused host regressions for each issue.
  When delegating, assign file/region ownership and use isolated test outputs; one
  coordinator owns shared generated assets and target/emulator builds. Do not run a
  complete firmware build or full suite independently in every subtask. Target-only
  probes remain appropriate when needed to decide a compiler or resource tradeoff.
- Include affected cross-feature reference tests in those focused checks: for DSP
  changes, trace preset/engine-switch and mixed-effect audio oracles as well as the
  new feature's tests. Resolve intended transition differences before the long
  integrated run; retain historical goldens when the existing contract can be isolated.
- At the frozen integrated revision, run the full applicable validation once and
  produce one fresh target artifact per required build variant, with aggregate budget
  checks. Reuse successful CI evidence for that exact revision/variant where it covers
  the required checks. Fix failures and rerun affected checks; finish with the required
  integrated CI checks passing on the final head. Batching does not waive sound,
  compatibility, deadline or hardware requirements.
- Provide one combined hardware procedure: backup and install once per required
  artifact, reuse the same known project/MIDI/audio setup, run each issue's targeted
  checks, then one shared mixed-load regression. Where A/B evidence is necessary,
  compare the baseline with the combined candidate and retain per-issue observations.
  Name the exact commit/package, defaults, variants and expected results. Do not ask
  for a new flash after each issue. Unperformed device checks remain pending; do not
  flash, merge or publish beyond the user's authorization.

## User-facing documentation

For every added or changed user-facing feature, read [README.md](README.md) and
check whether its feature list and usage instructions still describe the result.
Update the affected README sections in the same PR when needed, including how to
access the feature, its defaults, limitations and compatibility implications.
Keep detailed instructions in the relevant guide when appropriate and link them
from the README so users can discover the feature.

Before completing the change, record the README assessment in the PR description
(or completion report when there is no PR): name the sections updated, or explain
specifically why the existing README already covers the resulting behavior.

## Architecture and ownership

| Location | Responsibility |
| --- | --- |
| `firmware/src/felucca.c` | Single translation unit: includes the other C files in dependency order |
| `firmware/src/core.h`, `engines.c`, `voice.c` | Types, stable engine IDs, per-part engine memory, voice allocation |
| `firmware/src/audio.c`, `fx.c`, `eng_*.c` | Audio interrupt, mixer, effects, engines, fixed-point helpers |
| `firmware/src/main.c`, `ui*.c`, `panel.c` | Boot, main loop, UI and panel event handling |
| `firmware/engines/` | Pinned MIT engine interface, shared DSP/tables and ANALOG/LOFI/TRIO/WHEEL/NOISE; commit changes in the Engines fork before updating the gitlink |
| `firmware/hal/` | Registers, interrupt assembly, peripheral access, hardware guards |
| `firmware/app.ld`, `firmware/loader/` | Memory layout and the separate update loader |
| `firmware/src/storage*.c`, `project.c`, `upreset.c`, `settings_persist.c` | Flash and versioned persistence |
| `tools/`, `tests/` | Target build, asset generators, host simulation and regression checks |
| `build/gen/` | Generated headers; change their generator or input asset |
| `web/emu/` | Browser emulator; editor/installer development has moved to Felucca-WebApp |

Keep hardware register access in `hal/`; expose a HAL helper to application and loader
code. `tools/build.py` enforces this boundary. Follow the existing include order and use
`static` for implementation-local functions and state. A new C file must be wired into
the firmware and relevant host/emulator compilation paths, not merely added to disk.

## Invariants that changes must preserve

- **Bounded interrupts.** Audio fills each DMA half within its deadline; the higher-priority
  TIMER5 scan can nest inside it. Keep rendering and scan work bounded. Handle UI, preset
  loading, flash operations and formatted diagnostics in the main loop, using the existing
  request/service paths. Keep allocation, blocking I/O and waiting locks outside interrupts.
- **Explicit ownership.** Preserve each queue's producer/consumer, its bounds and publication
  order (`RING_PUBLISH()` in `core.h`). An interrupt-shared flag and a multi-field snapshot
  need different synchronization. `volatile` alone does not publish surrounding data.
- **Predictable memory.** Size static state and buffers against the linker regions. Engine
  state shared by a part goes through `eng_mem_claim()` and `ENG_MEM_FITS`; preserve the fade,
  reset and ownership rules and the switch regressions. Main-loop scratch may be shared only
  when its lifetimes cannot overlap. Keep stack guards, reserved RAM and reset diagnostics intact.
- **Stable sound.** Preserve fixed-point units, rounding, saturation, phase/RNG order,
  click-free transitions and release tails. Check arithmetic bounds before moving a multiply,
  changing a division to a shift, or narrowing storage. Follow existing naming and formatting;
  comments should explain units, ownership or hardware constraints that the code cannot show.
  Sequence side-effecting register/test-clock accesses in separate statements so evaluation
  order is explicit; compiler sequencing warnings undermine timing-test evidence.
- **Stable data and wire IDs.** Engine numbers and stored/protocol parameter IDs are contracts.
  Append engine IDs; keep retired IDs reserved. Common track parameters are added before
  `P_E0` with the existing count-based mapping. Update old-format imports, validation, defaults,
  round trips and malformed-input tests together; state downgrade limitations explicitly.
- **Flash-safe execution.** Flash-busy code and its required data must be accessible from RAM.
  Preserve the `.ram_text` no-call check, loader RAM-only checks, deferred/coalesced settings
  saves, and stopped/idle autosave policy. An erase pauses audio and scanning; a knob detent
  must not introduce a new immediate erase.
- **Measured compiler choices.** Keep the selective size pass in `tools/size_fns.py`: interrupt
  paths retain `-Os`, eligible main-loop functions get `minsize`. Trace ISR reachability when
  changing those lists or introducing callbacks. Judge an optimization by target output and
  repeatable measurements, including regressions in the other resource budgets.

## Build and validate

Use the setup and environment overrides in `BUILDING.md`. From the repository root:

```sh
./build.sh
tests/run_tests.sh
```

For a short DSP iteration after a successful build, the runner produces these binaries:

```sh
build/host/regress tests/golden.txt tests/cpu_baseline.txt
build/host/regress_os tests/golden.txt tests/cpu_baseline_os.txt
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
build/host/union_test tests/union_golden.txt  # engine-memory changes
```

Rebuild the affected harness after source changes; an existing binary is not evidence for
new code. Finish firmware changes with the full applicable suite, a fresh target build
with no new warnings, and the resource checks in `docs/performance.md`. Record every skipped
check, especially unavailable host instruction counters, DaisySP or browser tooling.
For UI changes, inspect the generated `build/ui_new/` images and the actual panel behavior;
for USB/MIDI changes, exercise the affected host configuration and hardware path.

For browser UI/audio changes, use the [cloud browser gate](docs/cloud-testing.md)
after a fresh emulator build: `npm test --prefix web/emu`. Read its one-line result
and `build/browser/run-*/summary.json` first; open only media relevant to a failure.
The gate makes no model calls and keeps screenshots/WAV only on failure by default.
Reuse existing replay scenarios and deterministic comparisons before requesting
visual/audio model review. Do not stream full logs, PCM or repeated screenshots
into agent context. Browser/emulator evidence remains separate from FM-1 evidence.

`GOLDEN_UPDATE=1` and `BUDGET_UPDATE=1` intentionally rewrite baselines. Use them only for
explained changes in sound or cost, review every changed entry, and retain unaffected entries.
A failed budget is a finding to investigate, not a reason to regenerate all baselines.

New source files carry the GPL-3.0-only SPDX header; preserve third-party attribution.
For documentation-only changes, verify instructions and links; a firmware run is needed only
when establishing or changing build/measurement claims.

## PR user testing instructions

Every PR must include actionable **User test instructions**, separate from the author's
validation evidence. Use the [PR testing skill](.agents/skills/pr-testing/SKILL.md) when
preparing or updating that handoff; its detailed checklist need not be read for unrelated work.
Explain what to test and the expected results. For FM-1 checks, describe the complete route
from a known device state to the function, including buttons, hold/tap gestures, pages and
knobs. Mark unperformed device checks pending. For changes that need no hardware testing,
explain why and give the applicable documentation or tooling checks instead.

## Real FM-1 CLI diagnostics (macOS/Linux)

Run `tools/fm1_diagnostics.py` on the host connected to the FM-1 by USB. It uses Python 3's
standard library. Enable **USB SERIAL** on the device, close other serial applications,
and explicitly select its CDC tty; the collector does not discover or select ports.
Follow the [idle baseline setup](docs/diagnostics.md#idle-baseline-setup) to reach a
stopped HOME screen with no MIDI/audio stream or held notes. From the repository root,
replace the example port with the connected device's port:

```sh
# macOS
python3 tools/fm1_diagnostics.py --port /dev/cu.usbmodem1234 \
  --scenario 'idle; transport stopped; no MIDI/audio stream; USB SERIAL on' --duration 60 --interval 5
# Linux
python3 tools/fm1_diagnostics.py --port /dev/ttyACM0 \
  --scenario 'idle; transport stopped; no MIDI/audio stream; USB SERIAL on' --duration 60 --interval 5
```

The scenario is a report label: arrange and run the stated workload separately. For
playback or stress tests, document the starting project, track/engine/preset, effects,
MIDI/audio configuration and exact panel actions or external input sequence before
collection; a label such as "four-track playback with effects" is not a setup procedure. The
collector sends only `status`, `dbg`, `inp` and `crash`; it does not generate MIDI load,
control the panel, change settings or flash firmware. Reports (`summary.json`,
`samples.jsonl`, `console.raw`) go to a new directory under ignored `build/diagnostics/`.
See [the diagnostics guide](docs/diagnostics.md) for supplied device-build provenance,
timeouts, input instrumentation and capture interpretation.

`VALID` means collection was complete and continuous, not that the firmware passed.
Inspect counter deltas for audio lateness, voice shedding, USB errors and UART drops;
listen to the audio and check panel responsiveness. `cpu_pct` measures audio render load,
not whole-chip CPU utilization. Assess static RAM/POOL usage from the matching target
build under [the performance guide](docs/performance.md); the collector does not measure
live RAM or stack high-water usage. Emulator replay and host stress results remain
separate from device evidence. If this session cannot access the connected host/device,
report real-device checks as pending rather than treating host fixtures as hardware tests.

## Completion evidence

Report the revision and build flags, tests passed/skipped, firmware and RAM deltas, and
the workload/method behind CPU claims. Separate host regressions, target static estimates,
browser behavior and real FM-1 observations. Hardware-dependent changes require real-device
validation under `CONTRIBUTING.md`; if unavailable, name the remaining hardware checks.
Flash or publish only within the user's requested scope. Commit or push when requested,
and keep generated binaries, logs and temporary measurements under ignored `build/`.
