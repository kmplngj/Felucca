<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Raw render-stage evidence (#94)

`FELUCCA_RENDER_STAGE=1` enables one development observer: CPU0's elapsed
`mix_block()` calls, summed over each rendered DMA half. The flag defaults to
`0`; normal builds compile out its hooks, state and console fields, and
`--release` refuses the enabled flag. This is measurement infrastructure for
[#94](https://github.com/kmplngj/Felucca/issues/94), without a DSP optimization or
a completed retain/reject decision. **FM-1 validation remains pending.**

The observer reads the existing HAL `fm1_ticks()` helper and reports raw uint32
TIMER4 ticks. A mix interval includes TIMER5 preemption and, when the worker is
used, elapsed CPU1 execution/wait overlap. It measures neither exclusive CPU0
synthesis work nor CPU1 work, whole-chip utilization, instruction cycles or a
clock frequency. Do not convert these fields to time using a guessed frequency.
Existing `cpu_pct`/`audio_max_us` keep their separate legacy semantics described
in [diagnostics interpretation](diagnostics.md#interpreting-a-report).

## Window, ownership and lifetime

For each CTL block, CPU0 takes an adjacent timer-read pair as an empty-region
control, then reads the timer around `mix_block()`. The reads are explicitly
sequenced with compiler publication barriers. The observer sums the mix intervals
and empty controls separately within the half; it never subtracts the controls.
TIMER5 can preempt either interval, including the empty control.

The **observer window** begins inside the rendered-half branch, after the legacy
`t0` read, nested-counter reset, auxiliary acknowledgement and free-half lookup.
It ends at the same raw ending read used by the legacy meter, after rendering,
half acknowledgement and `audio_halves` increment. It includes the empty controls,
stage reads and per-block observer bookkeeping. Publication, legacy shedding/load
bookkeeping after that ending read, late detection and the remainder of ISR exit
are outside the window. It is not complete interrupt-entry-to-exit timing.

Each window boundary reads `t5_nested_ticks` before and after its timer read.
Equal bracketing values permit the matching ending-minus-starting nested total.
A changed bracket rejects that half instead of silently including TIMER5 service
from outside the window. The next unambiguous half can recover. The earlier legacy
`t0`/reset boundary is not claimed to align with this separate window; this feature
does not repair or redefine the legacy meter.

ALNK0 on CPU0 alone writes observer state. CPU1 part renderers and TIMER5 never
write it. CPU0 publishes once per rendered half using an odd/even sequence and
the existing compiler publication barrier. Foreground `status` attempts one
fixed-size copy, with interrupts enabled, and validates the sequence before
formatting that local copy. An active or intervening writer makes that reply's
stage snapshot unavailable; there is no retry loop or IRQ-disabled copy. Other
`status` fields and the collector's four-command snapshot remain separate reads.

All state is ordinary BSS, initialized at application startup. Counts and accepted
maxima last for that application lifetime. Collection never clears them; there is
no reset command or retained observer state. Reset/restart begins a new lifetime,
so retain the build identity and `boots` evidence and never join counters across
reboots. An auxiliary-only audio interrupt publishes no stage observation.

## Output contract

The existing `status` command supplies these optional fields. Counts, error bits
and raw tick values use an explicit `0x` prefix; small schema/availability flags
use decimal. The unchanged collector preserves the fields as unknown optional
data, including their unsigned values, without inventing counter deltas or stage
validity rules. Inspect them in `samples.jsonl` and the snapshots in `summary.json`.

| Field | Meaning |
| --- | --- |
| `stage_schema` | `1` identifies this schema; absent when instrumentation is compiled out. |
| `stage_readable` | `1` means a coherent copy was obtained. At `0`, all remaining stage fields are absent. |
| `stage_error` | Sticky error bits: `0x1` range/progression/consistency; `0x2` sum overflow; `0x4` count exhaustion. Bits may combine. |
| `stage_halves` | Number of accepted rendered-half observations since startup. |
| `stage_blocks` | Number of CTL mix calls in those accepted halves. |
| `stage_rejected` | Number of boundary-ambiguous halves rejected before any sticky failure. It is not a count of foreground snapshot-copy failures. |
| `stage_available` | `1` only when the latest published half was accepted and no sticky failure exists. `0` includes startup before the first observation, a latest rejected half, or sticky failure. |
| `stage_mix_last_t4`, `stage_mix_max_t4` | Latest accepted sum of inclusive mix intervals per half, and the largest accepted such sum. |
| `stage_empty_last_t4`, `stage_empty_max_t4` | Latest accepted sum of adjacent empty-read controls per half, and its accepted maximum. |
| `stage_window_last_t4`, `stage_window_max_t4` | Latest accepted observer-window elapsed ticks, and its accepted maximum. |
| `stage_nested_last_t4`, `stage_nested_max_t4` | TIMER5 service ticks matching the latest accepted window, and its accepted maximum. |

All eight timing fields are absent when `stage_available=0`. A latest rejected
half does not expose the preceding successful timing as a fresh sample. After
recovery, maxima still cover accepted halves only. Any rejected observations mean
those maxima do not establish a complete worst-case ceiling. A coherent foreground
copy can also be older than the current half by the time its text reaches the host.

Unsigned subtraction permits one TIMER4 wrap for a bounded interval. A mix interval
must be positive and at most `0x7fffffff`; an empty control may quantize to zero
and has the same upper bound. An accepted window must be positive, at most
`0x7fffffff`, contain at least one sampled block, and be no smaller than its nested,
mix-sum or empty-sum value. Sum overflow and any count increment that would exceed
uint32 fail closed before wrapping. Counts and timing history then freeze; the
sticky error and unavailable state remain until application startup resets BSS.
The sequence number itself wraps modulo uint32; a foreground copy must not span
an entire sequence cycle.

These bounds cannot detect a stall of a full timer period or more. The HAL exposes
raw counter reads, not a live clock-identity/availability attestation. Zero or
inconsistent observations fail closed, but plausible progressing values cannot
certify a modified/unsupported timer configuration. Use the normal HAL startup,
retain exact configuration, and leave physical clock identity unproved unless
separately established. This observer adds no clock decoder and depends on neither
the unmerged boot-clock observation nor instruction/cache probes.

Do not subtract independent maxima, add overlapping maxima, subtract nested work
twice, or automatically subtract empty controls. Mix, window and nested maxima
can come from different halves. The fields provide no distribution or p95/p99.
An unchanged cumulative maximum does not identify the collection interval's peak.

## Builds and resource evidence

Use the [build prerequisites](../BUILDING.md#prerequisites-macos), the same clean
candidate revision, profile, engine pin, assets, JieLi toolchain/SDK and selective
size settings for both builds. Disable other diagnostic experiments. For example,
from a trusted checkout, prepare separate saved artifact directories:

```sh
export FELUCCA_PROFILE=standard FELUCCA_CPU2=1 FELUCCA_CDC=1 FELUCCA_CDC_DEFAULT=1
export FELUCCA_CRASH_CTX=0 FELUCCA_MUL64_REPRO=0 FELUCCA_SCREEN_CAPTURE=0 FELUCCA_ISR_ASSERT=0
mkdir -p build/render-stage-off build/render-stage-on
FELUCCA_RENDER_STAGE=0 uv run --locked --group build ./build.sh
cp build/felucca.fwsc build/felucca.bin build/felucca.elf build/felucca.dis build/felucca.dis.profile.json build/resource-report.json build/build-identity.json build/render-stage-off/
cp build/gen/resolved-profile.json build/render-stage-off/
FELUCCA_RENDER_STAGE=1 uv run --locked --group build ./build.sh
cp build/felucca.fwsc build/felucca.bin build/felucca.elf build/felucca.dis build/felucca.dis.profile.json build/resource-report.json build/build-identity.json build/render-stage-on/
cp build/gen/resolved-profile.json build/render-stage-on/
```

Use fresh output directories and check each build succeeds before preserving its
artifacts; keep logs and complete [performance provenance](performance.md).
`macro` requires a separate matched pair and its own package filename. An ordinary
PR/default-profile artifact does not establish an enabled diagnostic build.

Source layout currently adds **72 B of static observer BSS** when enabled: 52 B
record, 4 B sequence and 16 B per-half accumulator. The foreground copy is 52 B;
this is not the function's complete stack frame or peak stack usage. The observer
declares no POOL, RAMTEXT or NOINIT state. These are source-layout observations,
pending linked target accounting, alignment and compiler effects.
Exact measured numbers belong in the PR's validation evidence, bound to its final
revision and build inputs; the source sizes here are not whole-ISR stack deltas.

| Required comparison | Status |
| --- | --- |
| OFF/ON app, regular RAM, POOL, RAMTEXT and NOINIT bytes/margins | Pending coordinator's fresh matched target builds. |
| Target frames, stack reservations/margins and changed ISR code | Pending coordinator's exact-candidate target evidence. |
| Default code/data elimination and host/target observer cost | Pending coordinator's integrated checks; host results do not measure FM-1 overhead. |
| Device observer/collector impact, deadlines and scan misses | Pending matched FM-1 runs below. |

## User test instructions — pending hardware validation

These are manual tester steps, not a record of performed installation or device
tests. Use an FM-1, USB data cable, Mac/Linux CDC host, headphones or analogue
monitoring, and a saved reproducible project/MIDI timeline for loaded cases. Finish
edits first and retain the normal package plus any needed project/settings backup.
The observer introduces no saved format, but menu changes below alter settings.

1. Retain each reviewed OFF/ON package, source revision, resource report, flags and
   build identity. From a trusted caller checkout, install only the intended saved
   package using the [manual installer](../BUILDING.md#install):

   ```sh
   uv run --locked --group midi tools/fm1_install.py build/render-stage-off/felucca.fwsc
   uv run --locked --group midi tools/fm1_install.py --info
   ```

   Let the installer prompt for confirmation and require successful restart.
   Repeat with `build/render-stage-on/felucca.fwsc` for the enabled case. Preserve
   package/build provenance; the displayed version alone does not distinguish
   variants, and an updater success does not test observer behavior.
2. Follow the [idle setup](diagnostics.md#idle-baseline-setup): restart with no keys
   held, close MIDI/audio/serial applications, disconnect TRS input and start on
   HOME with transport stopped. Hold **HOME** for more than 0.7 s, release when MENU
   opens, turn **ALGORITHM** to **SYSTEM**, and turn **PRESETS** to **ABOUT**.
   Tap **OCT+**, record identity, then **OCT−** to return. Select **USB SERIAL** with
   PRESETS, record its old value, tap **OCT+** for ON if needed, then tap HOME to
   close MENU. Identify the newly enumerated CDC port explicitly.
3. In SYSTEM, similarly record **2ND CORE** and set it **OFF** with OCT− for the
   first matched pair. Close MENU and restart: this setting takes effect on the
   next boot. Return to HOME/USB SERIAL as above. Keep the same restored project,
   settings and host configuration for both images; allow 10 s to settle. Require
   silent audio and PLAY unlit before labeling the case idle.
4. Collect equal 60 s idle cases with 5 s intervals. Replace the example port and
   `FULL_OFF_REVISION`/`FULL_ON_REVISION` with the installed builds' full revisions:

   ```sh
   python3 tools/fm1_diagnostics.py --port /dev/cu.usbmodem1234 --duration 60 --interval 5 --firmware-revision FULL_OFF_REVISION --manifest build/render-stage-off/resource-report.json --scenario 'render-stage OFF; CPU2 OFF; idle' --output build/diagnostics/render-stage-off-idle
   python3 tools/fm1_diagnostics.py --port /dev/cu.usbmodem1234 --duration 60 --interval 5 --firmware-revision FULL_ON_REVISION --manifest build/render-stage-on/resource-report.json --scenario 'render-stage ON; CPU2 OFF; idle' --output build/diagnostics/render-stage-on-idle
   ```

   Run each command only after installing its corresponding variant; on Linux
   substitute the selected `/dev/ttyACM…`. Use new output paths for repeats. These
   operator-supplied revision/manifest labels do not independently prove device
   identity. The collector creates no notes or USB audio stream.
5. Expect OFF replies to omit every `stage_*` field. ON should supply coherent
   available observations with `stage_error=0`; an interrupted foreground read or
   boundary rejection is explicitly unavailable and may recover on later reads.
   Retain every rejection/error and do not treat a missing value as zero. Counts
   and accepted maxima should persist across captures within one boot. Restart
   the enabled image and collect again to establish a new lifetime, retaining
   boot evidence rather than joining the two sessions.
6. Compare OFF/ON error deltas, sound and controls at the same workload. Retain
   `audio_late`, `voices_shed`/`voices_given_up`, USB/UART/UAC errors, input scan
   windows and surviving-voice observations together. A collector `VALID` result
   means continuity, not an audio/deadline pass. Inspect enabled empty-control
   sums separately as inclusive read-pair controls; they do not calibrate the full
   observer or collector overhead, including publication outside its window.
7. For loaded qualification, retain the exact saved project, engines/presets,
   effects, routing and a fixed MIDI file/event log. A simple initial timeline is
   CH1 note 48, velocity 100, held 3.5 s and released for 0.5 s, repeated 15 times
   with transport stopped. Confirm that the intended track receives CH1 and keep
   identical admitted/surviving voices. Record acquisition alignment and repeat
   the same event file for both images; the collector does not synchronize it.
   Expand to sustained chords, attacks/releases and engine/FX transitions only
   with equally specified input. Reuse the [#540 workload description](audio-deadline-investigation-2026-10-21.md#workload-and-acquisition)
   where appropriate without assuming its older timing baseline reproduces.
   Repeat matched runs while the host records Felucca USB audio first at 44.1 kHz
   and then 48 kHz; confirm the actual UAC alternate/rate in replies. Add a fixed
   MIDI/panel-activity timeline, and test CPU2 ON separately only when that worker
   configuration is deliberately under test. Never combine those configurations.
8. Report OFF and observer-only results separately from any later optimization.
   No optimization variant is supplied here. A smaller surviving workload cannot
   establish a gain; unexplained new misses/errors or observer failures block an
   acceptance claim. Retain raw replies, JSONL/summary, sound observations,
   revision/configuration, duration and resource reports for a retain/reject
   decision. Device clock and observer/collector overhead remain unmeasured until
   separately supported by the physical evidence.
9. Stop host notes/streams and close the collector. Restore original menu settings
   through the same SYSTEM route; OCT− sets USB SERIAL OFF when that was its
   original value. Restore 2ND CORE as required and restart for its change. Install
   the retained normal `.fwsc` with the same trusted installer and verify identity.
   Restore the original project/settings as needed and report unperformed cases
   as pending.

README assessment: no overview change is needed for this narrow default-off
instrumentation slice; the existing performance/diagnostic overview covers its
purpose. Activation and limits are indexed in diagnostics/build options, and the
changelog's Added entry links this guide.
