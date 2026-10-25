<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Measuring and optimizing Felucca

Use this procedure for DSP, interrupt, memory, compiler, font/sample or firmware-size work.
Build setup remains in [BUILDING.md](../BUILDING.md); the budget authorities are
`firmware/app.ld`, `tools/build.py`, `tests/regress.c` and `tests/target_budget.py`.
Re-read them if their behavior changes. Dated resource figures below precede the 1.6.1 backport. The default now compiles second-core
support while its runtime preference stays OFF; measure both that build and `FELUCCA_CPU2=0`
under the current [modularity direction](modularity.md).

## Establish a comparable baseline

1. Record the revision and local diff, target and host compiler versions, SDK revision,
   feature flags, sample assets and whether selective size optimization is enabled.
2. Build and run the relevant regression/stress workloads before editing. Preserve the
   logs, target disassembly and binaries under a separate ignored `build/` subdirectory.
3. Repeat the same build and workloads after the change. Compare CPU, both RAM regions,
   app size, audio output and latency; an improvement in one does not establish the others.

Basic capture (choose a new directory name for each baseline/candidate). Set the
positional arguments to the untracked source/assets that affect this build, using
repository-relative file paths; leave them empty when there are no such inputs:

```sh
set -eu
set --  # Example: set -- 'firmware/src/new engine.c' 'assets/new sample.wav'
mkdir -p build/perf-before
git rev-parse HEAD > build/perf-before/revision.txt
git diff --binary HEAD > build/perf-before/local.diff
git diff --binary --cached > build/perf-before/index.diff
git status --porcelain=v1 -z > build/perf-before/status.paths0
git ls-files --others --exclude-standard -z > build/perf-before/untracked-candidates.paths0
: > build/perf-before/untracked-inputs.paths0
if [ "$#" -gt 0 ]; then
    printf '%s\0' "$@" > build/perf-before/untracked-inputs.paths0
    COPYFILE_DISABLE=1 tar -cf build/perf-before/untracked-inputs.tar -- "$@"
fi
./build.sh > build/perf-before/build.log 2>&1
env -u GOLDEN_UPDATE -u BUDGET_UPDATE tests/run_tests.sh > build/perf-before/tests.log 2>&1
cp build/felucca.bin build/felucca.elf build/felucca.dis build/felucca.dis.profile.json build/felucca.fwsc build/perf-before/
```

`local.diff` records the tracked working tree relative to `HEAD`, including both staged
and unstaged changes, with binary payloads. `index.diff` records the index separately.
The NUL-delimited candidate list records all non-ignored untracked paths; it is an
inventory, not the inputs' contents. Review that list and populate `set --` with the
build-relevant files before running the capture. The selected-path list and tar archive
preserve those files, including names with spaces and binary assets. Archive only the
inputs needed for this build; keep unrelated files and credentials outside the archive.
`COPYFILE_DISABLE=1` omits macOS AppleDouble metadata entries from this build-input archive.

To reconstruct the measured inputs in a clean checkout at `revision.txt`, apply the
nonempty `local.diff`, restore the selected untracked archive, and reproduce the recorded
flags/toolchain/SDK. To reproduce staging as well, apply the nonempty `index.diff` with
`git apply --cached` after restoring the working tree. A candidate list without the
selected inputs' contents is not complete provenance for a build that uses them.

Keep `felucca.dis.profile.json` beside its matching listing when archiving or renaming
disassembly. The target budget checker verifies its listing hash and selects the recorded
engine set, independently of the current `build/gen` profile. A listing without a sidecar
retains the historical full checks; a stale or incompatible sidecar fails validation.

Run the build and suite sequentially and check each exit status before using its artifacts.
For release builds, substitute the actual versioned package name. Record the relevant
environment overrides separately; do not archive unrelated credentials/environment variables.

## CPU: three different kinds of evidence

