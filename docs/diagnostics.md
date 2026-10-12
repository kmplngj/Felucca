<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Collecting device diagnostics

`tools/fm1_diagnostics.py` collects the existing Felucca CDC console on macOS and Linux
using Python 3's standard library. Enable USB SERIAL on the device and explicitly select
its CDC tty. Close other serial applications first. The collector opens the tty exclusively,
asserts DTR to obtain the console banner, and restores terminal settings on close.
Opening a port does not establish that its firmware matches the checkout.

From this checkout's root, for a 60-second workload with equal 5-second windows:

```sh
python3 tools/fm1_diagnostics.py --port /dev/cu.usbmodem1234 \
  --scenario 'four parts; USB audio 48 kHz; USB and TRS MIDI; USB SERIAL on' \
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

`cpu_pct` is the smoothed render/deadline ratio with nested TIMER5 scan time subtracted.
It excludes the main loop and is not whole-chip CPU utilization. `audio_max_us` and
`dbg.max_us` are cumulative maxima which can persist across reboot; they are not maxima
for the measured interval. Compare audio lateness, overload `voices_shed`, voice-budget
`voices_given_up`, USB audio errors, USB stalls and UART drops together.

`inp` resets scan gaps/histograms, encoder statistics and key latency on read. Its
`timer_irqs` and `nested` fields are cumulative and receive separate deltas. Later input
windows are checked against the requested equal interval and reported separately as valid
or invalid; an invalid later window also invalidates the session. Key latency remains
`UNMEASURED` without confirmed instrumentation, a valid window and observed presses/notes.
Raw zeros are retained without being presented as measured latency.

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
