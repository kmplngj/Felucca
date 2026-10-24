<!-- SPDX-License-Identifier: GPL-3.0-only -->
# LCD transfer failure containment

The normal FM-1 driver stops display work after the first completion timeout.
A timeout does not release the SPI bus or its source: command scratch, fill and
canvas bytes stay unchanged until the existing completion indication arrives.
Audio, panel input, MIDI and ordinary main-loop services continue. The physical
panel may retain an incomplete old picture; do not treat it as current state.

This is always part of the native driver, with no new setting or build flag.
Successful transfer order, RGB565 bytes, configured SPI clock and the final
asynchronous pixel transfer remain unchanged. No second framebuffer, allocation,
flash operation, IRQ recovery or audio-stop path is added.

## Ownership and recovery

The HAL returns a completion outcome. It acknowledges the pending marker only
when completion is observed. The first missing completion retains the existing
4,000,000-poll upper bound; it is not a wall-clock deadline. Later work in that
failed frame stops, including large raster/clear loops and source-buffer reuse.
Subsequent normal frames skip display work while other services run.

The first subsequent drawing service arms a 250 ms backoff. At most once per
250 ms it checks completion without waiting or submitting more bytes. Clock
subtraction is wrap-safe. If completion never arrives, ownership and the display
fault remain indefinitely. No timeout, CS change, count write or peripheral reset
is used as an abort. The SDK identifies CON bit 14 as pending-marker acknowledgment;
it does not establish that acknowledging a timeout stops outstanding DMA reads.

After verified late completion, the driver releases the old transfer. Software
cannot know whether a failed sleep command completed late, so normal UI recovery
waits 120 ms from that release, sends SLPOUT, waits another 120 ms, clears the
whole screen and redraws the latest page/theme/overlay, then sends DISPON. These
are nonblocking frame transitions. Panel/musical input remains active during
fault containment and recovery. A failure at any recovery step relatches the
same ownership/backoff policy; no later draw or visibility claim is published.
Recovery latency therefore includes up to the next 250 ms observation, both
120 ms waits, frame scheduling and transfer time; it is not a measured device bound.

An initialization failure is different: a partial controller setup is not fixed
by redrawing pixels. It stays display-faulted until reboot, even if the old
transfer later completes. Init never resets an owned transfer. Boot, rescue,
UPDATE, UBOOT and crash callers stop issuing display work after failure while
retaining their existing underlying boot/update/reboot policy. The normal LCD
fault path does not invoke crash or stop audio. PA2 remains powered because it
also supplies the input matrix; this adds no backlight-off or controller probe.

## Diagnostics and screenshots

With the existing USB SERIAL/CDC capability, `status` adds:

| Field | Meaning |
| --- | --- |
| `lcd_fault` | 1 while display work is latched failed; 0 permits display service |
| `lcd_owned` | 1 while a command or data transfer still owns SPI/source bytes; healthy final DMA can also be owned |
| `lcd_faults` | Cumulative first-timeout latches since boot |
| `lcd_recoveries` | Verified late completions released for a normal redraw attempt, not successful visible redraws |

These fields/state use ordinary RAM and reset on reboot. They are not retained
crash counters. The [read-only collector](diagnostics.md) includes fault/recovery
deltas when supplied by the installed firmware; older firmware can omit them.
A zero fault count does not prove physical display health: transmitted SPI bytes
have no LCD acknowledgment. No new console control or fault-injection command exists.

An opt-in [screen capture](screen-capture.md) that encounters display failure
terminates as `coverage`, never READY, and releases any explicit wake hold.
It has no completed LCD wire image to publish. No capture protocol version or
stored/protocol IDs change. A subsequent capture requires the ordinary service
to recover first; capture does not abort or reset the transport.

## Evidence and limits

[`lcd_fault_test.c`](../tests/lcd_fault_test.c) compiles actual driver, canvas and
native UI against an independent delayed-consumption DMA model. It checks
command/coordinate/payload/final-DMA failure, persistent ownership, bounded
observations, wrap, repeated recovery failure, late sleep/wake, full-clear failure,
latest menu/page/name/dialog/theme/mixer pixels, direct mixer knob writes after
failed canvas acquisition, active panel edits, capture and partial
initialization. [`lcd_wait_test.py`](../tests/lcd_wait_test.py) compiles the actual
HAL completion/wait functions with substituted registers to check poll and
acknowledgment behavior. Existing power and independent screenshot-wire models
retain their healthy-path and deliberate ownership-negative checks.

Primary SDK source is AC79NN_SDK_V1.2.1_2023-12-13 at
`d179b4484759423312073f5fbb232501aa491047`:
[register layout](https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK/blob/d179b4484759423312073f5fbb232501aa491047/include_lib/driver/cpu/wl82/asm/WL82.h),
[SPI interface](https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK/blob/d179b4484759423312073f5fbb232501aa491047/include_lib/driver/cpu/wl82/asm/spi.h),
[marker acknowledgment and DMA submission example](https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK/blob/d179b4484759423312073f5fbb232501aa491047/apps/common/example/peripheral/spi/spi_slave/spi_nomask_interrupt.c).
The receive example does not establish a transmit abort contract.

**Real FM-1 qualification remains pending and is required before merge.** Host
injection, target budgets and emulator pixels cannot prove peripheral completion,
physical source lifetimes, loaded USB/audio service or visible recovery. Keep
safe abort/reset recovery unsupported until primary evidence and matching bench
tests establish it. Use the PR's exact-package hardware procedure and the
[performance stress method](performance.md#device-timing-and-stress-procedure);
no hardware access or flashing is authorized by these host tests.
