<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Silent FX bus regression (#153)

`python3 tests/fx_rest_test.py` is wired into `tests/run_tests.sh`. It builds
fresh host binaries at `-O2` and `-Os` with vectorization disabled for the latter.
It requires generated headers from `./build.sh`, as the other DSP tests do.

The chorus, delay and HALL rest paths come from PR #41. The suite invokes
`python3 tests/fx_rest_test.py --require-rest`, so removal of the optimization
fails instead of silently skipping. SPRING's skip assertion becomes active
with the combined #159/#172 (#39) implementation. Direct invocation
without `--require-rest` can still inspect older sources and explicitly skips
when all rest paths are absent. The adapter also supports PR #159's external
`spring_rest`/`spring_live` gate and asserts its actual skip execution.

To validate another compatible FX revision, provide its checked-out `fx.c`:

```sh
python3 tests/fx_rest_test.py --fx-source /path/to/pr41/firmware/src/fx.c \
    --require-rest --mutation-check
```

Other firmware sources and generated assets still come from this checkout.
This is a focused FX compatibility check, not that branch's full regression
suite. `--cc` or `CC` selects the host compiler. Outputs are under the ignored
`build/host/fx_rest/` directory; `--out DIRECTORY` isolates another run.
`--timeout SECONDS` bounds each compile/render subprocess (default 180).
The runner prints the selected FX and harness SHA-256, compiler identity,
flags, configuration count, skip counts and elapsed time. Retain that output
with the checkout/engine revision and generated-profile provenance when
comparing runs. No network requests or git mutations are made by the runner.

The adapter inserts a force-off switch and counters into temporary source
copies. Every insertion requires one exact match; edits to the optimization
must be reviewed alongside this adapter. It never changes production sources
or compiler options. The reference runs the same DSP with skipping disabled,
so intentional changes to sound need no new golden.

Each of 63 trajectories covers a reverb model (ROOM/SPRING/HALL), feedback
0/60/120, and a combination of chorus/delay/reverb sends (each bus alone,
every pair, all three). Corner settings vary SIZE, DAMP, chorus depth/rate,
delay color and dotted delay time. A loud burst is followed by 20 seconds of
silence, signed sends of amplitude 1 and 4, a SIZE/DAMP change while silent,
a burst three blocks into the SIZE glide, model switches, and actual ECHO
THROW and REV THROW send injection via `perf_throw`.

Fourteen additional trajectories exercise boundaries without repeating the
long matrix:

- Six signed, mixed-bus trajectories each start 15 episodes from empty state.
  Only the final input sample is nonzero, at amplitudes +1/+4/+65536 or
  -1/-4/-65536. ROOM and SPRING use blocks of 1, 2, CTL/2, CTL-1 and CTL
  samples. HALL uses CTL throughout: its production implementation explicitly
  renders HL_NC=CTL/2 and ignores `n`, so shorter HALL blocks and partial
  transitions involving HALL are outside this interface's contract.
- The delay return MIX is zero for each wake and re-enabled after the next
  block. At amplitudes 4 and 65536 the test requires recorded live delay
  history at re-enable. Subsequent production-size blocks extend beyond the
  full delay line, comparing future wet/side PCM and state. The tiny +1 send
  can quantize to zero; its raw input must still prevent the rest branch.
- Eight delay probes combine filter states -1/+1, feedback 0/127 and color
  0/127 with zero lines. They check the first block's exact rest eligibility
  and subsequent state/audio. These filter states are deliberately seeded
  arithmetic endpoints, not a claim that every combination is reached by a
  normal audio render. No inconsistent nonzero line with a zero live counter
  is used to judge the optimization.
- Zero-length calls with a pending model change must preserve all FX/HALL
  state (including caches and scratch), full buffers, skip counters and output
  scratch. They do not count as successful skips.

The comparison covers wet and effective stereo-side samples and persistent
FX/HALL state after every block. Full line buffers are checked every 257
blocks and at the end. Cached HALL gains and block scratch arrays are masked:
the regular path recomputes them even during silence, while rest skips them.
Each trajectory must actually skip chorus/delay, its initial HALL model, and
its initial SPRING model when PR #159 or #172 is present. Forced-off runs must report
zero skips. ROOM has no skip assertion: its floored comb feedback can retain
an offset. After every nonempty block, counters also assert that a bus did
not skip any nonzero raw input or recorded live history; delay and HALL
checks include active filter/output state. These are one-way obligations:
zero input/counters alone do not establish that a skip is safe. PCM and
persistent-state comparisons establish equivalence on the rendered
trajectories. Counters assert branch execution, not a timing or CPU improvement.

Every invocation builds three negative controls in separate temporary source
copies: incorrect chorus and delay rest write-index advances, and a zero-input
scan that overlooks the final sample. Each must fail the reference audio/state
comparison or the input/live gate assertion. Compiler failures, crashes,
timeouts and missing skip coverage do not qualify as successful detection.
`--mutation-check` additionally changes the HALL rest phase advance and, when
present, the SPRING rest write-index advance. All mutations use the compact
14-trajectory boundary set at `-O2`; the unmodified 77 trajectories run at both
`-O2` and `-Os`. Production firmware and goldens/budgets are never modified.

The merged SPRING path retains #159's external `spring_rest`/`spring_live`
helpers and #172's generalized exact filter fixed-point predicate. Liveness
updates occur once per rendered block; skipped blocks advance state once.
The reverb harness also covers nonzero low-cut fixed points at high DAMP.
