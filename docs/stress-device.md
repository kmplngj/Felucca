<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM-1 stress capture handoff

The [catalogue](../tests/stress_catalog.json) names host, integrated-emulator and
physical cases. Copy [the result template](../tests/stress_device_result.json) into
a new ignored `build/stress/device-*` directory for every physical run. Null means
unmeasured, never zero. This checkout has no connected FM-1: **all physical cases
are pending**. The runnable device collection path is the existing
[#56 collector](diagnostics.md); automatic musical workload delivery, audio capture,
jitter logging and backup/restoration belong to [#57](https://github.com/kmplngj/Felucca/issues/57).
The manual cases have separate IDs and are not the exact host/emulator workload.

## Prepare the device

1. Use an FM-1 already running the intended revision. If installing a comparison
   build, follow [BUILDING > Install](../BUILDING.md#install), using the matching
   `.fwsc` package, never a raw `.bin`. Retain the package SHA-256, revision,
   provenance manifest, profile/font/CPU2/FM4 and input-latency flags. Baseline and
   candidate must differ only by the experiment under study; enable FPU/CPU2
   independently. Local build metadata alone cannot identify connected firmware.
2. Export a validated backup using the documented backup workflow before changing
   musical state. Use a disposable project and unused USER slot; do not overwrite
   stored music. Retain its slot, exported bytes/hash, settings and preset identities.
   Autosave and RESTORE LAST can preserve edits: absence of an explicit SAVE is
   not proof of preservation. This procedure does not automate restoration.
3. Start stopped on HOME, with no held keys/MIDI notes. Follow
   [diagnostics > Idle baseline setup](diagnostics.md#idle-baseline-setup), including
   the exact HOME-hold → SYSTEM → ABOUT / USB SERIAL route. Retain the displayed
   version and installed artifact identity. Keep USB SERIAL ON for both builds;
   closing MENU after changing it re-enumerates USB. Select the CDC port explicitly.
4. Connect headphones or line-out recording. For stream cases use a USB data cable,
   a host recorder with an explicitly selected FM-1 stereo input and sample rate,
   an explicitly selected USB MIDI output, and a MIDI source/correct TRS adapter
   connected to FM-1 MIDI IN. Record OS, application, endpoints, channel mapping,
   capture buffer and rates. Keep host capture overflow separate from UAC counters.

## Run the named device cases

For `fm1_idle_v1`, close all MIDI/audio applications, disconnect TRS MIDI, leave
HOME stopped and warm up five seconds. Run this command, replacing the port and
revision with the actual connected build; `--manifest` is optional when unavailable:

```sh
python3 tools/fm1_diagnostics.py --port /dev/ttyACM0 \
  --scenario fm1_idle_v1 --duration 60 --interval 5 \
  --firmware-revision DEVICE_REVISION --manifest build/device-manifest.json
```

On macOS use the selected `/dev/cu.usbmodem…` port. The collector only observes;
it does not arrange the workload. Record its output directory in the result template.

For `fm1_usb44100_midi_v1` and `fm1_usb48000_midi_v1`:

1. Record every part's engine, factory/user preset, VOICE mode, envelope, effects,
   levels and routing in the result before playing. Set the external sources to
   USB channel 1 (notes 60/64/67, velocity 96) and TRS channel 2 (48/55, velocity 96).
   Verify a single source note reaches the intended part, then release it. Reject
   an ambiguous route; do not infer channel routing from the host matrix defaults.
2. In the recorder select the FM-1 stereo capture endpoint, two channels and exactly
   **44,100 Hz** for the first case or **48,000 Hz** for the second. Confirm the
   endpoint's actual rate, disable host resampling/effects and record those settings.
   Start capture, warm up five seconds, and start the collector with that scenario
   ID and the same 60-second/5-second settings above. Keep initial and end snapshots.
3. After the initial snapshot, play the declared chord on each source for ten seconds,
   send explicit note-offs, then allow 50 seconds of release/recovery. Record the
   actual onset/offset times relative to the diagnostic samples and WAV; extend
   collection if needed to contain the complete workload. This manual timing is
   an observation, not sample-exact scheduling or the direct `usb_trs_midi` timeline.
   If it does not fit the measured interval, mark the case incomplete and rerun.
4. Stop recording after the final snapshot and retain the WAV/hash, rate, channel
   count, frames, clipping/peak and capture-overflow status. Repeat at the other
   rate from the same initial project/settings. Repeat baseline/candidate with
   the same recorder configuration and actual schedule; report scheduling variance.

For a **separate save check**, start stopped on HOME, select a disposable sound
and ensure the first available USER slot is empty. Tap/release **SAVE** once to
open **USER** (SLOT/LOAD/ERASE/SAVE), verify the chosen SLOT, then tap/release
**OCT+** to open NAME and tap/release **OCT+** again to save the suggested name.
A populated slot opens an overwrite dialog: tap **OCT−** to cancel and choose an
unused slot with **KNOB 1** before retrying. Observe the documented stopped flash
pause, successful saved indication and recovery; tap/release HOME, press/release
G3 and listen for a clean note/release. Collect before/after diagnostics as a
separate interval; never compare this deliberate pause with steady-playback misses.
The executable emulator equivalent is `tests/scenarios/stress-save.json`; real NOR
latency, pause length, wear and preservation remain physical checks.

For panel/redraw checks, the executable gesture data is
`tests/scenarios/stress-panel.json`: factory tracks receive eight note requests,
ENV opens, all four knobs turn every 80 ms, and FX-held D5/E5 apply REV/ECHO THROW.
Manual reproduction must keep a separate case ID and record the actual gesture
schedule. It is not an equivalent-workload timing comparison. The direct matrix's
other presets, ratchets, modulation and effects are explicit event data; automatic
FM-1 delivery of those exact events is pending #57, rather than an invented panel route.

## Accept and retain observations

A complete collector `VALID` result establishes continuity, not performance success.
Copy/link its start/end snapshots and cumulative deltas for `audio_late`,
`voices_shed`, `voices_given_up`, UAC underruns/overruns/missed/stalls and UART drops.
Keep unavailable fields null and list them. Retain raw `console.raw`, `samples.jsonl`
and `summary.json`; reject reboot/reset/wrap/disconnect intervals rather than
subtract discontinuous counters. Separate boot-surviving `audio_max_us` from new
interval maxima. Discard the first reset-on-read `inp` window and compare equal
remaining windows, including scan gaps and encoder losses. Without a proven
`FM1_INPUT_LAT` build, latency stays unmeasured. `cpu_pct` excludes nested scan work
and is not whole-chip CPU use; current audio timing has averages/maxima, not p95/p99.

For ordinary load expect no new audio misses, shedding, stream errors or UART drops;
record audible clicks/clipping/silence/tails and panel response. Deliberate overload
must compare degradation and recovery, not just the lower post-shedding CPU number.
Repeat an otherwise identical run without periodic collection to assess collector
overhead, retaining the available start/end observations and audio; do not invent
an overhead percentage without those runs. Optional per-stage instrumentation needs
its own measured overhead and is not implemented by these tools.

Release all MIDI notes, stop transport/capture, restore original USB SERIAL and
musical/settings state using the retained backup, and verify it. Record failed or
unverified restoration. Report revision/artifact, scenario ID, actual duration,
settings, baseline/candidate result paths and observed versus expected behavior.
