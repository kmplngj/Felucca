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

Target coverage includes the new `analog_render_1` helper. Its measured default
JieLi Clang 4.0.1 M8Stealth static cost is 671: 807 total instructions, 543 loop
instructions, 16 weighted divides, no calls inside loops. This row counts both
LP and BP/HP copies and branch-layout loop spans; it does not measure one executed
sample path or device cycles. Existing entries retain their original budgets.
The default target build uses `-Os` with selective main-loop `minsize`; the new
helper remains reachable from audio and is not selected for `minsize`.

The new helper saves `rets,r15-r4` (52 bytes) and reserves 80 stack bytes. Its
caller retains its 52-byte save plus 108-byte allocation and calls the helper
once per block. Thus the MIX-zero LP path adds a 132-byte frame compared with
its formerly inlined loop. This renderer pair's additive frames (292 bytes)
remain below the existing SYNC path (328 bytes); outgoing arguments, enclosing
callers and interrupt nesting still require real-device guard/timing checks.
Host equivalence and a static budget pass do not establish FM-1 timing or stack
high-water use. Device listening, MIX re-entry, USB streaming and diagnostics
remain pending in the PR description.
