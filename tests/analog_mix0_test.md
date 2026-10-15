<!-- SPDX-License-Identifier: GPL-3.0-only -->
# ANALOG zero-mix regression

`analog_mix0_test.c` compiles the real host-simulated firmware. It compares each
PCM sample, the complete three-voice state and the track state against independent
copies of current main's two-oscillator and SYNC/SUB loops. The classic reference
always evaluates both waveforms, including when MIX is zero.

Run after `./build.sh` (the full runner includes both builds):

```sh
mkdir -p build/host
clang -O2 -w -Ibuild/gen -Ifirmware/src tests/analog_mix0_test.c -lm -o build/host/analog_mix0_test
build/host/analog_mix0_test
clang -Os -fno-vectorize -fno-slp-vectorize -w -Ibuild/gen -Ifirmware/src tests/analog_mix0_test.c -lm -o build/host/analog_mix0_test_os
build/host/analog_mix0_test_os
python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt
```

Expected: both deliberate reference faults are detected, then 604,800 blocks
compare identically. Faults replace OSC 1's Q15 multiply with direct assignment
or stop OSC 2 phase advancement while silent. They establish that the comparison
can reject these tempting but incorrect shortcuts.

The matrix covers SAW/SQR/TRI/SIN/PWM/SYNC/SUB, LP/BP/HP, MIX 0/1/64/127 and
mid-phrase zero/nonzero transitions, detune/noise/cutoff/resonance/drive corners,
low/high pitch, shape modulation, bend, glide, retrigger, legato and three summed
voices. Reference SYNC/SUB implementations are independent, rather than delegating
to the candidate's unchanged renderer.

The implementation lives in the pinned MIT Engines submodule. It was implemented
against its current MIT source; this GPL test retains the old two-oscillator
reference for independent output/state comparisons. The portable contract, engine
IDs, stored data and user controls remain unchanged.

Target coverage includes the new `analog_render_1` helper, including profile
metadata so profiles that omit ANALOG omit this helper too. At the integrated
1.6.1 revision, its measured default JieLi Clang 4.0.1 M8Stealth static cost is
702: 838 total instructions, 558 loop instructions, 18 weighted divides and no
calls inside loops. This row counts both LP and BP/HP copies and branch-layout
loop spans; it does not measure one executed sample path or device cycles.
Existing entries retain their original budgets. The default target build uses
`-Os` with selective main-loop `minsize`; the new helper remains reachable from
audio and is not selected for `minsize`.

The helper saves `rets,r15-r4` (52 bytes) and reserves 84 stack bytes. Its caller
saves 52 bytes and reserves 112 bytes, and calls it once per block. The pair's
additive frames total 300 bytes; outgoing arguments, enclosing callers and
interrupt nesting still require real-device guard/timing checks. Host equivalence
and a static budget pass do not establish FM-1 timing or stack high-water use.
Device listening, MIX re-entry, USB streaming and diagnostics remain pending.
