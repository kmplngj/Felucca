<!-- SPDX-License-Identifier: GPL-3.0-only -->
# LCD colour-regression A/B — 2026-10-22

The owner reports wrong colours and unreadable text immediately after installing
PR #549's verified merge package `b392d9ae`. Its source tree equals PR head
`df101a20b79475a4805deaaa9f1cb0765aa66b80`.

The pre/post device settings are CRC-checked: only AUTO OFF byte 559 changed,
0 to 106. COLOR remains CUSTOM; its five RGB565 colours equal HI-CON and are
unchanged. All built-in palettes in the actual target binary match the generator.
Actual Chromium page/AudioWorklet testing with those device settings finds
CUSTOM, MONO, PAPER, GREEN and GREY readable and the unchanged menu regions
pixel-identical to `d9c3072`. The browser does not execute the physical LCD driver.

The leading unconfirmed cause is the probe's new boot/wake `0x53`/`0x51` command
sequence. An immediate-boot failure excludes a wake-only trigger. This A/B restores
`firmware/src/lcd.c` byte-for-byte from `d9c307265f6012d4df4b74128bb038580956f595`;
it preserves every new AUTO OFF control, timer, heartbeat and setting ID. It does
not implement independent physical backlight-off. SCREEN and ALL DARK can blank
the image while the backlight remains powered. PA2 and input scanning stay enabled.

## Validation

`tests/lcd_power_test.c` checks actual-driver command traffic, unchanged RGB565
payloads, delayed DMA ownership, boot, sleep, redraw/wake and emergency visibility.
Normal and ASan/UBSan runs pass. The same test rejects the original PR #549 driver;
an intentional in-flight DMA mutation also fails. Neither result proves physical
colours or backlight behavior. Exact target build/package evidence accompanies
the local artifact; target-only A/B validation is not merge qualification.

## Device procedure — pending a separate A/B flash release

1. Retain the verified original package, preflash backup and this exact A/B
   artifact/checksum. Install only after the owner releases this changed candidate.
2. After boot, hold HOME >0.7 seconds and release. Turn ALGORITHM to DISPLAY,
   PRESETS to COLOR. Compare CUSTOM, then GREEN, PAPER and MONO with the captured
   browser references. Record whether colours/text are correct immediately after boot.
3. Return COLOR to CUSTOM. Read AUTO OFF/ALL DARK/WAKE through MIDI: LEDS5m,
   30 MIN, +MIDI must remain, as must ordinary LED brightness DIM LO.
4. Check panel/key/encoder input and a normal sleep/wake cycle. No physical
   backlight-off claim is expected for this candidate. Record remaining checks.

If colour corruption persists, the command rollback has not isolated its cause;
do not report it fixed. No merge or deployment is authorized by this guide.
README assessment: its integration/experiment overview remains accurate; this
unqualified diagnostic is not a feature milestone. Changelog assessment: no entry
for an unmerged A/B experiment; record a confirmed fix with its hardware evidence.
