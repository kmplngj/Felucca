<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM-1 deadline and voice-envelope investigation (#540), 2026-10-21

Repeated note attacks reproduce audio deadline misses on the physical FM-1, including without USB capture. A render-only timing record exceeded the nominal deadline. Dense requests recover by shedding voices; the resulting smaller load is not successful rendering of the original requested workload. No #540 firmware change or universal polyphony limit is delivered here.

The local PHYS DRONE STRING test retained five voices without new late/shed/USB errors in one 60-second USB-48 kHz run; six requests were marginal and eight were not retained. This applies only to the tested pitches, part distribution, parameters, USB configuration and image. It is not a universal five-voice guarantee. Local, intermediate CI and delivery HEAD images are distinct; the delivery hardware artifact comes from a target-only CI workflow, independently of the full PR merge build.

## Images and provenance

| Artifact | Compiled identity and source head | App B | App SHA-256 | Package SHA-256 |
|---|---|---:|---|---|
| Local screen | `c0f637c5003b111b59cac3d4bf60b0e583eff0cc-dirty` | 488852 | `d620ec7b20216b97dbeea312d106c3a1d7c831fef8869a1711696cf62ababfb9` | `8a7808042b358f5d8ce38766dce250be98862c39ab06dc3f104d75076c6f4b1c` |
| Clean CI baseline | PR #509 merge `d33f0d35883de7c35d98de8ae3eb1d9d1227c287`; head `c0f637c5003b111b59cac3d4bf60b0e583eff0cc` | 489256 | `66c1f7209a29855178762a3f72456dafb2b31cc242a8106205fa557a1a73a81d` | `d4efc34f2d0e50252ab19c1beafc584bb13f2d8e5a9b8460d894f39622062190` |
| Intermediate CI candidate | PR #541 merge `a0813bdb059fa54fb789912eb617d275b0e55ad5`; head `02d90cc54f6c64151772eae3fc83ac8caab7ba75` | 489048 | `1dc4c6366df13b8c91bb01a42c793afcf3798583dfbe408ff358fc33d351bd16` | `b2b7bdfd92aaee6b20841405825b6fd6821d9e3ee2e324ca917ddf60035fabdd` |
| Delivery HEAD target-only CI | Exact PR #541 head `9144ed2cc8b71f425c2769500c67c1f0a877a317`; target run `39668797779`, clean | 489044 | `72d3110a238eb512d4d03b6a0b1f3b697d6b6edef6c03ce616ccfd6243a83d35` | `7c2360e0028a8571f3a7d805dda646eb2fb04a6443f6044b4073d9439c719ccf` |

The coordinator observed baseline C-to-LLVM translation before production edits and attributed its dirty flag to untracked regression fixtures. No starting working-tree/source-diff manifest was retained. Baseline and merged-main `fcb69c3` committed trees both hash to `30c72e6cba43f893ab3143b566d019ce0944be5c`; that does not reconstruct the dirty tree. Archived target instructions independently show deferred nested UART polling, unconditional word-width HRXCNT consumption and the original sample-based external clock. Local basic-layout Pillow assets and development identity differ from CI Raqm and compiled PR-label/UI code. Do not combine local and CI byte deltas or call the local image a clean CI artifact.

Both CI builds use standard profile/M8Stealth, JieLi Clang4.0.1 (SHA `c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f`), selective minsize defaults, Engines `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`, CPU2 compiled in but runtime OFF, and normal crash/reproducer flags OFF. CI provenance retains SDK/blob, sample and profile identities. Package validation checks every extent/CRC and known loader family. Complete installed app readbacks establish each running image.

## Workload and acquisition

1. Load the stated factory sound on all four parts: PHYS DRONE STRING; controls FM6 PAD and VOICE CHOIR AAH. No sound changes during a measurement. Reset sound-load-retained parameter IDs `0,39,40,17..32,45..48,81,82,94` to firmware DESC defaults. Retain full four-part parameter dumps; later runs also retain selected-track/global DUMP. Internal clock120BPM, tune0, CH1–4 routing, transport stopped, no armed/muted part. Factory sound effects remain as the dumps describe.
2. Velocity100; pitches `[48,52,55,59,62,66]` (C4=60). Dense input sends all six pitches to CH1, then CH2, CH3, CH4. Smaller inputs use the first N `(channel=i%4,pitch=pitches[i//4])` pairs, sorted by channel/pitch. Four requests are one C3 per part; five add E3 on part1; six add E3 on part2; eight are C3/E3 on every part.
3. Fifteen cycles at4s cadence: each note holds3.5s with0.5s release. Stagger offsets successive ons by20ms and their matching offs equally. Actual simultaneous holds3.491–3.505s; stagger3.491–3.509s, with all eight overlapping at least3.357s. This changes onset schedule and recovery, not total per-note hold.
4. Native macOS CoreAudio AudioQueue records Felucca PCM16 stereo at actual44100/48000Hz, eight8192-frame buffers. Verify host nominal rate and firmware UAC alternate/rate. Stream settles3s before sampling, then stops naturally. Accepted WAV length equals44+4×reported frames; sample-time discontinuities, missing frames and write errors are0. Host sample continuity does not prove uninterrupted USB delivery or absence of audible glitches. Inactive capture requires alternate0 with CDC unchanged; no analogue capture/listening result exists for those cases.
5. Endpoint `status/dbg/inp/crash` snapshots enclose60s load with about1s lead/2s tail (about63s total). Phased status requests target attack+0.2s, sustain+1.8s and release+3.8s; dbg is also read after attacks. An ordinary attack-ending window spans roughly t−0.2s to t+0.2s; the first includes lead-in idle. These are not timestamps of specific DMA halves. Endpoint-only controls omit ongoing queries.
6. Read-only `memr` snapshots at first/last1.8s sustain use exact ELF/disassembly-derived addresses and source field offsets. Four-part reads take about0.26–0.59s and are non-atomic. Retain note/gate/active/stage and exclude stage4 fades as `voices_busy()` does. They measure sampled sustained/recovery state, never initial admission or every intervening half. No firmware instrumentation or clock/voltage/protection change is used.

Normalized retained parameter ID:value pairs are `0:104,39:0,40:0,17:0,18:2,19:1,20:64,21:0,22:127,23:0,24:0,25:0,26:0,27:0,28:0,29:16,30:2,31:0,32:64,45:0,46:1,47:1,48:127,81:0,82:0,94:1`. The complete dumps retain the remaining factory engine/effect values. Four-part dumps and selected-part/global DUMP match byte-for-byte across all six completed CI baseline/intermediate/delivery controls (`ci-parameter-parity.json`).

## Clean CI baseline, intermediate and delivery comparison

| Case | Requests/attack | Late | Shed | Other kills | UAC under | Gated sampled |
|---|---:|---:|---:|---:|---:|---|
| `ci-baseline-phys-48-4-on` | 4 | 0 | 0 | 0 | 0 | 4/4 |
| `ci-baseline-phys-48-8-on` | 8 | 45 | 45 | 0 | 181 | 5/5 |
| `delivery-head9144-phys-48-4-on` | 4 | 0 | 0 | 0 | 0 | 4/4 |
| `delivery-head9144-phys-48-8-on` | 8 | 45 | 45 | 0 | 181 | 5/5 |
| `final-ci-phys-48-4-on` | 4 | 0 | 0 | 0 | 0 | 4/4 |
| `final-ci-phys-48-8-on` | 8 | 45 | 45 | 0 | 182 | 5/5 |

The legacy local path prefix `final-ci-` identifies intermediate merge `a0813bdb` only; it does not identify the revised delivery artifact. Hardware was released idle after those controls, with CPU2 OFF, while the threshold fix was reviewed. No long clock run began on the intermediate image. The `delivery-head9144-` prefix identifies the exact HEAD target-only artifact. Its compiled head identity differs from the independently built full-PR synthetic merge identity; those package/app hashes must not be substituted.

`ci-overhead-comparison.json` retains input-window timing, IRQ counts, scan costs/gaps, cumulative render maxima before/after and UART-idle limitations. No small single-run difference is an improvement claim. The table is populated only from completed runs.

| CI case (~63.06 s endpoint window) | TIMER5 IRQ delta | Nested IRQ delta | Scan average ns / max us | Scan gap max us | Cumulative render max before → after us |
|---|---:|---:|---|---:|---|
| Baseline, 4 requests | 629471 | 389143 | 5958 / 11 | 103 | 735 → 2394 |
| Baseline, 8 requests | 629646 | 437427 | 5916 / 11 | 102 | 2394 → 3678 |
| Intermediate, 4 requests | 629567 | 391531 | 5875 / 10 | 102 | 740 → 2467 |
| Intermediate, 8 requests | 629654 | 440212 | 5875 / 10 | 102 | 2467 → 3684 |
| Delivery HEAD, 4 requests | 629491 | 392651 | 5875 / 11 | 102 | 741 → 2400 |
| Delivery HEAD, 8 requests | 629616 | 441882 | 5875 / 10 | 102 | 2400 → 3684 |

The scan measurements cover `fm1_input_tick`, not the complete TIMER5 handler. Nested entries do not measure nested duration. Each row established a new cumulative render maximum; the maximum still does not time a named stage or include nested TIMER5 execution. UART receive bytes and drops remained zero throughout.

The delivery image retained all four sampled voices in the four-request control with no new lateness, shedding or underruns. At eight requests it reproduced the baseline's45 late/45 shed/181 underruns and five gated voices in both sampled sustains. These15-cycle controls do not establish a #540 fix or a universal lower voice limit. All six CI captures passed the host acquisition checks. The full completed-case audit covers29 cases and1228 status snapshots; only the previously excluded local24-request repeat WAV fails capture validation.

## Local screening and discriminators

| Case | Requests/attack | Late | Shed | Other kills | UAC under | Gated sampled |
|---|---:|---:|---:|---:|---:|---|
| `baseline-fm6-44100-24-on-r1` | 24 | 0 | 0 | 334 | 0 | not sampled |
| `baseline-fm6-48000-24-on-r1` | 24 | 3 | 2 | 330 | 9 | not sampled |
| `baseline-phys-48-1-off-r1` | 1 | 0 | 0 | 0 | 0 | 1/1 |
| `baseline-phys-48-1-on-r1` | 1 | 0 | 0 | 0 | 0 | 1/1 |
| `baseline-phys-48-12-off-r1` | 12 | 32 | 30 | 116 | 0 | 6/6 |
| `baseline-phys-48-12-on-r1` | 12 | 45 | 45 | 102 | 177 | 5/5 |
| `baseline-phys-48-24-off-nopoll` | 24 | 25 | 30 | 116 | 0 | not sampled |
| `baseline-phys-48-24-off-r1` | 24 | 24 | 30 | 116 | 0 | not sampled |
| `baseline-phys-48-24-off-r2` | 24 | 23 | 30 | 116 | 0 | not sampled |
| `baseline-phys-48-24-on-nopoll` | 24 | 40 | 45 | 102 | 177 | not sampled |
| `baseline-phys-48-24-on-r1` | 24 | 38 | 45 | 102 | 163 | not sampled |
| `baseline-phys-48-24-on-r2` | 24 | 39 | 45 | 102 | 171 | not sampled |
| `baseline-phys-48-4-off-r1` | 4 | 0 | 0 | 0 | 0 | 4/4 |
| `baseline-phys-48-4-on-r1` | 4 | 0 | 0 | 0 | 0 | 4/4 |
| `baseline-phys-48-5-on-r1` | 5 | 0 | 0 | 0 | 0 | 5/5 |
| `baseline-phys-48-6-off-r1` | 6 | 1 | 6 | 0 | 0 | 5/6 |
| `baseline-phys-48-6-on-r1` | 6 | 12 | 18 | 0 | 39 | 4/5 |
| `baseline-phys-48-8-off-r1` | 8 | 34 | 30 | 0 | 0 | 6/6 |
| `baseline-phys-48-8-on-r1` | 8 | 45 | 45 | 0 | 182 | 5/5 |
| `baseline-phys-48-8-on-simultaneous-r2` | 8 | 45 | 45 | 0 | 184 | 5/5 |
| `baseline-phys-48-8-on-stagger20ms` | 8 | 8 | 104 | 0 | 25 | 6/6 |
| `baseline-voice-44100-24-on-r1` | 24 | 0 | 0 | 218 | 0 | not sampled |
| `baseline-voice-48000-24-on-r1` | 24 | 7 | 1 | 217 | 24 | not sampled |

The second dense24-note USB-on WAV is rejected for truncation/write errors; its before/after counter proof remains a separate repeatability observation. Other accepted captures pass acquisition checks.

## Interpretation

- Dense PHYS48 repeats with capture give38/39 late and45/45 shed; without capture24/23 late and30/30 shed. Capture is not necessary for the symptom. It adds pressure in these observations; packet-by-packet USB-underrun causality is not established.
- Endpoint-only polling gives40late/45shed/177underruns with capture,25/30/0 without. Removing ongoing CDC queries does not remove the symptom. This bounds the tested polling condition, not all instrumentation overhead.
- In the first local dense run, cumulative render-only `audio_max_us` was729 before and4594 by the first post-attack sample, above nominal128/44100≈2902us even with nested TIMER5 time subtracted. The exact half/stage is unknown. `cpu_pct` is smoothed render load, not whole-chip CPU. Later unchanged cumulative maxima are not interval maxima.
- Simultaneous8 requests give45late/45shed and five gated survivors in both local repeats. Stagger gives8late/104shed/25underruns and six gated survivors. The first stagger attack has0late/2shed versus3/3 simultaneous. It never demonstrates all eight retained. Lower lateness with more shedding is not equal-workload improvement; sustained eight remains unqualified.
- `voices_given_up` counts `voice_kill()` calls, including overload and budget victim fades. `voices_shed` separately counts overload victims. Their difference is the additional non-overload kill component after call-site audit. Neither counts rejected/admitted requests; in-place reuse is not counted. Six/eight-request failures have no additional budget-kill component.
- `audio_late` is the existing DMA-half lateness observation, not audible-click count. UAC underruns share attack-ending windows; continuous AudioQueue sample timestamps can conceal device stream interruptions.
- `inp` scan cost covers `fm1_input_tick`, not full TIMER5 USB/UART work. `nested` counts IRQ entries, not time. Full nested duration, entry delay and per-stage render cost remain unmeasured. UART is idle: CoreMIDI lists only Felucca and no external TRS sender is connected.

The outcome is a bounded measured envelope with protection preserved, not a global voice-cap change or recommendation to enable beta CPU2. Any subsequent optimization needs targeted event/initialization versus per-voice/render/UAC stage timing and total nested/entry-delay evidence before selecting one cause. This evidence justifies no ring enlargement, DMA acknowledgement reorder, weakened protection, clock/voltage change or blanket noinline mitigation.

## Exclusions and restoration

A preliminary voice probe was rejected before memr by the diagnostic Console's intentional four-command allowlist. The explicit read-only memory transport was separated and rerun; the production collector was unchanged.

One12-request attempt lost CDC during stream startup before MIDI began. The device returned at boots1 instead of3, default runtime, no retained crash and `dbg.prev_rst=1` (recorded P3 power-on class; WDT bit2 absent). This identifies no firmware cause and does not prove manual power cycling. Exclude the attempt. Before further writes, fresh15-object backup and full baseline-app read were retained: stored objects unchanged, settings differed only by authorized RESTORE LAST OFF. A20s idle collector was VALID with continuous boots1→1/uptime and zero error deltas. Subsequent runs use their own endpoint deltas, never aggregates across this boundary.

Original installed app/package, validated15-object backup and11 raw store objects were preserved before tests. Raw autosave sequence40/CRC1462438099 equaled initial live music. Original app SHA `77b64fa7ed674df8a8ff4616d95006ce396a4f3653aee38828cc469130a3eefa`; package SHA `c6383098e9fd8d12de6d3dfa8169c70e5e8583ed8458236aa5b1b2b63b757cec`. Final restoration/readback is recorded after the combined hardware handoff; this draft does not claim restoration yet.

## Retained evidence and commands

Temporary tools, originals, recordings and per-case request/send/snapshot data are in ignored `/Users/jankampling/.codex/worktrees/felucca-509-midi-dsp/Felucca/build/deadline540/`. These tools are not available in a normal repository checkout. The bundle includes `artifact-identities.json`, `ci-package-preflight.json`, per-case `harness-sha256.json`/source copies, `completed-audit.json`, `current-summary.json`, `ci-overhead-comparison.json`, full installed-app proofs and the timestamped `evidence-sha256.json` hash manifest. The older #42512-recording bundle remains separately at `/Users/jankampling/.codex/worktrees/soak425-device/Felucca/build/soak425`; `retained-analysis.json` captures inspected timelines/digital waveform features, not listening.

Commands actually run include:

```sh
rtk proxy env UV_PROJECT_ENVIRONMENT=build/deadline540/venv uv run --locked --group midi python build/deadline540/backup_identity.py
rtk proxy env UV_PROJECT_ENVIRONMENT=build/deadline540/venv uv run --locked --group midi python build/deadline540/run_initial_matrix.py
rtk proxy env UV_PROJECT_ENVIRONMENT=build/deadline540/venv uv run --locked --group midi python build/deadline540/run_threshold_probes.py
rtk proxy env UV_PROJECT_ENVIRONMENT=build/deadline540/venv uv run --locked --group midi python build/deadline540/run_ci_ab.py
rtk proxy env UV_PROJECT_ENVIRONMENT=build/deadline540/venv uv run --locked --group midi python build/deadline540/run_delivery_controls.py --artifact-dir build/revised-head-target/firmware-target-39668797779/build --app-sha256 72d3110a238eb512d4d03b6a0b1f3b697d6b6edef6c03ce616ccfd6243a83d35 --package-sha256 7c2360e0028a8571f3a7d805dda646eb2fb04a6443f6044b4073d9439c719ccf --layout build/deadline540/voice-layout-delivery-head9144.json --label delivery-head9144 --run
rtk proxy python3 build/deadline540/audit_completed.py
```

Retained pipeline sources/configs name native capture, actual notes/timing, trusted installer and complete app-verifier invocations. They do not save project slots, presets or samples. RESTORE LAST is reversibly OFF and CPU2 OFF during deadline tests; final restoration uses the original backup.

Host regressions, target static budgets, browser evidence and other MIDI-batch hardware qualification are separate. No subjective listening, analogue capture, physical panel response, full-rate TRS proof, universal voice limit or universal CPU2 reliability is established.
