<!-- SPDX-License-Identifier: GPL-3.0-only -->
# USB music routing and capture checks

`USB LEVEL` selects where MASTER applies to music sent to the USB recorder.
The same stereo mix, effects, limiter and `SPEAKER EQ` feed both output routes.
The metronome is added after the USB tap and stays on the analog DAC route.

| Setting | USB music | Analog music and metronome |
| --- | --- | --- |
| MASTER | Follows MASTER; zero is silent | Follows MASTER; zero is silent |
| FIXED | Full music level, independent of MASTER; no metronome | Follows MASTER; zero is silent |

`SPEAKER EQ` is shared processing: FLAT, LOWCUT and BASS+ can change the USB
recording too. It is not a speaker mute. MASTER attenuates speaker and
headphone/line output together; this procedure adds no separate mute control.

## Software coverage

The existing [audio fixture](../tests/audio_test.c) renders real musical audio
through `audio_block`, observes its stereo USB tap, and feeds the production UAC
producer, ring, resampler and packet consumer at 44.1 and 48 kHz. Its routing
matrix combines both modes, zero/quarter/full internal MASTER levels, click
off/on and all three EQ settings. Held notes, release and an audible FX-only
tail are checked separately. Live mode switches also exercise attenuated MASTER.
The [click fixture](../tests/click_test.c) checks stereo click-only output with
the same modes, MASTER levels and EQ settings. Existing
[UI checks](../tests/ui_test.c) retain menu application and preference reload.

At 44.1 kHz, consumed packets are checked against the ordered observed tap PCM.
At 48 kHz, routing comparisons, nonzero output and packet duration checks reuse
the actual FIR; the independent numerical FIR and transport oracle remains in
[uac_test.c](../tests/uac_test.c). Host packet production does not exercise the
physical USB controller, recorder or DAC. The fixture's exact internal full
MASTER value is a reference; a physical pot's smoothed maximum need not equal it.

From a checkout prepared with the [build prerequisites](../BUILDING.md), run:

```sh
uv run --locked --group build ./build.sh
SANITIZE=1 uv run --locked --group build python tests/test_jobs.py tests/run_tests.sh --preflight --select audio,click,ui,usb,asan_usb,asan_audio_stage --ai-output
```

Use only unit names present in that revision's `tests/run_tests.sh --plan`.
The complete applicable CI plan remains required for the final candidate.
No golden or instruction-budget rewrite is needed for these routing tests.

## Pending FM-1 recording procedure

Hardware checks are performed during PR review. No device result is supplied by
the host matrix. Use one reviewed standard-profile artifact with its exact source
and package SHA256 recorded, a verified backup and disposable project, USB data
cable, headphones/line monitoring, a MIDI source and a recorder that explicitly
selects the FM-1 stereo input and 44,100 or 48,000 Hz. Retain the host/OS, recorder
version, CPU2 setting, diagnostic flags and channel selection. A hosted demo or a
raw `.bin` does not identify an installed candidate.

1. Start at HOME with PLAY off and REC off. Tap HOME if needed; turn ALGORITHM
   left to track 1. Hold EDIT, turn KNOB 1 to ANALOG, use KNOB 2 to choose a known
   factory sound, then release EDIT. Use the same held chord, release and FX
   settings for every comparison. Record the sound and settings rather than
   assuming every factory sound has the same release tail.
2. Hold HOME until MENU opens (over 0.7 s), then release. Turn ALGORITHM to
   AUDIO and PRESETS to USB LEVEL. KNOB 4 or OCT−/+ selects MASTER/FIXED.
   PRESETS selects SPEAKER EQ (FLAT/LOWCUT/BASS+), CLICK (OFF/REC/ON) and CLICK
   LEVEL (LOW/MID/HIGH); change values with KNOB 4 or OCT−/+. Record original
   values. Tap HOME to close MENU. CLICK ON sounds during playback; use a
   disposable pattern and tap PLAY to start, then PLAY again to stop.
3. At each selected rate, record both modes at physical MASTER zero, a repeatable
   low position and full. Repeat with CLICK OFF/ON and each EQ mode. Include
   quiet input, held notes, note release and FX tails; also run a click-only
   section without held notes. Monitor or independently record analog output
   during the same run. Expect the table above in both stereo channels: FIXED
   USB music persists at MASTER zero, while analog music/click is silent.
   A silent analog or replay recording alone cannot establish USB silence.
4. At low MASTER while a note sounds, change USB LEVEL MASTER→FIXED→MASTER by
   the same menu route. Expect USB gain to follow the selected policy while
   analog remains controlled by MASTER. Stop and restart the recorder and repeat
   at the other supported rate. Retain initial priming separately from established
   streaming; report repeated/held samples, host overflow or capture gaps.
5. Repeat a declared mixed musical workload with ordinary panel activity. Collect
   [aligned diagnostic intervals](diagnostics.md#collect-diagnostics), recording
   available UAC underrun/overrun/missed/stall and audio late/shedding deltas.
   Recorder status and device counters are separate evidence. A `VALID` diagnostic
   report establishes continuity, not artifact-free audio or whole-chip CPU use.
   Keep intentional overload separate from ordinary workload acceptance.
6. Stop playback and recording, release notes, and restore original menu values,
   project and CPU2 preference. Check preference reload after an ordinary restart
   when that is part of the review. Retain WAVs and a manifest with exact artifact,
   rate, mode, MASTER position, EQ/click settings, duration, workload, host status,
   diagnostics path and expected versus observed USB/analog result. Keep unavailable
   scenarios pending. Do not inject flash faults or interrupt an update for this test.

Use a results row for each scenario rather than inferring unrecorded combinations:

| Artifact / host / rate | Mode / MASTER / EQ / click | Workload / duration | USB WAV / status | Analog evidence | Diagnostic interval / deltas | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Pending | Pending | Pending | Pending | Pending | Pending | Pending |

The [offline tone checker](diagnostics.md#usb-test-tone-recordings) applies only
to a known diagnostic-tone build, whose signal replaces ordinary USB music.
A passing tone capture does not qualify musical gain routing. Ring-depth changes,
MASTER ADC/LCD interference and the broader automated capture/session adapter
remain separate issues (#427, #757 and #57).
