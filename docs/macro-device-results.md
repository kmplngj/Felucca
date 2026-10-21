<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MACRO device results

The user's initial device feedback was:

> marco seems to work fine so far

This is an initial smoke report. The quote is retained verbatim; it does not
identify the installed commit/package, device version, host, models, duration or
specific checks performed. The user subsequently reported:

> i tried the models and controls, also switching during held nites. i noticed that the upper key row now longer does work. even on fm-6 instruments.

This records partial model/control and held-note switching coverage; the models,
values, duration and individual outcomes are unspecified. The raised/black-key
symptom also affected FM6 and remained after power cycling. After correcting QNT,
the user confirmed the keys work:

> okay war nur falsch eingestellt dann. danke.

The keyboard report is **resolved by a setting correction**. QNT WHITE deliberately
silences black keys and is retained across engine changes and project recall. The
first diagnostic instruction incorrectly called the physical button SCL; the
corrected route used the printed **SEL** button → scale page → KNOB 3 QNT OFF.
No keyboard regression remains reported, and this symptom is no longer a merge
blocker. The installed SHA and exact initial QNT value remain unknown.

No audio recording, CDC log, timing measurement or successful flash-persistence
result accompanied these reports. Host/emulator results are recorded separately
in [rebase validation](macro-rebase-validation.md).

## Acceptance status

Follow the numbered [hardware procedure](macro-hardware-test.md) and update only
the rows actually exercised. Partial coverage is labelled separately; every
unperformed check remains **Pending hardware validation** until its inputs and
observed outcome are supplied.

| Check | Status | Observation/evidence |
| --- | --- | --- |
| Initial general smoke report | Reported; scope unknown | User quote above |
| Exact macro-profile artifact and successful installation | Pending | Commit, package SHA-256, Actions run/provenance and ABOUT identity unknown |
| Physical panel/LCD and all 48 model/control sweeps | Partial; qualification pending | User tried models/controls; extent and installed SHA unknown |
| Raised/black keys, including earlier FM6 symptom | Resolved; user-confirmed setting correction | Keys work after QNT correction; quote above |
| Legacy eight voices and added-model one-voice allocation | Pending | No scenario-level observations supplied |
| Held notes, retriggers, release and live preset/model/engine transitions | Partial; qualification pending | User tried switching during held notes; exact transitions and outcomes unspecified |
| USER save/cancel/load and power-cycle recall | Pending | No flash-persistence observations supplied |
| Four project slots and D song save/load/power-cycle recall | Pending | No project/song observations supplied |
| Four MACRO parts, mixed engines, effects and automation | Pending | No defined workload observation supplied |
| USB audio at recorded host rate/routing | Pending | No stream/capture evidence supplied |
| USB MIDI and TRS MIDI separately and together | Pending | No transport evidence supplied |
| Idle/load CDC continuity, error deltas and crash/guard records | Pending | No diagnostic files supplied |
| Audio render timing/deadlines and interrupt stack high-water | Pending | No physical measurements supplied; missing counters are unavailable |
| Same-workload baseline comparison | Pending | Baseline identity and measurements unknown |

## Record a completed run

Copy this block into the PR or append a dated run here. Replace `unknown` only
with observed data; keep unrun rows pending. A successful install or general
listening report does not fill the other acceptance rows.

```text
Date / tester: unknown
Firmware full commit / PR / Actions run: unknown
Package filename / SHA-256 / provenance path: unknown
Resolved profile / feature flags / font: unknown
Device ABOUT identity / model: unknown
Host OS / editor revision / DAW or MIDI player: unknown
USB audio rate / channels / routing: unknown
USB MIDI / TRS MIDI source and channel mapping: unknown
Pack manifest SHA-256 / generator source revision: unknown
Pre-test backup path / previous firmware package: unknown
Disposable project slots: A, B, C, D; USER slot: unknown
RESTORE LAST / USB SERIAL / 2ND CORE original and test values: unknown
Procedure step / fixture / duration / exact edits: unknown
Expected result: unknown
Observed result / pass or failure: unknown
Audio / photos / summary.json / samples.jsonl / console.raw: unknown
Baseline firmware and same-workload comparison: unknown
Unperformed checks: pending
Cleanup / restored backup and settings: unknown
Remaining device qualification: https://github.com/kmplngj/Felucca/issues/27
```

Issue [#27](https://github.com/kmplngj/Felucca/issues/27) remains the acceptance
owner for the pending physical checks. Portable collection extraction is tracked
separately in [Felucca-Engines-GPL #25](https://github.com/kmplngj/Felucca-Engines-GPL/issues/25).
This record does not claim that the complete checklist passed or that the opt-in
candidate has been merged.
