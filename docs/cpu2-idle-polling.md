<!-- SPDX-License-Identifier: GPL-3.0-only -->
# CPU2 idle mailbox polling — FM-1 investigation, 2026-10-22

[Issue #554](https://github.com/kmplngj/Felucca/issues/554) owns this bounded fix
to the integrated worker. The device calls it **2ND CORE / CPU2**; the HAL calls
the same worker **core 1 / CPU1**. Core 0 is the main/audio-interrupt core.

## Result and scope

The worker's idle branch now executes 32 NOP instructions in RAM before polling
the mailbox again. The unchanged firmware repeatedly observed an invalid job on
the connected FM-1. Pacing the idle branch passed the matched two-part device
comparison described below. This is an empirical mitigation on one unit; the
underlying silicon, cache, bus or compiler mechanism has not been established.

Every observed invalid sequence/function/checksum still follows the existing
failure path. Completion acquisition, the 4 ms timeout, halt-before-fallback,
retained exclusion, default **OFF**, clocks and supply are unchanged. No engine,
voice allocation, saved format, wire ID or DSP arithmetic changes accompany it.
The separate [retained recovery policy](fork-features.md#retained-exclusion-after-a-failed-worker-410)
still applies. CPU2 remains beta; other units, engines/profiles, physical TRS,
reset/flash scenarios and subjective listening require their own qualification.

## Physical feedback loop

The baseline was non-PR main `4c32f77b5c311488767b0f4145c1540060a2ef50`,
standard profile, Engines `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`.
`d9c307265f6012d4df4b74128bb038580956f595` differs only in documentation;
firmware, tools, tests, profiles, assets and locked dependencies were compared.
The installed app was read back in full and compared with the intended binary.
Subsequent diagnostic packages likewise have exact ELF symbols, binary hashes,
source diffs, build identities and full device-app comparisons.

Before testing, a fresh complete backup, raw stored-object export, all menu
values, runtime state and original firmware were captured. **RESTORE LAST was
set OFF** for temporary project edits. Retries used supported 2ND CORE OFF/ON
menu operations followed by a normal package restart. The coordinator serialized
installation, readback, MIDI workload and CDC collection; no raw guard writes,
clock/supply changes or concurrent device clients were used.

The minimized scene uses two ANALOG parts and one held MIDI note 60, velocity 80,
on each of channels 1 and 2. All retained part parameters are normalized from
firmware descriptors, followed by LEVEL 90, ARP OFF and the recorded common
parameter overrides. Transport is stopped; there is no MIDI clock, CC traffic
or USB audio stream. Complete part dumps are compared with the original normalized
four-part fixture, with ARP changed to OFF. Removing the second part yields a
30-second control with **zero worker jobs**; that control does not qualify CPU2.

The automated diagnostic command is retained with the session evidence under
ignored `build/cpu2-bad-job/`:

```sh
uv run --locked --group build --group midi python build/cpu2-bad-job/trial.py \
  --artifact-dir build/cpu2-bad-job/matched-baseline \
  --out build/cpu2-bad-job/matched-baseline/NEW-TRIAL \
  --setup tones --parts 2 --notes 1 --seconds 120 \
  --audio 0 --controllers 0 --arp 0 --transport 0 --clock 0
```

Exit 2 means increased BAD/gave-up counters, CPU2 stopped, retained BAD_JOB and
continuous boot identity. Exit 0 means no BAD_JOB in that bounded run. These
session-local scripts require their preserved fixtures and backups; they are
not a general installer or a portable user-test command. The PR description
provides the independent user procedure and exact final package.

## What the controls establish

The original full workload reproduced BAD_JOB with four normalized ANALOG parts,
sequencer/ARP, held notes, USB clocks, CC/NRPN and native USB audio. Removing
audio, controllers, ARP, transport and clocks separately retained the failure.
The minimized two-part case also failed. Counter deltas refer to dispatched
audio subblocks across setup and the workload, not notes, CPU utilization or a
wire-latency measurement.

| Control | Dispatched subblocks | Observed result |
| --- | ---: | --- |
| Empty worker; all real DSP on core 0 | 672 | BAD_JOB, bit 28 |
| Same empty worker, different RAM layout | 14,064 | BAD_JOB, bit 28 |
| Checksum multiplication moved after job validation | 432 | BAD_JOB, bit 22 |
| Empty worker, paced idle loop, 30 s musical window | 41,419 | No BAD_JOB |
| Same paced empty worker, 120 s musical window | 193,860 | No BAD_JOB; zero new late/shed/reset counters |
| Matched unchanged real-DSP negative control | 1,344 | BAD_JOB, bit 28 |
| Paced real-DSP candidate, 120 s musical window | 165,503 | No BAD_JOB; zero new late/shed/reset counters |
| Paced real DSP, four-part mixed load, 300 s at 44.1 kHz | 506,092 | No BAD_JOB; all musical-window error deltas zero; natural capture passed |

The RAM-layout control moves the mailbox from `0x01c09340` to `0x01c09c00`
and changes other BSS placement; it cannot isolate a particular RAM cell or bank.
A larger alignment probe failed the required RAM-headroom check and was never
installed. Moving the multiplication rules out that particular hoisting pattern
as a sufficient fix, not every possible arithmetic/hardware interaction.

Cold-path diagnostic fields temporarily used the worker's reserved mailbox words,
without changing its size, alignment, normal polling sequence or guard verdict.
One example recorded `done = 0x000009ef`, observed job `0x100009ef`, then two
immediate reads of `0x000009ef`; the captured payload checksum matched that job.
The deferred-multiplication control similarly observed `0x004001af` where the
following reads and local done were `0x000001af`. These are changing observations;
they do not prove exactly where the transient corruption originated.

`bad_fn == 0` does not establish a null function read: an out-of-sequence job
skips that branch. A later core-0 `job == done` also does not make BAD harmless:
the original worker may complete a subsequently valid job before core 0 holds
it. The existing failure verdict therefore remains authoritative. Diagnostic
fields, the empty worker, relocation and multiplication experiments are absent
from the delivered firmware.

The physical pattern is related to reports in
[fm1-x0x#10](https://github.com/charlesvestal/fm1-x0x/issues/10) and
[Melodee#21](https://github.com/keremimo/melodee/pull/21). Those reports concern
other firmware/units and do not establish this device's hardware cause.

Incomplete setup attempts are excluded from workload acceptance. One 48 kHz
attempt received no reply to read-only TRACK_STEP `[0,50]`, before selecting
48 kHz or starting audio/music. After closing the failed client, CDC still showed
active CPU2, zero BAD and unchanged boot identity; the same request succeeded on
a fresh MIDI connection. Its cause remains unknown. Subsequent setup/snapshot
SysEx requests are spaced by 10 ms, with no automatic retry or change to timed
musical traffic. A separate metadata-schema error before tone setup and an early
port-open attempt during an unfinished restart are likewise invalid setup,
not firmware or 48 kHz test outcomes.

## Target and host validation

Matched local baseline/candidate builds use the same actual dirty build identity
(`d9c30726`), generated-input hashes, standard profile, engine pin, font/assets,
JieLi Clang 4.0.1 and pinned SDK. The baseline firmware sources are unchanged;
the meaningful host protection-test additions make both builds dirty. The
compiler SHA-256 is `c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f`.
Local Pillow lacks Raqm and uses its basic-layout fallback; these matched local
sizes must not be compared with cloud sizes as an isolated code delta.

| Region/artifact | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| App | 489,088 B | 489,152 B | +64 B |
| Worker RAMTEXT | 164 B | 228 B | +64 B |
| Data + BSS | 62,152 B | 62,152 B | 0 |
| POOL | 336,440 B | 336,440 B | 0 |
| NOINIT | 15,576 B | 15,576 B | 0; 120 B spare |
| Package | 610,134 B | 610,134 B | 0 |

The +64 B RAMTEXT is the same code also counted in the app, not an additional
flash increase. Target checks retain RAM/POOL/NOINIT headroom, HAL register
boundaries, RAM-only idle execution and the worker's single permitted indirect
job call. Target instruction budgets pass. No golden or budget baseline changed.
The two-part real-DSP candidate's worker stack watermark was 388 B and cumulative
maximum wait 9 us; those observations are not worst-case engine/stack guarantees.

With `FELUCCA_CPU2=0`, baseline and candidate app, package, ELF and LLVM are
byte-identical: app 485,088 B, data+BSS 55,540 B, POOL 336,440 B, NOINIT 15,564 B.
Only the intended default variant was installed for this comparison.

The actual-HAL protocol suite passes all nine tests, including existing barrier
mutation checks. New typed read hooks return a single or persistent wrong job
without modifying backing RAM; both must remain BAD_JOB. A matching DONE must
not override BAD. Deliberate guard-policy mutations are rejected. These host
cases test protection semantics; **the physical A/B workload is the regression
signal for this mitigation**. Host coherence cannot model the physical fault.
The unchanged audio harnesses also pass: 0 of 32 dual-core scenes differ, and all
25 partial-work failure results preserve canonical/stored parameters without
replaying potentially advanced DSP state.

Final-head CI, fresh artifact identity and further device workloads are recorded
in the implementing PR. This guide does not convert prototype measurements into
final-head acceptance. A full source/asset/flag match is required to reuse an
artifact, and PR build-label overhead must be separated from the matched code delta.

## Workload and remaining checks

The shared mixed-load setup uses four normalized ANALOG parts, level 90, USB
120 BPM clock, sequencer divisions 1/16, 1/32, 8T and 16T, lengths 64/17/23/64,
and ARP rates 1/16, 1/32, 16T and 1/4. Each step has one note `48 + 4 * part`,
velocity 80, 100% chance, ratchet x1, zero nudge/condition and no parameter locks.
Held notes 60 and 64 use velocity 80. Every two seconds CC7 changes the four
levels and standard NRPN traffic exercises the unchanged unsupported-NRPN path.
Native CoreAudio captures PCM16 stereo from the actual requested 44.1/48 kHz
device rate. The final PR distinguishes completed recordings from aborted probes,
checks sample-time continuity and device-counter deltas, and records objective
signal presence separately from subjective listening and acoustic latency.

Physical TRS input is unavailable. USB tests do not qualify its timestamp,
throughput, MIDI Learn or nested-UART cost. This work also does not close the
separate [arithmetic investigation #425](https://github.com/kmplngj/Felucca/issues/425),
qualify every engine/profile, establish clock-phase jitter, or prove retention
through every reset/power-loss class. Keep CPU2 beta and OFF by default. Restore
the original package, runtime/settings and unchanged stored objects after tests;
the implementing PR records the actual restoration proof and any retained
diagnostic differences.
