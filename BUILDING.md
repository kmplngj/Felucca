# Building Felucca

Pull requests and `main` run the [firmware CI checks](.github/CI.md). That guide also
explains failure diagnostics, dependency pins and tagged/manual release packaging.

The build makes three files in `build/`:

| File | What |
| --- | --- |
| `felucca.bin` | the firmware app |
| `loader/ota.bin` | the update loader |
| `felucca.fwsc` | the installable package (app + loader) |

Development invariants are in [AGENTS.md](AGENTS.md). For repeatable CPU, RAM and
firmware-size comparisons, follow [Measuring and optimizing Felucca](docs/performance.md).

## Prerequisites (macOS)

- Python 3 with Pillow and fontTools: `pip3 install Pillow 'fonttools[woff]'` (the UI font and icons are
  rasterised at build time)
- Docker Desktop. The JieLi toolchain is Linux x86-64 only; the build runs each tool in a
  `linux/amd64` `debian:bookworm-slim` container (Rosetta on Apple silicon). Keep the source
  tree in a folder Docker can share, e.g. under `/Users`.
- The JieLi Linux toolchain (clang 4.0.1 for pi32v2, from JieLi's package server):

  ```
  tools/get_toolchain.sh            # installs to ~/.jieli/toolchain
  ```

- The JieLi AC79 SDK (Apache-2.0). The package uses three of its files
  (`cpu/wl82/tools/uboot.boot`, `cfg_tool.bin`, `cfg/eq_cfg_hw.bin`); they are not part of this tree.

  ```
  git clone --depth 1 --branch AC79NN_SDK_V1.2.1_2023-12-13 \
      https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK.git ~/fw-AC79_AIoT_SDK
  ```

- Node.js (optional, for the web tests).
- Emscripten (optional, `emcc`: the browser emulator, `web/emu/`).

On Linux x86-64 the toolchain runs natively and Docker is not needed.

## Build

```
./build.sh
```

`JIELI_TOOLCHAIN` and `AC79_SDK` override the default locations
(`~/.jieli/toolchain`, `~/fw-AC79_AIoT_SDK`).

Choose the firmware UI font with `FELUCCA_FONT`. The choice is compiled into the
firmware:

| Value | UI font |
| --- | --- |
| `inter-tight` | Inter Tight |
| `tamzen` | Tamzen regular 6×12 / 8×16 pixel faces |
| `m8stealth` | Trash80 M8Stealth57 / M8Stealth89 pixel faces, the default |

```sh
FELUCCA_FONT=inter-tight ./build.sh
FELUCCA_FONT=tamzen ./build.sh
FELUCCA_FONT=m8stealth ./build.sh
```

Plain `./build.sh` selects M8Stealth when `FELUCCA_FONT` is unset. The pixel fonts
save about 39 KB of firmware flash and use 1,032 B less POOL RAM for Huffman
decode caches than Inter Tight; other RAM regions are unchanged. Tamzen stores
6×12 and 8×16 pixel faces as 1-bit glyphs; large readouts share the 8×16 data at 2×.
The line boxes and baselines keep the existing layout metrics, while the visible
capital heights change. Rebuild after choosing a variant, then run
`tests/run_tests.sh`; host tests and the browser emulator use the generated font
header from that build. Real FM-1 readability and redraw behavior still need
comparison.
M8Stealth uses Trash80's native 5×7 and 8×9 faces, with 6/9 px advances and shared
M ink at 2× for L, with 17 px large advances to fit three-digit card readouts.
Its WOFF2 inputs require Brotli (`fonttools[woff]`); the WOFF2
container is decoded only during asset generation. The ten extra Felucca marks
are explicit local bitmap adaptations. All font variants retain Inter Tight keycaps.
Measurements and validation are recorded in [the font experiment](docs/font-experiment.md).

`./build.sh --release 1.0` makes a release build: the package identity becomes `FM-1_910`
and the version string `v1.0`; the package is `build/felucca-1.0.fwsc`, and
`build/release-1.0/` holds what a release ships: the package, the app
(`felucca-1.0-app.bin`), `SHA256SUMS`, the sample attribution, `LICENSE`, `LICENSING.md` and
`LICENSES/` (the package contains Apache-2.0 SDK files, so the licence texts travel with it).

### Build product identity (forks)

`--product FM-1_XXX` sets the package identity explicitly, independent of the display version:
`./build.sh --release 1.0 --product FM-1_ACME` builds version `v1.0` with identity `FM-1_ACME`.
The one resolved value is the target `FELUCCA_ID` define, the package marker, the build summary
and (with `--release`) `BUILD-INPUTS.txt` in the release folder. Precedence: `--product`, then the
identity derived from `--release` (`FM-1_9XY`), then the development default `FM-1_900`. Without
`--product` nothing changes: same defines, outputs and file names.

The value is checked before anything is generated, compiled or written: `FM-1_` followed by 1 to 15
of `A-Z 0-9 . _ -` (ASCII upper case only, 20 characters at most, as the package marker allows; upper
case so that no two products share a file name on a case-insensitive file system); empty, lower-case,
overlong, non-ASCII, control, space, quote, backslash and newline values are refused, as is
`FM-1_015` (the stock firmware's identity, from which the loader's USB identity is derived). The
loader keeps its own identity `ota-FM-1_900` whatever the app uses. An explicit product that differs
from the default is part of the output names (`felucca-1.0-FM-1_ACME.fwsc`, `release-1.0-FM-1_ACME/`),
so two products at one version do not overwrite each other.

A fork should pick a reviewed identity, record it with its releases and not reuse another
project's. A syntactically valid product is not a registration: it does not mean the FM-1 hosts,
installers or any Hub will accept, list or update it.

Build options (environment, `0` or `1`; defaults in `firmware/src/felucca.c`, `core.h` and `icons.c`):

| Flag | Default | |
| --- | --- | --- |
| `FELUCCA_FLASH` | 1 | settings, presets and projects in flash |
| `FELUCCA_OTA` | 1 | update entry (needs `FELUCCA_FLASH`) |
| `FELUCCA_CDC` | 1 | USB serial console |
| `FELUCCA_CDC_DEFAULT` | 1 | `0`: the console is built in but left out of USB from boot (as MENU > USB SERIAL OFF) |
| `FELUCCA_UAC` | 1 | USB audio input (the master output, stereo, 44.1 or 48 kHz) |
| `FELUCCA_UAC_48K` | 1 | `0`: the USB audio input at 44.1 kHz only, as up to 1.0.5.2 (`firmware/src/usb.c`) |
| `FELUCCA_UAC_AS_FIRST` | 1 | the audio control header lists the audio streaming interface before the MIDI one, so the USB audio driver of older macOS (up to 15) finds it; `0`: 1.0 to 1.5's order, byte for byte (`firmware/src/usb.c`) |
| `FELUCCA_UART` | 1 | TRS MIDI IN |
| `FELUCCA_SLICE` | 1 | the SLICE engine |
| `FELUCCA_ICONS` | 1 | parameter icons on the knob cards |
| `FELUCCA_FM4` | 0 | the retired DIGITAL engine (4-operator FM) instead of its FM6 conversion |

`FELUCCA_USB_LAYOUT` (`0` to `3`, default `0`) picks other USB descriptor layouts for testing; see
`firmware/src/usb.c`.

## Samples

The CC0 instrument samples that the SAMPLE engine uses are in `assets/samples-cc0/`
(Versilian Studios, see `ATTRIBUTION.txt` there). `tools/fetch_cc0.py` downloads them
again from the source repositories. Without that folder the build still works, with no
instrument sets in the SAMPLE engine and no PIANO in SLICE (the PIANO set's middle C): they play a plain sine
at the note's pitch instead, and the screen says NO SAMPLE.

## Browser emulator

```
./build.sh
sh web/emu/build.sh
python3 -m http.server -d build/emu 8790     # open http://localhost:8790/
```

`web/emu/felucca_web.c` builds the firmware's sources as the host tests do, against a simulated FM-1, and
Emscripten compiles it to WebAssembly (`build/emu/felucca.wasm`, with `index.html`, `worklet.js` and the font in `fonts/`). The page
keeps the flash's storage sectors (projects, user presets, settings) in the browser. Not emulated: USB (audio,
MIDI out, the editor, updates), TRS MIDI and the user sample slots. A build of it is on the site:
<https://hugelton.github.io/Felucca/webapp/try/>.

## Tests

```
tests/run_tests.sh
```

Runs the host tests and, with Node.js, the web page tests (and, with Emscripten too, the browser emulator's). Run it after `./build.sh`
(it uses `build/` and needs `AC79_SDK` set as for the build). The suites cover flash storage,
user presets, projects of every format, backup, the keys and knobs, MIDI (USB, TRS, clock,
control), USB audio, the update entry and loader, the command-line installer, the UI (the real
drawing code against stubs: every screen in every palette is rendered and checked for clipped or
overlapping text; PNGs land in `build/ui_new/`), every engine (DRUM, NOISE, PHYS, FM6, SLICE, the
DIGITAL conversion), the chord keys, the modulation matrix, the FX layer, the reverbs, the SLICER
and swing. With `DAISYSP` pointing at a DaisySP checkout, the PHYS models are also compared with
their floating-point originals; without it that test is skipped.

With Pillow, the real UI renders also include `manifest.json` with revision, compiler,
font/generated-asset hashes and render settings. `tests/ui_compare.py BEFORE AFTER`
produces exact pixel counts, bounds and before/after/diff sheets under `build/ui_compare`.
Use `--strict` for an approved baseline gate; report mode returns success after writing
its findings. See [UI comparison](docs/ui-comparison.md) for capture, selections, exit
codes and the separate hardware readability check.

The regression suite (`tests/regress.c`) renders every engine and preset and compares a
hash of each render with `tests/golden.txt`; it also checks levels, voices and the CPU
cost (`tests/cpu_baseline.txt`, `tests/target_budget.txt`). It runs a second time built as
the target is, `-Os -fno-vectorize -fno-slp-vectorize` (no SIMD; `-O2` on Apple silicon
vectorises with NEON and understates engines such as PHYS and WHEEL by up to a third), with
the same goldens and its own `tests/cpu_baseline_os.txt`: the host count closest to the
device, for measuring DSP changes. `tests/target_budget.txt` (from the pi32v2 disassembly,
needs the toolchain) stays the exact, static check. After an intended change of
the sound, `GOLDEN_UPDATE=1 sh tests/run_tests.sh` rewrites the hashes; `BUDGET_UPDATE=1`
does the same for the cost files (all three).
The two host CPU baselines apply to macOS arm64; on Linux the counter is `perf_event_open`
(user-space instructions, needs `perf_event_paranoid` <= 2) and the baselines are
`tests/cpu_baseline_<os>_<arch>_<compiler>_<version>_<build-id>[_os].txt`, skipped with a reason
when absent or when any counter is unavailable. See [docs/performance.md](docs/performance.md).

## Device diagnostics

For repeatable read-only CDC diagnostics captures, see [Collecting device diagnostics](docs/diagnostics.md).
The client needs Python 3 on macOS/Linux and an explicitly selected serial port; it does not install firmware.

## Install

Use the web installer in Chrome or Edge:
<https://hugelton.github.io/Felucca/webapp/installer/>. It installs the released package.

From the command line (needs `pip3 install mido python-rtmidi`):

```
python3 tools/fm1_install.py build/felucca.fwsc
python3 tools/fm1_install.py --info          # identity of the connected FM-1
```

Or, to install your own build from the web installer, make a local copy of the site and open it from `localhost`
(Web MIDI needs a secure context):

```
python3 web/make_site.py build/felucca.fwsc dev /tmp/felucca-site
cd /tmp/felucca-site && python3 -m http.server 8000
# open http://localhost:8000/webapp/installer/
```

Installing firmware is at your own risk. If an install fails and the FM-1 no longer
starts, recovery needs [FM-1-transporter](https://github.com/kurogedelic/FM-1-transporter).

### Package validation and file errors

When given a package, the command-line installer validates its identity, UFW structure,
file extents, sizes, CRCs and loader headers before opening MIDI ports or sending update
data. A damaged or unsupported file is a local package error (exit code 2): obtain an
intact copy of the intended package, or rebuild it with the supported toolchain and SDK
from [Build](#build). See the [download and checksum guide](.github/CI.md#downloads-and-checksums)
for release files. Package acceptance alone does not establish compatibility with your
FM-1 or a successful installation; the installer still checks the device and final identity.

`--force` only overrides the requirement for the Felucca loader marker. Package structure
and CRC checks still apply. The exact unmodified official V15 file is accepted through its
pinned SHA-256 digest without `--force`; this exception does not cover arbitrary vendor files.

Device discovery and connection errors occur later: exit code 3 means the FM-1 was not
found (check the USB data cable and other apps using MIDI), 4 means the connection was lost
or the device stopped, 5 means a timeout, and 6 means a model or installed-identity mismatch.
Run `python3 tools/fm1_install.py --help` for the options and complete exit-code list.

If package generation reports `app area is ... B, available ... B`, the app region plus
the SDK configuration files and headers exceeds the flash boundary. The app fitting its
own slot is not enough: use the supported SDK files and review the reported sizes under
[Measuring and optimizing Felucca](docs/performance.md). Keep the package guard enabled.
