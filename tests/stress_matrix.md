<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Reproducible stress scenario matrix

The [#46](https://github.com/kmplngj/Felucca/issues/46) matrix combines bounded
direct DSP workloads and the existing integrated interaction replay. There are no
firmware changes. The [catalogue](stress_catalog.json) records both executable
inputs and separately named physical cases, including 44.1/48 kHz capture. Run after generating fresh assets with `./build.sh`:

```sh
python3 tests/stress_matrix.py
python3 tests/stress_matrix.py --out build/stress/my-baseline
python3 tests/stress_replay.py --out build/stress/my-integrated-baseline
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
| `step` | Step index / `{notes, ratchet, drums, velocity}` | Native `step_t`; up to four notes, x1–x4, eight-lane drum mask |
| `transport` | 0 / 1 start, 0 stop; part 0 | `seq_start` / `seq_stop` |
| `perform` | Default white-key map index 0–15 / down 0–1; part 0 | `perf_press(perf_map[index])`; 12/13 = REV/ECHO THROW |
| `usb_midi` | Channel status / `data1 + (data2 << 8)` | Actual USB packet queue → `midi_poll`, fail on overflow |
| `trs_byte` | 0 / byte 0–255 | Actual `um_byte` parser → shared MIDI queue; explicit/running status |

The Python name map is the whitelist of supported base parameters. Values have
their firmware descriptor units. The original `on`/`off` operations call native musical input directly.
The traffic case exercises packet routing and the TRS byte parser, not USB endpoints,
UART DMA, scan interrupts, physical wire speed or arrival jitter. It is not UAC coverage.
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
| `dense_ratchets_modulation` | Four native four-step tracks, DRUM kick/closed-hat masks, x4 ratchets, 240 BPM / 1/32, LFO→CUT, explicit transport stop |
| `effects_throws` | Original INSERT/chorus/delay/HALL notes plus overlapping REV/ECHO THROW gestures and 18-second tail |
| `usb_trs_midi` | 24 paired note/CC/release cycles through USB packet routing and TRS parsing, including running status |

The original idle/voice/switch scenarios last eight seconds; new traffic/dense cases
last twelve seconds. Existing schedules remain unchanged. `checks` fixes minimum signal, observed
voice load and voice starts, final engine identities and maximum tail magnitude.
All parts must finish with no active/gated/held voices or unfinished fade, and the
last quarter-second must settle within six Q15 units. Output must remain in signed
16-bit bounds before WAV conversion. These health bounds supplement exact replay
comparison; they are not a listening-quality assessment.

## Retained evidence and measurement limits

Each scenario runs twice at `-O2` and twice at `-Os` with vectorization disabled,
all with host arena-owner checks enabled. Repeat runs and the two builds must
have identical raw stereo int32 PCM hashes and reported checkpoints. These
checkpoints cover voice load/starts, final engine/request/voice ownership, transport,
MIDI pending/drop/message counts, released performance keys and shared RNG; they do not serialize all future DSP/filter state. Existing goldens,
union and partition tests remain the authorities for their broader contracts.
Negative controls remove note-ons (must change PCM) and note-offs (must leave gated
voices and fail health); renderer crashes cannot count as successful controls. Additional controls remove
transport, performance gestures or MIDI traffic: missing required input fails health,
and every removal must change PCM.

`report.json` retains results, compiler commands/version, host byte order, revision,
source/generated-asset hashes, matrix hash and explicit measurement availability.
`matrix.json`, `local.diff`, status and harness-source copies identify local inputs.
Each run retains stdout/stderr, exact `audio.s32` and a stereo 16-bit `audio.wav`.
The report is written on replay/build and metadata-command failures too, with
completed results retained. Metadata commands and the compiler probe each have a
15-second timeout; compilation and each replay have 120/90-second timeouts.
Timed-out commands retain their captured stdout/stderr before propagating the
failure, including byte output that is not valid UTF-8.
Generated assets are hashed, not archived: use the build provenance and matching
inputs to regenerate them when reconstructing a measurement.

`ns_per_frame` is informational host wall time of `mix_block` calls only, including
owner-check overhead and two clock reads per block. A separate fresh `--count` replay uses the shared `host_instructions.h` policy
already used by `regress.c`: macOS process instructions or Linux user-thread perf
instructions; missing, short or multiplexed counters produce null plus a reason.
`instructions_per_frame` covers the whole count-only loop (event dispatch, DSP, clocks,
PCM checksum and health checks), excluding WAV/PCM file IO and setup, with no warmup exclusion.
It is a host workload count, not isolated DSP cost or FM-1 utilization. Count-only
checkpoint state must equal the captured run. Instruction counts are informational,
not part of bit-exact comparison or a cost gate. All device measurements are unmeasured. Compare
only identical timelines, flags, compiler, assets and instrumentation. No golden or
CPU baseline is generated or updated by this runner.

## Integrated panel and save cases

`stress_replay.py` invokes `tools/fm1_replay.py` in fresh processes twice for each
checked-in interaction timeline. It requires identical PCM24 WAV, LCD hashes,
publication/checkpoint state and final state, with minimum note/redraw activity
and complete release. The panel case requests eight factory-track notes (six gated
voices observed with the factory sounds), edits ENV and overlaps FX-held throws.
The separate stopped save case requires USER occupancy to move 0→1, then a played
and released note. Read-only `user_presets` observations count validated in-memory
records; they do not establish power-cycle persistence or real flash timing.

The existing replay's factory state, clock, native firmware/UI/storage integration,
publication latency, output bounds and provenance contract remain authoritative:
see [interaction replay](../docs/interaction-replay.md). This adapter never presents
its fake clock as CPU cost. These panel/save timelines have different initial state
and audio tap from the direct DSP schedules; their hashes are not interchangeable.
The catalogue keeps them separate instead of translating events approximately.

## Heaviest presets and physical observations

The catalogue includes every stable engine ID and the existing `regress.c` CPU
survey contract for selecting its heaviest factory preset. After fresh O2/Os builds,
run `build/host/regress tests/golden.txt -` and
`build/host/regress_os tests/golden.txt -`, retaining stdout/compiler/flags/assets.
Only use the printed per-engine ranking when **all** counts are available and the
run succeeds. Keep O2/Os rankings independently; a host ranking is not a pi32v2
ranking. Pin the resulting explicit engine/preset IDs in a new scenario rather than
silently replacing an old workload. On this environment perf is unavailable, so
selection is explicitly unmeasured, with no invented default winner or wall-time
ranking. DIGITAL and SLICE additionally depend on their build features; sample
assets must match. Existing CPU baselines are not evidence for the current host.

The [FM-1 procedure](../docs/stress-device.md) gives concrete collection commands,
USB44.1/48+USB/TRS cases, a stopped save route and interpretation/cleanup steps.
[stress_device_result.json](stress_device_result.json) is the reusable result template:
revision/flags, workload/duration/scheduling, start/end diagnostics, UAC/UART/scan
observations, WAV/listening and restoration, with unmeasured values null.
#56 owns collection; #57 owns exact hardware musical delivery/capture/restoration.
Manual device case IDs are deliberately distinct from exact direct/emulator replays.
Optional DSP-stage timing remains unimplemented and requires quantified overhead.

The [fresh unchanged baseline](../docs/stress-baseline-2026-10-16.md) records the
current revision, exact PCM hashes and measurement availability. Retain raw reports,
WAVs and logs under ignored `build/`; CI's existing diagnostics artifact includes
`build/stress/`, including the integrated captures and failures. This completes the
scenario/runner, reproducibility, procedure/template and baseline implementation
acceptance for #46; physical observations and automatic #57 delivery remain pending.
