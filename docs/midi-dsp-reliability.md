<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI timing and DSP reliability

The original bounded integration covers #525–#529 with separate fix commits and a
shared qualification candidate. It changed no engine pin, data/wire IDs, sound
goldens or performance thresholds. The 1.7.0 arithmetic follow-up below advances
the engine pin separately. #540 remains a separate measurement-led deadline diagnosis.

## Changes and provenance

| Owner | Production change | Focused regression |
| --- | --- | --- |
| #525 | 2 kHz TRS polling also nested in audio; consumer ownership unchanged | `timer5_midi_test.c`, including learned CC/four sequencers and UART disabled |
| #526 | RX/overtime event gate, 16-bit control/count registers, one-byte event threshold within 128-byte ring | `uart_dma_test.c`, empty/stale polls, running status, partial/wrapped/deferred traffic |
| #527 | Fixed 24,000-unit quarter notes and per-consumer carries; tempo phase rescaling, queued Start, bounded ARP overshoot | `midi_drift_test.c`, 20-minute pulse counts, all ten rates, swing, Stop/Continue, wrap, SONG clock-track changes |
| #528 | Defined signed DC/low-cut/FM6/PHYS scaling; unsigned FM6 phase additions | `signed_audio_scaling_test.c`, `phys_signed_test.c`, normal goldens/transition suite |
| #529 | Descriptor-based local 120 BPM fallback for invalid stored tempo | `beat_samples_test.c`, exhaustive int16 and real stress-event publication |

Adapted from fgunited upstream #258 `f3290a70529dbe8c49e3a5981999c58a3fbcdcc5`
and #269 `ebdf867d631b2e9dff0dc64880ee29d26855c111`, ordenador #264
`1a3bc4a6c1a74c3964edf8f1ae3b792017bbfcc2` and #265
`c91d7b6f905706a8ebe47873d230ef6185aa64c7`. Original notices remain.
That integration retained MIT Engines at `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`.

