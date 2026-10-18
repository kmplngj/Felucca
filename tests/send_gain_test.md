<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Shared-send gain experiment (#278)

`python3 tests/send_gain_test.py` checks the real mixer with `-O2`, `-Os` without
vectorization, CPU2 compiled both ways, and ASan/UBSan when available. It covers every
128×128 parameter transition at all 1..32-frame caller sizes, signed eight-voice
headroom, exact endpoints, four summed parts, MOD restoration, idle/restart, runtime
zeroing, engine changes and poisoned partial worker state. The separate UI fixture
uses the real project, factory/user preset, undo and engine-load routes.

Only CHO/DLY/REV gains glide during an already sounding part's next rendered block.
Dry LEVEL/PAN and effect algorithms are unchanged. Each short caller block finishes
at its target; splitting an edited block changes the glide duration deliberately,
because targets are sampled at the actual caller boundary. The audio ISR calls with
32 frames. A zero-frame part call leaves state untouched.

A silent early return invalidates previous gains, so the next attack starts directly
at the current effective MOD target. Active project/preset loads preserve the last
heard gains and glide during their native release/fade; those loaders replace explicit
parameters, not the whole runtime track. Undo and serializers never copy these new
runtime fields. Boot/whole-runtime zeroing invalidates them. A held failed worker's
sums are dropped as before, and only that worker's parts invalidate their uncertain
gain transaction before serial fallback.

While either REV/ECHO THROW enters, holds or releases (`pf.thr`), **all three** base
sends retain their original snapshot arithmetic and synchronize previous gains.
This preserves the existing shaped THROW path exactly, including chorus.
Synchronizing gains prevents a stale glide when THROW finishes. No preference, stored field or wire ID is added.

## Native recordings

The audio experiment is separate from the routine runner and requires NumPy for
analysis. Generated copies, binaries, raw int32 streams, metrics and WAVs remain
under the requested ignored output directory:

```sh
mkdir -p build/send-baseline
# d2c3ff7 is the unchanged PR401 baseline used for this experiment.
git show d2c3ff7:firmware/src/fx.c > build/send-baseline/fx-source.c
python3 tests/send_gain_audio.py --fx-source build/send-baseline/fx-source.c --out build/send-baseline/audio
python3 tests/send_gain_audio.py --out build/send-candidate/audio --compare build/send-baseline/audio
```

The 144 native scenarios pair identical edited/unedited timelines: ANALOG sine or a
four-note bright saw chord; mono/SPREAD127; each bus/all buses; full up/down jumps,
63→64 detents, alternating full jumps every block, and slow detents. Additional
pairs use real `perf_press`, `perf_begin` and `perf_throw`: press both throws at
frame1024, edit at8192, release at16384. Two additional modes alternate full sends
on every active THROW block, including its enter/release boundaries; one uses
LEVEL127 and eight held notes to exercise native loud headroom. Each recording has 32768 frames at nominal
44.1kHz; MASTER is2048 and LEVEL88. Raw sends and final stereo MASTER have separate
WAVs; `data.bin` also retains pre-FX dry channels at full int32 precision. WAV values
are clamped only by the WAV writer; analysis uses the raw stream.

`metrics.json` reports edit-minus-unedited residual maxima of first/second sample
differences, normalized by the actual unedited dry RMS. It also retains the initial
whole-record Hann residual energy above8kHz. Initial gates were declared from the
unchanged recordings before candidate creation: raw large-jump median ratios≤0.5,
MASTER median ratios≤1.1 and worst spectral ratio≤1.25; dry/steady PCM exact.

The raw-send whole-record spectral median gate (≤0.5) **did not pass** for isolated
jumps (ratio≈1); the separate MASTER worst-case≤1.25 gate passed. That
window puts the edit almost at its zero-weight edge and measures mostly sustained
changed tone. It is not evidence against or for transition smoothing. A supplemental
measurement, defined after the first candidate, takes the maximum256-frame Hann
STFT residual above8kHz, hop32, starting8064..32512 so edits and delayed wet arrivals
are inside windows. The same0.5 raw/1.1 MASTER median thresholds apply; this revised
metric was not preregistered. Negative controls are measured unedited streams from both sources (zero residual) and the measured
nonzero baseline step residual divided by its identical reference (ratio1, fails
the0.5 gate).
Do not report the original gate as passing or infer an audible improvement from
these numerical measurements.

On GCC14.2.0 `-O2`, unchanged source SHA256
`e898fb75c5a6ed28237f2db021c2600f4de45b0d053db82c8af7239e0971eab8`:

| edit | raw step ratio | raw second difference ratio | local raw spectral ratio | MASTER step ratio | local MASTER spectral ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0→127 |0.364|0.218|0.184|0.545|0.666|
| 127→0 |0.371|0.223|0.189|0.591|0.658|
| alternating0/127 |0.044|0.063|0.042|0.070|0.063|
| slow detents |0.933|0.475|0.703|1.000|0.996|

These are medians of scenario ratios, not device timings. Local MASTER worst-case
large-jump spectral ratio was1.060; one-detent and slow-edit changes were small.
All80 ordinary unedited controls and all128 complete THROW edited/control timelines
were bit-identical across raw sends, dry and MASTER; ordinary edited dry PCM was
also exact. End-of-render voice, oscillator/LFO phase and global/MOD RNG state are
compared separately; intentionally changed effect tails are not required to match.
Hardware listening remains a distinct check.

An initial independent-ramp candidate was rejected: while THROW was fully held,
127→0 produced approximately1.97× the baseline full send, and0→127 approximately
0.03×. Its raw MASTER difference reached216 Q15 counts in this fixture. The retained
THROW guard removes that coupling without modifying `perf_throw`.

## Evidence limits

Exact source/compiler/generated-header hashes and timelines are retained under
`build/batch-fx/278/` for this run; target budgets and resource measurements belong
to the matching combined batch build. CPU2 track size grows16 bytes per part
(+64 bytes static RAM); CPU2=0 reuses padding and keeps its size. Changed blocks
add one bounded send pass and three divisions per block; steady loops keep their
original sample arithmetic. No target speedup or complete deadline claim is made.

Real FM-1 A/B listening/recording, maximum four-track modulation/lock load, TIMER5
interference, panel/MIDI responsiveness and USB44.1/48kHz checks remain pending.
No device was flashed or listened to during this experiment. The existing silent-bus comparison harness passed63 forced-rest-on/off audio/state
comparisons at both `-O2` and `-Os`, exercising chorus, delay, HALL and SPRING skips.
Those results remain separate from real-device evidence.


## Target probe resources

The root's combined dirty-tree probes used native JieLi Clang4.0.1 `-Os` and the
same flags/assets as unchanged `d2c3ff7`. Final CI artifacts must identify the
frozen committed source; these figures describe the reviewed probe inputs.

| quantity | default CPU2 compiled | CPU2=0 |
| --- | ---: | ---: |
| app bytes |485200→485672 (+472)|480944→481344 (+400)|
| static RAM bytes |61960→62024 (+64)|55444 unchanged|
| POOL bytes |336440 unchanged|336440 unchanged|
| NOINIT bytes |15568 unchanged|15564 unchanged|
| IRQ static heuristic |8529→8537|37821→37959|
| `mix_part` heuristic |3549→2835|see combined report|
| `mix_spread` heuristic |73→67|69→66|
| new `send_begin`/`send_add` heuristic |16/88|16/77|

The lower caller heuristic reflects changed loop/layout selection and excludes
new callees; it is not a speedup. Existing IRQ/mix guards remain, and new helper
coverage uses default73/16/88 for spread/begin/add. The host instruction counter
and actual device timing are separate evidence.

Default prologs show `mix_part` locals140→152 bytes, `mix_spread`52→60 bytes,
and `send_add`36 local bytes plus52 saved-register bytes (88 total). Compared with
the old call chain, an edited mono call adds100 bytes and an edited spread call
adds108 bytes, excluding unchanged outer callers and nested TIMER5. CPU2=0 IRQ
locals156→172, spread40→44, and send_add24+52=76 bytes. Real interrupt nesting,
stack high-water and deadline qualification remain pending on the FM-1.
