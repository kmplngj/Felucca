<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Felucca development guide

Felucca is bare-metal synth firmware for the M-VAVE FM-1 (JieLi AC791N / pi32v2).
Develop for the actual JieLi Clang 4.0.1 toolchain, its memory map, and audio deadlines.
Host tests and the browser emulator compile the real DSP sources against simulated hardware.

## Commands

Run from the repository root; setup and environment overrides are in [BUILDING.md](BUILDING.md).

```sh
uv run --locked --group build ./build.sh                       # target firmware and host harnesses
uv run --locked --group build tests/run_tests.sh --ai-output   # full host suite, compact output
npm test --prefix web/emu                                      # browser gate, after a fresh emulator build
```

Short DSP iteration after a successful build (rebuild the harness after source changes):

```sh
build/host/regress tests/golden.txt tests/cpu_baseline.txt
build/host/regress_os tests/golden.txt tests/cpu_baseline_os.txt
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
build/host/union_test tests/union_golden.txt  # engine-memory changes
```

## Start here

1. Check the branch and working tree; preserve changes belonging to other work.
2. Read the relevant sources and the documents below before changing behavior.
3. For an optimization, capture a baseline from the unchanged revision, change one cause,
   and repeat the same measurements. Report bytes and timing with their provenance.

| Before you… | Read |
| --- | --- |
| Build, generate assets, or run tests | [BUILDING.md](BUILDING.md) |
| Collect diagnostics from a connected FM-1 | [docs/diagnostics.md](docs/diagnostics.md), including [idle setup](docs/diagnostics.md#idle-baseline-setup) and [interpretation](docs/diagnostics.md#interpreting-a-report); [docs/performance.md](docs/performance.md) |
| Add or change diagnostic commands, fields, build flags or host tools | [Diagnostic capabilities](docs/diagnostics.md#diagnostic-capabilities), [BUILDING.md](BUILDING.md), and the affected usage/protocol guide |
| Change DSP, interrupt scheduling, buffers, compiler options, or resource use | [docs/performance.md](docs/performance.md) |
| Change MIDI, saved parameters, backup, or editor messages | [web/EDITOR_PROTOCOL.md](web/EDITOR_PROTOCOL.md), the affected serializers and their tests |
| Contribute or package third-party code/data | [CONTRIBUTING.md](CONTRIBUTING.md), [LICENSING.md](LICENSING.md) |
| Add an engine, effect or platform/persistence hook | [docs/extending.md](docs/extending.md) |
| Create an issue, start engine work or split work across repositories | [Repository ownership](docs/repository-ownership.md) |
| Evaluate an idea from another FM-1 firmware | [The dated development review](docs/development-review-2026-10-11.md), then that project's current source |
| Scan registered firmware sources, backfill history or maintain scan progress | [Firmware-watch skill](.agents/skills/firmware-watch/SKILL.md) and [ledger guide](docs/firmware-watch.md) |
| Plan build profiles, usage modes, new engine IDs or new persistent data | [docs/modularity.md](docs/modularity.md) and the issues it maps; for flash sectors, saved bytes or retained RAM, the [capacity plan](docs/flash-capacity.md) |
| Select or implement a batch of related issues for one hardware handoff | [Batch procedure](docs/development-batches.md); prefer two or three issues sharing a subsystem and test setup |
| Complete a change: README, changelog and diagnostic-guide assessment | [Documentation policy](docs/documentation-policy.md) |
| Create or update a PR, or hand off a change for user testing | [PR testing skill](.agents/skills/pr-testing/SKILL.md) |

If this checkout has a `.codegraph/` index, use CodeGraph first to locate code and trace
callers. Otherwise use normal source search; indexing is the owner's choice.

For AI-assisted work, use [the workflow guide](docs/ai-workflows.md) when planning
context or reporting changes to AI tooling. Read task-specific references once
per revision, and inspect summaries before raw logs or media. Keep large outputs
under ignored `build/`; page required evidence rather than accepting truncation.
Preserve complete relevant diffs, callers, invariants and validation coverage.

## Every change considers

- **Three builds.** The target firmware, host tests and browser emulator compile the same
  sources; shared code and macros must build in all three.
- **Every resource budget.** Flash, RAM, stack and interrupt time are judged together; a
  saving in one is reported with its effect on the others.
- **Older data and clients.** Saved projects, presets and backups from earlier firmware
  still load, and Felucca-WebApp still talks to every released firmware.
- **Build profiles.** An engine or feature may be absent from a profile; see
  [docs/modularity.md](docs/modularity.md).

## Reuse before reimplementing

Before writing a function, DSP block, table, queue, parameter path or tool, search for
one that already does the job, and extend or generalize it in its owner:

- Fixed-point math, oscillators and shared DSP: `firmware/engines/src/dsp.c` and
  `felucca_engine.h`; firmware-side blocks in `firmware/src/*_dsp.c`.
- Tables and generated headers: the existing `tools/gen_*.py` generators.
- Main-loop work requested from an interrupt: the existing request/service paths.

A port from another fork adapts to Felucca's helpers instead of carrying its own copy.
Keep a parallel version only for a stated, measured reason, such as interrupt-path cost.

## Architecture

Repository choice and license placement are in [Repository ownership](docs/repository-ownership.md).

| Location | Responsibility |
| --- | --- |
| `firmware/src/felucca.c` | Single translation unit: includes the other C files in dependency order |
| `firmware/src/core.h`, `engines.c`, `voice.c` | Types, stable engine IDs, per-part engine memory, voice allocation |
| `firmware/src/sound.c` | Sound install: the one path that publishes engine, preset and values into a track ([extending](docs/extending.md#14-switching-fades-and-reset)) |
| `firmware/src/audio.c`, `fx.c`, `eng_*.c` | Audio interrupt, mixer, effects, engines, fixed-point helpers |
| `firmware/src/main.c`, `ui*.c`, `panel.c` | Boot, main loop, UI and panel event handling |
| `firmware/src/ui_knob.c` | Panel knob editing: the value a knob edits on HOME, MIXER, a page, GLO and MOMENTARY, and its turn/capture/LEARN policy ([extending](docs/extending.md#38-panel-drawing-and-main-loop-services)) |
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

Rebuild the affected harness after source changes; an existing binary is not evidence for
new code. Finish firmware changes with the full applicable suite, a fresh target build
with no new warnings, and the resource checks in `docs/performance.md`. Record every skipped
check, especially unavailable host instruction counters, DaisySP or browser tooling.
For UI changes, inspect the generated `build/ui_new/` images and the actual panel behavior;
for USB/MIDI changes, exercise the affected host configuration and hardware path.

`--ai-output` keeps full logs while printing compact results; see
[the output contract](BUILDING.md#tests). Inspect warning/skip hints and failed,
blocked or cancelled logs. Omit the flag for the complete console transcript.

For browser UI/audio changes, run the [cloud browser gate](docs/cloud-testing.md)
after a fresh emulator build. Read its one-line result and
`build/browser/run-*/summary.json` first; open only media relevant to a failure.
The gate makes no model calls and keeps screenshots/WAV only on failure by default.
Reuse existing replay scenarios and deterministic comparisons before requesting
visual/audio model review. Keep full logs, PCM and repeated screenshots in `build/`
rather than agent context. Browser/emulator evidence remains separate from FM-1 evidence.

`GOLDEN_UPDATE=1` and `BUDGET_UPDATE=1` intentionally rewrite baselines. Use them only for
explained changes in sound or cost, review every changed entry, and retain unaffected entries.
A failed budget is a finding to investigate, not a reason to regenerate all baselines.

New source files carry the GPL-3.0-only SPDX header; preserve third-party attribution.
For documentation-only changes, verify instructions and links; a firmware run is needed only
when establishing or changing build/measurement claims.

## Tests worth keeping

A checked-in test pins behavior that can regress, and fails without the change it covers:

- a contract: engine and parameter IDs, wire format, saved-data round trips, old-format
  imports and malformed input;
- a bound: memory fit, stack, budgets and deadlines;
- a sound: golden output for a defined workload;
- a reproduced bug: the scenario that failed before the fix.

Exercise the path the firmware uses, through its public entry points, and extend the
existing harness (`regress`, `union_test`, the protocol and backup tests, browser
replay scenarios) before adding a new binary. Development probes that only restate the
implementation or a constant stay under ignored `build/`.

## PR user testing instructions

Every PR must include actionable **User test instructions**, separate from the author's
validation evidence: what to test and the expected results. For FM-1 checks, describe the
complete route from a known device state to the function, including buttons, hold/tap
gestures, pages and knobs. Mark unperformed device checks pending. For changes that need
no hardware testing, explain why and give the applicable documentation or tooling checks.
The [PR testing skill](.agents/skills/pr-testing/SKILL.md) holds the full procedure.

## Completion evidence

Report the revision and build flags, tests passed/skipped, firmware and RAM deltas, and
the workload/method behind CPU claims. Separate host regressions, target static estimates,
browser behavior and real FM-1 observations. A `VALID` diagnostics capture establishes
continuity only; render load is not whole-chip CPU use, and collection does not measure
live RAM or stack. Hardware-dependent changes require real-device validation under
`CONTRIBUTING.md`; if unavailable, name the remaining hardware checks. Record the README,
changelog and diagnostic-guide assessments from the [documentation policy](docs/documentation-policy.md).
Flash or publish only within the user's requested scope. Commit or push when requested,
and keep generated binaries, logs and temporary measurements under ignored `build/`.
