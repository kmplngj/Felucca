<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Felucca development and measurement review — 2026-10-11

This is a dated source/build snapshot, not a rolling policy. The maintained agent entry
point is [AGENTS.md](../AGENTS.md); the repeatable resource procedure is
[performance.md](performance.md). Research covered the local firmware, recent upstream
changes, Tinycast's guide, and three related open-source M-VAVE FM-1 firmwares. No device
was flashed or measured, and no firmware implementation was changed for this review.

Publication context (2026-10-12): the documentation PR is based on fork main at
`89fc57c`, after the target-like host CPU harness (#25) and modal-resonator optimization
(#26) were merged. `AGENTS.md` and `performance.md` describe both current CPU harnesses;
the measurements below remain evidence for the original `ef1f561` snapshot, not the newer
firmware or any other local feature branch. The separately requested input-test warning
fix is outside this documentation PR.

## Baseline and recent Felucca changes

The checkout is at `ef1f561b6b10` (2026-10-11), matching the upstream main commit observed
through GitHub's API. That commit removes sponsorship links; the recent functional
releases are [1.5](https://github.com/hugelton/Felucca/releases/tag/v1.5) and
[1.5.1](https://github.com/hugelton/Felucca/releases/tag/v1.5.1), the latter published on
2026-10-10. This fork's configured origin is `kmplngj/Felucca`; upstream observations
refer to `hugelton/Felucca`, not a newly synchronized remote branch.

The 1.5 commit (`129a4cf`) replaces separate large engine-state arrays with one region
per part and changes the RAM/POOL split to 72/360 KiB. It also changes saved sound/project
layouts for new parameters. The 1.5.1 commit (`a4d7ca2`) keeps that format, moves MIDI
Program Change loading to the main loop and coalesces settings saves that previously
paused audio and LEDs on every PRESETS turn. These are concrete precedents for ownership,
format compatibility and interrupt/main-loop separation. The USB descriptor fix for
older macOS is described by upstream as awaiting confirmation on those OS versions;
host descriptor tests cannot supply it. [1.5.1 release notes](https://github.com/hugelton/Felucca/releases/tag/v1.5.1).

## Fresh local measurements

The default target build was regenerated from the unchanged firmware sources using
JieLi Clang **4.0.1**, toolchain package `jieli-linux-toolchains-20260730.1`, Docker
`linux/amd64`, the default selective size pass, and AC79 SDK commit
`d179b4484759423312073f5fbb232501aa491047`. Sample generation reported five instrument
sets, eleven zones and 126,244 B of ADPCM data. Host harnesses use Apple Clang **21.0.0**
on arm64 macOS. The local Python environment/helper under ignored `build/` was used for
the target build because the shell's default Python lacks Pillow; it is not a portable
repository build entry point. Follow `BUILDING.md` for a new environment.

| Resource | Used | Capacity | Spare | Used % |
| --- | ---: | ---: | ---: | ---: |
| App (`felucca.bin`) | 495,580 B | 581,564 B | 85,984 B | 85.2% |
| RAM (`.data+.bss`) | 54,964 B | 73,728 B | 18,764 B | 74.5% |
| POOL | 327,800 B | 368,640 B | 40,840 B | 88.9% |
| RAMTEXT | 2,924 B | 24,576 B | 21,652 B | 11.9% |
| NOINIT | 15,564 B | 15,696 B | **132 B** | **99.2%** |

The package is 610,086 B (`FM-1_900`, development identity); the update loader is 6,930 B
wrapped / 8,216 B raw. App sections are `.text` 492,240 B, `.ram_text` 2,924 B and `.data`
416 B. All target-build checks passed, including no calls in `.ram_text`, HAL-only
register access, and minimum RAM/POOL margins. These figures account for static sections;
stack high-water use and real-device CPU utilization remain unmeasured.

The largest measured RAM objects make the potential tradeoffs specific:

| Object | Bytes | Implication |
| --- | ---: | --- |
| `dly_buf` | 131,072 | Delay capacity is the largest pool consumer; shortening it changes tempo/time coverage |
| `cv_px` | 59,520 | The 240×124 RGB565 drawing canvas; reuse depends on LCD/DMA completion (`lcd_sync`) |
| `eng_mem` | 51,552 | Four 12,888 B arenas already share mutually exclusive engines; growth costs x4 |
| `sl_buf` | 32,768 | SLICE buffer: assess reverse/loop behavior before changing its capacity |
| `chain` | 13,096 | Song source/cache state in BSS; its preparation keeps storage work outside playback |

The close-to-full NOINIT region matters for new persisted project fields and diagnostics:
four retained project slots multiply layout growth. A passing RAM/POOL line is not a
claim that every SRAM region has ample room. Preserve the explicit linker placement;
review NOINIT capacity before extending those structures.

Host DSP regression observations (instruction counts include the idle mix in this table):

| Scenario | Host instructions/sample | Informational ns/sample |
| --- | ---: | ---: |
| Idle mixer | 310 | 11.2 |
| ANALOG / RAVE | 1,610 | 78.3 |
| PHASE / WIRE | 1,601 | 57.5 |
| FM6 / PAD | 1,398 | 81.7 |
| Three full synth parts plus drums | 1,542 | 70.4 |

These are host observations, not a ranking of pi32v2 CPU load. Different voice caps,
presets and enabled work matter; actual render deadlines include interrupt interference.
Three subsequent runs of the unchanged harness also passed: ANALOG/RAVE used 1,610–1,611,
PHASE/WIRE 1,601–1,602 and FM6/PAD 1,397–1,405 host instructions/sample. FM6/PAD wall time
ranged from 80.7 to 157.1 ns/sample despite its instruction count varying by less than 1%.
That outlier illustrates why host wall time alone is weak evidence for a DSP improvement;
it does not identify the cause of the timing variation. Repeat logs are under
`build/agent-guide-regress-repeat-{1,2,3}.log`.
Raw evidence is in ignored `build/agent-guide-build.log` and `build/agent-guide-tests.log`.
The completed test outcome and its limitations are recorded below.

## What the code already does well

- The audio ISR fills one 128-frame half in four 32-frame blocks; TIMER5 maintains panel
  scanning and USB service while audio is active. `audio.c` tracks timing, misses and
  overload shedding, and `console.c` exposes those counters. This is a useful starting
  point for hardware evidence without adding printf calls to the render path.
- Fixed-point helpers encode nontrivial arithmetic choices. For example, `dsp.c:amp_at`
  replaces a division with a signed-rounding-preserving shift because this target compiler
  can retain even constant hardware divides. Optimizations must preserve these semantics.
- `engines.c` bounds and aligns per-part shared state, and `tests/union_test.c` covers
  720 switch sequences. The current regression run preserved all switch hashes and all
  92 audio golden renders, with no health, voice/routing or CPU-budget failures.
- The build validates app capacity, RAM/POOL margins, flash-safe code and HAL isolation.
  `size_fns.py` applies `minsize` selectively while retaining ISR-reachable code at `-Os`.
- Versioned serializers, torn-write tests, malformed-input tests and sanitizer/fuzz paths
  protect persistent data and protocol input. They are stronger evidence than a clean compile.

One existing test-quality issue surfaced: Clang reports five `-Wunsequenced` warnings in
`tests/input_test.c` (lines 252, 473, 820, 898 and 1039). Chained assignments expand two
`FM1_PR` macros, each modifying the simulated `host_now` clock. Sequence those accesses
as separate statements before relying on compiler-independent timing results. This is a
host test concern identified from the actual warning/source, not an observed device defect.
It was left unchanged within this documentation/research task.

## Lessons from current related projects

Projects were located through the [FM-1 resource directory](https://github.com/cicloid/awesome-fm-1),
then checked against their own commits, releases and source. Branch code may include work
that the latest release does not ship. These are design references, not drop-in changes.

| Project | Latest release observed | Source snapshot examined | Applicable practice |
| --- | --- | --- | --- |
| [Melodee](https://github.com/keremimo/melodee/releases/tag/v1.1.0) | 1.1.0, published Oct 10; API release text describes an Oct 11 rebuild | `01a78bdf0fb0`, Oct 11, default branch `main`; schedules nightlies from `next` | Test performance accounting; retain serial/parallel equivalence and single-core variants |
| [ChoralRoot FM-1](https://github.com/Quixotic7/ChoralRootFM1/releases/tag/v0.17) | 0.17, Oct 11 | `e8efc993c986`, Oct 11; includes preparation for 0.18 effects | Script realistic worst-case scenarios and retain audio artifacts |
| [SLOOP](https://github.com/isod89/sloop-fm1/releases/tag/v2.6) | 2.6, Oct 11 | `4365a1d0075b`, Oct 11 | Measure audible behavior, latency and RAM together when changing DSP |

**Melodee:** its budget-checker tests cover backward jumps that are alternative code paths,
split/nested loops, calls, conservative fallbacks and undecoded FPU instructions. Felucca's
checker currently approximates loops by backward spans, so equivalent tests are a useful
next improvement before trusting more ambitious refactors.
[Checker tests](https://github.com/keremimo/melodee/blob/01a78bdf0fb0e1a9d953567e36a59d80dea54a8a/tests/target_budget_test.py).
The concurrent worker test compares complete mixer PCM and internal synth state against
serial rendering, including changing controls, engine retirement and counter wrap.
[Worker tests](https://github.com/keremimo/melodee/blob/01a78bdf0fb0e1a9d953567e36a59d80dea54a8a/tests/dual_core_test.c).
Its latest nightly workflow pins the SDK commit, builds variants, runs host/web checks and
publishes commit provenance/checksums. This is worth adopting as measurement infrastructure,
without treating a scheduled nightly as a pull-request gate.
[Nightly workflow](https://github.com/keremimo/melodee/blob/01a78bdf0fb0e1a9d953567e36a59d80dea54a8a/.github/workflows/nightly.yml).

**ChoralRoot:** `tools/emu/perf.sh` exercises heavy chords, bass plus arp/loop, scope drawing,
rapid knob changes, effects and saves. It saves WAVs and cost logs and reruns scenarios with
stage instrumentation; it explicitly distinguishes host/device estimates and real dual-core
work from emulator execution. A Felucca version of this workload matrix would improve
coverage beyond isolated engine presets.
[Stress runner](https://github.com/Quixotic7/ChoralRootFM1/blob/e8efc993c986f8d7661c515ebfc8c46c6e77057c/tools/emu/perf.sh).
Its dual-core design also identifies shared RNG/scratch and keeps event ordering and output
equivalence explicit. The dated dual-core document contains an old hardware-status sentence,
so its measurements and claims must be read with their stated dates, not as live device status.
[Dual-core design](https://github.com/Quixotic7/ChoralRootFM1/blob/e8efc993c986f8d7661c515ebfc8c46c6e77057c/docs/DUALCORE.md).

**SLOOP:** its 2.6 limiter looks ahead by one control block to avoid transient crackle,
adding about 0.73 ms and stereo delay state. Its engine arena shares exclusive engine
state and can count ownership violations in host tests. Both illustrate the right evidence
bar: a sound or memory change needs lifecycle, waveform and latency checks together.
[Limiter source](https://github.com/isod89/sloop-fm1/blob/4365a1d0075b9194de1c44826325abbd39751bc1/firmware/src/fx.c),
[Arena source](https://github.com/isod89/sloop-fm1/blob/4365a1d0075b9194de1c44826325abbd39751bc1/firmware/src/engines.c).
These address SLOOP's signal chain; they are not evidence that Felucca has the same crackle
or requires the same limiter.

Dual core is an experiment, not the first optimization: Melodee documents CPU1 misreads,
faults and stalls with one-core fallback, and ChoralRoot defaults it off.
[Melodee reliability work](https://github.com/keremimo/melodee/pull/21),
[ChoralRoot dual-core policy](https://github.com/Quixotic7/ChoralRootFM1/blob/e8efc993c986f8d7661c515ebfc8c46c6e77057c/docs/DUALCORE.md).
Those reports do not establish Felucca's stability on another unit. Clock/voltage changes
and parallel rendering require separate hardware evidence and retained serial behavior.

## Agent guide design and next improvements

[Tinycast's AGENTS.md](https://github.com/abue-ammar/tinycast/blob/126c998d87cd7e93bd5e3437098d9c646eb6a714/AGENTS.md)
is a good structural example: a short project map, conditional documentation pointers,
specific invariants, generated-file ownership and completion criteria. Its modern macOS
API posture and removal of compatibility layers do not fit Felucca's fixed compiler and
versioned project/protocol contracts. The new guide adopts the structure and derives its
rules from this firmware instead.

Recommended follow-up order, with no implementation made in this review:

1. **Remove the test-clock sequencing warnings.** Keep simulated bus timing deterministic
   and rerun input tests before expanding measurement claims.
2. **Automate resource/provenance capture and missing-check visibility.** Felucca has no
   checked-in workflow under `.github/workflows/`. A Linux build/test job could retain app
   and every RAM-section size, flags, SDK/toolchain identity, logs and disassembly. Linux
   currently lacks this harness's macOS instruction counter: retain a Mac run or add an
   explicit equivalent counter. Treat skips/missing budget entries as visible coverage gaps.
3. **Test the target-budget estimator itself.** Cover alternative backward branches,
   loop nesting and extracted callees, then evaluate whether control-flow-aware accounting
   improves it. Correct the estimator before refreshing budgets, retaining reviewed evidence.
4. **Add a reproducible device/stress result format.** Capture workloads and start/end
   counters, audio output and scan responsiveness. Stage timing/stack watermarks can follow
   where profiling identifies an actual unknown; quantify instrumentation overhead.
5. **Optimize a measured hotspot.** Start with per-sample repeated work, disabled-effect
   paths, and large objects identified above. Preserve waveform/engine-switch equivalence
   and budget margins. Asset compression, smaller buffers, FPU or a second core each
   introduce fidelity/latency/reliability tradeoffs and need an explicit experiment.

## Validation outcome

The target build passed without compiler warnings. `tests/run_tests.sh` completed with
`ALL HOST TESTS PASSED`: 92 golden renders unchanged, 720 engine-switch sequences unchanged,
zero host CPU-budget failures, passing target budgets, sanitizer/fuzz checks, web tests and
browser/native PCM parity. The optional DaisySP physical-model reference comparison was
skipped because no checkout was configured. Host instruction counters were available.
The five existing input-test sequencing warnings above remain; passing tests do not remove
that limitation. Three target-cost reductions were informational notes, not failures;
their baselines were retained. No baseline files were regenerated (`GOLDEN_UPDATE` and
`BUDGET_UPDATE` were unset), and no real-device performance was measured.

Local Markdown links/code fences were checked, and the documented section/symbol reporting
command was executed successfully. Raw output is in `build/agent-guide-resource-report.log`.
The documentation change leaves firmware, test implementations and baseline files unchanged.
