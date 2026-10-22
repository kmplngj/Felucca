<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Historical LCD controller backlight probe — #546

The controller probe has been removed from the current candidate. The owner
reported wrong colours and unreadable text immediately after installing PR #549
merge `b392d9ae`; after the authorized rollback A/B `cfbcb596`, colours and text
were correct immediately after reboot. See the [A/B evidence](lcd-colour-ab-2026-10-22.md).

The current `firmware/src/lcd.c` uses the exact command sequence from
`d9c307265f6012d4df4b74128bb038580956f595` and sends no `0x51`/`0x53` commands.
The two-stage AUTO OFF controls remain. ALL DARK blanks the image and every LED,
but the physical backlight rail stays powered; independent backlight-off is
unresolved. PA2/input scanning remain enabled, with no CPU sleep or power-saving
claim. The [current control guide](display-idle.md) describes the retained menu,
protocol compatibility and remaining timed/wake/audio checks.

## Historical experiment

This section records the removed experiment under
[#546](https://github.com/kmplngj/Felucca/issues/546), not the current driver.
Its source and original test are pinned at
[PR head df101a20](https://github.com/kmplngj/Felucca/tree/df101a20b79475a4805deaaa9f1cb0765aa66b80).
The initial isolated probe used AUTO OFF candidate
`ba6582eb5913cbc30fc4ceea13d6c2025c581997` from
[PR #547](https://github.com/kmplngj/Felucca/pull/547); it was later combined with
[#555](https://github.com/kmplngj/Felucca/issues/555)'s two-stage controls in PR #549.

PA2 enables the backlight and input/LED matrix together. Disabling it has prevented
panel wake; the early-rescue investigation also found input needs this shared rail.
See the [LCD HAL](../firmware/hal/fm1_lcd_hw.h) and
[physical-entry evidence](usb-rescue.md#physical-entry-evidence-and-related-firmware).
The probe retained PA2 and scanning and tried the controller's optional backlight
outputs instead. The exact controller and FM-1 wiring remain unverified.

The [Sitronix ST7789V v1.3 datasheet](https://newhavendisplay.com/content/datasheets/ST7789V.pdf)
describes optional LED_PWM/LED_EN outputs (page 36), brightness command `0x51`
(pages 233–235) and control command `0x53` (page 237). This was a lead, not proof
that those outputs are connected or behave as assumed on the FM-1.

| Historical path | Added traffic around the existing display commands |
| --- | --- |
| Sleep | `DISPOFF` → `53 20` → `51 00` → `SLPIN` |
| Wake completes | Finish redraw DMA → `DISPON` → `53 20` → `51 FF` → `53 24` |
| Boot | Existing initialization/black fill → `DISPON` → the same on sequence |
| Crash/update/UBOOT wake | Existing waits and `SLPOUT`/`DISPON` → the same on sequence; retain PA2 enable |

The intended settings were BCTRL enabled, BL gated on/off and DD/reserved bits
zero. The helper synchronized before reusing `lcd_small` and completed its final
DMA. Those properties did not establish correct physical colours or backlight
control: the subsequent owner report exposed a device regression.

## Historical tests and current regression checks

The removed [`tests/lcd_backlight_probe_test.c`](https://github.com/kmplngj/Felucca/blob/df101a20b79475a4805deaaa9f1cb0765aa66b80/tests/lcd_backlight_probe_test.c)
passed its delayed-DMA model and sanitizers for the historical command contract.
It verified transfer ownership and specified payloads, not whether those commands
were appropriate for the actual panel. That test exists only in the pinned
historical checkout; it is not the current test to run.

The current [LCD power test](../tests/lcd_power_test.c) verifies the restored
baseline commands, unchanged RGB565 payloads and delayed-DMA ownership. It rejects
the removed probe traffic; its intentional in-flight scratch mutation also fails
as expected. See [current validation and commands](lcd-colour-ab-2026-10-22.md#validation).
No further probe flash is part of this historical guide. The already-installed
A/B's colour recovery does not establish independent physical backlight-off or
complete timed/wake/audio qualification.

README assessment: the existing integration/experiment overview remains accurate;
this withdrawn probe adds no feature milestone. Changelog assessment: no entry
for this unmerged experiment. The A/B record distinguishes confirmed owner colour
recovery from unresolved backlight control and pending qualification.