The official AC79NN SDK V1.2.1_2023-12-13 WL82.h and `cpu.a` were retrieved from
[JieLi's tagged source](https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK/tree/AC79NN_SDK_V1.2.1_2023-12-13).
WL82.h SHA-256 `6f5a44f39282f66203d837a1c74c9d8197d2856547356fce8ed0d191318ff645`
defines CON0/CON1/BAUD/HRXCNT as 16-bit and RXCNT as 32-bit. `cpu.a` SHA-256
`00cea21d3c8d99487821f2c2b203f2c5a04b2cc8421bc05e9b875a0d70e42c62`, extracted
`spec_uart.c.o`, was decoded to LLVM IR with the actual JieLi compiler. `uartx_isr`
gates on `0x4800`, sets RDC `0x80`, performs CSYNC, acknowledges `0x1400`, then
reads 16-bit HRXCNT; its interrupt-enable checks are not needed in the polled host.
No-event stale-count fixtures model permitted retention, not a measured silicon race.

The event threshold is one byte, with UART interrupts still disabled. Review of the
combined timestamp/event fixes caught a 32-byte threshold that delayed continuous
MIDI by up to 10 ms: without an idle gap no timeout flushes that batch. The integrated
TIMER5 timing fixture now exercises the production HAL event gate, RDC/latch/ack
sequence and parser together. A retained 32-byte negative reproduces the delay;
one-byte events preserve the 2 kHz poll's at-most-1 ms timestamp bound. The SDK
describes a byte-count threshold and programs RXCNT directly without a minimum or
alignment clamp; this changes no UART interrupt enable or queue ownership.

## Baseline and focused host evidence

Unchanged baseline `c0f637c` combines PR #509 with main `57dfa4b0`. Its production
source matches that main. Apple Clang, macOS arm64, standard profile, generated
assets and unchanged Engines pin are used for local comparisons. Target builds
use JieLi Clang 4.0.1, `-Os`, the existing selective minsize pass and verified SDK
package blobs. Raw build, compiler commands and counter logs stay under `build/`.

Before correction, the saturated wire simulation reports maximum 5 ms timestamp
lag; after correction it reports at most 1 ms, 31,250 bytes, 10,256 CC messages and
480 clocks without drops. UART empty polls reproduce stale replay on the original
policy; the corrected model retains all 840,000 bytes and 70,000 packets.
The unmodified phase fixture reports 108.8534 ms sequence drift at steady TRS120
BPM after 20 simulated minutes. All five fixed wire-pulse scenarios pass a 2 ms
host phase bound after correction. This tolerance does not measure physical jitter.

Strict fatal UBSan reproduces negative shifts in DC feedback, FM6 velocity and
PHYS on baseline. Optimized and strict ASan/UBSan focused runs pass after correction;
PHYS output hash remains `43636377a989c407` with positive and negative samples.
All 65,536 signed tempo values pass internal, unmeasured and measured external
paths. Zero-initialized baseline divides by zero; the guarded helper does not.

The intermittent zero-tempo publication report remains **unreproduced**. Production
boot initializes globals before audio starts; project replacement masks interrupts
and clamps globals; SONG changes track timing without replacing global tempo.
The existing preempted drumfuzz boot fixture blocks its signal through initialization.
Separate fully strict short drumfuzz probes (seed1/one seed/50 steps and SONG
seed101/one seed/50 steps) stop at existing negative shifts in fx.c delay feedback
and eng_drum.c gain scaling. They do not establish an invalid-tempo race and do not
justify broad sanitizer exclusions. The focused new fixtures use no exclusions.

`midi_grid_advance` uses uint32 arithmetic: at accepted tempo its maximum numerator
is `12000*66150+23999 = 793823999`. Tempo rescaling uses 64-bit multiply/divide on
estimation changes, not per sample; #425 audit and real timing remain separate.
A live ARP rate reduction can leave a backlog. Eight firings per control block
bound work; unconsumed phase drains later, including a filtered-empty-list case.
Legal SEQ/ARP rates are the ten N_DIV values; dotted rates are delay-only.

## Upstream 1.7.0 arithmetic follow-up

The [1.7.0 release](https://github.com/hugelton/Felucca/releases/tag/v1.7.0)
at `d7b1b7c4099bba28854869ddb256b3d9f634cee8` also advances its Engines
dependency. Its five firmware fixes above were already present in this fork;
the remaining arithmetic changes come from Felucca-Engines
`e88bc70200beece3c13b831cafc76c009d20afbb` (ANALOG signed scaling) and
`7511c0a784dc10d5fadc5e06dcb583118e02010e` (LOFI, NOISE, TRIO and WHEEL,
with explicit wrapping helpers). Native PHASE adopts the output multiplication
from Engines `04ffe903eb87a752305d1e5b10da01b53e4ab004`.
The fork's integrated Engines pin is
`7cf364f6c2ce0130be4fe8bf436ffe62077cb175`, already published on the Engines
fork's main branch with these fixes and the fork's integration contracts.

This selective backport retains the firmware's fixed 44.1 kHz configuration,
contract-v1 checks, zero-mix ANALOG render path and per-part PHASE crossfade
scratch. The library also supports other sample rates and includes a standalone
MIT PHASE; this firmware explicitly rejects other rates in `core.h` and continues
to compile its native PHASE. It does not replace the HAL with felucca-bsp. BSP
alignment remains [#430](https://github.com/kmplngj/Felucca/issues/430);
cross-bootloader stock return remains in
[PR #622](https://github.com/kmplngj/Felucca/pull/622). Engine IDs, stored formats,
presets and protocol do not change.

The PHASE regression in `signed_audio_scaling_test.c` freezes 36,864 samples
across all eight waves, three notes and FOLD 0/1/127. On unchanged `05a3de5`,
fatal UBSan rejects the first negative output shift; the optimized reference hash
is `be19079679d9c71d`. No sound or cost baseline is regenerated. Host and target
validation do not establish physical FM-1 listening or deadline qualification.

For device acceptance, follow the setup and comparison procedure below with
CPU2 OFF first, then repeat with CPU2 ON separately. Include ANALOG (MIX 0 and
nonzero), LOFI, TRIO, WHEEL, NOISE and PHASE (FOLD off/on), using identical notes,
presets, controls and output levels before/after. Exercise held notes, releases
and engine changes. Expect unchanged sound and no new clicks or dropouts; these
checks remain pending until performed on an FM-1.

## Combined user test instructions

The [2026-10-21 device results](midi-dsp-device-results-2026-10-21.md) record the
passed USB pulse-count checks with CPU2 OFF and the BAD_JOB fallback reproduced
with CPU2 ON on both baseline and candidate. CPU2 ON remains unqualified; no
candidate-specific regression is established. The report also records exact
restoration and pending TRS/listening checks.

Use the exact PR revision, linked CI artifact and `.fwsc` named in the PR description.
Follow [BUILDING](../BUILDING.md#install) prerequisites and the backup protocol;
retain the existing full backup and exact original package before installing once.
Use `uv run --locked --group midi tools/fm1_pr.py NUMBER` from a trusted checkout.
This procedure describes additional user acceptance; automated device observations
and outstanding checks are recorded separately in the PR, never inferred from host tests.

1. Start stopped on HOME with no held keys. Hold HOME for more than 0.7 seconds,
   release in MENU, choose SYSTEM with ALGORITHM, ABOUT with PRESETS, tap OCT+ and
   record build identity; OCT− returns. Choose USB SERIAL, OCT+ for ON, then tap
   HOME. Keep serial configuration identical in comparisons. First leave 2ND CORE
   OFF; test ON (BETA) only as a separate recorded run after restarting.
2. Hold HOME again; select MIDI with ALGORITHM and MIDI IN with PRESETS. Set CH1–4
   with OCT−/OCT+ and tap HOME. On HOME, tap HOME once for MIXER and again for CLOCK.
   KNOB1 is BPM, KNOB2 SWG and KNOB3 CLK (INT/USB/TRS). Select USB first, later TRS
   with the corresponding physical MIDI source connected. Send external Start and
   24 clocks per quarter at 40, 97, 120 and 240 BPM. Use a known disposable four-track
   sequence and held two-note ARP chord; record its project/parameter readback.
3. Run stable/jittered clocks, tempo changes, Stop/Continue, all ten sequence/ARP
   rates and maximum swing. Record audio against counted master pulses for 20 minutes
   for the long-run check. There must be no accumulating phase error, stuck note or
   lost Stop; gates must end while stopped. A new stopped key tap still sounds once.
   Extreme live 4BAR→1/32 ARP changes may settle over several control blocks.
4. Repeat full-rate TRS CC/NRPN/note traffic with clocks while USB audio records at
   native 44.1 and 48 kHz; exercise MIDI Learn, four sequencers and mixed effects.
   Keep cable route, source schedule and project fixed. Collect status/dbg/inp/crash
   using the diagnostics guide and compare counter deltas, scan and nested timing.
   Physical throughput and latency require the TRS cable; USB injection cannot prove them.
5. Play the same FM6 PAD and PHYS DRONE STRING notes before/after, change presets
   and engines while held, then release with delay/reverb/chorus tails. Compare captured
   PCM/listening at matching levels; no changed sound is intended. Invalid BPM is a
   corruption-boundary host test, not a supported front-panel value to enter.
6. Stop the master, release all notes and restore the original settings/runtime
   project and package as recorded. Read the backup back and compare all unchanged
   stored objects. Report exact artifact, USB rate, CPU2 state, wiring, duration,
   diagnostics and audible observations. Unperformed listening/panel/TRS checks remain pending.
