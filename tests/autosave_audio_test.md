<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Automatic saves and effect tails (#178)

`autosave_audio_test.c` uses the real native FX buses, final stereo mixer/master,
`autosave_poll` and the persistence fixture's A/B NOR store. It does not replace
output readiness with a manually set busy flag. The fixture's main is excluded
with `PERSISTENCE_FIXTURE`; the ordinary persistence suite still runs separately.

After `./build.sh`, run the full suite with `tests/run_tests.sh`, or rebuild this
focused test at `-O1` and `-Os`, matching the full runner:

```sh
cc -O1 -w -Ibuild/gen -Ifirmware/src tests/autosave_audio_test.c -lm -o build/host/autosave_audio_test
build/host/autosave_audio_test
cc -Os -w -Ibuild/gen -Ifirmware/src tests/autosave_audio_test.c -lm -o build/host/autosave_audio_test_os
build/host/autosave_audio_test_os
```

The full runner also runs it under ASan/UBSan. Output reports actual last-audible
and first-erase times, erase peaks and counts. A failed assertion exits nonzero.
The independent PCM oracle requires no erase during an audible block or within
ten seconds afterward, exactly one eventual save, no repeated unchanged write,
and restoration of the deferred edit.

## Exact threshold and target ISR cost

Keep the per-channel energy sums in `uint64_t`. A CTL=32 block can require 36
bits, and shifting each squared sample before a 32-bit sum changes the exact
RMS threshold. For example, 30 final PCM samples at 32, one at 31 and one at 33
have energy `30*1024 + 961 + 1089 = 32770`, above `1024*32 = 32768`.
Summing each square shifted right by five gives `30*32 + 30 + 34 = 1024`,
which does not exceed `32*32 = 1024` and would incorrectly report quiet.
The native regression checks final alternating ±32 samples save once and ±33
samples continually defer; separately reported `-O2` runs are additional checks.

Fresh default target builds compare old main `0b407accd60f755e96a26a58419ebdd218090419`
with integration `f3354c6140956734b2a54402fbf9fffa9b19b97e`. Both use JieLi
Clang 4.0.1/pi32v2, target `-Os`, selective minsize, M8Stealth, normal feature
defaults including compiled CPU2 support, the checked-in CC0 samples and the
pinned AC79 SDK packaging inputs. Each revision uses its own pinned engine
submodule (`2d8853ad` and `9630426f`, respectively).

| Disassembly measure | Old main | Integration | Delta |
| --- | ---: | ---: | ---: |
| `fm1_alnk0_irq` decoded instructions | 1530 | 1658 | +128 |
| `fm1_alnk0_irq` instructions inside loop spans | 1421 | 1551 | +130 |
| `fm1_alnk0_irq` weighted loop cost | 8332 | 8441 | +109 (+1.31%) |
| `perf_master` decoded instructions | 46 | 79 | +33 |
| `perf_master` weighted loop cost | 30 | 44 | +14 |

These are `tests/target_budget.py` static disassembly estimates, not device
cycles, timing or a complete call-graph cost. The ISR retains seven divides
inside loop spans; calls there increase from 71 to 81. The comparison includes
all integrated changes and their compiler layout effects, so it does not
attribute the complete delta to energy accumulation alone. The fresh integration
passes the existing ISR budget 8285 (10% tolerance) and `perf_master` budget 46;
no budget was rewritten for this evidence. Hardware audio deadlines, shedding
and USB/MIDI stress remain pending on an FM-1.

## Reproduction and scenarios

On unchanged parent `8624a38`, a one-second 440 Hz sine send, amplitude 16000 Q15,
BPM 40, delay TIME 1/4 (65535 samples), FDBK 120, COLR/MIX 127, followed by zero
sends and no active voices, allows an autosave erase at **10250 ms** while the
real final master peaks at **5647 Q15**. BPM 40 is the current descriptor minimum;
it reaches the same maximum delay as the historical BPM-30 issue reproduction.
With the guard, the native delay remains above the 32-Q15 block-RMS threshold
through **52011 ms**, and the first erase is at **62250 ms**, peak **7 Q15**.
These are host scheduling observations, not device erase-time measurements.

The fixture covers silence, ROOM/SPRING/stereo HALL, chorus, the actual
`perf_begin`/`perf_master` branch, USB LEVEL FIXED with silent DAC, both scope
settings away from HOME, right-only bursts and an isolated negative pulse
between main-loop polls, exact +/-32 and +/-33 final PCM, generation and
millisecond-clock rollover, dirty-data retention/restoration, failed writes,
retry and wear gaps. The existing persistence suite covers playing/stopped,
physical input, active release voices, editor holds, damaged/torn copies,
RESTORE LAST OFF and long-session wear. Audio/MIDI/switch suites remain separate.

## Why block RMS

The threshold is per channel over each production CTL=32-frame block, about
0.726 ms, never a sum of left and right. Each channel's squared-Q15 energy is
compared with `32*32*n`, without division or square root. A loud single-sample
pulse still qualifies; isolated peaks just above 32 in otherwise quiet residuals
need not. Every qualifying block advances one audio-owned generation; main
resets its existing ten-second quiet/idle interval whenever that scalar changes.
There is no forced save timeout.

The unchanged ROOM DSP has varying rounded residuals. With SIZE 0/DAMP 0, the
149–150 s stereo output measured min -36, max 34, mean 0.392303 and AC RMS
9.905867 Q15 per channel (~-70.4 dBFS). A peak-only 32-Q15 gate would postpone
forever; block RMS allows the quiet residual to save. At SIZE 127/DAMP 0 the
same window measured min -202, max 200, mean -0.070460 and AC RMS 60.092732
Q15 (~-54.7 dBFS): it continues holding under the defined policy. The test runs
that output for 150 s with zero erases, then switches the real reverb model to
clear the old resonator and verifies an eventual save. No DSP rounding or sound
behavior is changed. Physical audibility still needs device listening.

Real FM-1 listening, save/reboot restoration and audio/scan/USB error counters
are pending hardware validation; host tests establish the scheduling decision.
