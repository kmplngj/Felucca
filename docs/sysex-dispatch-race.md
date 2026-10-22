<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Editor / updater SysEx ownership — 2026-10-22

[Issue #560](https://github.com/kmplngj/Felucca/issues/560) owns the missing replies
to supported, strictly serialized Editor requests. The original setup observations
were DESC `[0,29]` and TRACK_STEP `[0,50]` during CPU2 testing. The loss also
reproduces with CPU2 OFF, transport stopped and no USB audio or musical traffic.

## Cause and change

The main loop used two independent consumers: `ed_service(); ota_service();`.
An interrupt can publish an Editor request after the Editor has observed an empty
input. OTA then consumes that same pending frame and rejects it as not its own.
The host legitimately waits for a reply that can no longer be produced.

The Editor now returns an OTA handoff only for a positively observed, still-held
non-Editor frame. Empty input and a handled Editor frame return no handoff.
`sx_ready` prevents replacement of the observed non-Editor frame until OTA
releases it; a newly arriving Editor frame instead waits for the next Editor pass.
WATCH polling and the inner Editor loop are unchanged. There is no new interrupt
work, queue, buffer, allocation, protocol ID, retry, timeout or persistent format.
The updater and recovery/loader consumers keep their existing behavior.

## Reproduction and causal evidence

A fresh complete backup, raw stored-object export, all menus and original app
readback preceded testing. Session-local loops and captures are retained under
ignored `build/sysex-timeouts/`; they are not generic install or backup commands.
Every measured query waits for its matching command and arguments before sending
the next. Missing replies abort immediately, without measured-query retries.
The existing MIDI link can retry its INFO handshake before the measured loop;
that startup behavior is separate. Host receipt timestamps are dequeue times,
not USB wire timestamps or acoustic latency.

| Original firmware, CPU2 OFF | Result |
| --- | --- |
| Mixed DESC / TRACK_STEP, 10 ms spacing | 10,000 requests pass |
| Same mixed queries, no added gap | DESC `[0,16]` missing after 7,724 requests |
| DESC-only, no added gap | DESC `[0,51]` missing after 14,704 requests |
| Fixed DESC `[0,29]`, no added gap | Missing after 27,233 requests |

The original app was fully read back against its preserved package. Counters show
continuous boot/USB-reset identity, no new audio lateness, CPU2 OFF and no stream.
Wall and monotonic clocks both measure the three-second missing-reply timeout;
that instance is not explained by a wall-clock jump.

A temporary diagnostic build of the unchanged dispatch records a consumed Editor
frame inside `ota_take()`, immediately after its actual successful frame-get.
The 22,767th fixed DESC request has no reply and that counter
increases exactly one: command5, scope0, id29, six payload bytes. A separate
fixed TRACK_STEP `[0,50]` loop loses request37,461; the same counter again
increases exactly one and records command30, track0, step50, six payload bytes. Its matching
ELF symbols and full installed-app readback bind the observation to that package.
The probe adds only main-loop diagnostic data and is excluded from the loader.
An earlier probe before a second frame-get left its own observation window;
its zero count is retained but is not evidence against the consumption race.
**All diagnostic code is absent from the delivered fix.**

## Tests and resources

`tests/sysex_dispatch_test.py` compiles the real USB framing, Editor and OTA code
with the actual outer service block extracted from `main.c`. A narrow receive
adapter publishes a complete request immediately after the real empty check,
without changing that empty result. Both original requests lose their complete
reply on the baseline; the candidate preserves the entire reply. OTA identity,
unknown-frame cleanup and the next valid Editor request also pass, for frames
already pending and frames arriving at the boundary. An unconditional-OTA policy
mutation compiles successfully and loses exactly the Editor replies while those
controls remain valid. The test is part of the normal Editor test unit.

Matched local standard builds use `a3ebdbd-dirty`, identical generated inputs,
Engines `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`, JieLi Clang4.0.1 and the
pinned SDK. Local Pillow uses basic layout without Raqm; these numbers are not
an isolated comparison with cloud or PR-labelled builds.

| Artifact / region | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| App | 489,152 B | 489,164 B | +12 B |
| Data + BSS | 62,152 B | 62,152 B | 0 |
| POOL | 336,440 B | 336,440 B | 0 |
| NOINIT | 15,576 B | 15,576 B | 0; 120 B spare |

Both fresh target builds pass the memory/HAL guards without new compiler warnings.
Existing Editor tests with CPU2 compiled in/out and the OTA real-package/flash
simulation pass. The implementing PR records final signed-head CI, exact artifact
identity, retriefree device comparisons, native44.1/48kHz coexistence, and actual
restoration proof. Prototype results do not establish final-head acceptance.

## Scope and user checks

The wire contract is unchanged: send one request at a time; pushes can interleave.
No blanket minimum gap or automatic retry is introduced. Invalid commands may
still intentionally receive no reply under the documented protocol. Passing
bounded reads does not guarantee every host/cable/reset/load configuration.

The PR provides the exact package and independent user procedure. Preserve the
original package, music/settings and stored objects; use RESTORE LAST OFF for any
temporary musical setup. Final cleanup must restore that fresh snapshot and
preserve raw autosave metadata. Personal backups and PCM remain local.

Physical TRS is unavailable and not qualified by these USB reads. Subjective
listening, manual panel handling, other units/hosts/profiles and deliberate
reset/disconnect/overload classes remain separate checks. This fix neither closes
[#101](https://github.com/kmplngj/Felucca/issues/101)'s broader USB-service experiment
nor changes [CPU2 beta/default-OFF and recovery](fork-features.md#optional-second-core).