| Method | Measures | Interpretation |
| --- | --- | --- |
| `build/host/regress`, `build/host/regress_os` | Host instructions per sample and informational ns/sample, with separate compiler settings/baselines | Relative DSP cost on the same host/compiler; the `-Os` run disables vectorization, but neither run measures pi32v2 cycles or FM-1 utilization |
| `tests/target_budget.py` | Weighted instructions in target-disassembly loops, with divide and nesting penalties | A static regression heuristic; not execution time or a complete call-graph cost |
| FM-1 `status`, `dbg`, `inp` | Render timing, audio lateness, shedding, USB glitches and scan timing | Actual device observations for a stated workload and interval |

### Host regression

The full runner rebuilds the harness using the real firmware sources. For repeat sampling
of that unchanged build with Apple Clang on macOS arm64:

```sh
build/host/regress tests/golden.txt tests/cpu_baseline.txt
build/host/regress_os tests/golden.txt tests/cpu_baseline_os.txt
```

On other toolchains, use the qualified baseline paths printed by the runner instead
(or `-` to skip the CPU budget when that baseline is absent).

The runner builds `regress` at `-O2` and `regress_os` at `-Os` with vectorization
disabled. Clang uses `-fno-vectorize -fno-slp-vectorize`; the runner probes for those flags
and uses GCC's `-fno-tree-vectorize -fno-tree-slp-vectorize` when needed. Both use the same
audio goldens, but each uses its own CPU baseline. Prefer the latter when investigating
work hidden by host SIMD, and retain both checks. Its settings resemble the target's;
its instruction count still comes from the host architecture.

`regress.c` warms CPU scenarios for 0.5 s and counts the next 1 s. On macOS it uses
`proc_pid_rusage(..., RUSAGE_INFO_V4).ri_instructions`. On Linux each forked worker opens
`perf_event_open(PERF_COUNT_HW_INSTRUCTIONS)` for itself (user space only, calling thread,
`pid` 0, `cpu` -1; no root with `perf_event_paranoid` <= 2) and reads it with enabled/running
times; a multiplexed interval (running < enabled), a failed open or read, or a short read gives
no count. If any worker has no count, the entire CPU budget is explicitly skipped with the reason:
no partial comparisons, CPU failure or baseline update. Worker crashes and audio/voice failures
still fail the suite. A skipped budget is never reported as passed
(common reasons: `perf_event_paranoid` > 2, containers or VMs without a PMU). When counting,
the run prints the platform, architecture, compiler, flags and counter source.

CPU baselines are per platform and toolchain. Apple Clang on macOS arm64 retains the historical
`tests/cpu_baseline.txt` and `tests/cpu_baseline_os.txt` files; these legacy files still require
the same measured host/compiler when comparing costs. Other hosts/toolchains use
`tests/cpu_baseline_<os>_<arch>_<compiler>_<version>_<build-id>.txt` and the corresponding
`_os.txt` file. `tests/cpu_baseline.py` probes the actual `CC`, including wrappers, for compiler
macros: family (GCC/Clang), major/minor/patch version and a 12-digit SHA-256 prefix of the full
vendor/build version. Compiler aliases with identical macros select the same files; different
compiler families, versions or vendor builds select separate files. The runner prints the paths.
Old unqualified Linux filenames are no longer selected; review/re-measure them before adopting
the qualified names. If the file is missing the CPU budget is skipped (`regress` is passed `-`),
not created. To adopt a
host, run `BUDGET_UPDATE=1 tests/run_tests.sh` on it with a working counter (nothing is written
otherwise), review, and commit the files. Instruction counts differ by ISA, compiler and
microarchitecture, so a baseline is valid only for that host and toolchain. Preset budgets subtract the idle mixer cost. Failure requires a
growth above both 25% and 20 instructions/sample; mixed workloads use their full cost.
Host ns/sample depends on scheduling, clock and compiler, so compare repeated runs on
the same machine and keep CPU-heavy unrelated work out of timing experiments.

