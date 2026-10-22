<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM-1 rendered-screen capture

The opt-in `FELUCCA_SCREEN_CAPTURE=1` diagnostic build supports host-pulled
screenshots of **awake, stopped, static MENU views** over USB SERIAL. The normal
build defaults to `0`, reports capture disabled, and allocates no capture band.
The pilot does not provide MIDI capture or remote panel navigation.

The PNG contains the RGB565 pixels submitted by the firmware to the LCD. It is
not an optical readback: wrong controller colour interpretation, physical panel
faults and backlight glow can remain invisible in an otherwise correct PNG.
Use a camera or an explicit physical observation for those checks.

## Build and capture

Use the [build prerequisites](../BUILDING.md#build), the normal standard profile
and a clean, retained source revision:

```sh
FELUCCA_SCREEN_CAPTURE=1 uv run --locked --group build ./build.sh
```

The existing target resource guards remain enabled. This development-only flag
is rejected with `--release`. Install the exact reviewed `.fwsc` with the
[trusted installer](../BUILDING.md#install), retaining the package SHA256 and
source/build provenance. Installation is separate from the screenshot command.

On the connected FM-1, stop playback and release every control. Hold HOME for
more than 0.7 seconds, then release. Turn ALGORITHM to SYSTEM, PRESETS to USB
SERIAL and set it ON if needed; close MENU with HOME to apply USB enumeration.
Record its previous value. Open MENU again and select DISPLAY with ALGORITHM.
Leave the menu open, with no key/button held. SYSTEM INFO and dynamic HOME views
are outside the initial capture scope.

Identify the FM-1's CDC tty explicitly; the CLI does not discover or choose one.
Close other serial clients first. From the same checkout:

```sh
python3 tools/fm1_screenshot.py --port /dev/cu.usbmodem1234 \
  --expect-commit FULL_40_CHARACTER_COMMIT
```

Success prints the path to a new `build/screenshots/.../screen.png` and saves
`screen.json` beside it. Metadata records device-reported full commit, dirty
state, source, capture token, menu/page, RGB format, draw-stream fingerprint,
image CRC/SHA256 and acquisition timestamps. A dirty build's commit alone does
not identify its changed source bytes. Keep its matching source diff separately.

The default command timeout is 2 seconds and overall deadline 110 seconds,
below the firmware's fixed 120-second session lifetime. `--output` selects a
new directory inside this checkout's ignored `build/`; existing results are
never overwritten. PNG/JSON are published only after complete verification and
closing the tty. Unsupported/asleep/changed/incomplete/CRC/transport failures
exit nonzero without publishing a partial screenshot.

Do not touch the panel or change settings during acquisition. The command does
not wake the screen, change navigation/settings, stop playback or refresh the
inactivity timer. If the display is asleep, wake it physically and retry. Restore
USB SERIAL and any intentionally changed test settings afterwards.

## Bounded capture contract

The implementation copies only one owned 240×8 RGB565 band (3,840 bytes), with
coverage and session state. It taps actual fill/blit submissions before source
reuse and drains the last LCD DMA before declaring the band ready. The host pulls
at most 96 bytes per READ, verifies chunk CRC32 and assembles all 30 bands.

Each band requests an ordinary complete menu redraw. Every pixel in the band
must be covered. The ordered draw-stream fingerprint must match the first
band; input activity, sleep, unsupported scenes, missing coverage or a changed
draw stream abort acquisition. Identical final pixels can have different draw
streams and be conservatively rejected. **The draw fingerprint is not an image
CRC.** The host computes the final image checksum only after completing capture.

Capture runs in the main loop, without heap allocation, flash writes or ISR
capture work. CDC replies reserve ring space and defer input when the host is
slow, rather than waiting for a full-frame transfer. An abandoned host holds
only the bounded band until expiry; audio/input services continue.

See [the CDC protocol](../web/EDITOR_PROTOCOL.md#debug-screen-capture-cdc) for
the versioned command grammar. Existing MIDI command IDs are unchanged.

## Device acceptance procedure

Keep author results separate from checks not yet performed on a real FM-1.

1. Record the exact diagnostic revision, `FELUCCA_SCREEN_CAPTURE=1`, profile/font,
   package checksum, host OS/tty and preflash backup. Begin on stopped HOME;
   open DISPLAY MENU using the route above. Capture with `--expect-commit` and
   require a complete PNG/JSON, matching device commit and readable native menu.
2. Select COLOR with PRESETS; record its original value. Capture MONO, GREEN,
   PAPER and CUSTOM separately, changing each value before starting acquisition.
   Compare intended pixels with the matching renderer/browser reference; compare
   the physical LCD separately. Restore the original COLOR.
3. Select AUTO OFF with PRESETS and open with OCT+. Capture IDLE AFTER / IDLE
   MODE / ALL DARK / WAKE / BACK, including LARGE if relevant. A panel turn during
   a capture must produce a changed-scene failure, with no partial published PNG.
4. Close MENU with HOME and retry: unsupported HOME must fail without navigating.
   Repeat with playback active: capture must not stop transport. For an asleep
   display, the command must fail without waking it. Restore the starting state.
5. Disconnect/stop reading during acquisition and verify normal controls/audio
   remain responsive; allow the session to expire, then retry from an eligible
   menu. Check diagnostic deltas for new audio lateness, shedding and USB errors
   under the same defined workload, with capture disabled and enabled.
6. Restore COLOR, USB SERIAL, project and idle/wake settings. Read settings back
   through MIDI and compare saved objects with the pre-test backup. Report only
   observed device scenarios; screenshots do not qualify physical LED brightness,
   controller colours, panel gestures or backlight-off.
