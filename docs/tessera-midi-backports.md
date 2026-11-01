<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Tessera MIDI backports

This bounded port adopts two firmware fixes from
[Rastapopolix/tessera](https://github.com/Rastapopolix/tessera), inspected at
`99c71cb7d4144ecaf06ab6bb0f00ae3151547c6a`. It retains Felucca's UART reader,
fixed 24,000-unit quarter notes, per-consumer fractional carries, period-aware
phase rescaling and eight-fire ARP catch-up bound. No engine pin, persistence,
parameter IDs, diagnostic commands or editor command IDs change.

| Donor revision | Adopted code and tests | Necessary adaptation |
| --- | --- | --- |
| `998ca1a3040ed0ca05e25c95a7e10a8bffa791d2`, Kerem Kilic | `usb.c` CIN `0xF` SysEx handling; `midi_uart_test.c` integration vectors | Only USB fragments are adopted; the existing event-gated TRS DMA reader stays. |
| `87d0b3783c52e814435cad13e77611df1ef94160`, after Melodee's `6eca57d`, `1f5db7a` and `1a13939` | Tempo filter, display hysteresis, gap acquisition, local PLAY and physically held ARP behavior; control/timing tests | Q8 millisecond durations replace the donor's high-resolution TIMER4 ticks. Felucca's own fractional phase rescaling remains. First-note REC auto-start is deferred to preserve stopped STEP entry. |

The copied source closure is GPL-3.0-only; existing file notices and the
[licensing record](../LICENSING.md) retain attribution. The MIDI source changes
match the reviewed slices originally prepared on `348fa11`; integration onto
`73c1ed4fce36308e9adab550a99a65059d94d00f` preserves its key-pressure processing
and clock-loss notices. The only textual conflict combined the existing aftertouch
and new ARP test registrations in `midi_control_test.c`.

## Behavior and compatibility

A selected external input is distinct from transport ownership. Local PLAY with
an absent or lost master runs internally, with the normal count-in when recording.
A master's recently running pulses keep external timing. Selected-source Start,
Continue and Stop reclaim transport; pulses alone cannot claim local playback.
Physically held ARP keys play locally while the master is stopped. Releasing a
HOLD chord leaves it waiting for external transport instead of free-running.

The six-pulse tempo measurement averages about two beats, with immediate lock for
changes above 6.25%, display hysteresis and reacquisition after a gap above 500 ms.
Musical phase still follows exact counted wire pulses. At 239.5 BPM with injected
jitter, whole-ms timestamp quantization can still alternate displayed 239/240;
covered modulation periods remain within 0.25%. This is not a jitter-free display
or hardware timing claim. USB single-byte fragments preserve realtime separation
and existing malformed-frame handling.

## Evidence and remaining gates

The new control assertions and tempo fixtures fail against the original firmware;
focused development harnesses pass with the port. Long-run tests retain twenty-minute
wire-pulse counts, all ten divisions, swing, wraps, Stop/Continue, SONG boundaries
and bounded catch-up. Full applicable CI must cover the final PR revision.
Physical FM-1 checks remain pending: fragmented SysEx from a real host, USB and TRS
master handoff, held versus released HOLD, and mixed audio/MIDI deadlines. Host and
browser evidence do not establish those observations. README, changelog and feature
controls are updated; the diagnostic guide needs no change because capabilities
and collection semantics are unchanged.
