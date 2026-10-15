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
`build/host/fx_rest/` directory. No network requests or git mutations are made
by the runner.

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

The comparison covers wet and effective stereo-side samples and persistent
FX/HALL state after every block. Full line buffers are checked every 257
blocks and at the end. Cached HALL gains and block scratch arrays are masked:
the regular path recomputes them even during silence, while rest skips them.
Each trajectory must actually skip chorus/delay, its initial HALL model, and
its initial SPRING model when PR #159 or #172 is present. Forced-off runs must report
zero skips. ROOM has no skip assertion: its floored comb feedback can retain
an offset. Counters assert branch execution, not a timing or CPU improvement.

`--mutation-check` deliberately changes the HALL rest phase advance and, when
present, the SPRING rest write-index advance in separate temporary copies.
Each must produce an audio/state mismatch. The check is optional because it
adds complete pairs of renders.

The merged SPRING path retains #159's external `spring_rest`/`spring_live`
helpers and #172's generalized exact filter fixed-point predicate. Liveness
updates occur once per rendered block; skipped blocks advance state once.
The reverb harness also covers nonzero low-cut fixed points at high DAMP.
