<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Experimental LCD controller backlight probe — #546

This branch tests whether the FM-1's LCD controller can extinguish its backlight
without disabling panel input. It is an **unmerged experiment, pending real FM-1
validation**, tracked in [#546](https://github.com/kmplngj/Felucca/issues/546).
It is based on AUTO OFF candidate
`ba6582eb5913cbc30fc4ceea13d6c2025c581997` from
[PR #547](https://github.com/kmplngj/Felucca/pull/547). That candidate's backlight
behavior is unchanged by this separate branch. The hosted firmware and browser
demo do not establish the experimental device result.

## What is known, and what the probe changes

PA2 enables the backlight and the input/LED matrix together. Turning it off has
prevented panel wake; the recent early-rescue investigation also found that input
needs this shared rail enabled. See the actual [LCD HAL](../firmware/hal/fm1_lcd_hw.h),
[LCD driver](../firmware/src/lcd.c) and
[physical-entry evidence](usb-rescue.md#physical-entry-evidence-and-related-firmware).
This probe leaves PA2 enabled. It does not gate the rail, change the input scanner,
add interrupt work, or add a preference or persistent bytes.

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

The source changes only `firmware/src/lcd.c`:

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

Use the experimental PR handoff's exact PR number, 40-character head commit,
standard-profile `.fwsc` artifact/run link, checksum and build flags. Do not
install PR #547 expecting this probe. The handoff must identify the experimental
package before these steps are performed; a raw `.bin` is not installable firmware.

1. Keep a compatible editor Backup export and the previous known-good `.fwsc`.
   Connect one M-VAVE FM-1 to the host with a USB data cable and use headphones
   at low MASTER level. Close other MIDI applications and disconnect TRS MIDI.
   From a trusted reviewed caller checkout with
   [uv and GitHub CLI set up](../BUILDING.md#test-a-pull-request-on-hardware), use
   `uv run --locked --group midi tools/fm1_pr.py NUMBER --commit FULL_SHA --profile standard --validation target`,
   replacing NUMBER and FULL_SHA with the exact experimental PR identity from
   its handoff. If its verified artifact is already downloaded, use the
   [documented package installer](../BUILDING.md#install). Install this candidate
   once; do not reflash between the following scenarios.
2. Confirm the initial display is readable and its brightness is comparable to
   the baseline. Tap HOME to reach HOME, stop transport with PLAY if running,
   and release all keys. Record the selected track, engine and preset; press and
   release one piano key to establish its audible baseline. Hold
   HOME for more than 0.7 seconds, release when MENU appears, turn ALGORITHM to
   SYSTEM and PRESETS to INFO, then tap OCT+. Record the device's commit/PR
   identity as well as the package provenance. OCT− returns to the menu.
   Record RESTORE LAST's value and set it OFF with KNOB 1; record original
   DISPLAY AUTO OFF/LEDS/ANIM and MIDI SCREEN WAKE/MIDI IN values too.
3. First test SCREEN alone. In MENU turn ALGORITHM to DISPLAY, PRESETS to LEDS,
   and select DIM HI using KNOB 1. Select ANIM OFF, then AUTO OFF SCREEN 5m.
   Turn ALGORITHM to MIDI, PRESETS to SCREEN WAKE, and select PANEL with KNOB 1.
   Tap HOME to close MENU. Start a stopwatch after releasing HOME and do not
   touch any controls for five minutes. Compare against the same baseline
   conditions in a dim room: success means the physical backlight glow goes
   away, while normal panel LEDs remain available. A black image with the same
   backlight glow is a failed backlight-control result. Record the observation.
4. While dark, tap PLAY once. The LCD and backlight must return to their previous
   visible brightness; transport must stay stopped. Release PLAY, wait at least
   0.3 seconds and tap it again: transport must start normally. Tap PLAY to stop.
   If the screen stays dark, controls stop responding or brightness is wrong,
   stop the experiment and restore the previous package using the documented
   installer; do not attempt an unreviewed PA2 or power-rail workaround.
5. If the first sleep/wake succeeds, repeat a fresh five-minute SCREEN timeout
   twice. First wake with a piano key: the first key must be silent through its
   release; after 0.3 seconds a second press must sound and release normally.
   On the next timeout, wake by turning KNOB 1 one detent: it must restore the
   display without changing the HOME parameter; after 0.3 seconds a second
   detent must change it. Repeat sleep/wake at least three times in total and
   record flicker, delayed light, brightness drift or missed input.
6. Test the combined setting: hold HOME, select DISPLAY with ALGORITHM, AUTO OFF
   with PRESETS, and BOTH 5m with KNOB 1; tap HOME to close. Use a known saved
   looping project: from HOME, tap SAVE four times (USER → PRESETS → PHRASES →
   PROJECT), select its slot with KNOB 1, select LOAD with KNOB 3 and tap OCT+.
   Record its slot, name, track engines/presets and effects, then tap PLAY. Leave
   playback qualification pending if no suitable known project is available.
   Leave controls alone for six minutes. At five minutes
   the LCD backlight and ordinary LEDs must go dark; at 5:30 and 6:00 only a
   brief piano-key LED pulse is expected. Audio must continue unchanged. The
   first PLAY tap wakes only; release, wait 0.3 seconds, then tap PLAY to stop.
7. Test MIDI wake separately. Hold HOME, use ALGORITHM/PRESETS to select MIDI /
   MIDI IN and set CH1-4 with KNOB 1. Select SCREEN WAKE +MIDI. Close MENU and
   establish that the note sequence below sounds while awake, releasing its note
   before waiting for a fresh BOTH 5m timeout. From the host, send USB MIDI note 60 on
   channel 1 at velocity 64, followed by note-off one second later. T1 must play
   and the LCD/backlight must return. Set SCREEN WAKE PANEL and repeat: T1 must
   play while LCD/backlight stay dark; a panel wake must still work. Repeat via
   TRS MIDI if available, and mark untested paths pending.
8. While the display is awake, hold OCT− and OCT+ together for about 2.5 seconds
   until the UPDATE MODE countdown appears, then release both before five
   seconds. The countdown must stay readable and cancel back to the previous
   page. Do not deliberately trigger a crash or enter/flash the bootloader just
   for this check. The actual immediate crash/update wake path remains pending
   hardware qualification unless exercised through a separately approved
   recovery/update procedure; the focused host test covers its command order.
9. Stop transport, release notes, restore the original menu values and allow
   two seconds for stopped settings saves. Restart normally and verify the
   display/backlight are readable at the same brightness. If the experimental
   backlight control did not work or this candidate will not be retained,
   reinstall the previous verified package. Report artifact/commit, FM-1 unit,
   host/MIDI setup, baseline comparison, timer and wake observations, repeated
   cycle count, and every pending scenario in the experimental PR or #546.

No agent has flashed a device or observed a real backlight change for this probe.
