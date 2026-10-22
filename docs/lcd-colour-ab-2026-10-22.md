<!-- SPDX-License-Identifier: GPL-3.0-only -->
# LCD colour-regression A/B — 2026-10-22

The owner reports that colours and text are correct immediately after rebooting
with the authorized A/B candidate
`cfbcb596a1593fd1fe552369d4e8047de61d5e3b`. The preceding PR #549 merge package
`b392d9ae8f1262552ff49d1bece8fdb07efe32a0` produced wrong colours and unreadable
text immediately after installation. Its source tree equals PR head
`df101a20b79475a4805deaaa9f1cb0765aa66b80`.

The A/B restores `firmware/src/lcd.c` byte-for-byte from
`d9c307265f6012d4df4b74128bb038580956f595`, retaining every new AUTO OFF control,
timer, heartbeat and setting ID. It removes the probe's `0x53`/`0x51` traffic
from boot, sleep and wake. This reported result supports the command rollback as
the colour recovery; it does not identify which removed command caused the
physical regression or establish the controller's backlight wiring.

**The physical backlight remains powered.** SCREEN sleeps the LCD image;
ALL DARK additionally suppresses every LED, without a heartbeat. PA2 and input
scanning stay enabled. Independent backlight-off remains unresolved; the retained
ALL DARK label does not promise complete physical darkness. There is no CPU sleep
or measured power-saving claim. See [current controls](display-idle.md) and the
[historical probe](lcd-backlight-probe.md).

## Evidence and scope

- **Original PR installation:** CRC-checked pre/post settings differ only at AUTO
  OFF byte 559, from 0 to 106. COLOR was CUSTOM with unchanged HI-CON RGB565
  colours. The actual target binary's ten built-in palettes match the generator.
- **Browser comparison:** the real Chromium page/AudioWorklet with those device
  settings shows readable CUSTOM, MONO, PAPER, GREEN and GREY. Unchanged menu
  regions are pixel-identical to `d9c3072`. The browser does not execute the
  physical LCD driver and could not exclude its regression.
- **Rollback A/B installation:** the owner authorized and received `cfbcb596`.
  MIDI readbacks before/after retain ID 17 LEDS 5m, ID 33 30 MIN and ID 31 +MIDI,
  with the saved settings record identical. COLOR is currently MONO. The owner
  confirms correct physical colours/text immediately after reboot.
- **Still pending:** timed first/second-stage LED behavior, repeated panel wake,
  USB/TRS wake, mixed-load audio and a full physical palette matrix. An immediate
  colour recovery report does not establish those scenarios. Final integrated
  CI evidence belongs to the final PR head; a target-only A/B build is not merge
  qualification.

## Validation

[tests/lcd_power_test.c](../tests/lcd_power_test.c) exercises the actual driver
with a delayed-DMA HAL model: baseline initialization (COLMOD `55`, MADCTL `00`,
inversion), sleep/redraw/wake, emergency PA2 enable and unchanged RGB565 payloads.
It rejects `0x51`/`0x53` traffic anywhere in those paths. Normal and ASan/UBSan
runs pass. Running the same model against an isolated original PR #549 driver
fails; the intentional in-flight DMA negative control also exits nonzero. These
are software command/ownership checks, separate from the owner's physical report.

From the repository root, focused checks need no generated assets or device:

```sh
mkdir -p build/lcd-power
cc -std=c11 -Wextra -Werror tests/lcd_power_test.c -o build/lcd-power/model
build/lcd-power/model
cc -std=c11 -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/lcd_power_test.c -o build/lcd-power/model-sanitized
build/lcd-power/model-sanitized
# Intentional negative control: expect exit 1 and the DMA-ownership FAIL line.
build/lcd-power/model --dma-negative
```

The isolated old-driver red check and compiler/source hashes are retained with
local validation under `build/validation/lcd-colour-ab/`; generated evidence is
ignored by Git. The current driver issues no controller brightness commands.

## Remaining device checks

Continue on the installed A/B using the [combined procedure](display-idle.md#combined-user-test-procedure--remaining-fm-1-checks).
Keep its exact package/checksum and preflash backup with the report. There is no
need to reinstall it for each scenario; subsequent artifacts follow the owner's
requested test scope and the exact PR handoff.

1. The immediate reboot colour check is owner-confirmed. For additional palette
   coverage, hold HOME >0.7 seconds and release, turn ALGORITHM to DISPLAY and
   PRESETS to COLOR. Compare MONO, GREEN, PAPER and CUSTOM with browser references;
   mark only the combinations actually inspected as tested. Record/restore the
   pre-test COLOR value (currently MONO).
2. Confirm retained AUTO OFF values through MIDI: LEDS 5m, ALL DARK 30 MIN and
   WAKE +MIDI. These readbacks and an identical saved settings record were already
   verified across the A/B installation; no rewrite is needed to repeat them.
3. Complete timed LED/image blanking, panel/key/encoder wake, +MIDI/PANEL behavior
   and uninterrupted audio using the combined guide. The physical backlight is
   expected to remain powered; do not report image blanking as backlight-off.
   Keep unperformed checks pending and report the exact artifact and observations.

README assessment: the existing integration/experiment overview remains accurate;
this unmerged diagnostic is not a feature milestone. Changelog assessment: no
entry for the unmerged A/B work. Preserve the confirmed owner colour recovery and
remaining hardware limits in the PR evidence.
