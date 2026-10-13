<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Reproducible host stress replay

First increment of [#46](https://github.com/kmplngj/Felucca/issues/46): a bounded,
data-driven workload foundation using the real DSP, with no device access or
firmware changes. Run after generating fresh assets with `./build.sh`:

```sh
python3 tests/stress_matrix.py
python3 tests/stress_matrix.py --out build/stress/my-baseline
```

The full host runner also runs the matrix. Default output is a fresh
`build/stress/run-*` directory; explicit output must be a new directory under
`build/`. Existing evidence is never overwritten. `CC` supports a compiler with
flags, following the host runner. A little-endian host is required by the existing
hostsim WAV adapter.

## Workload contract

`stress_scenarios.json` version 1 records nominal rate 44,100 Hz, control blocks
of 32 frames, exact duration in frames, seed, ordered events and health requirements.
Each event is `[frame, operation, part, argument, value]`; parts are zero-based.
Times must be multiples of CTL. Events at one frame execute in listed order,
immediately before that block. There is no implicit rounding, sorting or cleanup.
The last note-offs are part of the workload; a missing release must fail health.

| Operation | Argument / value | Host adapter |
| --- | --- | --- |
| `preset` | Stable engine ID / factory preset index | `host_preset_req`; native block-boundary fade/claim, with out-of-range indices rejected |
| `param` | Named track parameter / value | Track base parameter, range checked against `track_desc` |
| `global` | Named global parameter / value; part 0 | Global base parameter, descriptor range checked |
| `on` | MIDI note / nonzero velocity | `input_on` on the named track |
| `off` | MIDI note / zero | `input_off` on the named track |

The Python name map is the whitelist of supported base parameters. Values have
their firmware descriptor units. This adapter calls native musical input directly;
it does not exercise the USB/TRS parsers, interrupt queues or physical arrival jitter.
Engine/preset IDs are explicit, never resolved to a measured "heaviest" preset.
Sample-dependent workloads require separately recorded assets.

Every replay is a fresh process, using `host_tracks_init` (ROOM, master Q12 4096),
four ANALOG SINE KEY factory preset 5 parts, POLY, zero sends and release 24.
The declared seed initializes `libc.c`'s shared RNG; other engine/voice static
seeds retain their source defaults. `fm1_ms` follows logical rendered frames.
No prior scenario state survives. Add scenarios without replacing existing timelines
when comparing an optimization; matrix hashes must match between baseline/candidate.
`shared_eight` is retained as the sustained-note negative-control workload.

| Scenario | Required activity |
| --- | --- |
| `idle` | Exact zero signal, no voices |
| `shared_eight` | Two held notes per part, all eight shared voices, explicit releases |
| `voice_pressure` | Eight held notes followed by four additional note requests; fade victims excluded from the eight sounding-voice bound |
| `active_effects` | Three notes through INSERT, chorus, delay and HALL; twelve-second render including release/tail |
| `engine_switch_tails` | Another part keeps playing while part 0 requests ANALOG → FM6 → PHYS → ANALOG, with notes at the switch boundary |

The other scenarios last eight seconds. `checks` fixes minimum signal, observed
voice load and voice starts, final engine identities and maximum tail magnitude.
All parts must finish with no active/gated/held voices or unfinished fade, and the
last quarter-second must settle within six Q15 units. Output must remain in signed
16-bit bounds before WAV conversion. These health bounds supplement exact replay
comparison; they are not a listening-quality assessment.

## Retained evidence and measurement limits

Each scenario runs twice at `-O2` and twice at `-Os` with vectorization disabled,
all with host arena-owner checks enabled. Repeat runs and the two builds must
have identical raw stereo int32 PCM hashes and reported checkpoints. These
checkpoints cover voice load/starts, final engine/request/voice ownership, transport
and shared RNG; they do not serialize all future DSP/filter state. Existing goldens,
union and partition tests remain the authorities for their broader contracts.
Negative controls remove note-ons (must change PCM) and note-offs (must leave gated
voices and fail health); renderer crashes cannot count as successful controls.

`report.json` retains results, compiler commands/version, host byte order, revision,
source/generated-asset hashes, matrix hash and explicit measurement availability.
`matrix.json`, `local.diff`, status and harness-source copies identify local inputs.
Each run retains stdout/stderr, exact `audio.s32` and a stereo 16-bit `audio.wav`.
The report is written on replay/build failures too, with completed results retained.
Generated assets are hashed, not archived: use the build provenance and matching
inputs to regenerate them when reconstructing a measurement.

`ns_per_frame` is informational host wall time of `mix_block` calls only, including
owner-check overhead and two clock reads per block. There is no warm-up exclusion,
instruction-counter adapter, cost budget or FM-1 utilization claim in this increment.
Instruction counts and all device measurements are explicitly unmeasured. Compare
only identical timelines, flags, compiler, assets and instrumentation. No golden or
CPU baseline is generated or updated by this runner.

## Shared adapters and remaining issue #46 work

The JSON is the shared replay input for future emulator/device adapters; neither
adapter is implemented here. Retain event order and timestamps and report the first
boundary at which each adapter can publish an event. Do not call a manual approximation
the same workload. Hardware runs must use an adapter that applies explicit presets,
parameters and notes, and verify timing and routing before cost comparisons.

For a future FM-1 run, capture the same revision/build configuration, matrix hash,
scenario/seed, actual event publication timeline and duration. Follow
[device timing and stress procedure](../docs/performance.md#device-timing-and-stress-procedure)
and the [diagnostics collector](../docs/diagnostics.md). Retain start/end `status`,
`dbg`, `inp` and `crash`, plus WAV/listening observations. The result record must name
counter deltas for `audio_late`, `voices_shed`, UAC errors, UART drops and scan gaps;
separate boot maxima from interval measurements and record collector overhead.
Until such a run occurs, device evidence stays `unmeasured`.

Remaining work: host instruction-count adapter, measured heaviest-preset selection,
dense sequencer/ratchet/modulation and performance-throw scenarios, panel redraws,
USB 44.1/48 kHz and USB/TRS traffic, separate save-operation scenarios, emulator and
device adapters, and optional DSP-stage measurements with quantified overhead.
This first increment leaves #46 open and makes no target speed or memory claim.
