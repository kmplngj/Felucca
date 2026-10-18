<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Stress baseline, 2026-10-16

Captured **before editing**, from clean firmware/harness revision
`a1496ddbc20cc2322513de98f938fd3180b4f31f`, Linux x86_64, Debian Clang
19.1.7 (3+b1). Submodule `firmware/engines` was initialized at its pinned
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. Fresh default standard/M8Stealth
assets were generated using `tools.build.generate()`; no target firmware was
changed or built for this tooling-only baseline. Exact source/generated hashes,
commands, compiler version, clean status and empty local diff are retained in
`build/stress/unchanged-a1496dd/report.json` and its sibling files.

Command: `python3 tests/stress_matrix.py --out build/stress/unchanged-a1496dd`.
Each scenario ran twice in fresh processes at `-O2` and twice at
`-Os -fno-vectorize -fno-slp-vectorize`, with `FELUCCA_ARENA_CHECK=1`.
All PCM/checkpoints/health checks and the dropped-on/off negative controls passed.
The four runs per scenario have these identical SHA-256 hashes of raw interleaved
stereo little-endian int32 PCM (not the WAV container):

| Scenario | PCM SHA-256 |
| --- | --- |
| idle | `4d5dfececf9ba311f7dce724f3e5f00f9d05c24c267d4f94905ce0be10c7ebee` |
| shared_eight | `ed2bc75f5e875c56f68264a8c1ca55f49c2251cd21a521fcb21fe49cdf004734` |
| voice_pressure | `9876248b07027adb740c0dcef8750c05227c0a964459b48b3a86137332ebbb08` |
| active_effects | `6a970324468f98e75543715d693b2a797391b4ab85a077c227097399ce112ed6` |
| engine_switch_tails | `4cf81f13be909503503e740fdb3f47451c4388bd3e50bbd19be7994bf960fb29` |

Original matrix SHA-256:
`7360153db4e8cef2d02b9dd7090306893467e0be5e670515ec86d11c05e78027`.
These five schedules are retained unchanged in the expanded matrix. A future
comparison must use the exact saved `matrix.json` and assets; adding scenarios
changes the overall matrix hash even when these timelines remain unchanged.
Use the new runner's `--matrix build/stress/unchanged-a1496dd/matrix.json` to replay
that exact input. Raw WAV/PCM, reports and logs remain under ignored `build/`;
this document records provenance/results, not a new automatic golden or CPU budget.

Instruction counts were unavailable in the original runner. The new shared counter
adapter also reports `perf_event_open failed: No such file or directory` in this
environment (no usable PMU). No measured heaviest-preset ranking, instruction-cost
baseline, target speedup or FM-1 utilization is claimed. Host wall times were
recorded for information only; concurrent unrelated builds make them unsuitable
for a performance comparison. Target static resource deltas and all physical
FM-1/USB/TRS/LCD/NOR observations are unmeasured; no firmware inputs were modified.

The expanded direct and integrated runs retain their own complete inputs under
`build/stress/expanded-a1496dd/` and `build/stress/integrated-first/`. The integrated
cases are independently reproducible emulator baselines with their own factory
state, consumer/producer timing and DAC tap; they are not interchangeable with
the direct DSP hashes above. For #24/JUNO/CPU2/FPU comparisons, preserve these
artifacts, choose the relevant exact input and capture a fresh candidate using
identical flags/assets/instrumentation. Only physical runs establish device margins.
