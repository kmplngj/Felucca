<!-- SPDX-License-Identifier: GPL-3.0-only -->
# SPRING and PHASER stage equivalence

`stage_unroll_test.c` retains the original loop implementations from main
`eca522498797838f112e3555f2c589a079b150f5` and compares them with the real firmware.
The reference preserves rounding, saturation, stage order and persistent state.
`tests/run_tests.sh` rebuilds/runs it at `-O2` and `-Os` without vectorization.
After a fresh target/asset build, a focused run is:

```sh
clang -O2 -w -Ibuild/gen -Ifirmware/src tests/stage_unroll_test.c -lm -o build/stage_unroll_test
build/stage_unroll_test
clang -Os -fno-vectorize -fno-slp-vectorize -w -Ibuild/gen -Ifirmware/src tests/stage_unroll_test.c -lm -o build/stage_unroll_test_os
build/stage_unroll_test_os
```

Both runs must report identical PCM and state for 4,608 SPRING blocks, 6,912
INSERT PHASR blocks and 2,304 FX-layer PHASER blocks. Blocks have 1, 17 or 32
samples. SPRING crosses line wraps, changes SIZE at block boundaries, exercises
SIZE/DAMP 0/64/127, bursts up to 90,000 and silence; comparisons include the whole
FX state, line and stage buffers, including addition to nonzero output. INSERT
exercises RATE/DEPTH/FDBK 0/64/127, phase wrap, MIX fades and input up to 2^22.
FX PHASER exercises stereo and single-sided bursts, silence, 60/120/240 BPM,
macro depths 0/50/100 and on/off fades, including complete performance state.
The final three intentional mutations must be detected: one SPRING output
sample and one persistent state field in each PHASER caller. Their expected
mismatch diagnostics are followed by a success message and exit status zero.
The existing reverb, insert, performance and golden regressions remain required.

## Why SPRING's static budget changes

Measured with JieLi Clang 4.0.1, default target `-Os` and selective `minsize`,
M8Stealth, default features, the same generated assets and SDK packaging inputs.
The clean-main production inputs also match the preserved build at `8424c1a`.
Addresses below come from those before/after disassemblies and move with code.
They identify instruction ranges; they are not runtime cycle measurements.

| Target range | Original loop | Unrolled stages |
| --- | --- | --- |
| SPRING sample loop | `0x2007704..0x2007814`, 91 decoded instructions | `0x2007754..0x200791e`, 161 instructions |
| SPRING inner stage loop | `0x2007796..0x20077b4`, 12 instructions | absent |
| INSERT PHASR stage loop | `0x2006306..0x200632e`, 15 instructions | absent |
| FX PHASER stage loop | `0x2008294..0x20082b4`, 13 instructions | absent |

In the original SPRING code, `r0 = 1` directly precedes the stage loop; its
backward branch is `if (r0 != 11) goto ...`, with `r0 += 1` in that loop.
Thus all twelve inner instructions run **ten** times per sample. The generic
budget estimator instead applies `NEST=4` to every nested loop: it reports
`91 + 12*(4-1) = 127` (the historical budget entry was 126). Once the stage
loop is removed it reports 161, apparently 28% above that old entry.

Accounting for the actual ten stage iterations gives the original sample-span
instruction bound `91 + 12*(10-1) = 199`, versus 161 after unrolling: 38 fewer
instructions in that bound. This sums conditional instruction sites and is
not an executed-instruction trace or timing claim. The new SPRING loop has
fixed stage offsets 4 through 40 bytes, no backward stage branch, and no calls.
Both PHASER stage loops are also removed; the sample/channel and initialization
loops remain. `sp_ap` and `ph_ap` have no out-of-line target symbols. The generic
static costs for INSERT/FX PHASER fall 230→213 and 448→407 respectively.

Only `rev_spring` is calibrated to its measured new generic cost of **161**;
the estimator and every other budget entry are retained. A new target build
must pass `python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt`.
No audio goldens or host CPU baselines change.

All three functions retain the same saved register set (`rets`, `r15-r4`):
52 bytes. Additional local stack allocation changes SPRING 44→40 bytes,
INSERT 16→20 bytes and FX PHASER 24→20 bytes. INSERT's extra four bytes are
bounded; no allocation or recursion is introduced. App storage grows by 344
bytes (469,292→469,636); RAM occupied span and POOL remain 55,364 and 327,908
bytes. Device stack high-water, audio deadlines and audible A/B remain pending
on a real FM-1; host/reference and static checks cannot establish them.
