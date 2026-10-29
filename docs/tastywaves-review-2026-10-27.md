<!-- SPDX-License-Identifier: GPL-3.0-only -->
# TastyWaves optimization review — 2026-10-27

Recommendation: register TastyWaves for ongoing review, investigate its nonblocking
MASTER ADC/LCD-DMA scheduling under [#757](https://github.com/kmplngj/Felucca/issues/757),
and keep active-chorus modulation ramps with existing
[#110](https://github.com/kmplngj/Felucca/issues/110). No distinct unowned CPU/RAM
optimization with demonstrated native gains was found in this topic review.
No firmware implementation, donor-script execution, build benchmark or FM-1 test
was performed. The new issue is an investigation, not a confirmed native defect.

## Revisions, method and ownership

- Donor: [marksweiss/tastywaves main](https://github.com/marksweiss/tastywaves/tree/12d3499d056ae4c93908783748ca3ddb5d4d61fc),
  `12d3499d056ae4c93908783748ca3ddb5d4d61fc`, GitHub repository ID `1433738566`.
  A complete non-shallow clone passed `git fsck --full`; `git rev-list --count`
  found 133 commits reachable from the pinned main tip.
- Native: [kmplngj/Felucca main](https://github.com/kmplngj/Felucca/tree/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730),
  `fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730`, freshly fetched and rechecked before
  issue creation. Instructions and comparison code came from that isolated checkout;
  the original user checkout was preserved.
- Deduplication: full paginated all-state Issues, issue comments and closed PRs
  (including merged PRs) across Felucca, Felucca-Engines, Felucca-Engines-GPL and
  Felucca-WebApp. Canonical issue URLs and upstream markers were checked; no
  TastyWaves marker/redirect required recovery. All three firmware/engine repositories
  have Issues enabled; WebApp has Issues disabled. Inventory was refreshed before
  the new issue write. Search indexing alone was not used to establish absence.
- Scope: current DSP, relevant originating diffs, LCD/ADC and USB paths, native
  callers/tests and storage layout comparison. Reading the full Git graph and
  selected source topics does not constitute 133 individual commit assessments.
  In particular, the large donor root and complete patch-log history were not
  individually assessed. No journal/frontier/coverage credit is claimed.

The [ownership guide](repository-ownership.md) places the proposed ADC work in
Felucca's host/HAL. It needs no engine collection or client implementation issue.
Portable GPL engines would belong in Engines-GPL, but adopting the donor's whole
wavetable synth is a separate feature request, outside this optimization intake.

## Decisions

| Mechanism | Current native comparison | Decision |
| --- | --- | --- |
| Skip MASTER ADC conversion while LCD pixel DMA is active | `master_poll()` samples unconditionally; final LCD DMA may remain active | New bounded investigation [#757](https://github.com/kmplngj/Felucca/issues/757); verify native overlap/noise before retaining a guard |
| Evaluate chorus modulation at 16-sample endpoints and ramp delay between them | Shared chorus and INSERT CHOR still evaluate their waveform per sample | Already owned by [#110](https://github.com/kmplngj/Felucca/issues/110); no duplicate issue |
| Replace USB resampler with 12-tap Q15 instead of native 24-tap Q30 | Changes coefficients, precision, response and latency | Reject as a sound-preserving optimization; fewer operations do not establish an acceptable native tradeoff |
| Guarded wavetable interpolation, mip levels, precombined weights | Different synth/data from native engines; generated coefficients/helpers already exist | Feature/quality design, not a demonstrated native optimization |
| Donor flash slots, patch log, simplified platform, larger audio halves | Conflicting flash ownership and different latency/features/recovery contracts | No direct transplant |
| Send a closing F7 after a timed-out partial SysEx reply | Native lacks donor recovery flag, but supported-host failure is unproved | Watch lead only; no new issue or confirmed bug claim |

### MASTER ADC and LCD DMA

The complete three-file
[340fb0a488ac1f3ac0e1a4c1b5ad514826c92fad diff](https://github.com/marksweiss/tastywaves/commit/340fb0a488ac1f3ac0e1a4c1b5ad514826c92fad)
adds a read-only HAL completion query, a driver `lcd_idle()` helper and a guard
before MASTER sampling. The [current donor caller](https://github.com/marksweiss/tastywaves/blob/12d3499d056ae4c93908783748ca3ddb5d4d61fc/firmware/src/platform.c#L294)
does not wait, acknowledge completion or end buffer ownership. The donor reports
volume jumps/crackle during tall drawings; this is donor testimony, not a native test.

Native [MASTER sampling](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/master.c#L8)
has no guard, and [lcd_data](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/lcd.c#L39)
leaves the last DMA running. However native sampling occurs before drawing with
[roughly 15 ms frame spacing](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/main.c#L291),
so most normal samples may already be quiet. #757 requires correlation of actual
SPI completion, raw stationary-pot readings and output under static/heavy redraw,
followed by an unchanged-baseline versus guard-only A/B on the same FM-1.

Preserve `master_boot()` before audio starts, the 1/8 IIR and mapping, battery
sensing, splash/sleep/wake, buffer/CS ownership and the bounded main loop. A
software busy flag alone remains set after hardware completion: using it alone
can suppress reads indefinitely. Never replace observation with a blocking
`lcd_sync()`. Measure skipped-read gaps and knob response under sustained redraws.
Host fixtures must distinguish running DMA from completed-but-unsynchronized DMA;
only hardware can establish electrical noise reduction.

### Chorus LFO endpoint ramps

The complete
[da83c57bc97c11404034206ad238fa17bcca528b diff](https://github.com/marksweiss/tastywaves/commit/da83c57bc97c11404034206ad238fa17bcca528b)
replaces per-sample sine evaluation with endpoint calculations and signed integer
ramps. [Donor fx.h](https://github.com/marksweiss/tastywaves/blob/12d3499d056ae4c93908783748ca3ddb5d4d61fc/firmware/src/fx.h#L35)
is a useful additional implementation reference for #110. Its task log explicitly
says the optimization still needed device remeasurement; earlier donor percentages
do not quantify this patch.

Native [INSERT swept effects](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/fx.c#L911)
and [shared chorus](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/fx.c#L704)
have different phase timing, routing and smoothing. Retain #110's existing scope
and separate variants; the exact settled-zero-Depth experiment remains
[#637](https://github.com/kmplngj/Felucca/issues/637)/
[#646](https://github.com/kmplngj/Felucca/pull/646).

Key constraints: native rates reach 40 Hz, donor chorus approximately 1.7 Hz;
signed delta division truncates and can miss its endpoint; partial blocks and
phase wrap need explicit policies. The donor patch also changes its original
advance-before-read alignment by a sample. Native flanger uses a squared triangle,
not donor sine, and shared chorus has per-sample Depth slew. Blindly copying the
whole donor loop changes sound and state. Reuse `insert_test`, `stage_unroll_test`
and the shared-chorus reference tests; quantify delay/PCM/spectral error and
inspect actual JieLi code for runtime divides/spills before claiming a gain.

### Rejected transplants and an unresolved USB lead

The [donor USB path](https://github.com/marksweiss/tastywaves/blob/12d3499d056ae4c93908783748ca3ddb5d4d61fc/firmware/src/usb.c#L1010)
uses a shorter, lower-precision FIR than
[native](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/usb.c#L1076).
Its source tables are 5,760 bytes smaller and stereo history 128 bytes smaller;
these are declared-data differences, not linked-image measurements or a recommendation.
Cutoff/window, precision and latency differ. Its cross-array indexing and
reverse-pointer arithmetic must not replace native independent-channel pointers
and safe coefficient traversal. Preserve native rate-switch, scheduling, oracle
and streaming diagnostics coverage.

The [donor flash layout](https://github.com/marksweiss/tastywaves/blob/12d3499d056ae4c93908783748ca3ddb5d4d61fc/firmware/src/platform.c#L72)
overlaps native project/sample/preset/autosave ownership. Native already has
[A/B storage and commit validation](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/storage.c#L5)
with torn-write tests. Donor's 256-frame DMA halves versus native 128, disabled
CDC/UART and reduced diagnostics are different latency/feature choices, not free
optimizations. Its full guarded wavetable bank is 427,776 raw bytes before 4,096
bytes of sinc coefficients; importing it would require an explicit feature,
licensing and capacity plan rather than an optimization patch.

Donor partial-SysEx recovery originates in
[root beb829f146bd66fc3e8cf929080504898b1cd67a](https://github.com/marksweiss/tastywaves/blob/beb829f146bd66fc3e8cf929080504898b1cd67a/firmware/src/usb.c#L815).
[Native ota_wire_send](https://github.com/kmplngj/Felucca/blob/fd768dc3f989c4f98f4f60c7cc0f7e14ad2a6730/firmware/src/usb.c#L897)
can time out after partial enqueue, but the next F0 may already resynchronize a
supported host. Before filing work, model a response larger than the 192-payload-byte
TX ring, stop host reads past 200 ms, resume, then inspect the next reply and notes
through actual client parsers. Include disconnect/reset and repeated timeout.
Do not copy the donor's 500 ms timeout without responsiveness evidence. This lead
does not establish completion of the root commit's review.

## Validation, licensing and watch handoff

Future candidates require matched SDK/assets/profile/flags and JieLi Clang 4.0.1,
unchanged-baseline A/B evidence, app/RAM/POOL/RAMTEXT/NOINIT and stack deltas,
audio/scan/USB deadlines, applicable host regressions and FM-1 observations.
Host instruction counts and static target estimates are not physical CPU gains.
Sound-changing ramps additionally require an explicit error/acceptance policy.

[Donor licensing](https://github.com/marksweiss/tastywaves/blob/12d3499d056ae4c93908783748ca3ddb5d4d61fc/LICENSING.md)
and relevant source headers identify GPL-3.0-only, Mark Weiss and inherited
Felucca/SLOOP/Dinghy attribution. Host ADC/LCD/FX adaptations stay in Felucca with
those notices. They require no donor font, waveform, sample or SDK-binary copying;
no GPL helper should be copied into the MIT engine collection.

The pending source entry preserves the immutable main pin, stable ID and 133-commit
inventory with **zero reviewed commits**. Ordinary review to main precedes guarded
registry reconciliation and initialization on `automation/firmware-watch`. The
existing runner must verify identity, pin and complete history again, preserve
all previous sources/intervals/journal, and keep blockers explicit. This PR changes
no runtime state, assessment journal, schedule or automation. Pending registration
must not be presented as active scanning.
