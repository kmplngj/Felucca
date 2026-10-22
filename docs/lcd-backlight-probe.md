<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Experimental LCD controller backlight probe — #546

This branch tests whether the FM-1's LCD controller can extinguish its backlight
without disabling panel input. It is an **unmerged experiment, pending real FM-1
validation**, tracked in [#546](https://github.com/kmplngj/Felucca/issues/546).
The initial isolated probe was based on AUTO OFF candidate
`ba6582eb5913cbc30fc4ceea13d6c2025c581997` from
[PR #547](https://github.com/kmplngj/Felucca/pull/547). PR #549 now combines that
probe with the accepted two-stage AUTO OFF controls under [#555](https://github.com/kmplngj/Felucca/issues/555).
The [current control and test guide](display-idle.md) describes the native submenu,
new ALL DARK timer, MIDI descriptors and downgrade behavior. Hosted firmware or
emulator results do not establish the experimental device result.

## What is known, and what the probe changes

PA2 enables the backlight and the input/LED matrix together. Turning it off has
prevented panel wake; the recent early-rescue investigation also found that input
needs this shared rail enabled. See the actual [LCD HAL](../firmware/hal/fm1_lcd_hw.h),
[LCD driver](../firmware/src/lcd.c) and
[physical-entry evidence](usb-rescue.md#physical-entry-evidence-and-related-firmware).
The controller probe leaves PA2 enabled and does not change the scanner or add
interrupt work. The companion controls reuse existing settings-byte bits; no
record bytes are added.

The firmware identifies its panel as ST7789-class; the exact controller and the
connection of its optional backlight outputs on the FM-1 are unverified. The
[Sitronix ST7789V v1.3 datasheet](https://newhavendisplay.com/content/datasheets/ST7789V.pdf)
describes optional LED_PWM/LED_EN outputs (page 36), brightness command `0x51`
(pages 233–235), and control command `0x53` (page 237). Their existence does not
prove those outputs are connected on this device.

| Command and parameter | Controller meaning used by this experiment |
| --- | --- |
| `0x53 0x20` | Manual brightness block enabled; backlight output off; dimming disabled |
| `0x51 0x00` | Minimum brightness; this alone is not a guaranteed backlight-off command |
| `0x51 0xFF` | Maximum brightness |
| `0x53 0x24` | Manual brightness block enabled; backlight output on; dimming disabled |

WRCTRLD bit 5 is BCTRL, bit 3 is DD and bit 2 is BL. Reserved bits remain zero.
The brightness register resets in sleep, so the probe reloads it on wake. The
datasheet requires a quiet interval after sleep commands; the existing UI's
120 ms wake intervals remain in place.

The controller-probe portion changes only `firmware/src/lcd.c`:

| Path | Command sequence added around the existing display commands |
| --- | --- |
| Sleep | `DISPOFF` → `53 20` → `51 00` → `SLPIN` last |
| Wake begins | `SLPOUT` alone; existing wait and full redraw follow |
| Wake completes | Finish redraw DMA → `DISPON` → `53 20` → `51 FF` → `53 24` |
| Boot | Existing initialization and black fill → `DISPON` → the same on sequence |
| Immediate crash/update/UBOOT wake | Existing waits and `SLPOUT`/`DISPON` → the same on sequence; retain PA2 enable |

The helper synchronizes before reusing `lcd_small` and completes its last DMA
before returning. Source-level cost is four additional SPI bytes per sleep and
six per completed wake or initialization, using the existing scratch buffer.
These counts are not firmware-size, CPU-load or power measurements. No target
resource delta is claimed here.

## Author validation and remaining gates

`tests/lcd_backlight_probe_test.c` compiles the actual LCD driver with a delayed
DMA HAL model; it needs no generated assets or engine checkout. It verifies exact
payloads and ordering for boot, sleep, normal wake and immediate wake, pending
scratch/pixel DMA completion, 32 repeated cycles, and absence of a PA2-off call.
A negative fixture deliberately overwrites an in-flight scratch byte and must be
detected by the DMA oracle. The model does not establish controller recognition,
backlight wiring, physical brightness, real timing or panel responsiveness.

The focused test passed with `-std=c11 -Wall -Wextra -Werror -O1 -g`, and with
ASan/UBSan added. Reproduce from the repository root:

```sh
mkdir -p build/lcd-backlight-probe
cc -std=c11 -Wall -Wextra -Werror -O1 -g \
  tests/lcd_backlight_probe_test.c \
  -o build/lcd-backlight-probe/lcd_backlight_probe_test
build/lcd-backlight-probe/lcd_backlight_probe_test
cc -std=c11 -Wall -Wextra -Werror -O1 -g \
  -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer \
  tests/lcd_backlight_probe_test.c \
  -o build/lcd-backlight-probe/lcd_backlight_probe_test_sanitized
build/lcd-backlight-probe/lcd_backlight_probe_test_sanitized
```

Target build/package checks belong to the exact artifact's PR handoff. A
target-only build is for this hardware experiment; it does not substitute for
full integration validation before any later merge. Full firmware, browser and
FM-1 checks have not been run as part of the focused test above. No merge or
production-fix claim is justified until the physical result succeeds. An unchanged
backlight means the experiment failed to demonstrate control, even if every
software test passes.

README assessment: its introduction already distinguishes integration experiments
from adopted features; this isolated probe establishes no new capability or
overall milestone. No README overview change is warranted. Changelog assessment:
no entry is added for this unmerged, unqualified experiment. A proven backlight
fix would warrant a later entry with its hardware scope.

## User test instructions — pending FM-1 validation

The owner has paused all FM-1 connections, flashing and settings changes while
other tests run. **Wait for a fresh explicit release.** Prepare/download the exact
candidate without device access using the PR handoff's `--download-only` command.

After release, follow the [combined procedure](display-idle.md#combined-user-test-procedure--pending-fm-1-validation)
for backup, installation, revision confirmation, complete wake/audio checks and
restoration. Isolate the controller effect before relying on ALL DARK:

1. From stopped HOME, hold HOME >0.7 seconds and release. Turn ALGORITHM to
   DISPLAY, PRESETS to LEDS and KNOB 1 to DIM HI; set ANIM OFF. Select AUTO OFF
   and tap OCT+ to open its detail page. PRESETS selects rows and KNOB 1 edits:
   IDLE AFTER 5 MIN, IDLE MODE SCREEN, ALL DARK NEVER, WAKE PANEL. HOME closes.
2. Leave controls untouched for five minutes in the same dim room used for the
   baseline. Physical backlight glow must extinguish while ordinary LEDs remain
   available. Black pixels with unchanged glow mean the probe has not succeeded.
3. Tap PLAY once: brightness/image return and transport remains stopped. Release,
   wait 0.3 seconds, then tap PLAY again; transport starts. Repeat with a piano
   key and encoder, checking consumed first gestures, subsequent operation and
   no stuck notes. Stop and restore the previous verified package if input or
   brightness fails; do not try a PA2-off workaround.
4. If successful, continue the combined guide's first/second-stage, repeated wake,
   playback, +MIDI/PANEL, persistence and emergency visibility checks. Record the
   exact commit/package, physical observations and remaining unperformed checks.

No real backlight change is established for this probe by host or browser tests.
