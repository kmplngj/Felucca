<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Collecting device diagnostics

## Diagnostic capabilities

Choose the capability for the question being investigated. Console commands require
a build with USB CDC enabled and MENU > SYSTEM > USB SERIAL ON. Read
[build options](../BUILDING.md#build-product-identity-forks) before selecting a diagnostic
variant; enabling a flag locally does not identify the firmware already on a device.

| Capability | Access | Availability and scope |
| --- | --- | --- |
| Build identity | Startup, ABOUT, INFO | Normal firmware identifies the version, commit or PR and fork source; see [build identity](../BUILDING.md#build-revision-and-pr-identity). |
| Health, input and retained crashes | USB SERIAL `status`, `dbg`, `inp`, `crash`; `tools/fm1_diagnostics.py` | Normal CDC builds. The read-only collector retains raw replies, JSONL and summary counter deltas; [collection and interpretation](#collect-diagnostics) are described below. Input latency requires confirmed `FM1_INPUT_LAT` instrumentation; render load is not whole-chip CPU use. |
| Boot clock registers | USB SERIAL `status` keys `boot_clock_*`; the same read-only collector | Normal CDC builds, captured once before normal initialization. Seven raw words help compare boot paths; they neither measure MHz nor correct clocks. See [boot clock evidence](#boot-clock-evidence). |
| Interrupt misuse | `status` keys `isr_misuse`, `isr_misuse_pc` | Opt-in `FELUCCA_ISR_ASSERT=1` on the FM-1, default `0`. Counts guarded main-loop calls made in interrupt context; [target and host behavior differ](#interrupt-context-assertion-felucca_isr_assert). |
| Crash register context | `crash` register fields; `status` key `crash_ctx` | Development-only `FELUCCA_CRASH_CTX=1`, default `0`. Adds retained faulting-core registers and 76 B NOINIT; read the [layout, transition and capture limits](#diagnostic-builds-for-425-felucca_crash_ctx-felucca_mul64_repro). |
| Arithmetic reproducer | `status` keys `mul64_*` | Development-only `FELUCCA_MUL64_REPRO=1`, default `0`. Adds bounded main-loop test work; see [the diagnostic build](#diagnostic-builds-for-425-felucca_crash_ctx-felucca_mul64_repro) and [matched device-soak procedure](mul64-hload-audit.md#phase-2-step-1-synthetic-reproducer-and-device-soak). It does not fix or prove the cause of audio failures. |
| Boot area and declared clock | `tools/fm1_bootarea.py --raw DUMP.bin` | Offline and read-only, any firmware: names a flash dump's or package's boot area (M-VAVE V15/V16, m-bootloader, unknown), checks its record and SPL CRCs, and reads the chip key and `isd_config.ini` clock fields. Needs a dump from FM-1 Transporter or M-Flasher; it does not read live clock registers (#618). See the [offline boot-area survey](boot-area-survey.md) for bounded input checks, formats and interpretation. |
| Rendered-screen screenshots | USB SERIAL `screen` commands; `tools/fm1_screenshot.py` | Development-only `FELUCCA_SCREEN_CAPTURE=1`, default `0`. Stopped static HOME/menu pixels become a verified PNG/JSON. Default capture requires an awake display; explicit `--wake` silently wakes, awaits redraw and holds awake for the bounded session. See [capture setup, bounded memory and failure modes](screen-capture.md); physical LCD colours/backlight are outside its scope. |
| MIDI consumer queue evidence | Optional `status` `mq_*` fields; existing read-only collector | Development-only `FELUCCA_MIDI_QUEUE=1`, default `0`. Consumer conservation, per-source/class enqueue-age maxima in milliseconds and inclusive raw TIMER4 drain ticks; [units, lifetime, unavailable states, cost and device checks](midi-queue-evidence.md). Excludes wire/acquisition, USB pre-admission and downstream musical timing; hardware/overhead qualification is pending. |
| USB test-tone continuity | Existing stereo WAV files; `tools/uac_tone_check.py` | Offline checker for a known `FELUCCA_UAC_TONE=1` build; tone mode defaults off. Requires complete 16-bit stereo PCM at the configured 44.1/48 kHz rate and actual tone synchronization. See [recording interpretation](#usb-test-tone-recordings); this is separate from CDC collection and does not qualify physical USB or measure diagnostic overhead. |
| Raw render-stage evidence | Optional `status` `stage_*` fields; existing read-only collector | Development-only `FELUCCA_RENDER_STAGE=1`, default `0`. Inclusive CPU0 mix-call sums, empty controls and an observer window with matching nested ticks; rejected/invalid snapshots remain unavailable. See [units, lifetimes, resource limits and matched FM-1 procedure](render-stage-evidence.md). Raw TIMER4 ticks establish no frequency, exclusive CPU cost or measured overhead; hardware acceptance is pending. |
| Voice-retirement/LFO observation | Explicit `tools/retirement_measure.py` host run | Off unless invoked. Exports pinned source and applies guarded instrumentation only to ignored host copies; no device transport, firmware flag or target resource reservation. Observer file IO invalidates timing comparisons. See the [host measurement and reproduction](voice-retirement-measurement.md) and [performance scope](performance.md#host-retirement-observation). |
| Native emulator replay evidence | Explicit `tools/native_emulator_replay.py` host run | Off unless invoked. Requires matched existing native artifacts and a corrected pinned-emulator receipt; retains bounded repeated trace/PCM, modeled-UART delivery and silent controls. Builds no firmware and changes no target resource reservation or device state. See the [reproduction and limits](native-emulator-replay.md); this is not a hotspot or physical-timing report. |
| Native guest hotspot attribution | Explicit `tools/native_hotspots.py` host run | Off unless invoked. Rechecks retained replay evidence and matched native artifacts, then counts declared guest windows by function range and emulator instruction class. Executes no firmware and changes no target resource reservation or device state. See the [inputs and counting limits](native-hotspots.md); entry hits are not calls or physical timing. |
| Native audio-window evidence | Explicit `tools/native_audio_window.py` host run | Off unless invoked. Uses seven bounded emulator children and a verified retained replay basis to qualify a partial renderer window, repeated trace/PCM and silent controls. Builds no firmware and opens no device. See the [source-qualified recipe and limits](native-audio-window.md); modeled IRQ state and guest counts are not physical timing. |
| Factory-sound digital levels | Explicit `tools/loudness_audit.py` host run with the optional `audit` dependency group | Off unless invoked. Renders 1–8 selected standard-profile cases with isolated generated inputs; retains pre/post-master stereo raw data, JSON metrics and fixed-scale WAVs under ignored `build/`. No device transport, firmware flag, target resource reservation or automatic level trim. Native arithmetic failures stop capture. See the [bounded workflow and meter/listening limits](loudness-audit.md); host levels do not calibrate physical DAC/USB output. |

The development-only flags above are refused with `--release`. The four-command
collector does not run a reproducer, enable instrumentation or capture screenshots;
it only reads fields supplied by the installed build. Record the exact build, flags,
workload and hardware observations with each result. See the linked guides for resource
costs and distinguish host/emulator coverage from real FM-1 observations.

## Boot clock evidence

With `FELUCCA_CDC=1` (the normal default), startup reads these seven 32-bit
registers, in order, after the existing CPU1 hold when compiled in and before TIMER4/reset/peripheral
initialization. Their values survive RAM initialization through a startup-stack
snapshot and are copied into a 32-byte target POOL record. Nothing is added to
NOINIT or persistent storage. The status handler reads the saved words, never the
live clock registers; polling does not add clock-register accesses.

| Status key | Register address |
| --- | --- |
| `boot_clock_10014` | `0x10014`, including the low-eight-bit system-clock selector and the other original bits |
| `boot_clock_1000c` | `0x1000C` |
| `boot_clock_10008` | `0x10008` |
| `boot_clock_119a8` | `0x119A8` |
| `boot_clock_119ac` | `0x119AC` |
| `boot_clock_119a0` | `0x119A0` |
| `boot_clock_119a4` | `0x119A4` |

These hexadecimal words are observations, not counters. The collector preserves
them in each status snapshot in JSONL and the summary's start/end snapshots; it
does not subtract them, classify the bootloader, infer MHz or label a clock safe.
Older firmware may omit all seven. A partial group or malformed/out-of-range word
invalidates that reply; absence is unavailable evidence, never seven zero values.
CDC-disabled builds omit capture and storage. Early MMIO capture is target-only;
native replay and browser emulation do not read these hardware addresses.
MIDI-only rescue has no CDC console;
returning to normal startup captures a new boot, not the earlier rescue state.

The added workload is seven sequential volatile reads once at boot, the POOL
record and seven formatted lines per status reply. The startup caller does not
return while the application runs: its enlarged frame remains active rather than
being reclaimed after publication. There is no added audio/TIMER5 operation,
PLL/clock write, delay or corrective path.
Use matched polling/no-polling runs when assessing the extra reply traffic. Exact
linked region/frame costs belong to the candidate's target resource report.
A controlled standard-profile comparison against `29ad24fd` measured +324 bytes
app and +32 bytes POOL, unchanged ordinary RAM/RAMTEXT/NOINIT, and a startup
caller frame of 32 rather than 8 bytes (+24 bytes, persistent). Protected interrupt
function sizes/frames and static budget metrics matched that baseline; relocated
addresses change machine bytes. This is static build evidence, not device timing
or a complete stack bound; final committed-package results are recorded in the PR.

For a device comparison, follow the idle setup below on an already installed,
identified candidate and collect one run per available bootloader/reset path.
Record known bootloader identity, cold versus warm start, firmware/package hash
and all seven words. Do not switch bootloaders or interrupt updates merely to
collect another row. Host fake-register/parser tests establish ordering and format
only. [Recorded device observations](https://github.com/kmplngj/Felucca/pull/761#issuecomment-6490745576)
cover V15/V16 and m-bootloader 1.2 cold starts and OTA returns on the earlier
standalone #648 and integrated `526824f3` builds. They do not qualify this merged
revision. Its reset-path checks, loaded polling comparisons and live stack evidence
remain pending. [#618](https://github.com/kmplngj/Felucca/issues/618) owns the later
retain/defer decision; no clock correction is enabled by this diagnostic.

## USB test-tone recordings

For an existing recording from a known `FELUCCA_UAC_TONE=1` build, run:

```sh
python3 tools/uac_tone_check.py recording.wav
```

Record the firmware revision/flags, configured USB rate, recorder rate and host
setup alongside the WAV. Tone mode supplies fixed diagnostic triangles on the USB
capture stream; an ordinary musical recording is not a tone fixture. The checker
accesses no device and changes no firmware or settings.

Leading silence is allowed. The first non-silent data must synchronize with a
pair of consecutive tone frames; unrelated data, a nonzero invalid prefix,
unsupported rates and incomplete PCM fail. The reported checked-frame count
includes only matched frames. A discontinuity in the expected tone sequence
produces a break; resynchronization does not make that file pass. The pattern
repeats every 100 frames, so loss or repetition of a complete pattern period can
be indistinguishable from a shorter or longer valid recording. WAV checks alone
cannot detect those cases. Every complete
final frame is checked once synchronized, but file boundaries cannot establish
continuity outside the recording. Each file is reported even if another input
is malformed; the command exits 1 if any file fails.

A passing WAV establishes this pattern's continuity only over the checked samples.
Physical USB qualification still needs matched device counters, recorder error
status, workload/build identity and repeated captures. This checker does not measure
clock accuracy, instrumentation overhead or real-device audio deadlines.

## Collect diagnostics

For early boot failure, see [USB rescue and compatible loaders](usb-rescue.md).
Rescue is MIDI-only and has no CDC diagnostics console; this guide applies after
normal application startup.

`tools/fm1_diagnostics.py` collects the existing Felucca CDC console on macOS and Linux
using Python 3's standard library. Enable USB SERIAL on the device and explicitly select
its CDC tty. Close other serial applications first. The collector opens the tty exclusively,
asserts DTR to obtain the console banner, and restores terminal settings on close.
Opening a port does not establish that its firmware matches the checkout.

Follow the [idle baseline setup](#idle-baseline-setup) below. From this checkout's root,
collect 60 seconds with equal 5-second windows:

```sh
python3 tools/fm1_diagnostics.py --port /dev/cu.usbmodem1234 \
  --scenario 'idle; transport stopped; no MIDI/audio stream; USB SERIAL on' \
  --duration 60 --interval 5
```

The port is required; there is no discovery or automatic selection. Linux tty names commonly
start with `/dev/ttyACM`. The default output is a fresh timestamped directory inside
`build/diagnostics/`; `--output build/diagnostics/my-run` selects another new directory
inside this checkout's ignored `build/`. Existing directories are never overwritten.
Windows serial transport is not implemented.

Only `status`, `dbg`, `inp` and `crash` are sent, in that order for each snapshot.
The collector has no arbitrary-command option, memory writes, UBOOT, installation,
settings changes or MIDI endpoint. Felucca MIDI command 72 remains `MENU_DESC`;
Melodee's command 72 diagnostics are incompatible and are not used.

Startup and every command have a timeout (`--timeout`, default 2 seconds, maximum 30)
and a 64 KiB response limit. Partial reads, command echo and the final `> ` prompt
are handled explicitly. A timeout, framing error or disconnect preserves partial bytes
and stops the session, so a delayed response cannot become another command's sample.
Ctrl-C during collection saves an invalid session with the evidence received so far.
Terminal setup/restoration failures are reported as invalid captures as well.

## Idle baseline setup

This is a quiet baseline for the current project's settings, not a four-track or USB
audio stress test. Use the same project and settings for repeated comparisons; record
the installed build revision separately from the displayed version. The following route
matches this checkout's panel code; real-device execution remains pending.

1. Start with an FM-1 already running a Felucca build with `FELUCCA_CDC=1` and
   `FELUCCA_CDC_DEFAULT=1` (the defaults). Finish any edits before restarting it.
   Close the web editor, DAW, MIDI senders, audio capture
   and serial applications; disconnect TRS MIDI input. Restart the FM-1 with no keys or
   buttons held, then connect its USB data cable to the Mac/Linux host. Boot reaches HOME
   with transport stopped; RESTORE LAST can restore project settings, but not playback.
2. Hold **HOME** for more than 0.7 seconds until MENU appears, then release. Turn
   **ALGORITHM** until the **SYSTEM** tab appears. Turn **PRESETS** until **ABOUT** is
   selected, tap **OCT+** to open it, and record the firmware version. Tap **OCT−** to
   return to the tab's rows.
3. Turn **PRESETS** to **USB SERIAL**. Record its original value. If it is OFF, tap
   **OCT+** to set it to **ON**. Tap and release **HOME** to close MENU and return to
   HOME. A USB SERIAL change re-enumerates the device when MENU closes; wait for the
   host to show its CDC port. A build with either CDC flag disabled cannot expose the console.
4. Identify the device's port in the host's device listing (macOS `/dev/cu.usbmodem*`,
   Linux `/dev/ttyACM*`); with multiple devices, compare listings before/after unplugging
   this FM-1. Select that exact port explicitly. Do not open a serial monitor alongside
   the collector. Linux requires permission to open the selected tty.
5. Keep the device on HOME, without starting playback, pressing keys, turning knobs or
   opening MIDI/audio streams. The green PLAY indicator should remain off and the audio
   should be silent; if these conditions fail, investigate before labeling the run idle.
   Allow 10 seconds to settle. Record the current project/settings
   and host configuration; keep them identical for baseline and candidate runs.
6. Run the command above (on Linux, replace its port with the selected `/dev/ttyACM…`).
   Leave the device idle until the command finishes. The printed path identifies
   `summary.json`; retain it with `samples.jsonl` and `console.raw`. Expect continuous
   collection (`VALID`), `playing: 0` in every status snapshot, and no new audio misses,
   voice shedding or stream errors. If fields are unavailable or collection is INVALID,
   report the limitation/reason instead of treating missing measurements as zero. Use
   the counter deltas and interpretation rules below; an idle capture cannot establish
   loaded performance or input latency.
7. After collection, restore USB SERIAL to its original value if changed: hold HOME,
   release after MENU opens, select SYSTEM with ALGORITHM and USB SERIAL with PRESETS,
   tap **OCT−** for OFF if needed, then tap HOME to close. Restore the host applications
   and MIDI cable as needed. Report the device build/version, host OS, scenario, logs
   and any observed versus expected differences.

For a playback/stress scenario, supply a separate reproducible setup: the initial
project and transport state, each track's engine/preset and effects, panel buttons and
knob values or a fixed external MIDI sequence, plus USB audio rate/routing. Run that
workload during collection and keep it identical across comparisons. Changing
`--scenario` only changes the report label; it does not create notes, effects or streams.

## Evidence files and provenance

- `console.raw`: exact received bytes, including startup, echoes and prompts.
- `samples.jsonl`: session metadata, each raw/parsed response, snapshots, intervals and
  a final summary. Responses contain base64 bytes, readable text, and offsets/lengths
  into `console.raw`. Unknown fields and unrecognized lines are retained. Missing
  counters remain absent in snapshots and `null` in deltas; supported zero is `0`.
  Oversize numeric values in unknown fields remain strings; malformed known counters
  invalidate collection while preserving their raw response.
- `summary.json`: the final session result with start/end snapshots, observed device
  versions, counter deltas, input-window counts, semantics and provenance.

All timing uses host monotonic seconds; a UTC label and host OS identify the run.
Duration, interval, selected port and scenario are recorded. Command timestamps expose
collector time spent requesting diagnostics, but do not measure its impact on the device.
Snapshots are sequential reads, not atomic, and the final snapshot takes additional time
after the requested workload duration. Duration must be a whole number of intervals;
intervals are 0.1..120 seconds. Choose an interval longer than a complete snapshot.
Unexpected host or device windows differing by more than 5% (minimum 20 ms tolerance)
invalidate their intervals. The first input window is always discarded.

If the connected firmware's provenance is known, supply it explicitly:

```sh
python3 tools/fm1_diagnostics.py --port /dev/cu.usbmodem1234 --scenario idle \
  --firmware-revision YOUR_DEVICE_BUILD_REVISION --manifest build/device-manifest.json \
  --input-latency enabled
```

`--manifest` preserves supplied JSON and its SHA-256. The collector never reads local
Git state to label the connected firmware, and supplied provenance is marked as an operator
claim whose device/build match has not been independently verified. `--input-latency`
defaults to `unknown`; use `enabled` only with evidence that the connected firmware was
built with `FM1_INPUT_LAT`. A locally enabled flag is not evidence about the device.

## Interpreting a report

`VALID` means complete, continuous collection with equal measured input windows after
the discarded first window. It does **not** mean the workload passed an audio or error
budget: inspect the counter deltas and listen to the output. `INVALID` exits with status 1
and sets all aggregate cumulative deltas to `null`. Every interrupted, rebooted, wrapped
or reset interval remains in the JSONL. A later valid interval cannot repair an invalid
aggregate. Initial/end snapshots remain available for investigation.

Boot count or device-version changes, stopped/decreasing uptime, and decreasing known
cumulative counters reject continuity. Signed decimal output from the firmware's uint32
counters is normalized, so `2147483647` to `-2147483648` is continuous; uint32 wrap is
invalid. Crash-record uptime is historic and is never compared with current uptime.
Older firmware without boot-count evidence cannot establish continuity. Unknown future
fields are preserved but do not acquire guessed counter/delta semantics.

`usb_retries` counts local controller restarts; `usb_resets` counts host bus resets.
A local restart abandons configuration and pending control/CDC/UAC session state
before reattachment, then waits for fresh host configuration. It retains data
still in application rings at restart; a later host bus reset keeps the existing
MIDI/SysEx output-drop policy. Neither counter establishes packet delivery or
physical recovery. Check host re-enumeration, stream behavior and error deltas
alongside the retained report.

Present known numeric fields are validated before generic colon records. For
example, `audio_late 1:2` is malformed counter evidence, rather than an unknown
record; empty known fields and duplicate valid/malformed occurrences also
invalidate collection. Optional fields omitted by older firmware remain absent.

`status.uac_pkts` is local to a USB audio sample-rate epoch: firmware resets it on
an effective rate change. With packet counts at both endpoints, an observed rate
or `uac_rate_sets` change invalidates the interval, even if a reset count has
already overtaken its previous value. `uac_rate_sets` counts SET_CUR requests,
including harmless same-rate requests; the collector conservatively rejects those
ambiguous boundaries too. A packet delta requires unchanged 44100/48000 Hz and an
unchanged valid setter count. Missing packet endpoints or missing/unsupported rate
markers leave that delta `null`; other continuous legacy evidence remains usable.
The status fields are read sequentially, so this rejects observed boundaries rather
than proving that no rate reset occurred between individual field reads. Keep the
rate fixed for a workload capture and retain the raw replies.

In builds with second-core support (`FELUCCA_CPU2=1`), `crash` includes `core 0` for
the main core or `core 1` for the worker. This identifies the retained crash's origin,
even after the device falls back to one core; current `status` worker state describes
the running system instead. Builds with `FELUCCA_CPU2=0` and older firmware omit the
field. The collector preserves it when supplied and leaves it absent otherwise.
In those builds `status` also reports the retained worker guard (#410): `cpu2_excl`
(0 none, 1 bad job, 2 timeout, 3 core 0 fault, 4 hang, 5 corrupt, 15 the worker answers
and no failure is recorded) and `cpu2_refused`, the number of starts it refused (saturating
at 255). A value of 1 to 5 means the saved **2ND CORE ON** is overridden until the player
sets it OFF and ON again in the menu ([recovery](fork-features.md#retained-exclusion-after-a-failed-worker-410)).
It is the firmware's record, not proof of the cause, and it is not a measurement of
whether `.noinit` survives a reset on the connected unit: when you collect after a warm
reset, record the reset class and whether the value persisted. The collector keeps both
keys as unknown fields.
Each `crash` reply formats one validated local copy. If the retained record is absent
or changes while it is copied, the reply is `no crash record`; a later request can retry.

`cpu_pct` is the smoothed render/deadline ratio with nested TIMER5 scan time subtracted.
It excludes the main loop and is not whole-chip CPU utilization. `audio_max_us` and
`dbg.max_us` expose the same cumulative render maximum. Current firmware explicitly
resets it to zero at application startup (`main.c`, `fm1_main`), even though
`felucca_dbg` lives in `.noinit`; other retained counters and breadcrumbs have their
own reset semantics. The maximum accumulates within that boot and is not reset by
collection. Record its starting and ending values, but do not subtract them or infer
the measured interval's peak from an unchanged maximum. Older firmware and historical
reports may have different reset semantics; retain their revision and matching evidence.
Compare audio lateness, overload `voices_shed`,
`voices_given_up`, USB audio errors, USB stalls and UART drops together.
`voices_given_up` counts all `voice_kill()` calls, including overload, allocator
victims and MIDI All Sound Off. It does not measure rejected or admitted requests;
`voices_shed` is its overload subset. A clean sustain after shedding is a smaller
workload, so retain actual surviving-voice observations when available.

`status` `cpu2_stack`, when present, scans the worker's 4,096 B user allocation
for its fill pattern. This allocation includes a 256 B low guard; its usable
user window is 3,840 B. The separate 256 B worker supervisor stack and both CPU0
stacks are outside this measurement. The pattern is refilled on each worker
start attempt, including a failed attempt; starting an already-running worker
does not refill it. Before the first attempt it reports zero, which does not
establish that a workload was measured. Holding the worker retains the prior
pattern until another start attempt. Do not treat this field as a boot-wide or
collection-interval maximum, subtract samples, or infer CPU0 stack use from it.

`inp` resets scan gaps/histograms, encoder statistics and key latency on read. Its
`timer_irqs` and `nested` fields are cumulative and receive separate deltas. Later input
windows are checked against the requested equal interval and reported separately as valid
or invalid; an invalid later window also invalidates the session. Key latency remains
`UNMEASURED` without confirmed instrumentation, a valid window, observed presses/notes
and the complete key-latency group: `key_presses`, `key_press_avg_us`,
`key_press_max_us`, `key_notes`, `key_noteon_avg_us`, `key_noteon_max_us`,
`key_dac_avg_us` and `key_dac_max_us`. Older replies missing some or all of these
fields still provide continuity evidence, but no measured latency. Every present
known latency field must be a nonnegative 32-bit integer; malformed, negative or
out-of-range values invalidate the response and session while retaining the raw
reply. Unknown future fields are preserved. Zero press/note counts mean no samples
and remain `UNMEASURED`; valid sampled times may round to zero microseconds.
Malformed colon values such as `key_press_max_us 1:2` also invalidate collection;
they cannot disguise a known latency scalar as an unknown colon record.

## Interrupt-context assertion (`FELUCCA_ISR_ASSERT`)

`fm1_sp_in_isr()` (`firmware/hal/fm1_guard.h`) is true when core 0's `sp` lies between the
linker symbols `_guard1` and `_sstack_top`, the system (interrupt) stack; the main loop runs on the
user stack below it (`crt0.S`). Core 1 has its own stacks, so the function is always false there.
`FM1_ASSERT_THREAD()` (`firmware/src/isr_assert.h`) uses it to check code that must not run in an interrupt.
It sits at the entry of `st_save_to` (every project, settings, autosave and user-preset save), `st_erase`
and `st_prog` (`storage_hw.c`), `con_exec` (formatted console replies), `usb_start` (waits 25 ms) and
`apply_preset_to` (preset loads) and `sound_install` (every sound load, `sound.c`), before any `irq_save()`. It is not placed in `.ram_text` code or in
interrupt paths.

| `FELUCCA_ISR_ASSERT` | Where | Effect |
| --- | --- | --- |
| `0` | FM-1 default and the update loader | The macros expand to `((void)0)`: no code or data (release image byte-identical apart from the embedded commit id). |
| `1` | Default for host tests and the emulator | `fm1_alnk0_irq` and `fm1_timer5_irq` raise a simulated-interrupt depth; a guarded call in it prints `file:line` and aborts (a test may set `fm1_isr_assert_hook` instead). |
| `1` | FM-1 development build: `FELUCCA_ISR_ASSERT=1 ./build.sh` | A violation increments `isr_misuse` and records the first caller's address (`isr_misuse_pc`); both are keys of `status`, not `inp`, and `isr_misuse` is included in the collector's `status` counter deltas and carries on: no abort, flash write or output from the interrupt. |

`tests/storage_test.c` (a real save) and `tests/audio_test.c` (a call from inside the real audio handler)
check that the assertion fires in simulated interrupt context and stays quiet in the main loop. On the device the
check assumes interrupts run on the system stack as `fm1_isr.S` and the stack guards describe; that has not
been observed on an FM-1 yet.

## Diagnostic builds for #425 (`FELUCCA_CRASH_CTX`, `FELUCCA_MUL64_REPRO`)

Two opt-in build flags serve the [#425 soak test](mul64-hload-audit.md#phase-2-step-1-synthetic-reproducer-and-device-soak).
Both default to `0`; release and standard builds compile neither, and `./build.sh --release` refuses them.
They are development images: install them only for the test and reinstall the normal build afterwards.

**`FELUCCA_CRASH_CTX=1`** (#428): the fault handler (`fm1_fault_c`, `hal/fm1_irq.h`) also keeps the faulting core's
`r0`..`r15`, `usp` and `ssp` from the frame `fm1_fatal_common` saved, in the same retained record and under the same
invalidate / publish protocol as the other fields, for core 0 and for the worker (`core 1`). One record, the most
recent crash, as before. A one-bit register error such as the donor's loop index `0x00800012` is visible only here.

| Key | Meaning |
| --- | --- |
| `status` `crash_ctx 1` | the running firmware is a `FELUCCA_CRASH_CTX=1` build |
| `crash` `ctx` | `1`: the registers below belong to this record; `0`: the record was written by a firmware without them (no register lines follow) |
| `crash` `r0` .. `r15`, `usp`, `ssp` | hex, after the existing keys, which keep their order and meaning |

Cost: +76 B NOINIT (`fm1_crash` grows from 68 to 144 B: a key word and 18 registers), which puts this build at
44 B spare, below the 100 B floor that release and standard builds keep; `tools/build.py` checks a 24 B floor for
this build only ([performance](performance.md#ram-and-stack), capacity plan rule A7). `fm1_crash` stays the first
`.noinit` object, so its address is unchanged; the objects after it move by 76 B between a normal and a CRASH_CTX
build. The retained flash mirrors, boot guard, panel copy and CPU1 exclusion are validated at boot (magic, checksum
or key), so the first boot after switching discards rather than misreads them, as with any build that changes a
`.noinit` object (`FELUCCA_CPU2` already changes `fm1_crash`). `crash_seen` has no check: when a crash record exists,
that first boot may take it for a new crash and skip the LED sweep and the RESTORE LAST autosave once. Keep the
music for the test in a saved project, not only in the autosave.

**`FELUCCA_MUL64_REPRO=1`** (#425): the synthetic reproducer (`firmware/src/mul64_repro.c`) runs in the main loop's
idle wait. `status` adds:

| Key | Meaning |
| --- | --- |
| `mul64_repro` | `1`: the reproducer is built in |
| `mul64_runs` | steps that compared both variants; each runs 2 x 128 loop iterations with 3 64-bit multiplies (384 per variant) |
| `mul64_inl_bad` | checksum mismatches of the inline variant (multiplies among the 16-bit loads) |
| `mul64_nol_bad` | checksum mismatches of the noinline variant (each multiply in a helper that uses the product at once) |
| `mul64_ref_bad` | reference set-ups whose two noinline results disagreed (retried later); an inline result differing from two agreeing noinline ones counts in `mul64_inl_bad` instead |
| `mul64_first_var`, `mul64_first_run`, `mul64_first_xor` | the first mismatch: variant (1 inline, 2 noinline, 3 reference), step, and the XOR of the wrong and the reference checksum (hex; one set bit is a one-bit result error) |

The collector counts `mul64_runs`, `mul64_inl_bad`, `mul64_nol_bad` and `mul64_ref_bad` as `status` counters
(interval deltas); they are absent, not zero, in other builds. A corrupted loop counter may instead make a kernel
loop run for minutes: the watchdog then resets the FM-1, the collector reports the reboot as a discontinuity, and
`boots` increases. Report that as a candidate observation together with the time and the workload.
`tests/mul64_repro_test.c` checks the bookkeeping on the host; `tests/diagnostics_test.py` checks the console keys
and the collector's deltas; `tests/crash_record_test.py` and `tests/crash_snapshot_test.py` check register capture,
the record replaced while it is read, and the console output in both build variants. None of them tests the chip.

## Validation scope

Run `python3 tests/diagnostics_test.py` for console-shaped parser/transport fixtures and
a deterministic simulated session. It also runs through `tests/run_tests.sh`. These tests
cover partial reads, unknown fields, unavailable versus zero, timeout, disconnect, size
limits, reset/wrap, signed boundaries, first/unequal input windows, expected deltas and
rejection of interrupted or intervening reboot intervals. They do not establish device
behavior or collector overhead.

A real FM-1 acceptance session remains required: keep baseline/candidate USB configuration
identical, collect under USB audio and USB/TRS MIDI load, listen to the output and check
panel responsiveness. Compare the same workload with/without polling to quantify collector
overhead, including lateness, shedding, stream errors and scan timing; record both runs'
provenance, duration and configuration. No hardware session is implied by simulated logs.
This host-only client changes no firmware source, build flags, target code or RAM.
