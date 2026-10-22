<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Collecting device diagnostics

For opt-in PNG capture of firmware-rendered static menu pixels, use the separate
[screen capture guide](screen-capture.md). The collector below remains read-only
and sends only its existing four diagnostic commands.

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
`dbg.max_us` are cumulative maxima which can persist across reboot; they are not maxima
for the measured interval. Compare audio lateness, overload `voices_shed`,
`voices_given_up`, USB audio errors, USB stalls and UART drops together.
`voices_given_up` counts all `voice_kill()` calls, including overload, allocator
victims and MIDI All Sound Off. It does not measure rejected or admitted requests;
`voices_shed` is its overload subset. A clean sustain after shedding is a smaller
workload, so retain actual surviving-voice observations when available.

`inp` resets scan gaps/histograms, encoder statistics and key latency on read. Its
`timer_irqs` and `nested` fields are cumulative and receive separate deltas. Later input
windows are checked against the requested equal interval and reported separately as valid
or invalid; an invalid later window also invalidates the session. Key latency remains
`UNMEASURED` without confirmed instrumentation, a valid window and observed presses/notes.
Raw zeros are retained without being presented as measured latency.

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
