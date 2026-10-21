<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI/DSP FM-1 qualification, 2026-10-21

PR #541 implements #525–#529. The physical USB clock test passed a twenty-minute
pulse-count comparison on four sequencers and four arpeggiators. Physical TRS
throughput/timestamping, subjective listening and physical panel response remain
pending. Host models do not establish the UART silicon's behavior.

## Exact artifacts and validation

The device ran exact head `76107db4b903dd737210ff207e1cd8863ef7960d`, standard profile,
M8Stealth, JieLi Clang 4.0.1, selective minsize defaults, Engines
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. Its installed 489456-byte app was read back
completely and matched SHA-256
`81f538c6bfcafb8a160e5d058de111516fd2f4ed1a40b7cfed40aea49b8a4894`.
The package SHA-256 is
`71ec7a691bd2881e6d066d7f95ad0a6ad59e927323ba46955e04a351c75f679e`, from
[exact-head target CI](https://github.com/kmplngj/Felucca/actions/runs/39670531943).

Subsequent main changes affected only tests and the protocol reference. Whole-app
comparison against fresh exact-head `9d80408b0ca7eb8ec792d20dd5ed8fa61138ab66`
[target CI](https://github.com/kmplngj/Felucca/actions/runs/39675188662) finds only seven
ASCII bytes changed inside the eight-character build identity. Every other app byte
is identical. Actual device identity remains `76107db4`; it is not relabeled.

[Full final integration CI](https://github.com/kmplngj/Felucca/actions/runs/39675067128)
passes at synthetic merge `6886239a8f1dfcfb585bf11e9bb50729bf8942e0` for head `9d80408b`:
124 host units, target/resource guards, sanitizer, web/emulator, seven Chromium checks,
unchanged golden renders and clean-checkout package reproduction. Host PMU cost
counters and proprietary official-V15 restore are unavailable. Focused strict new
fixtures use no sanitizer exclusions; historical broad-suite exclusions remain.

The matched target delta from main `3c7d43e0` is app −292 B, data+bss extent +64 B;
POOL 336440 B, NOINIT 15576 B and RAMTEXT 2924 B are unchanged. CPU2 compiled-out
is a separate variant: app +476 B, data+bss +48 B, POOL/NOINIT unchanged. These are
static measurements, not live RAM/stack or a runtime speedup.

## Reproducible temporary workload

Original package, all backup objects, raw stores and runtime were exported before
mutation. RESTORE LAST was temporarily OFF; no project slot, preset or sample was
saved. Setup/readback completed before native audio recording began. The musical
state was replaced only in temporary runtime.

All four parts use ANALOG with all 111 parameters initialized from firmware DESC
defaults, then a deliberately modified patch: SAW, DTN10, MIX64, NOISE0, CUT90,
RES30, DRV0, KTR64, ADSR10/70/90/60. Although the preset label remains SAW LEAD,
this is not the unchanged factory patch. Each of 64 steps has pitch48/52/56/60 by
part, velocity80, chance100, ratchet1, nudge0, no condition/automation/locks.
SEQ DIV is 1/16,1/32,8T,16T; LEN64/17/23/64. All ARPs are UP, one octave, held
60+64, DIV1/16,1/32,16T,1/4, gate64, swing0. Levels90, CH1–4; CC7 sweeps80..99
and unsupported NRPN no-ops accompany the clock stream. The long stage is dry.

The short stage adds SOFT insert1 (A32/B96/C96/MIX64), chorus24/delay32/reverb24,
global delay1/8/feedback60/color70/mix90, HALL reverb size90/damp60 and chorus
rate40/depth60. It sends 120→97→240→40→120 BPM with requested 1 ms jitter,
96 progress clocks per segment, then Stop/Continue. Full parameter/project readbacks,
host send timestamps and command sources are retained with each case.

Actual paired ON readbacks match: four normalized 225-byte TRACK_DUMPs, including
all 111 parameters plus engine/preset, and four post-CC/NRPN dumps. The 256 step,
508 track-parameter, 13 global-parameter and four motion replies also match.
No extra post-effects whole-project dump is claimed (`paired-setup-parity.json`).

## Physical results

The 1200-second stage sent 57600 progress F8 clocks plus one initial anchor over
CoreMIDI USB. At the stopped stable endpoint the firmware reports clock position
57600000 and rendered position57600999; the latter includes bounded interpolation.
The independent oracle uses emitted pulse count ×1000 musical units and each
consumer's position/index/carry, comparing sequencers modulo their lengths. All
four SEQ errors are below 0.000001 ms (floating-point comparison residue) and all four ARP errors are zero. This passes
the justified 2 ms musical-phase bound. The tempo-change endpoint also passes,
with errors below 0.000001 ms (floating-point comparison residue), and Continue advances every consumer.

Host send lateness reached 24.283 ms (mean 5.328 ms). These results demonstrate
retained musical phase against incoming counts, not precise wire scheduling,
estimated-BPM stability, DAC onset alignment or acoustic jitter. The stopped
memory endpoint is not a continuous per-sample audio timestamp measurement.

CPU2 OFF / 44100 Hz: late/shed/UAC under-over-missed-stall/UART drops/USB reset and
frame-stall deltas are zero, with boot identity continuous. `voices_given_up`
increases by 29976: source audit identifies shared eight-voice allocation victim fades;
regular note-off does not increment it. No all-requested-notes-retained claim is
made. Natural PCM16 stereo acquisition completes 55588352 frames (1260.507 s),
with zero host timestamp discontinuities, missing frames and write errors.
A one-second midpoint sample has RMS 1441.14 and peak 7508 (s16), proving signal
presence only; no listening verdict is inferred.

This allocation attribution is specific to the controlled recorded traffic: all
four wire logs contain zero CC120 (All Sound Off), UART byte deltas are zero and
shedding deltas are zero. CC120 is another production `voice_kill` caller; CC123
uses ordinary release. The aggregate counter itself does not encode the cause.

CPU2 OFF / 48000 Hz also passes1440 progress clocks, the480-pulse mixed-effects
tempo stage and Continue, with all listed error deltas zero and945 allocation
victims. Natural acquisition completes4319232 frames (89.984 s), with zero host
acquisition defects.

CPU2 ON / 44100 Hz **fails device acceptance**. After1376 worker blocks,
`cpu2_bad` and `cpu2_gave_up` each increase1; CPU2 preference/runtime fall1→0.
Late increases1 and UAC missed5, with boot3 continuous and no crash record.
Musical endpoints pass after the worker fallback, so they do not qualify continuous
active-CPU2 phase; the the failure teardown aborts capture at51.15 s; this
is not a successful natural90-second recording.48000 Hz ON is not attempted
after the protective fallback.

Read-only exact-ELF mailbox preservation records `bad_job=0x1000055f` and
`bad_done=0x55f`, XOR0x10000000, with `bad_fn=0`. The worker reports a non-successor
job; this is consistent with a transient incorrect read but does not prove its
physical cause. Core0 mailbox readback remains consistent. Retained BAD_JOB
exclusion is honored, then deliberately retried through supported MENU_SET row32
OFF→ON for one unchanged-main comparison; no raw guard write or protection change.
Source for the worker, its retained guard, audio/voice paths and engine pin is
unchanged between e987 and76107. Target C1 code is164 B, with only one byte
changed for the trace-address relocation (+64 B BSS); other163 code bytes match.
This static comparison alone does not prove the hardware failure is unrelated
to the integration.

The unchanged e987 baseline reproduces the same BAD_JOB class under the same
30-second/mixed-effects/CC/tempo/Continue workload:736 worker blocks, bad/gave_up
each+1, CPU2 preference/runtime1→0, late+1, UAC missed+5, shed0, boot4 continuous.
Its mailbox records job/done736, bad_job0x100002df, bad_done0x2df, XOR0x10000000
and bad_fn0. The baseline rational-grid oracle is explicitly UNMEASURED because
that firmware has the old scheduler; Continue passes. Collection completes
naturally3967488 frames (89.966 s), zero acquisition defects, nonzero PCM
(RMS1368.84/peak5791). Device acceptance remains FAIL/exit2.

This establishes the failure on unchanged main as well as the candidate; it does
not establish a candidate-specific cause, a physical SRAM fault or a fix. CPU2
remains beta/defaultOFF and unqualified on this unit. Its protection, clocks,
voltage and fallback policy are unchanged. No48kON retry or repeated attempt to
obtain a green result is performed. Retained recovery policy is owned by
[#410](https://github.com/kmplngj/Felucca/issues/410).

The separate [deadline investigation](audio-deadline-investigation-2026-10-21.md)
records matched PHYS four/eight-request controls, intentional overload and acquisition
exclusions. Its cumulative counters are not merged with these clock-test intervals.

## Restoration and remaining checks

Original restoration completes successfully after the paired baseline. Full489256-byte
app readback matches original SHA-256
`77b64fa7ed674df8a8ff4616d95006ce396a4f3653aee38828cc469130a3eefa`; original
package SHA-256 is
`c6383098e9fd8d12de6d3dfa8169c70e5e8583ed8458236aa5b1b2b63b757cec`.
All15 backup payloads are byte-equal, all33 menu replies match, settings payload
is exact and all10 raw nonsettings objects retain exact metadata/payload, including
autosave sequence40/CRC1462438099. No stored project/preset/sample object was
written. Runtime was restored with autosave OFF, then original settings immediately
before rebooting the original package; boot loads the untouched original autosave.

Final verifier status: boot5, CPU2 preference/runtimeOFF, stopped, UAC alternate0.
The test-triggered retained BAD_JOB exclusion remains1; it is a diagnostic safety
record, separate from exact restored user data/settings. It was not erased to make
the result appear pristine. No raw guard writes or remaining device handles exist.
The recovery BOTH5m settings snapshot is also retained separately; final user
settings match the original pre-test SCREEN5m snapshot. Proofs are
`build/deadline540/restored/restoration.json` and `runtime-guard-proof.json`.

No accessible external TRS sender was identified; the port was idle throughout USB
tests. Continuous full-rate physical TRS with clocks/CC/NRPN/note-off, MIDI Learn,
USB audio and CPU2 OFF/ON remains pending for #525/#526. Subjective FM6/PHYS sound,
held preset/engine switches, effect tails and physical panel behavior also remain
user checks. Follow the [combined test procedure](midi-dsp-reliability.md#combined-user-test-instructions)
and exact package above. USB injection cannot qualify physical TRS.

## Retained evidence

The ignored directory
`/Users/jankampling/.codex/worktrees/felucca-509-midi-dsp/Felucca/build/usb-clock/`
contains the harness/configuration, exact ELF/disassembly layouts, full original
runtime, per-case parameters, send schedules, endpoint dumps, counter snapshots,
natural acquisition reports and recordings. `head76107-off-44100-long/result.json`
is the long-run summary. The long-run oracle's offline positive case passes and an
injected +10 ms SEQ error is rejected. Interrupted/superseded attempts do not count
as successful long runs. Temporary tools are not shipped in a normal checkout.
