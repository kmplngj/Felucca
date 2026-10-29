<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI consumer queue evidence (#551)

`FELUCCA_MIDI_QUEUE=1` enables a bounded development observer in the existing
audio-side `events_block` consumer. Default `0` compiles out its state, timer
reads, event observations and console fields. Release builds refuse the flag.
This is **partial delivery of [#551](https://github.com/kmplngj/Felucca/issues/551)**;
it changes no admission, queue capacity, live-index drain, ordering, recovery,
musical clock, defaults or saved data. FM-1 qualification remains pending.

## Measurement boundaries

The shared USB/TRS queue has 64 usable event slots. Both producers publish each
packet, enqueue millisecond timestamp and source before incrementing `mi_w`.
TIMER5 can admit TRS events while nested inside audio; USB polling is deferred
outside audio. The observer never writes producer state or changes `mi_r`.

Queue accounting starts immediately before the existing broken-stream recovery
check, after clock-mode/transport/routing handling. It ends after the live drain
loop. It includes arrivals during recovery, engine/keyboard service and drain.
`entry + arrivals == dispatched + flush + residual` uses accepted event packets,
not bytes. The final producer-index read defines the end of this accounting
window; later arrivals belong to the next call. An arrival after the loop's empty
check can therefore appear as residual. Producer-index subtraction is uint32
modular arithmetic; accepted progression must stay within `0x7fffffff` per call.
Observed entry peak is **not** an instantaneous queue occupancy high-water: it
can miss a peak between consumer calls or during service.

The drain timer reads existing HAL `fm1_ticks()` immediately before the loop and
immediately after its last empty check, with publication barriers. Raw uint32
TIMER4 elapsed ticks include per-event observer work, channel/clock/transport
dispatch and TIMER5 preemption. They exclude pre-drain recovery, engine/keyboard
work, final observer accounting/publication and downstream clock advance,
chain/SEQ/ARP work. An empty drain is a no-event control, not a calibrated
empty timer-read pair. These values are neither whole control-block/DMA-half
cost nor exclusive CPU execution, instruction cycles or a measured frequency.
Never add independent maxima from different calls/stages.

Each dispatched event samples `fm1_ms - stored_enqueue_ms` before dispatch and
before freeing the slot. This is integer-millisecond enqueue age, with unsigned
wrap permitted for an age at most `0x7fffffff` ms. It is not wire arrival,
dispatch completion or audible response latency, and has no submillisecond
accuracy. Larger differences are ambiguous and reject the observer lifetime.
USB EP1 can remain pending/NAKed before admission when fewer than 24 slots are
free; none of that delay appears in enqueue age. UART DMA acquisition/overwrite,
parser delay, rejected packets and pre-admission USB wait are unmeasured here.
Existing `uart_rx_drops` combines causes/units and must not be added to these
event counters as though it counted unique lost packets.

## Ownership, validity and lifetime

Audio on CPU0 alone writes 104 B ordinary BSS (100 B data, 4 B publication
sequence). CPU1 and producers never update it. The writer brackets updates with
an odd/even sequence and `RING_PUBLISH()` compiler barriers. Foreground `status`
makes one fixed-size copy with interrupts enabled, then validates its sequence;
an intervening/active writer makes that reply unreadable, without a retry or
waiting lock. Formatting/CDC transfer uses only the local 100 B copy outside
interrupts. Other status keys and the collector's four replies remain separate
reads. Values can already be old when the host receives them.

The observer records one call even for an empty queue. Counts/maxima last for
the application lifetime; reading never clears them, and no reset command or
retained state is added. Restart begins a new lifetime. Keep exact build flags,
package identity, `boots` and uptime; do not combine histories across restart.

`mq_error` bits are sticky: `0x1` means an out-of-range age, elapsed interval,
queue depth/progression or failed conservation; `0x2` means cumulative count or
publication-sequence exhaustion. Counts never wrap silently. Sequence exhaustion
is detected before wrap. After failure, later control blocks skip observer work
while normal musical service continues. Restart is required for fresh evidence.
Raw interval subtraction permits a TIMER4 wrap only under the explicit bounded
interval assumption (at most `0x7fffffff` ticks); multiple wraps or an unobserved
clock fault cannot be detected from two reads. Zero ticks are retained, without
proving the timer was progressing. Ages have the same modular observation limit.

## Optional status fields

All fields below are absent in OFF builds. Schema/readability/availability are
decimal; other values have explicit `0x` unsigned formatting. The unchanged
read-only collector preserves these unknown optional fields in `samples.jsonl`
and start/end snapshots; it computes no new validity rules or deltas for them.

| Field | Meaning |
| --- | --- |
| `mq_schema` | `1`, this schema. |
| `mq_readable` | `1` for a coherent copy. At `0`, no other `mq_*` fields except schema are emitted. |
| `mq_error` | Sticky bits described above. |
| `mq_available` | `1` after a completed call with no sticky error. At `0`, measurement fields below are absent, including startup before any call. |
| `mq_calls`, `mq_events` | Observed calls and dispatched packets since startup. |
| `mq_recoveries`, `mq_flushed` | Broken-stream recovery actions and packets discarded by them; a recovery can flush zero packets if the queue already drained. |
| `mq_entry_peak`, `mq_events_peak` | Maximum observed entry depth and dispatched packets per call. Live arrivals can make dispatched count exceed 64; no quota is introduced. |
| `mq_entry`, `mq_arrivals`, `mq_dispatched`, `mq_flush`, `mq_residual` | Latest call's conservation tuple; all in accepted event packets. |
| `mq_drain_last_t4`, `mq_drain_max_t4` | Latest and lifetime maximum inclusive drain raw TIMER4 ticks. |
| `mq_age_seen` | Bit mask for source/class observations: USB bits 0–4, TRS bits 5–9. |
| `mq_usb_on_ms`, `mq_trs_on_ms` | Lifetime maximum enqueue age for nonzero Note-On (class 0). |
| `mq_usb_release_ms`, `mq_trs_release_ms` | Note-Off or Note-On velocity zero (class 1). |
| `mq_usb_cc_ms`, `mq_trs_cc_ms` | Control Change, including sustain (class 2). |
| `mq_usb_rt_ms`, `mq_trs_rt_ms` | Queued realtime clock/transport, including ignored non-selected source (class 3). |
| `mq_usb_other_ms`, `mq_trs_other_ms` | All other dispatched channel messages (class 4). |

An unseen class has no age field, not a zero age. A seen zero is valid at this
resolution. Source uses the consumer's existing zero-source fallback to USB.
These maxima describe observed dispatches, not dropped/flushed events or a
complete wire-latency distribution. They establish no p95/p99 or interval maximum;
do not subtract maxima or infer a run's maximum from an unchanged lifetime value.

## Resource and validation gates

Enabled work has constant bounded observer cost per dispatched event and per
control call: two HAL timer reads per call, one millisecond read/class update
per event, fixed accounting and publication. No observer loop is added to the
ISR; the original live drain remains unchanged and is not newly bounded by 64.
The enabled foreground copy is 100 B plus compiler frame/call-chain overhead.
No heap, POOL, RAMTEXT, NOINIT or stack reservation is added. Source sizes do not
establish linked region deltas or complete nested stack use.

Before acceptance, retain matched exact-revision OFF/ON target builds and report
app/RAM/POOL/RAMTEXT/NOINIT used/spare, interrupt/foreground entry frames and
remaining unsupported stack evidence. Preserve every existing resource floor and
static budget; verify absent observer symbols and unchanged interrupt code OFF.
Check all intended profiles and CPU2 build/runtime settings separately. Instrumented
profiles must fit the existing app slot; a normal profile's fit is not evidence
for its instrumented variant. Target instructions and host synthetic timer values
do not establish actual observer overhead. Device comparison must show no new
normal-load misses, shedding, stream errors or scan regressions for identical
accepted traces and admitted voices; otherwise reject the enabled build for
that workload rather than changing service policy or relaxing a budget.

The existing `midi_control` host unit runs OFF/ON production dispatch/recovery
fixtures plus queue-boundary, source/class/index/time-wrap, nested arrival and
failure tests. `midi_partition` compares exact PCM/result records across OFF/ON
(including hashes of its selected ownership/controller/clock/voice fields) and
USB-only/TRS-only/mixed production traces, including sustain and clock/transport
negative controls. Generated prerequisites must match the baseline; copied
headers do not establish candidate target provenance. Full current-head CI,
target resources, observer overhead and physical MIDI/audio remain separate gates.
The browser/native receipt requires the observer flag to match; an enabled native
image is not paired to the normal observer-OFF browser. Host fixtures use a
synthetic clock solely to test accounting, never to estimate execution time.

## User test instructions — pending hardware validation

1. Retain matching standard-profile OFF and ON packages from this reviewed
   candidate, built with `FELUCCA_MIDI_QUEUE=0` and `=1` respectively using
   `uv run --locked --group build ./build.sh` (set the chosen flag in the
   environment). Retain exact commits, flags, Engines/assets, JieLi compiler/SDK,
   ELF/disassembly, resource reports and package hashes. Keep all other diagnostic,
   CDC and CPU2 settings identical; the normal automatic artifact has this flag
   OFF. Follow [prerequisites](../BUILDING.md#prerequisites-macos) and
   [installation](../BUILDING.md#install). From a trusted caller checkout install
   only the intended retained package using
   `uv run --locked --group midi tools/fm1_install.py PATH/TO/felucca.fwsc`.
   Keep the normal package for restoration. This procedure claims no installation.
2. Connect headphones/analogue monitoring, a USB data cable and a Mac/Linux CDC
   host. Restart without held buttons; transport starts stopped on HOME.
   Hold HOME over 0.7 seconds, release at MENU. Turn ALGORITHM to SYSTEM,
   PRESETS to ABOUT, tap OCT+, record identity, tap OCT− to return. Select
   USB SERIAL with PRESETS, tap OCT+ for ON if needed. Select 2ND CORE in the
   same tab and use OCT− for OFF for the first pair; restart if changed. Tap
   HOME to close MENU. Identify the exact CDC port and close other serial apps.
3. Follow the [idle setup](diagnostics.md#idle-baseline-setup), allow 10 seconds
   warm-up, then collect with
   `python3 tools/fm1_diagnostics.py --port PORT --duration 60 --interval 5 --scenario 'queue OFF or ON; CPU2 OFF; idle'`.
   Include `--firmware-revision FULL_SHA --manifest PATH/TO/manifest.json` with
   the installed artifact's evidence. OFF has no `mq_*` fields. ON should offer
   readable/available data, `mq_error=0`, empty conservation tuples and no age
   fields before MIDI arrives. Unreadable copies are explicit; never substitute
   zero. Repeat collection without restart to verify lifetime counters persist.
4. For each package replay the same retained timestamped USB-only, TRS-only and
   interleaved trace, with channel 1 on a fixed saved ANALOG preset and identical
   project/FX. Include Note-On, CC bursts, sustain down, Note-Off/velocity zero,
   sustain up, Clock/Start/Stop/Continue and idle-to-active transitions. Retain
   sender file/hash, requested/admitted voices, scheduling/capture uncertainty
   and starting/ending diagnostics. Expect identical note/release/transport
   behavior, conservation, seen classes and no new normal-load errors. Repeated
   nonzero-age events may still share one-millisecond ages; small USB age does
   not qualify host-to-device latency. Compare intentional overload recovery
   separately, reporting discarded work and eventual release rather than a speedup.
5. Use three 60-second runs per selected load/transport, then a ten-minute mixed
   soak. Repeat a fixed heavy audio/FX project with panel/redraw work and UAC
   44.1/48 kHz, retaining no-poll controls as well as collector-on runs. Qualify
   CPU2 ON separately. Quantify observer/collector overhead with matched OFF/ON
   runs, health/scan/deadline deltas and a justified physical timing reference;
   this observer alone cannot supply wire/acquisition/downstream timing. No
   acceptable physical overhead bound or speed benefit is claimed before this gate.
6. Stop senders/streams, release sustain and all notes, close collection, restore
   original SYSTEM settings and the retained normal image with the trusted
   installer. Report artifacts/flags, host/cables/workload, observations versus
   expected behavior and raw captures. A `VALID` collection establishes continuity
   only; all unperformed device checks stay pending.
