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
| Scan registered firmware sources, backfill history or maintain scan progress | [Firmware-watch skill](.agents/skills/firmware-watch/SKILL.md) and [ledger guide](docs/firmware-watch.md) |
| Plan build profiles, usage modes, new engine IDs or new persistent data | [docs/modularity.md](docs/modularity.md) and the issues it maps; for flash sectors, saved bytes or retained RAM, the [capacity plan](docs/flash-capacity.md) |
| Create or update a PR, or hand off a change for user testing | [PR testing skill](.agents/skills/pr-testing/SKILL.md) |

If this checkout has a `.codegraph/` index, use CodeGraph first to locate code and trace
callers. Otherwise use normal source search; indexing is the owner's choice.

## User-facing documentation

During development, read [README.md](README.md) and assess whether the change affects
the fork's purpose, overall progress, available engines, installation or compatibility.
This is a personal integration fork collecting features, engines and optimizations
from upstream and other forks, with a focus on CPU, RAM and firmware-size improvements.
Keep that purpose clear and distinguish implemented capabilities from plans and experiments.

Update the README in the same PR for meaningful milestones or changes to that overview.
Summarize the resulting capability or development stage; do not add a changelog entry
for every commit, small fix or internal optimization. Put detailed controls, defaults,
limitations and compatibility instructions in [the fork feature guide](docs/fork-features.md)
or the relevant focused guide, and link from the README when discoverability requires it.
Keep performance claims tied to documented measurements and their validation scope.

Before completing the change, record the README assessment in the PR description
(or completion report when there is no PR): name the sections updated, or explain
specifically why the existing README already covers the resulting behavior. If a broader
README change would be useful but depends on unresolved scope or direction, propose the
concrete wording in that report and identify the open decision. Apply clear, factual
documentation updates directly without waiting for a separate request.

## Architecture and ownership

### Choose the repository before implementation or issue creation

| Repository | Implementation and issue ownership |
| --- | --- |
| [kmplngj/Felucca-Engines](https://github.com/kmplngj/Felucca-Engines) (MIT) | Portable engines, engine-exclusive presets/assets/generators, reusable DSP/interface and collection tests with an MIT-compatible source/dependency closure. Maze, original-data Bouba/Kiki, Paula and WAVE S belong here. |
| [kmplngj/Felucca-Engines-GPL](https://github.com/kmplngj/Felucca-Engines-GPL) (GPL) | GPL-derived portable engines, their exclusive content/generators and collection tests, including DUELL WAVE, JUNO, SID, CZ, Prophet and other GPL fork ports. Retain permissive dependencies' own notices. |
| [kmplngj/Felucca](https://github.com/kmplngj/Felucca) | Firmware host: global stable IDs, registration/profiles, exact dependency pins, voice/arena and service hooks, hardware, native panel/MOD, effects, storage, firmware-produced protocol/descriptors, emulator/runtime, integration and FM-1 qualification. Cross-repository adoption plans stay here. Existing firmware-native engine work stays here until an explicitly scoped extraction. |
| [kmplngj/Felucca-WebApp](https://github.com/kmplngj/Felucca-WebApp) | Editor/installer client code, UI/assets, client tests and consumption of firmware descriptors/protocol. This repository does not own the firmware protocol or engine registry. |

Check the selected repository's live Issues setting and open/closed issues, relevant
comments and PRs across all four repositories before creating work. Reuse existing
owners and follow transferred URLs. If WebApp Issues is enabled, create client tickets
there. While disabled, track them in Felucca with a `Felucca-WebApp:` title and an
explicit **implementation repository: kmplngj/Felucca-WebApp** line; do not change
repository settings just to file a ticket. Client implementation and PRs still go
to WebApp. Resolve inaccessible or disabled engine destinations as a blocker rather
than silently filing portable engine work in firmware.

Choose the collection from the actual copied files, transitive dependencies and
asset licenses, not the donor's root license or the final firmware's GPL license.
Never relabel GPL code or host helpers as MIT. Retain Apache/BSD/MIT and asset notices
individually; GPL placement does not clear restricted factory banks, samples or artwork.
Unresolved provenance blocks copying; keep mixed-license source-selection work in
a Felucca coordination issue until the implementation boundary is established.

Split portable engine work from host integration and client work into linked issues
and PRs. Put source pins, provenance, portable controls/contracts and engine tests
in the collection issue; link a Felucca host owner for global IDs, profiles, memory,
services, persistence/protocol and hardware acceptance, plus a client owner if needed.
Do not reserve a global firmware ID in a collection alone. Commit/review collection
changes there first, then update Felucca to an exact commit and validate integration;
do not leave dependency edits only inside a submodule checkout. `firmware/engines/`
is the current MIT pin. The GPL collection and intended `firmware/engines-gpl/` pin
are still pending [#360](https://github.com/kmplngj/Felucca/issues/360), not a working
build input. The [instrument routing review](docs/instrument-issue-routing.md) records
the moved ideas and retained integration owners.

### Firmware locations

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