### Host retirement observation

The explicit [voice-retirement/LFO measurement](voice-retirement-measurement.md)
uses `tools/retirement_measure.py` to compare unchanged source, an observer and a
narrow fresh-phrase counterfactual in separate ignored host snapshots. It is off
unless invoked and adds no device transport, production hook, target flag or
resource reservation. Observer file IO invalidates host timing/cost comparisons;
CPU_FILE `-` means CPU budgets are not checked. PCM/state observations do not
establish a retirement policy, target timing or device behavior. Use the focused
guide's pinned inputs, prerequisites and reproduction steps.

### Target regression

```sh
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
```

Rebuild first: the script succeeds with a **skip** when disassembly is missing. It weights
loop nesting by 4 and divides by 9 and fails above the checked-in cost by 10%. Inspect
changed loops, new divides and calls in `build/felucca.dis`. Backward branches are treated
as loop spans: compiler layout can therefore distort the estimate. A moved hot helper
can escape the caller's count; keep coverage in `FUNCS` and inspect the callee as well.
Missing budget entries are reported but do not themselves fail. Passing this check alone
does not prove deadline headroom.

Early USB rescue shares the physical scan and USB poll with startup/main-loop
code. JieLi consequently outlines `usb_poll`, `fm1_input_tick`, `fm1__frame` and
`fm1__keys` from TIMER5. The caller's loop score drops because those instructions
move to callees; this is not evidence of faster interrupt service. All four stay
in the ISR-protected `-Os` closure. Separate optional budgets retain coverage when
they are outlined: 23757, 14, 134 and 204 respectively, using the largest measured
default/CPU2-off target score for this change. Existing ISR and engine baselines
are unchanged. These heuristic scores must not be summed into a timing claim.
The physical-entry correction powers PA2 before scanning and uses the tick scanner
in place of the old full-frame caller. `fm1__frame` and `fm1__keys` explicitly stay
outlined: otherwise JieLi folds them into `fm1_input_tick`, changing its isolated
score from 14 to 220. With the boundaries preserved, the default build retains
the original 344/137/82 total instructions and 14/134/204 scores for those three
functions, with no budget changes.

The combined optimization integration calibrates only the optional `mix_part`
score from 2,800 to 3,549. Against unchanged main `0b407accd60f755e96a26a58419ebdd218090419`,
the same JieLi Clang 4.0.1 default build has 679→684 total instructions and
598→603 instructions in backward-branch spans; both have six divides and 18
calls in those spans. Through offset `0x7a4`, the instruction operations and
control flow are unchanged; addresses relocate and two UI-state field offsets
move by four bytes. The five added instructions are in the silent
part's cold epilogue: `ins_rest` now calls the word-based `memset` rather than
inlining the byte loop, and the compiler duplicates a `mod_end` branch after
that call. Crossing backward spans increase the estimator's nesting weights,
producing the larger score despite unchanged hot loops. This is a narrow static
coverage calibration; it does not claim a 27% runtime increase or a device speed
improvement. This adjustment leaves the 10% tolerance, other function budgets and sound
goldens unchanged; the separate ANALOG, TOM and FX calibrations belong to their
original optimization changes and are recorded in `tests/target_budget.txt`.
Real-device timing and nested-interrupt stack checks remain pending.

