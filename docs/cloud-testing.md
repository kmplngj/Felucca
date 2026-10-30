<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Cloud browser testing

The short Chromium smoke test exercises this checkout's emulator page and its
real Wasm/AudioWorklet output. It needs no FM-1, target toolchain, SDK, API key or
model call. Existing DSP goldens, native/Wasm comparisons and interaction replay
remain the detailed regression checks; this adds the actual browser path.

## Run locally or in a cloud workspace

Install uv, Clang, Node 22 and
Emscripten 6.0.11 as described in [CI dependencies](../.github/CI.md#dependencies-and-provenance).
The locked `build` group supplies the Python dependencies automatically. Then,
from the repository root:

```sh
npm ci --prefix web/emu --ignore-scripts --no-audit --no-fund
npm exec --prefix web/emu -- playwright install --with-deps --only-shell chromium
uv run --locked --group build tools/ci.py emulator-tests
npm test --prefix web/emu
```

The Emscripten environment must be active. `emulator-tests` regenerates assets
and rebuilds the current native/Wasm peers, without building target firmware.
After a page-only edit, run `sh web/emu/build.sh` to refresh the served page.
The browser runner rejects stale generated build identity/profile inputs.
On a cloud image with Chromium and its system dependencies already installed,
skip the Playwright browser download and set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium` for the test instead.
`--with-deps` requires a machine where system package installation is available.

The runner serves only `build/emu/` on an ephemeral loopback port, opens an
isolated browser context, then closes the browser and server. It tests:

- Switch on, running AudioContext at 44.1 kHz and a nonblank LCD.
- A computer-keyboard note producing finite, nonzero PCM on both stereo channels,
  followed by a quiet release.
- Focused piano keys played with Enter, Space and numpad Enter: pressed-state
  accessibility, held repeats, simultaneous activation keys and release on blur,
  with actual sound and no unwanted scrolling.
- Physical SEL/SELECT legends, pointer navigation through SEL to ENV, and a
  keyboard encoder edit changing the LCD.
- GRAPH TURN (#572): turning KNOB 1 on HOME replaces the flat scope with the filter
  curve, and the same scope returns after the curve's hold.
- Keyboard hints and footer text meeting 4.5:1 contrast in desktop and portrait
  layouts, including text opacity, without horizontal page overflow.
- A playable key in the portrait layout.
- Panel save reaching localStorage, saved sectors reaching the restarted worklet,
  and loading USER slot 1 restoring the edited attack's exact envelope graph.
- Native MIDI layers through a virtual Web MIDI input and the page's normal handler:
  two distinct sounds, stereo PCM, independent LVL edits, shared CC7, sustain,
  held-note channel removal, rejoining and velocity-zero release. Setup uses real
  panel controls; read-only worklet observations confirm routing and note ownership.
  Channel-isolation checks allow the existing MIDI PAN=63 opposite-side leakage.
- MIDI performance controls through the same input and PCM path: sound NRPNs,
  pair-mix endpoints and midpoint, key and raw-velocity zones, soft pedal,
  overlapping mono/legato notes and glide state, held-note tuning frequency,
  panel-saved user-bank recall, and project-load session reset. Observations
  include actual track state and PCM; physical transports and deadlines remain
  separate device checks.
- Browser, network, console and AudioWorklet errors.

The test-only probe observes the existing worklet's messages and taps its actual
audio through a separate AudioWorklet. It does not replace firmware rendering or
add a remote-control API to the shipped page. Browser scheduling is asynchronous:
the checks use bounded waits and signal thresholds, not exact PCM hashes or
device timing claims. They do not assess whether a sound is musically desirable.
LCD checks cover nonblank output and changes, not every label or layout defect;
the existing renderer comparisons remain complementary.

## Keep agent context small

The command prints one result line and exits nonzero on failure. Each run writes
`build/browser/run-*/summary.json` with named checks, observations, browser version,
build identity and hashes of the served Wasm, page and worklet. Read that summary
first; open only evidence relevant to the failing check. A successful run retains
no media. There are no model calls, video streams, continuous screenshot uploads,
automatic retries, baseline rewrites or full console dumps.

On failure, the runner saves available LCD snapshots, a page screenshot and up
to eight seconds of stereo PCM as `audio.wav`. To retain these on success too:

```sh
npm test --prefix web/emu -- --artifacts=always
```

The WAV is a clipped PCM16 diagnostic export; signal validation uses the original
float PCM. Consult reported errors for non-finite/out-of-range output. Early setup
failures may have no media. Captures and dependencies are ignored by Git.

## GitHub Actions

The existing workflow runs this gate for emulator-only changes and in full
validation, including manual runs and releases. Changes under `web/emu/`, including
the test and dependency lockfile, use the focused emulator job. Documentation-only
changes keep their existing build skip. Full validation runs the browser gate
once, without an additional focused job.

Playwright and its browser revision are pinned by `web/emu/package-lock.json`.
Each run adds one line to the Actions summary. The existing diagnostic artifacts
include `build/browser/` for 14 days, with media only for failed checks by default.
The workflow does not publish the emulator or flash any device. The independently
maintained Felucca-WebApp editor/installer is outside this checkout's browser gate.
Physical FM-1 panel, display, codec/speaker, USB transport and deadlines remain
separate [device checks](stress-device.md).
