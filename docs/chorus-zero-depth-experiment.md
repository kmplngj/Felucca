<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Exact settled-zero shared chorus experiment

Issue [#637](https://github.com/kmplngj/Felucca/issues/637), measured 2026-10-24.
The bounded candidate removes sine/interpolation work only from the active shared
chorus at settled Depth zero. It is suitable for further validation; FM-1 audio,
deadline, scan and stream checks remain pending. No device speedup is established.
INSERT CHOR, sound controls, persistence, buffers and silent-bus policy are unchanged.

## Exact boundary

The original block snapshot remains authoritative. The additional dispatch requires
both effective `cdepth == 0` and transient `fx.cho_depth == 0`, after the existing
reset/drained initialization. A glide that reaches zero during a block keeps the
original general loop for that whole block. Nonzero and gliding blocks use the
original arithmetic.

At this endpoint the original Q8 delay is `400 << 8`, and its fraction is zero.
`c0 + (((c1 - c0) * 0) >> 8)` is exactly `c0`: both samples are signed int16,
so their difference fits int32 and the zero product introduces no rounding.
The output retains the existing scale, from -65536 through 65534. The candidate
keeps the input shift/clamp, write-before-read order, circular write index,
zero reduction, live countdown and per-sample phase increment. The increment is
still `LFO_INC[rate] / CTL`; uint32 addition preserves every wrap and later edit.
The compiler may aggregate these unsigned phase additions without changing state.

## Revisions and method

The unchanged baseline is firmware `1523fd0e9bb1483082ba5a71834e7255c04e7ff5`
with Engines `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. It was built before
editing. The candidate changes one production cause, the zero-depth dispatch in
`firmware/src/fx.c`. Its measured source SHA-256 is
`85dfd34bb38144509fb98ca443fe90ff91c6436a71725bfe7ac890a4f8bad90c`;
the baseline FX source is
`e6ba03145bd39f710aa25f695c6f1bfa01f6d0318b60be1462199ed5eddc7377`.
Before publication, the new integer-tap scale was corrected from a signed left
shift to `(int32_t)cho_buf[...] * 2`. The product fits int32 over the full int16
range, including negative values. The corrected FX source SHA-256 is
`b957b9118ab85812fe274de85c2a77c04ff9caeb75eb7adcde235752ad3f1766`. The initially measured source hash above remains recorded for
provenance. Generated-code equivalence and focused checks for this correction are
recorded below. The working candidate carries the build identity's dirty flag;
it is not a released firmware. The recorded app delta includes the complete linked result.

Both target builds use JieLi Clang 4.0.1, standard profile, default CPU2 support
(runtime preference remains OFF), selective minsize, standard assets, toolchain
`~/.jieli/toolchain`, and the reference-hashed AC79 SDK files. Their artifact-bound
resource reports retain compiler/tool/SDK/input hashes. The baseline was clean;
the candidate diff and source hashes are retained beside the measurements.

Raw local artifacts, reports, disassembly plus matching sidecars, logs and development
probes are retained under ignored `build/issue637/`. The first candidate target run
was invalidated by its build-input guard because a test file was edited while it
ran; it is retained as `candidate/build-invalidated-input-edit.log` and excluded
from the comparison. The final frozen-input build succeeded.

## Correctness checks

The existing Depth trajectories, stationary PCM checks within that harness, smoothing
assertions, four-track send checks, zero-frame guard and #153 burst/silence checks
remain unchanged. The extended Depth harness adds an independent wide-product
sample oracle that always computes the original modulated tap, including at zero.
It compares PCM, phase, write index, Q8 depth, live count and all 2048 delay samples
after every block.

Each of `-O2`, `-Os` without vectorization, and ASan/UBSan checks 1,455,488 additional
blocks, with every block length 1..32, every Rate, phase/index wraps, reset/drained
starts, both glide directions, rate edits, active/silent alternation, impulse,
clipped/noise/dense input and tails. The candidate asserts fast-path execution
(12,674,482 samples over the complete harness per build). The same expanded oracle
also passes against the captured unchanged source. Deliberately omitting fast-path
phase advancement and reading a stale 401-sample tap both fail behavior assertions.
The test adapter instruments ignored copies only.

Sanitizers retain the pre-existing `-fno-sanitize=shift` scope from the Depth harness:
existing fixed-point DSP left-shifts negative samples. No new sanitizer exclusion
was introduced. The new integer path now uses the defined bounded multiply rather
than introducing another negative-value left shift. Address and other undefined-behavior
checks remain enabled.

### Defined scaling correction and code equivalence

The new fast path's final scale now uses a widened signed multiply by two, whose
full result range is [-65536, 65534], rather than left-shifting a negative signed
sample. The coverage and stale-read mutation anchors were updated for that expression;
all other DSP code stayed fixed. The corrected oracle and both causal controls pass
again at -O2, -Os and ASan/UBSan, with the same block and fast-path coverage counts.

Complete host assembly before and after the correction is byte-identical at each
optimization level. SHA-256: -O2
`988c74bbe7a50e7f42758a1175944f386665325a97a68d5cb1d9c051a455c476`;
-Os `0fa16d18afdcb09932d9f690b764172bce90ef6fd177d193d7dcd7ad2b113ff6`.
The JieLi raw IR changes only `shl i32 ..., 1` to `mul nsw i32 ..., 2` plus
source-position metadata. After the same selective-size pass, all target code,
data and relocation sections are byte-identical. Across 1951 ELF sections, the
only container differences with differently named IR inputs are the source-file
symbol name and its string-table bytes; symbol values, sizes and relocations agree.
Compiling both variants with the same IR input filename also makes the entire
object byte-identical, SHA-256
`74843f604f280fc4e9d94c86658d9e811388205a3bea3c060b645744a38a6d94`.
The equivalence proofs, original/corrected IR, assembly and object hashes are retained
under `build/issue637/corrected/`. The target resource/path comparison is retained because its generated code is
unchanged. The initial host matrix is preserved as historical evidence and
superseded by the counter-validated complete matrix below.

The existing FX-rest suite passes all 77 configurations at both optimization levels
on baseline and candidate, including its original mandatory negative controls.
A separate actual four-track ANALOG/DRUM mixer comparison over 2048 varying-length
blocks, changing Depth/Rate/notes and nonzero chorus/delay/reverb sends, hashes PCM,
full FX state and the full chorus buffer identically (`be5c8d9b8f2c3da0`).
Run the checked-in focused tests after generating standard build inputs:

```sh
python3 tests/chorus_depth_test.py
python3 tests/fx_rest_test.py --require-rest
```

No checked-in audio goldens or CPU/target budgets were rewritten. Full host/emulator
and additional target-profile gates belong to the final integrated candidate.

## Paired host instructions

Apple Clang 21.0.0 (`clang-2100.3.34.2`), macOS arm64. A development probe calls the
real `fx_buses` or `mix_block`, warms 20,000 blocks, then measures 300,000 blocks
with `proc_pid_rusage(..., RUSAGE_INFO_V4).ri_instructions`. Three paired runs
alternate baseline/candidate order. Values below are medians in instructions/sample;
these are host instructions, not pi32v2 cycles or FM-1 CPU utilization. Informational
wall times are retained in `counter-validated/bench-results.jsonl`; concurrent system activity prevents
a target timing conclusion. Probe source SHA-256:
`3a7d2c8abfa2212379bf2700aeb45acca8da408bf2846867d2b6e7d089d55d1e`.

The initial probe silently returned zero if either counter read failed. Its old
raw results remain at `build/issue637/bench-results.json` as **historical and
superseded**. This concrete availability ambiguity justified one replacement
experiment, declared in `counter-validated/declared-plan.json` before running.
The corrected probe exits nonzero with an explicit read-number/error message on
any failed read. Eight bounded controls force read 1 or 2 to fail across both
sides and optimization modes; all exit 2 with an error and no measurement stdout.
The final table uses exactly one fresh complete 144-run matrix with the same
workloads, flags, warm-up, measurement length and paired order. No run is selected
from either matrix, repeated on failure or dropped from the declared matrix.

| 32-frame workload | -O2 baseline → candidate | Change | -Os baseline → candidate | Change |
| --- | --- | --- | --- | --- |
| Silent zero-send buses | 97.387 → 97.415 | +0.03% | 111.367 → 111.369 | +0.00% |
| Active settled zero Depth | 136.660 → 99.864 | -26.93% | 148.840 → 123.733 | -16.87% |
| Active nonzero Depth 80 | 136.704 → 136.905 | +0.15% | 148.830 → 148.865 | +0.02% |
| Forced live glide toward zero | 146.731 → 146.977 | +0.17% | 156.873 → 156.932 | +0.04% |
| Four ANALOG parts, zero Depth, chorus sends | 969.656 → 933.038 | -3.78% | 1053.350 → 1028.567 | -2.35% |
| Four ANALOG parts, dry/zero sends | 914.352 → 914.357 | +0.00% | 999.753 → 1000.036 | +0.03% |

| 1-frame workload | -O2 baseline → candidate | Change | -Os baseline → candidate | Change |
| --- | --- | --- | --- | --- |
| Silent zero-send buses | 334.035 → 335.177 | +0.34% | 337.121 → 337.022 | -0.03% |
| Active settled zero Depth | 347.022 → 333.101 | -4.01% | 360.177 → 332.039 | -7.81% |
| Active nonzero Depth 80 | 347.115 → 354.140 | +2.02% | 360.021 → 361.187 | +0.32% |
| Forced live glide toward zero | 358.191 → 366.021 | +2.19% | 369.080 → 371.193 | +0.57% |
| Four ANALOG parts, zero Depth, chorus sends | 4673.264 → 4659.216 | -0.30% | 5351.787 → 5324.965 | -0.50% |
| Four ANALOG parts, dry/zero sends | 4644.087 → 4645.082 | +0.02% | 5317.761 → 5316.194 | -0.03% |

The direct-bus inputs repeat a dense block spanning the native input clamp; delay
and reverb sends are zero. The glide workload resets current Q8 depth to the maximum
before each measured block so it cannot accidentally become a zero-depth hit.
The four-part workloads use the actual mixer with held notes and sends 127/0.
They do not simulate MIDI transport, UAC or physical panel work.

One-frame blocks expose the dispatch overhead: nonzero/gliding cost rises
2.02%/2.19% at -O2 and 0.32%/0.57% at -Os. Active zero Depth still improves
4.01% at -O2 and 7.81% at -Os. Four-part zero-depth improvements are 0.30%/0.50%.
The firmware audio path normally uses CTL=32; short-block correctness remains a
contract even though its relative host cost is less favorable.

## Target and static resources

| Resource | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| App bytes | 496316 | 496472 | +156 |
| App spare | 85248 | 85092 | -156 |
| RAM used / spare | 62392 / 11336 | 62392 / 11336 | 0 |
| POOL used / spare | 336440 / 32200 | 336440 / 32200 | 0 |
| RAMTEXT used / spare | 3152 / 21424 | 3152 / 21424 | 0 |
| NOINIT used / spare | 15576 / 120 | 15576 / 120 | 0 |
| Packaged bytes | 610134 | 610134 | 0 |
| Audio ISR local allocation | 84 | 84 | 0 |
| Audio ISR own frame, including saved registers | 136 | 136 | 0 |

RAMTEXT comprises 2924 bytes `.ram_text` and 228 bytes `.c1_text`. Stack reservations,
guards and ISR saved registers (`rets, r15-r4`) are unchanged. The saved set is
13 words (52 B): the 84 B local allocation plus those 52 B makes the ISR's own
frame **136 B** in both artifacts. This excludes callees and nested TIMER5 frames.
These are linked/static figures, not live stack watermarks. Both successful builds retain the pre-existing
`ui_draw.c:728` unused-variable warning; the baseline asset run also reports unavailable
Raqm layout and uses its existing fallback. There are no new compiler warnings.

Both unchanged target budgets pass. `fx_buses` and `mix_block` are inlined into
`fm1_alnk0_irq`; its complete instruction count rises 1555 → 1585 and heuristic
score 6980 → 7073, below the unchanged gate. No hot helper escapes coverage.
The shared-chorus sine is itself inlined: the original stationary loop has 53 listed
instructions (four signed halfword reads and three multiplies), the integer loop has
20 (one halfword read and zero multiplies). The general stationary and gliding paths
retain 53 and 67 listed instructions respectively, with the extra block predicates
and surrounding register/layout changes accounted in the whole ISR. These are
path/listing inventories, including conditional clamp alternatives, not executed
cycle counts. Neither compared chorus loop calls a helper. The unrelated standalone
`osc_sine` remains 14 instructions in both artifacts.

## Remaining acceptance and documentation

Keep the candidate as a bounded experiment pending final suite/review and physical
acceptance. FM-1 matched listening/audio, deadline/late/shedding, scan responsiveness,
USB/TRS MIDI, panel activity, 44.1/48 kHz UAC, CPU2 OFF then supported ON/fallback,
and nested-interrupt stack checks remain unperformed. No device was flashed.

README's existing fork purpose and **Development direction and process** already cover
measured optimization experiments and separate hardware validation; no capability,
control, engine or installation change warrants a new overview milestone. Changelog
**Optimized** receives a concise result and this evidence link, with device qualification
explicit. Diagnostic capabilities/protocols and the feature controls are unchanged.

## Appendix: reproduce the host comparison

This is the complete macOS arm64 probe used for the reported instruction counts.
It requires the native Apple Clang and `libproc`; it is not a Linux or target-cycle
benchmark. Save the following block as a local `probe.c`. Its exact bytes, including
the final newline, have the probe SHA-256 recorded above.

```c
/* SPDX-License-Identifier: GPL-3.0-only */
#define main hostsim_main
#include "bench-hostsim.c"
#undef main
#include <libproc.h>
#include <sys/resource.h>
#include <errno.h>
static unsigned counter_reads, forced_read;
static uint64_t insns(void) {
 struct rusage_info_v4 r; int result;
 counter_reads++;
 if(counter_reads == forced_read) { errno = EIO; result = -1; }
 else result = proc_pid_rusage(getpid(),RUSAGE_INFO_V4,(rusage_info_t *)&r);
 if(result) { fprintf(stderr,"chorus bench: proc_pid_rusage read %u failed: %s\n",counter_reads,strerror(errno)); exit(2); }
 return r.ri_instructions;
}
static volatile int32_t sink;
int main(int argc,char **argv) {
 const char *failure = getenv("CHORUS_BENCH_FAIL_READ"); forced_read = failure ? (unsigned)strtoul(failure, NULL, 10) : 0;
 int mode=atoi(argv[1]), shortblock=argc>2?atoi(argv[2]):32; uint32_t b,i,p,n=shortblock; int32_t in[CTL],z[CTL]={0},out[2*CTL];
 memset(&fx,0,sizeof fx); memset(&hl,0,sizeof hl);host_tracks_init();song.g[G_DMIX]=0;song.g[G_CRATE]=73;song.g[G_CDEPTH]=mode==2?80:0;
 for(i=0;i<CTL;i++)in[i]=(int32_t)(i*3333u%100000u)-50000;
 for(p=0;p<NTRK;p++){host_preset(&trk[p],0,0);trk[p].p[P_CHOR]=mode==4?127:0;trk[p].p[P_DLY]=trk[p].p[P_REV]=0;trk_note_on(&trk[p],48+p*4,90);}
 for(b=0;b<20000;b++){if(mode<4)fx_buses(mode?in:z,z,z,out,n);else mix_block(out,n);}
 uint64_t c=insns(),t=now_ns();
 for(b=0;b<300000;b++){if(mode==3)fx.cho_depth=127*6*256;if(mode<4)fx_buses(mode?in:z,z,z,out,n);else mix_block(out,n);sink=out[0];}
 t=now_ns()-t;c=insns()-c;
 printf("%d %u %.6f %.6f %d\n",mode,n,(double)c/(300000u*n),(double)t/(300000u*n),sink);return 0;
}
```

Prepare a checkout of this candidate with the exact Engines pin and standard
`build/gen` assets generated according to [BUILDING](../BUILDING.md). The baseline
FX source below is read directly from the pinned Git object. Both binaries use the
same remaining firmware, generated headers and adapted `tests/hostsim.c`; only the
FX include differs. No samples, tables or other assets are copied into the probe.
The setup rejects any other production-source difference from the measured base.

Set these paths for your checkout and the `probe.c` you saved. Choose a new output
directory; the setup deliberately refuses to overwrite an existing experiment.
The following commands use `rtk proxy` as in this repository's shell instructions.

```sh
export CHORUS_CANDIDATE_ROOT="/absolute/path/to/Felucca"
export CHORUS_BENCH_PROBE="/absolute/path/to/probe.c"
export CHORUS_BENCH_DIR="$CHORUS_CANDIDATE_ROOT/build/chorus-reproduce"
export CC=cc
rtk proxy python3 - <<'PY_SETUP'
from pathlib import Path
import hashlib
import json
import os
import shlex
import subprocess

root = Path(os.environ['CHORUS_CANDIDATE_ROOT']).resolve()
out = Path(os.environ['CHORUS_BENCH_DIR']).resolve()
base = '1523fd0e9bb1483082ba5a71834e7255c04e7ff5'
probe = Path(os.environ['CHORUS_BENCH_PROBE']).read_bytes()
assert hashlib.sha256(probe).hexdigest() == '3a7d2c8abfa2212379bf2700aeb45acca8da408bf2846867d2b6e7d089d55d1e'
assert (root / 'build/gen/felucca_tables.h').is_file()
changed = subprocess.check_output(
    ['git', '-C', str(root), 'diff', '--name-only', base, '--', 'firmware'],
    text=True).splitlines()
assert changed == ['firmware/src/fx.c'], changed
pin = subprocess.check_output(
    ['git', '-C', str(root / 'firmware/engines'), 'rev-parse', 'HEAD'],
    text=True).strip()
assert pin == '9630426f5c4a34a209ca851356fbe8ba3c4c6d19', pin
original = subprocess.check_output(
    ['git', '-C', str(root), 'show', base + ':firmware/src/fx.c'])
assert hashlib.sha256(original).hexdigest() == 'e6ba03145bd39f710aa25f695c6f1bfa01f6d0318b60be1462199ed5eddc7377'
assert hashlib.sha256((root / 'firmware/src/fx.c').read_bytes()).hexdigest() == 'b957b9118ab85812fe274de85c2a77c04ff9caeb75eb7adcde235752ad3f1766'
out.mkdir(parents=True, exist_ok=False)
plan = dict(probe_sha256=hashlib.sha256(probe).hexdigest(), warmup_blocks=20000,
            measured_blocks=300000, expected_process_runs=144,
            optimizations=['O2', 'Os-no-vectorization'], block_lengths=[32, 1],
            modes=list(range(6)), pairs_per_workload=3,
            order=[['baseline', 'candidate'], ['candidate', 'baseline'], ['baseline', 'candidate']],
            retry_policy='none; any failure invalidates the complete experiment')
(out / 'declared-plan.json').write_text(json.dumps(plan, indent=2))
(out / 'baseline-fx.c').write_bytes(original)
cc = shlex.split(os.environ.get('CC', 'cc'))
(out / 'compiler.txt').write_bytes(subprocess.check_output(cc + ['--version']))
host = (root / 'tests/hostsim.c').read_text()
needle = '#include "../firmware/src/fx.c"'
assert host.count(needle) == 1
for side in ('baseline', 'candidate'):
    directory = out / side
    directory.mkdir()
    fx = out / 'baseline-fx.c' if side == 'baseline' else root / 'firmware/src/fx.c'
    adapted = host.replace(needle, f'#include "{fx}"')
    adapted = adapted.replace('"../firmware/src/', f'"{root}/firmware/src/')
    (directory / 'bench-hostsim.c').write_text(adapted)
    (directory / 'bench.c').write_bytes(probe)
    for opt, flags in (('O2', ['-O2']),
                       ('Os', ['-Os', '-fno-vectorize', '-fno-slp-vectorize'])):
        command = cc + flags + ['-w', '-I' + str(root / 'build/gen'),
                                '-I' + str(root / 'firmware/src'),
                                str(directory / 'bench.c'), '-lm',
                                '-o', str(directory / ('bench-' + opt))]
        (directory / (opt + '-compile.txt')).write_text(shlex.join(command) + '\n')
        subprocess.run(command, check=True)
PY_SETUP
```

Before collecting measurements, prove both counter-error exits using a bounded
injection. `CHORUS_BENCH_FAIL_READ` is a standalone probe control, read before the
warm-up; it does not exist in firmware. It injects `EIO` on exactly read 1 or 2.
The control must exit 2 with a clear error and empty stdout; it cannot be mistaken
for a valid cost sample. These eight controls are separate from the 144 matrix runs.

```sh
rtk proxy python3 - <<'PY_CONTROL'
from pathlib import Path
import json
import os
import subprocess

out = Path(os.environ['CHORUS_BENCH_DIR']).resolve()
results = []
for opt in ('O2', 'Os'):
    for side in ('baseline', 'candidate'):
        for failure in (1, 2):
            environment = os.environ.copy()
            environment['CHORUS_BENCH_FAIL_READ'] = str(failure)
            result = subprocess.run([str(out / side / ('bench-' + opt)), '1', '32'],
                                    env=environment, capture_output=True, text=True)
            row = dict(opt=opt, side=side, forced_read=failure, exit=result.returncode,
                       stdout=result.stdout, stderr=result.stderr)
            results.append(row)
            assert result.returncode == 2 and not result.stdout, row
            assert f'proc_pid_rusage read {failure} failed:' in result.stderr, row
(out / 'forced-failure-controls.json').write_text(json.dumps(results, indent=2))
print('8 read-failure controls passed: explicit errors, no valid measurements')
PY_CONTROL
```

Run exactly the complete matrix below: two optimization modes × two block lengths
× six workload modes = **24 workloads**, three paired repetitions each, two sides
per pair = **144 process runs**. For each workload the order is baseline/candidate,
candidate/baseline, baseline/candidate. The emitted mode numbers are 0 silent buses,
1 active zero Depth, 2 active Depth 80, 3 forced glide, 4 four-part chorus, and
5 four-part dry. Every process starts fresh, performs its own warm-up, and measures
the same number of blocks. No warm-up or failed sample is substituted by a retry.

```sh
rtk proxy python3 - <<'PY_RUN'
from pathlib import Path
import json
import math
import os
import statistics
import subprocess

out = Path(os.environ['CHORUS_BENCH_DIR']).resolve()
plan = json.loads((out / 'declared-plan.json').read_text())
assert len(json.loads((out / 'forced-failure-controls.json').read_text())) == 8
assert 'CHORUS_BENCH_FAIL_READ' not in os.environ
raw = out / 'bench-results.jsonl'
rows = []
with raw.open('x') as log:
    for opt in ('O2', 'Os'):
        for n in (32, 1):
            for mode in range(6):
                for repeat in range(3):
                    order = ('baseline', 'candidate') if repeat % 2 == 0 else ('candidate', 'baseline')
                    for side in order:
                        result = subprocess.run([str(out / side / ('bench-' + opt)), str(mode), str(n)], capture_output=True, text=True)
                        if result.returncode:
                            (out / 'failure.json').write_text(json.dumps(dict(opt=opt, n=n, mode=mode, repeat=repeat, side=side, exit=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2))
                            raise RuntimeError('Measurement process failed; matrix invalidated without retry')
                        values = result.stdout.split()
                        assert len(values) == 5, result.stdout
                        assert (int(values[0]), int(values[1])) == (mode, n)
                        row = dict(opt=opt, n=n, mode=mode, repeat=repeat, side=side, ipc=float(values[2]), ns=float(values[3]), sink=int(values[4]))
                        assert math.isfinite(row['ipc']) and row['ipc'] > 0
                        assert math.isfinite(row['ns']) and row['ns'] > 0
                        rows.append(row)
                        log.write(json.dumps(row) + '\n')
                        log.flush()
                print(opt, n, mode, 'completed 6 of 6 paired measurements', flush=True)
assert len(rows) == plan['expected_process_runs'] == 144
summary = []
for opt in ('O2', 'Os'):
    for n in (32, 1):
        for mode in range(6):
            row = dict(opt=opt, n=n, mode=mode)
            for metric in ('ipc', 'ns'):
                medians = {side: statistics.median(r[metric] for r in rows if (r['opt'], r['n'], r['mode'], r['side']) == (opt, n, mode, side)) for side in ('baseline', 'candidate')}
                row[metric] = dict(**medians, delta_pct=100 * (medians['candidate'] / medians['baseline'] - 1))
            summary.append(row)
(out / 'bench-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print('Complete declared matrix: 144 valid runs, zero retries')
for row in summary:
    print(row['opt'], row['n'], row['mode'], row['ipc'])
PY_RUN
```

The reported percentage is `100 * (candidate median / baseline median - 1)` for
each workload; it is not a median of pairwise percentages. The instruction interval
also includes the two monotonic-clock reads and small measurement bookkeeping;
that identical fixed overhead is amortized over 300,000 blocks. Wall times remain
informational. Preserve all raw rows and the compiler version. A failed process,
unavailable instruction counter or incomplete matrix invalidates that run rather
than producing a partial passing comparison. The corrected probe exits before printing a result on either counter-read failure. Investigate failures; any deliberately
new experiment must retain its failed predecessor and state its changed cause.
This procedure measures host costs only and does not replace the remaining device
gates above.