`tests/mul64_hload_check.py` is a separate, informational target listing check: it counts 64-bit
multiplies and 16-bit loads per function and their ISR reachability (issue #425). It is not part of
the budget and gates nothing; see [the audit](mul64-hload-audit.md).

### Device timing and stress procedure

When a device run is in scope, use the existing CDC console with USB SERIAL enabled and
collect `status`, `dbg`, `inp` and `crash` (see `firmware/src/console.c`). Enabling serial
changes USB enumeration; use the same configuration for baseline and candidate.

At current settings, `HALF_FRAMES=128`, `FS=44100`, `CTL=32`: four control blocks per DMA
half and a nominal deadline of `128 * 1e6 / 44100`, about **2,902 us**. The I2S clock in
`audio.c` uses 544 crystal ticks per frame, about 44,117.6 Hz; the nominal deadline is the
firmware's own budgeting convention. TIMER4 is a 24 MHz wall clock, not the CPU clock.
The 10 kHz TIMER5 scan nests above audio.

Observe the following together:

- `cpu_pct`: a smoothed render/deadline ratio over roughly 93 ms. `shed_check()` subtracts
  nested TIMER5 ticks first, so this meter excludes that work and the main loop. It is
  **not whole-chip CPU utilization**.
- `audio_max_us`: maximum render time with nested scan time subtracted. Diagnostics in
  `.noinit` can survive reset; take a starting snapshot and identify prior maxima.
- `audio_late`: cumulative DMA deadline misses. Compare end minus start, using a workload
  interval; a low average cannot dismiss new misses.
- `voices_shed`: overload protection, triggered after two consecutive halves above 85%
  **including** nested TIMER5 time. A lower CPU reading accompanied by more shedding is
  not an equivalent-workload improvement. `voices_given_up` counts every
  `voice_kill()` fade: budget/allocator victims, overload victims and MIDI
  All Sound Off. It is not a count of rejected requests or admitted voices.
  `voices_shed` is the overload subset. Their difference describes non-overload
  kill calls only when those other sources are known; read back voices separately
  to measure the surviving load.
- `uac_underruns`, `uac_overruns`, `uac_missed`, `uac_stalls`, UART drops and USB stalls:
  capture their deltas while streaming and playing, not just an idle snapshot.
- `inp`: scan cost, worst gaps, encoder losses and key latency. It clears its interval
  statistics after reading; discard the first interval and sample equal windows thereafter.
  Key timing instrumentation is conditional on `FM1_INPUT_LAT`; zero counters without it
  are not a latency measurement (see `fm1_input.h`, `seq.c`, `audio.c`).

Suggested repeatable workload matrix: idle; the heaviest measured presets on each engine;
the shared voice limit across four parts; dense drums/ratchets plus fast sequencer and
modulation; INSERT and reverb/delay/chorus with performance throws; engine changes with
release tails; then those loads with continuous panel turns/redraws and USB audio at both
44.1 and 48 kHz plus USB/TRS MIDI traffic. Save operations are a separate scenario: observe
the documented pause, coalescing and recovery. Keep notes, presets, settings and duration
identical between runs. A 60 s steady run after warm-up is a useful initial screen, followed
by longer runs for timing-sensitive changes; record the chosen duration.

For ordinary workloads, require no new audio misses, overload shedding or stream errors
during the measured interval. For intentional overload tests, compare degradation and
recovery against baseline. Listen to/record the output for clicks, clipping, silence and
tails and check panel responsiveness. If hardware is unavailable, report the device columns
as unmeasured. Stage timing instrumentation and percentiles would need additional code;
the current console exposes averages and maxima, not p95/p99 histograms of audio cost.

The [2026-10-21 FM-1 investigation](audio-deadline-investigation-2026-10-21.md)
records a concrete PHYS request/surviving-voice envelope, capture-on/off controls and
acquisition limits. Its short-run observations are not a universal polyphony limit.

## RAM and stack

The build reports `.data+.bss` and `.pool` separately and fails unless at least **4,096 B**
of RAM and **8,192 B** of POOL remain. The current linker split is 72 KiB RAM / 360 KiB
POOL. It is one SRAM: moving the boundary reallocates budget, it does not create memory.
Report used and spare bytes for both regions.

The same check guards `.noinit`, the region that survives a warm reset ([capacity plan](flash-capacity.md#23-retained-ram-and-the-ram-mirrors)
rule A7): the build fails unless at least **100 B** of its 15,696 B (`0x3D50`, from `app.ld`) stay
unallocated (`NOINIT_SPARE_MIN` in `tools/build.py`, which prints `NOINIT <used> B of <length> (<spare> B spare)`).
The linker script defines no symbols for this section, so the used size is the larger of the `.noinit`
section's end in `objdump -h` (which also covers allocations without a sized symbol, such as `.space` data or
tail padding) and the end of the highest `.noinit` object in `objdump -t` (the snippet below lists the same
rows); the linker itself already refuses an overflow. The v1.6 baseline uses 15,564 B (132 B spare). In the 1.6.1 backport, the default
`FELUCCA_CPU2=1` build used 15,568 B (128 B spare): the existing crash record gains a
4-byte core identifier. The retained CPU1 exclusion guard (#410, 8 B, `fm1_c1_guard` in
`hal/fm1_sys.h`) brings the default build to 15,576 B (120 B spare); `FELUCCA_CPU2=0`
retains 15,564 B (132 B spare).
The only exception is the opt-in diagnostic build `FELUCCA_CRASH_CTX=1` (#428): its crash record keeps
one full register set (+76 B, 15,652 B used, 44 B spare), so that build alone checks a floor of 24 B
(`CRASH_CTX_NOINIT`); release and standard builds keep 100 B, and `--release` refuses the flag.
`tests/build_guard_test.py` covers the exact 100 B boundary, the one-byte failure and padding without a symbol. Raising the floor or
adding a `.noinit` user needs the plan's rule A7 review first.

Static accounting also includes `.ram_text`, `.noinit`, reserved RAM and the two stack
windows in `app.ld`. Stacks and guard bands follow the pool at fixed addresses; retain the
current spare margin and actual section placement. `.noinit` diagnostics and restore state
consume their own region. Host RSS, Wasm memory and the `.elf` file size are different
measurements, not firmware SRAM usage. Firmware storage is statically allocated; heap
statistics are not the useful baseline here.

Run the following from the root after a build for target sections and largest RAM objects.
It uses the same native/Docker selection as the build and respects `JIELI_TOOLCHAIN`:

```sh
python3 - <<'PY'
import os
from pathlib import Path
from tools import build

os.environ.setdefault("JIELI_TOOLCHAIN", str(Path.home() / ".jieli/toolchain"))
elf = build.OUT / "felucca.elf"
print(build.tc("common/bin/objdump", "-h", elf))
rows = []
for line in build.tc("common/bin/objdump", "-t", elf).splitlines():
    p = line.split()
    if len(p) < 5 or p[-3] not in (".data", ".bss", ".pool", ".noinit"):
        continue
    try:
        rows.append((int(p[-2], 16), p[-3], p[-1]))
    except ValueError:
        continue
for size, section, name in sorted(rows, reverse=True)[:20]:
    print(f"{size:8d} B  {section:8s} {name}")
PY
```

Optimize by proven lifetimes and multiplicative cost. `ENG_MEM_PART` grows once per part
(x4), voice fields grow per stored voice per part, and an FX buffer grows per sample and
channel. `eng_mem` already shares mutually exclusive engine state; verify every switch
with `union_test` before claiming further reuse. Keep immutable tables/assets in XIP.
Large automatic arrays and recursion spend stack even when static section sizes stay flat.
The hardware guards detect violations, not stack high-water usage; watermark measurement
would require separate instrumentation and nested-interrupt stress.

Engine-arena owner checks (host only): `-DFELUCCA_ARENA_CHECK=1` turns `ENG_MEM_OF`
(`engines.c`) into a checked accessor for GRAIN (`gr_of`), PHYS (`phys_slot_of`), DRUM
(`drum_kit_of`), FM6 (`fm6_note_of`) and SLICE (`slc_rb`). At each access it checks the part
(an aligned `trk[]` element), the engine being rendered (`t->engine`; `eng_req` may name the
next engine during a fade and is no owner) and the claimed owner (`eng_mem_owner`). A failure
calls `eng_arena_fail` before any access and hands back scratch memory. Without the define the
macro is plain `ENG_MEM(p)`: no code or data (identical `-O2`/`-Os` host assembly of
`tests/regress.c`; the target build is untouched). Fresh matched JieLi release
[standard, CPU2-off and MACRO builds](arena-check-target-footprint-139.md) also
prove byte-identical complete ELF/app/map output with the disabled wrappers removed. `tests/arena_test.c` (negative fixtures,
fixed-seed random runs) and a checked `union_test` run from `tests/run_tests.sh`, also under
ASan/UBSan. Limits: it does not see an out-of-bounds write inside the arena or a wrong slot of
the right owner, and engines that keep state outside the arena (WHEEL, `gr_rng`) are not covered.

## Firmware size and optimization order

Measure `build/felucca.bin` against `APP_SLOT` (`tools/fm1pkg_make.py`, currently
`0x8DFBC` = **581,564 B**). It includes XIP code/constants and the load images for RAM
code and initialized data. `.bss`/`.pool` have no payload in it. The `.fwsc` includes
loader, SDK files and packaging; its byte count is not the app-slot utilization.

Start with measured cost: hoist invariant coefficients and divisions out of per-sample
loops; reuse existing fixed-point helpers and tables; preserve the exact arithmetic
where output equivalence is intended. Inlining can trade app bytes for speed; inspect
the pi32v2 assembly and compare both host CPU baselines and the target budget. Keep
disabled effects' idle fast paths and bounded voice allocation. Size work should first
target noncritical UI/editor/store
code and generated assets, with visual/audio fidelity checks for asset changes.

`FELUCCA_SIZE=0 ./build.sh` disables the selective `minsize` pass for an A/B experiment;
archive the default result first, then rebuild the default afterward. LLVM 4 documents
that `minsize` may sacrifice runtime speed, unlike `optsize`'s more limited tradeoff:
[LLVM 4 function attributes](https://releases.llvm.org/4.0.1/docs/LangRef.html#function-attributes).
Current compiler flags and reachability exclusions are authoritative in `tools/build.py`
and `tools/size_fns.py`. The [remaining-helper experiment](selective-minsize-521.md)
measured a 64 B option for HELP/category helpers and rejected promotion because
of extra main-loop calls without service-latency evidence; production selection
is unchanged. Clock/voltage changes, a second core, or FPU/DSP rewrites are
separate hardware experiments with their own correctness, timing and reliability evidence.

## Soft-double link guard

`tools/build.py` always rejects known JieLi Clang 4.0.1 double-precision runtime
helpers defined in allocated executable sections of the final application ELF.
The [build policy and target probes](../BUILDING.md#final-image-soft-double-policy)
describe its exact arithmetic/conversion scope, excluded symbol states and
retained evidence. Integer-only 64-bit and fp32 helpers remain allowed by this
guard. Malformed matching symbol/section evidence fails rather than reporting
absence; the existing resource, ROM, HAL and flash-safe guards remain independent.

This prevents a class of future linked-helper regressions. It is not a measured
CPU or size improvement, a source-level double ban, or proof of single-precision
hardware FPU use. Inlined software arithmetic and new ABI names are outside its
exact-name policy. When a helper is reported, inspect its caller and conversion
units before changing arithmetic; then repeat the applicable sound, target budget,
resource and device measurements. A clean guard result cannot establish deadline
headroom or qualify a future float-kernel/FPU experiment.

## Report a result

Record: revision/diff, compiler/SDK/flags/assets, workload and duration, host counter
availability and repeated costs, target cost deltas, RAM/POOL used/spare, app/package
bytes, golden/audio results, device timing/error deltas, and remaining unmeasured paths.
Keep raw logs and artifacts under ignored `build/`. A dated example and the research
behind this procedure are in [the development review](development-review-2026-10-11.md).
