# Building Felucca

Pull requests and `main` select the [CI checks](.github/CI.md#change-based-validation)
affected by their complete change range. Firmware/build inputs run the full suite;
known independent Python, backup and emulator inputs use focused checks, and
documentation-only changes skip builds. Manual CI defaults to full validation;
an explicit target-only mode is available for exact PR hardware-test builds.
Releases always validate everything. That guide also explains failure diagnostics, dependency pins and
tagged/manual release packaging.

For engine, effect and platform changes, read the
[native extension contracts](docs/extending.md) before adding hooks or buffers.

The build makes three files in `build/`:

| File | What |
| --- | --- |
| `felucca.bin` | the firmware app |
| `loader/ota.bin` | the update loader |
| `felucca.fwsc` | the installable package (app + loader) |

Development invariants are in [AGENTS.md](AGENTS.md). For repeatable CPU, RAM and
firmware-size comparisons, follow [Measuring and optimizing Felucca](docs/performance.md).

## Get the source

Five engines are in a git submodule (`firmware/engines/`, [Felucca-Engines](https://github.com/hugelton/Felucca-Engines),
MIT), so clone with `--recurse-submodules`:

```
git clone --recurse-submodules https://github.com/kmplngj/Felucca.git
```

In a clone made without it, run `git submodule update --init` once. Alternatively,
use the complete `felucca-VERSION-source.tar.gz` asset from this fork's
[Releases](https://github.com/kmplngj/Felucca/releases), with its matching `.sha256`
sidecar. It includes the exact pinned Engines sources, fonts, samples, generators,
profile definitions, tests and license texts. GitHub's automatic "Source code"
ZIP/tar downloads and "Download ZIP" still leave `firmware/engines/` empty.

For example, after downloading both source assets for `1.6-rc1`:

```sh
sha256sum -c felucca-1.6-rc1-source.tar.gz.sha256  # macOS: shasum -a 256 -c ...
tar -xzf felucca-1.6-rc1-source.tar.gz
cd felucca-1.6-rc1-source
python3 tools/source_archive.py verify .
# Keep uv dependencies outside this verified source tree:
export UV_PROJECT_ENVIRONMENT="$HOME/.cache/felucca-source-venv"
uv run --locked --group build ./build.sh --release 1.6-rc1
```

Install the prerequisites below before building. The extracted source needs no
Git checkout or submodule download; the JieLi toolchain and three SDK files remain
external prerequisites. `SOURCE-PINS.json` records the firmware and Engines commits
and hashes/modes of every source file. The build verifies those files and rejects
additional source inputs before compilation. Generated files under `build/` and
`firmware/engines/build/` are permitted. Python bytecode (`.pyc`/`.pyo`) and source-tree
symlinks are rejected, including in generated directories. Extracted-source tools
verify the source before importing repository helpers and disable bytecode writes
for themselves and child generators, so repeated builds preserve the verified
tree. If an older build left bytecode caches, use a fresh extraction. A symlink
above the source directory, such as a linked workspace folder, is allowed. To
develop modifications, use a recursive Git clone; an extracted
release intentionally rejects modified source while its pin manifest is present.

Maintainers can export any clean committed checkout, without building firmware:

```sh
python3 tools/source_archive.py export 1.6-rc1
python3 tools/source_archive.py verify build/felucca-1.6-rc1-source.tar.gz
```

The exporter refuses missing, wrong or dirty Engines pins and modified tracked
firmware files. Untracked firmware files, ignored build output and Git metadata
are excluded. It preserves committed executable bits, orders all members, and
normalizes tar/gzip ownership and times to the firmware commit timestamp.
Release CI generates this source asset and sidecar, records both archive and pin
manifest SHA-256 in build provenance, reproduces it from a second checkout, and
builds the unpacked sources to compare the installable package byte for byte.

The firmware explicitly requires portable Engine API revision 1. A missing or incompatible
revision stops compilation with a contract diagnostic rather than silently accepting changed
shared types. Update the engine pin and host requirement together after reviewing the portable
contract; run `python3 tests/engine_contract_test.py` and the Engines standalone tests.

## Prerequisites (macOS)

- [uv](https://docs.astral.sh/uv/) and Python 3 (the UI font and icons are rasterised
  at build time). On macOS, install uv with `brew install uv`. The locked `build`
  dependency group provides Pillow, fontTools and Brotli.
- Docker Desktop. The JieLi toolchain is Linux x86-64 only; target builds use a
  `linux/amd64` `debian:bookworm-slim` container using Docker's x86 emulation on Apple silicon.
  Rosetta is optional and is not required for a successful build. Keep the source
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

A target-builder invocation owns one lazily started container: loader/app workers and
resource-report tool calls share it, with the toolchain mounted read-only. It is removed
on success, build failure, SIGINT or SIGTERM. Lifecycle Docker clients run in separate
sessions so terminal interrupts reach the Python owner, which waits for an in-flight
startup response before removing its container. No container or compiled-output cache is
reused across builds. Independent builds have different container identities. Linux-native
execution is unchanged. Standalone imported tool calls, including resource-report CLI
verification, continue to use temporary one-shot containers. A target builder called
outside Python's main thread also uses the one-shot path, because it cannot install
process signal handlers for persistent-container cleanup.

Before reuse, the builder inspects the selected `linux/amd64` image configuration.
It starts an advertised immutable repository digest when available, or the image ID
for older image stores. A manifest/index without a usable repository digest uses
the one-shot path rather than assuming its selected manifest ID is runnable.
Custom images with an `ENTRYPOINT`, or images whose selected configuration cannot be
verified, use the existing one-shot path with a visible note. The default image must
support `sleep infinity` and direct tool execution. Docker-compatible Podman clients may
use plain image inspection only when it proves the same Linux/amd64 configuration.
No TTY or shell wraps compiler arguments. Cleanup cannot be guaranteed after SIGKILL,
a host crash or loss of the container engine; a cleanup failure reports the exact owned
container name/ID and never removes another build's container. Do not treat that failure
as a clean successful lifecycle. This changes build overhead, not firmware arithmetic,
compiler flags or audio CPU use.

Install uv using its [installation instructions](https://docs.astral.sh/uv/getting-started/installation/).

### Python environments

Run dependency-using commands from the repository root with `uv run --locked` and
an explicit group: `build` for asset generation, firmware builds and image-dependent
host/emulator tests; `midi` for USB-MIDI installation and PR hardware handoff.
`uv run` automatically creates/synchronizes the project environment (`.venv` by
default) from `pyproject.toml` and `uv.lock` before starting the command. No shell
activation or manual pip installation is required. There are no default dependency
groups; add both `--group build --group midi` when a command needs both.
`.python-version` selects Python 3.12; uv downloads a managed interpreter if a
suitable local Python is unavailable.

Direct `python3` and shell entry points remain supported when the necessary
packages are already available in their interpreter. Their dependency checks
report the uv command to run; they do not install packages themselves. On Windows,
generated retry commands explicitly target PowerShell. Standard library tools
such as source-archive verification, diagnostics and package checks
continue to work with plain `python3`.

For a verified source archive, keep the uv environment **outside the extracted
tree**: its source verifier rejects extra inputs and symlinks, including `.venv`.
Set an absolute external path before any uv command, for example:

```sh
export UV_PROJECT_ENVIRONMENT="$HOME/.cache/felucca-source-venv"
```

Use a fresh extraction if an environment was already created inside it. A normal
Git clone can use uv's default `.venv`.

## Build

```
uv run --locked --group build ./build.sh
```

`JIELI_TOOLCHAIN` and `AC79_SDK` override the default locations
(`~/.jieli/toolchain`, `~/fw-AC79_AIoT_SDK`).

### Final-image soft-double policy

Every target application build checks the final linked ELF symbol table against
26 exact double-precision helper names exported by the generic JieLi Clang 4.0.1
compiler runtime (`SOFT_DOUBLE_HELPERS` in `tools/build.py`). The check covers double
arithmetic/comparisons, fp32/double and double/half conversions, signed/unsigned
32/64-bit integer/double conversions, and complex-double multiply/divide. A helper
defined in an allocated `CODE` output section fails the build, including local,
weak and zero-sized aliases. The diagnostic lists the names: inspect the expressions
that introduced them and use intentional fp32/fixed-point operations. There is no
profile or radio exemption and no override flag.

GNU-style section headers must show `ALLOC` and `CODE`. Their attribute lists use
only the reviewed words `CONTENTS`, `ALLOC`, `LOAD`, `READONLY`, `CODE`, `DATA` and
`DEBUGGING`; an unknown word or malformed list cannot establish nonexecution for a
matching helper and fails with a section-evidence diagnostic. The installed JieLi
objdump instead reports `TEXT`/`DATA`; for that format, the detector requires `TEXT`
in one of `app.ld`'s allocated executable outputs (`.text`, `.ram_text`, `.c1_text`).
An unfamiliar `TEXT` output containing a matching helper fails with a section-evidence
diagnostic until its allocation is reviewed.

Undefined, absolute, common, file/section/debug records and symbols in nonallocated
or nonexecutable sections do not establish linked code. Integer-only 64-bit helpers,
fp32 helpers and ordinary names containing `double` remain outside this policy.
Matching helper rows with malformed symbol/section evidence fail the check rather
than establishing absence. A successful check means only that no known helper is
defined in final executable sections; it does not prove hardware FPU use, absence
of every double expression or improved CPU time. New toolchain/ABI spellings need
a reviewed policy and fixture update. See [performance guidance](docs/performance.md#soft-double-link-guard).

Portable coverage is in `python3 tests/build_guard_test.py` (also run with `python3 -O`).
The separate `python3 tests/build_guard_target_test.py` compiles dynamic double
arithmetic/conversions and an fp32 control with the production generic flags. Only
these tiny probes link the installed generic `pi32v2/lib/libcompiler_rt.a` to prove
the final-image detector; the firmware's explicit-object link remains unchanged.
The fixture retains sources, objects, undefined object symbols, final ELF symbols,
section headers, disassembly, link logs and tool/runtime hashes in a fresh directory
under `build/host/build_guard_target/`. It also preserves the existing integer-64
compile/link cases. An absent default toolchain produces an explicit skip; an
explicitly configured missing toolchain, a missing runtime archive or a failed
probe fails the fixture. A skip is not target evidence. No FM-1 execution is needed
to validate this build-only policy.

Native firmware uses M8Stealth only. `FELUCCA_FONT` may be unset or explicitly
`m8stealth`; retired `tamzen` and `inter-tight` values fail before generation.
After updating from an older font build, rebuild assets and firmware before
running host tests or the browser emulator.

Trash80's native 5×7 and 8×9 faces have 6/9 px advances. L/N share M at exact 2× (18 px capitals),
with 17 px focused-value and 18 px full-name advances. Scaled roles add only
glyph metadata and descriptors, without another bitmap set or decode cache.
The WOFF2 inputs require Brotli (`fonttools[woff]`); decoding happens only during
asset generation. Ten extra Felucca marks are explicit local bitmap adaptations.
Keycap/badge legends use native M8Stealth57; their rounded pill edges and icons
retain antialiasing. The [LCD typography guide](docs/lcd-typography.md) describes
roles, fit and the independent source-raster checks. A doubled S would be exact
14 px ink too, but no current task requires another role, so it is not emitted.
Real FM-1 readability and
redraw behavior remain pending. The dated [font experiment](docs/font-experiment.md)
retains the historical comparisons; removing alternate build options does not
itself save bytes in a build that already selected M8Stealth.

`assets/fonts/m8stealth/resource-policy.json` pins the native font inputs, generated
header hash, glyph coverage/metrics and shared payloads. Generation writes
`build/gen/ui-font-manifest.json` and rejects an unreviewed change before writing
the font header. Host/emulator profile freshness checks reject a stale header or
manifest. The approved current pi32v2 array/descriptor bound is **4,630 B**:
1,164 B S/M bitmap payload, 3,176 B glyph records, 110 B extra-code arrays and
180 B descriptors. L/N/X reference M's payload. This excludes inter-object alignment
padding and supersedes the historical 3,340 B S/M/L-only figure for this gate.

For an intentional font change, review the generator/assets and reproduce its output
in an isolated directory. Use `font_resources.inventory(root, header_text)` to inspect
the proposed contract, then review the policy's `expected` and bound changes together.
There is no automatic budget update option. Confirm the target's actual `AF_*`
symbol sizes with JieLi Clang 4.0.1; the policy models 8 B glyph records and 36 B
descriptors with 4 B pointers. A successful target build checks those exact linked
sizes and records separate named keycap, icon, decoder/ramp and cache groups in
the existing resource report. Missing optional groups are marked unlocated, and
inlined code remains in its callers. Whole-image/RAM/POOL/stack accounting stays
in that report; these groups are subsets, not additional allocation.

To check the generator and causal rejection fixtures without hardware:

```sh
mkdir -p build/font-check
uv run --locked --group build python tools/gen_bitmap_font.py build/font-check/ui_fonts.h
python3 tests/bitmap_font_test.py
```

Expected: the approved configuration passes; fixtures reject extra faces, duplicated
scaled payloads, glyph/asset growth, stale inputs/configuration and incorrect linked
sizes. These checks change no runtime bytes or physical readability acceptance.

`uv run --locked --group build ./build.sh --release 1.0` makes a release build:
the package identity becomes `FM-1_910`
and the version string `v1.0`; the package is `build/felucca-1.0.fwsc`, and
`build/release-1.0/` holds what a release ships: the package, the app
(`felucca-1.0-app.bin`), `SHA256SUMS`, the sample attribution, `LICENSE`, `LICENSING.md` and
`LICENSES/` (the package contains Apache-2.0 SDK files, so the licence texts travel with it).

### Build revision and PR identity

Each build resolves its actual checkout into `build/gen/build_identity.h` and
`build/build-identity.json`; the version, eight-character commit, dirty flag and
optional PR label appear in MENU > SYSTEM > ABOUT (panel steps in
[the fork feature guide](docs/fork-features.md#identify-the-installed-build)).
The minimal splash shows one line: the verified PR label first; otherwise the version
only for a clean, identified `--release` build; otherwise the compiled commit or
`unknown`, preserving `-dirty`. A source-default version alone never marks a release.
The full identity remains in ABOUT and JSON. Splash colors follow the saved palette,
and every build keeps the same short automatic startup; any button or note key can
dismiss it after initialization. See [startup behavior](docs/fork-features.md#identify-the-installed-build).
No boot-time identity lookup is involved. CI provenance
includes the same `build_identity` object, and release folders include the JSON sidecar.
MENU > SYSTEM > INFO selects the verified PR label, clean identified release
version, or development commit, and includes a separate compiled-commit row for PRs.
The full revision remains in JSON; a short SHA is a readable identifier, not a checksum.

Clean Git builds use HEAD; tracked changes, untracked nonignored files and changed
submodules add `-dirty`. Commit changes before requesting a reproducible test artifact.
Release builds keep this commit identity while `--release` sets the display version;
package product IDs are independent. No wall-clock timestamp enters the display identity.
Complete verified source archives use `SOURCE-PINS.json`'s firmware revision after
verifying every source input; their app/package bytes match the corresponding clean
release checkout. Other no-Git trees display `unknown` and no PR label. There is no
branch-name inference or unchecked SHA/PR compiler override.

Normal PR CI validates the event, checkout SHA and PR-head parent, displays the actual
compiled merge SHA and labels `PR #N merge`. The exact-PR workflow verifies reachability
before checkout, binds the selected commit and PR number to the build, and labels
`PR #N head`; its SHA is that selected commit (possibly an older reachable PR commit).
Both paths reject dirty sources and malformed PR inputs (positive, at most seven digits).
No-Git archives cannot establish merge parentage and reject PR merge context; official
source reproduction runs in non-PR release context. Local/non-PR builds omit the label.

Metadata regenerates on every target/asset build. Host and emulator profile freshness
checks also reject stale identity after switching commits or clean/dirty state; rebuild
before compiling them. Generated source hashes continue to enforce input freshness.

ABOUT's source repository is also resolved at build time: GitHub Actions builds use
`GITHUB_REPOSITORY`, and local Git builds use the GitHub `origin` remote (HTTPS or
SSH). Forking and cloning your fork therefore updates the displayed owner/repository
without editing firmware. The readable source URL replaces the fixed upstream QR
code; upstream copyright and third-party credits remain. No network lookup or extra
dependency is needed. Complete source archives preserve this repository in
`SOURCE-PINS.json`; older archives, non-Git trees and unsupported/missing remotes show
`Source repository unavailable`. Changing `origin` requires an asset rebuild too.

### Build product identity (forks)

`--product FM-1_XXX` sets the package identity explicitly, independent of the display version:
`uv run --locked --group build ./build.sh --release 1.0 --product FM-1_ACME`
builds version `v1.0` with identity `FM-1_ACME`.
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
| `FELUCCA_CPU2` | 1 | the second core is built in (MENU > SYSTEM > 2ND CORE, OFF by default); `0`: none of it, 1.6's one-core code and RAM (`firmware/hal/fm1_cpu1.h`, `firmware/src/fx.c`) |
| `FELUCCA_UART` | 1 | TRS MIDI IN |
| `FELUCCA_SLICE` | 1 | the SLICE engine; `0` leaves engine id 13 out of the catalog (SLICE sounds in projects, user presets and backups are kept and shown N/A, [#212](web/EDITOR_PROTOCOL.md#engine-ids-212)) |
| `FELUCCA_ICONS` | 1 | parameter icons on the knob cards |
| `FELUCCA_FM4` | 0 | the retired DIGITAL engine (4-operator FM) instead of its FM6 conversion |
| `FELUCCA_ISR_ASSERT` | 0 | development build: count main-loop-only functions called in an interrupt ([diagnostics](docs/diagnostics.md#interrupt-context-assertion-felucca_isr_assert)) |
| `FELUCCA_CRASH_CTX` | 0 | diagnostic build: the crash record keeps r0..r15, usp and ssp (+76 B NOINIT, below the 100 B floor; [diagnostics](docs/diagnostics.md#diagnostic-builds-for-425-felucca_crash_ctx-felucca_mul64_repro)); refused with `--release` |
| `FELUCCA_MUL64_REPRO` | 0 | diagnostic build: the #425 synthetic reproducer runs in the main loop's idle time ([audit, phase 2](docs/mul64-hload-audit.md#phase-2-step-1-synthetic-reproducer-and-device-soak)); refused with `--release` |
| `FELUCCA_SCREEN_CAPTURE` | 0 | diagnostic build: bounded static HOME/menu RGB565 capture over USB SERIAL, exported as PNG/JSON by the [host tool](docs/screen-capture.md); explicit `--wake` silently wakes and holds the view during capture; refused with `--release` |

`FELUCCA_USB_LAYOUT` (`0` to `3`, default `0`) picks other USB descriptor layouts for testing; see
`firmware/src/usb.c`.

## Samples

The CC0 instrument samples that the SAMPLE engine uses are in `assets/samples-cc0/`
(Versilian Studios, see `ATTRIBUTION.txt` there). `tools/fetch_cc0.py` downloads them
again from the source repositories. Without that folder the build still works, with no
instrument sets in the SAMPLE engine and no PIANO in SLICE (the PIANO set's middle C): they play a plain sine
at the note's pitch instead, and the screen says NO SAMPLE.

The generated drum inputs use a private temporary directory per sample-generator
invocation; stale `build/genwav/` files cannot change the header. Headers and their
cache are published atomically for parallel invocations. The canonical WAV files
remain under `build/genwav/` for the SLICE test loop.

## Browser emulator

```
uv run --locked --group build ./build.sh
sh web/emu/build.sh
python3 -m http.server -d build/emu 8790     # open http://localhost:8790/
```

`web/emu/felucca_web.c` builds the firmware's sources as the host tests do, against a simulated FM-1, and
Emscripten compiles it to WebAssembly (`build/emu/felucca.wasm`, with `index.html`, `worklet.js` and the font in `fonts/`). The page
keeps the flash's storage sectors (projects, user presets, settings) in the browser. Not emulated: USB (audio,
MIDI out, the editor, updates), TRS MIDI and the user sample slots. A build of it is on the site:
<https://kmplngj.github.io/Felucca/webapp/try/>. The fork site follows successful
full builds of `main`; check its [source revisions](https://kmplngj.github.io/Felucca/sources.html)
before comparing it with a local build.

## Tests

For the short real-Chromium UI/audio gate and compact reports, see
[Cloud browser testing](docs/cloud-testing.md). It complements the native/Wasm
checks below and needs Playwright's pinned browser, without an FM-1 or target SDK.

For timestamped panel/MIDI replay with synchronized PCM24 WAV, LCD PPM frames and
provenance, see [Interaction replay](docs/interaction-replay.md). After the asset
build, run `python3 tools/fm1_replay.py tests/scenarios/interaction.json --out build/replay/example`.
This uses the native browser-emulator integration on Linux/macOS and needs no hardware.

```
uv run --locked --group build tests/run_tests.sh
```

In upstream GitHub Actions (`kmplngj/Felucca`), the `profiles` unit also runs
`tests/native_bundle_integration.py`:
two isolated real target builds (Git control and verified Git-free source), followed
by native bundle creation/verification and independent stable-key metadata checks.
It uses `build.sh` and its normal toolchain/SDK defaults; the original CI build and runtime stay untouched.
Local `profiles` remains a host-only check. To run the native proof explicitly after
a fresh matching target build in a clean committed checkout, use
`uv run --locked --group build python tests/native_bundle_integration.py`.
Stale reports or missing build prerequisites fail.
Logs and the actual bundle are retained under `build/ci/native-bundle/run-*/`.
The controlled pair uses commit identity without the CI PR display label; it does
not claim byte equality with the outer PR-labelled firmware or device acceptance.

The optional [offline level audit](docs/loudness-audit.md) uses the `audit`
dependency group and an isolated native host renderer. Its focused checks run with
`uv run --locked --group audit python tests/loudness_audit_test.py` and in the
separate **Host loudness audit** workflow; they need no target SDK or device.
The audit retains source,
compiler, sample-rate and capture provenance alongside its measurements and
bounded audition files. Host levels do not qualify physical DAC/USB levels or
authorize changing factory sounds.

The `input` unit also runs `python3 tests/input_contract_test.py`. It compiles
the actual hardware, UI-test, settings-test and browser input adapters against the
shared button-edge, note-edge and encoder function types they implement. Negative
fixtures require incompatible signatures across the UI, settings and browser
adapters to fail compilation. The UI fake supplies press edges only; this check
does not add release simulation or qualify physical input timing.

The native UI tests and their consumers share `tests/ui_harness.h`: the real
firmware UI/sound sources, input/clock fakes, RGB565 screen, delayed LCD DMA and
blank-frame observers, power-on setup and panel/keyboard helpers. Define any
consumer-specific IRQ, boot or drawing hooks before including it. The UI scenario
entry point stays in `tests/ui_test.c` and alone enables `UI_HARNESS_BLIT_TRACE`
for its LCD-submission ordering assertions. Consumers include the harness directly;
they do not compile the UI scenario body or use `UI_TEST_NO_MAIN`.

The backup and FM6-bank tests share `tests/host_nor.h`, including their sanitizer
builds. This existing NOR model only clears programmed bits, rejects 256-byte page
wrapping, and models sticky power cuts during programming or half an erase. Its
program counter counts completed bytes; its erase counter excludes requests
refused before work. Reads remain available for recovery after a cut. Storage and
persistence tests retain their different retry and operation-counting models.

Independent compile-and-test units run concurrently, using up to four workers by
default (fewer on a host with fewer CPUs). Set
`TEST_JOBS=1 uv run --locked --group build tests/run_tests.sh` for
serial debugging or a timing comparison; `TEST_JOBS=2` through `32` select an
explicit limit. With multiple units, each regression harness defaults to one
render child; an explicit `JOBS` overrides that inner limit. `GOLDEN_UPDATE` or
`BUDGET_UPDATE` forces serial execution because those modes write shared baselines.
The legacy shared-output overrides `UI_SCREEN_DIR`, `MENU_JSON` and `TRACKS` also
select serial execution. Presence counts, including an empty environment value.

Each run prints its unique `build/host/test-run-*/` directory. It contains one log
per unit and `summary.json` with start offsets, elapsed seconds, exit statuses and
dependencies. The combined transcript stays in script order. Failed prerequisites
block their consumers; independent checks still finish and any failure makes the
suite fail. Interrupting the runner terminates its worker process groups. Run
simultaneous full suites in separate worktrees: a checkout lock protects shared
generated outputs. Generate assets before starting a suite, and leave sources,
assets and build flags unchanged while it runs.

For development feedback, select named units and their prerequisite closure:

```sh
uv run --locked --group build python tests/test_jobs.py tests/run_tests.sh --preflight --select ui,ui_render --ai-output
```

This writes an explicitly focused report. It cannot satisfy strict full-suite
verification. Unknown units fail instead of silently reducing coverage.

Keep development PRs in draft: known source changes and matching test entry points
use focused CI plus fresh target/resource/package guards. Shared or unknown inputs
still select complete validation. A full local suite is not required just to open
a draft or after every edit. Mark the frozen candidate ready for review to run its
complete applicable CI plan before merge. Successful matching CI can supply final
validation evidence without an identical local full-suite rerun; refresh checks
after code changes or failures. See [the stage policy](.github/CI.md#feedback-and-merge-stages).
Exact selector/helper-contract-only changes need the unconditional workflow/helper
checks and skip firmware/audio/browser builds, even when ready or pushed to `main`.
Workflow YAML and shared scheduler/coverage implementations retain full validation.

CI runs the complete unit plan across two independent runners. Each uses
`tests/test_jobs.py tests/run_tests.sh --preflight --shard 1/2 --cohort ID`
(the other uses `2/2`), a fresh individual coverage ID and matching source,
generated inputs, compilers, profile and flags. Dependency-connected units stay
on the same runner; every unit has exactly one owner. The final required check
verifies both complete receipt directories with
`tools/test_coverage.py verify-shards --cohort ID RECEIPT1 RECEIPT2`.
Missing or duplicate units/shards, changed inputs, incomplete children and altered
logs or outputs fail the aggregate. Ordinary full verification rejects individual
shards. These controls preserve the existing full plan; they do not qualify FM-1
timing or physical behavior. See [CI stages and receipts](.github/CI.md#feedback-and-merge-stages).

For AI-assisted runs or a short console report, use:

```sh
uv run --locked --group build tests/run_tests.sh --ai-output
```

This runs the same preflight, plan and test units with the same failure exit codes.
Successful units omit their transcript; failed, blocked or cancelled units print
their status, log path and a bounded diagnostic excerpt. Warning/skip line hints
include counts and up to three samples per log. The final line reports unit totals,
diagnostic line counts and the summary path. These counts describe units and matching
log lines, not individual test cases or a complete warning/skip inventory: hints use
text patterns, and unfamiliar formats require reading the original log. A passed unit
can contain skipped checks. The compact mode changes presentation, not coverage.

The complete per-unit logs remain unchanged. Compact runs also retain `preflight.log`,
`plan.stdout.log` and `plan.stderr.log`; planning logs are retained in normal runs too.
Failed compact planning also creates `plan.failure.log` for an excerpt of both streams,
so a reason written to stdout remains visible.
`summary.json` adds `output_mode`, `unit_counts` and, in compact mode, `diagnostic_counts`
plus per-log `diagnostics`, bounded failure `excerpt` fields and their limitation flags.
Preflight/plan failures and cancellation remain failures even when no unit started.
Read the summary and relevant raw logs to investigate; do not equate a short report
with complete target or FM-1 qualification. The browser gate is already compact and
does not use this flag. Warning/skip hints remain presentation only; neither a
success banner nor a unit's zero exit establishes complete required coverage.

Every full runner invocation also writes versioned `coverage.json` beside its
summary, with the same contract in normal/compact and serial/parallel modes.
It records the source revision and input hashes before/after the run, clean exact
Engines pin, selected profile, relevant environment, actual compiler identities
and observed argv, child completion and semantic capability results. Private
per-run compiler passthroughs preserve multiword `CC`/`CXX`, argument boundaries,
exit codes and signals; their paths/logs are diagnostic, never release inputs.
Missing assets/tools stay in the expected plan with an explicit unavailable
outcome. Opt-in TSAN not requested and source-resolved MACRO exclusions are
`not_applicable`; they are not passed tests.

For strict verification, choose an explicit destination and a fresh identity
before launching the runner, then use the same environment for the verifier:

```sh
mkdir -p build/ci
export FELUCCA_COVERAGE_REPORT="$PWD/build/ci/coverage.json"
export FELUCCA_COVERAGE_ID="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
uv run --locked --group build tests/run_tests.sh --ai-output > build/ci/tests.log 2>&1
uv run --locked --group build python tools/ci.py verify-tests build/ci/tests.log
```

The destination is invalidated at startup; reusing its invocation ID is an error.
Keep sources, generated assets, compiler/configuration and outputs unchanged until
verification finishes. CI rejects required skips, missing child completion,
failed/blocked/cancelled units, altered/empty outputs, changed logs and stale or
unknown evidence. Local optional skips remain available but fail strict coverage.
Recorded unittest runs must execute at least one test; an empty successful suite
does not establish coverage.
Only absent proprietary V15 input, an unavailable whole CPU budget (counters or
matching baseline), C1's unqualified CPU comparison and declared applicability
exclusions retain their existing exceptions. Available CPU budgets missing entries
fail. See [CI policy](.github/CI.md#required-checks-and-evidence).
Baseline update modes (including empty or `0` environment values) cannot claim
comparison coverage and are rejected by strict verification. A report's
`complete` status means its execution and inputs completed consistently; the strict
verifier still evaluates every required capability. No report is a device result.

Runs the host tests and, with Node.js, the web page tests (and, with Emscripten too,
the browser emulator's). Run it after `uv run --locked --group build ./build.sh`
(it uses `build/` and needs `AC79_SDK` set as for the build). The suites cover flash storage,
user presets, projects of every format, backup, the keys and knobs, MIDI (USB, TRS, clock,
control), USB audio, the update entry and loader, the command-line installer, the UI (the real
drawing code against stubs: every screen in every palette is rendered and checked for clipped or
overlapping text; PNGs land in `build/ui_new/`), every engine (DRUM, NOISE, PHYS, FM6, SLICE, the
DIGITAL conversion), the chord keys, the modulation matrix, the FX layer, the reverbs, the SLICER
and swing. With `DAISYSP` pointing at a DaisySP checkout, the PHYS models are also compared with
their floating-point originals; without it that test is skipped. Felucca-Engines' own test
(`firmware/engines/tests/run.sh`) runs too, and its standalone host is built once more with Felucca's tables
against the same golden renders.

The engine-ID matrix also builds sparse host catalogs with DRUM (10), NOISE (11), FM6 (12)
and SLICE (13) omitted, plus `FELUCCA_SLICE=0`. It checks unavailable controls and silent
N/A tracks, retained project/preset/backup data, and serializers. Engine-memory switches
compare each sparse workload with the same workload in a full catalog; the default build
still checks all 720 existing union hashes. `FELUCCA_ENG_OMIT` is a host-test switch, not
a supported target build profile.

With Pillow, the real UI renders also include `manifest.json` with revision, compiler,
font/generated-asset hashes and render settings. `tests/ui_compare.py BEFORE AFTER`
produces exact pixel counts, bounds and before/after/diff sheets under `build/ui_compare`.
Use `--strict` for an approved baseline gate; report mode returns success after writing
its findings. See [UI comparison](docs/ui-comparison.md) for capture, selections, exit
codes and the separate hardware readability check.

The [silent FX bus regression](tests/fx_rest_test.md) compares bursts and long silences
with the rest paths forced off, at `-O2` and `-Os`, including persistent state and
actual skip counters. The suite requires the chorus, delay and HALL rest paths;
the guide also explains testing another compatible checked-out FX revision.

The [autosave audio regression](tests/autosave_audio_test.md) exercises real stereo FX/master
output and automatic saves against mocked NOR, including long tails and quiet residuals.

The native cross-feature audio transition check (#479) runs separately with:

```sh
python3 tests/audio_transition_test.py
```

It needs fresh generated assets from the selected build, a host C compiler and
POSIX threads, with no FM-1. The full runner includes it. Sixteen deterministic
scenarios cover real factory sound installation during held notes and release
tails, engine changes with a queued note, low-note voice stealing, performance
mute and return, DIST, INSERT type/bypass, sends, chorus depth, rapid edits,
four-part stereo HALL/delay/chorus with held and released parts, silence,
near-zero levels, a high saw attack, and a loud-left/quiet-right mix. Tails and
shared effects keep running throughout; this short capture does not establish
that long tails eventually drain.

Each capture renders 49,152 stereo frames (about 1.115 s), with edits starting at
frame 16,384. Per-channel maximum first and second differences in the next 2,048
frames are bounded against the same channel's waveform before and after the
edit. The report records the exact reference windows, peaks, derivatives and
limits. Smooth fixtures use 3x first and 6x second differences with floors of
6/12 Q15 counts; these are fixture regression bounds, not audibility thresholds.
The two engine-switch fixtures additionally compare with a separately rendered
native FM6 attack, since the note queued during the fade intentionally starts
the new sound. This reference does not replace or clear their old release tails.
DIST's existing abrupt transfer-function change also allows 3x/6x the measured
reference amplitude. The high saw attack uses twice the steady saw derivatives,
and an injected full-range impulse must still fail. Noisy/sharp waveforms can hide
smaller clicks inside their normal derivatives; the test asserts neither
universal click detection nor hardware sound quality.

Every configuration runs twice from a fresh process. Full stereo PCM and a
per-block hash of selected voice/control state must repeat exactly. Builds cover
`-O2`, `-Os` without vectorization, ASan/UBSan when available (the established
fixed-point shift exclusion, with undefined behavior made fatal), compile-time
CPU2 off, and an isolated generated `reduced-lofi` selection. No case relies on
LOFI or is skipped for that catalog.
An actual signed-overflow probe in the capture harness must exit nonzero and
retain its `.stderr` diagnostic and partial `.pcm` under the output directory.
The CPU2 build compares runtime OFF with a real worker thread rendering parts
1–3 while part 4 stays on the main thread; counters require the edited parts to
be assigned to the worker during the transition. A refusal fixture takes worker
jobs before the edit, then refuses submission so the real serial fallback runs.
Both policies must match complete OFF PCM and the selected state hash.
This covers submission refusal, not a worker stopped halfway through rendering,
HAL recovery, data races or physical inter-core timing.

Captures group native 32-frame mixer calls either singly or into 128-frame DMA
halves, as `audio.c` does; both groups must produce identical PCM and selected
state. They retain the FM-1's 32-frame controls and fade timing. Calling the mixer
directly with shorter blocks is outside this native fixture; variable browser
requests remain covered by the existing emulator partition suite.

Mandatory negative controls inject gain steps and one-sample impulses into
rendered PCM and require the same evaluator to reject them, including silence,
near-zero levels, the high saw attack, and the quiet right channel independently
of the loud left.
For an observable failing command, run
`python3 tests/audio_transition_test.py --inject impulse` or `--inject gain-step`:
both must exit nonzero and retain a short stereo WAV and JSON counters/metrics.
Normal runs save `build/host/audio-transitions/summary.json`; failed cases save
WAV/JSON pairs named by build, scenario, partition and CPU2 route. Use `--out DIR`
for independent outputs, `--optimization O2` for a focused iteration, or
`SANITIZE=0` to explicitly skip sanitizers. Existing focused FX/send/INSERT and
golden/budget regressions remain separate. FM-1 listening, deadlines, USB/MIDI
and physical control interaction remain pending qualification.

The regression suite (`tests/regress.c`) renders every engine and preset and compares a
hash of each render with `tests/golden.txt`; it also checks levels, voices and the CPU
cost (`tests/cpu_baseline.txt`, `tests/target_budget.txt`). It runs a second time built as
the target is, `-Os -fno-vectorize -fno-slp-vectorize` (no SIMD; `-O2` on Apple silicon
vectorises with NEON and understates engines such as PHYS and WHEEL by up to a third), with
the same goldens and its own `tests/cpu_baseline_os.txt`: the host count closest to the
device, for measuring DSP changes. `tests/target_budget.txt` (from the pi32v2 disassembly,
needs the toolchain) stays the exact, static check. After an intended change of
the sound, `GOLDEN_UPDATE=1 uv run --locked --group build sh tests/run_tests.sh` rewrites the hashes; `BUDGET_UPDATE=1`
does the same for the cost files (all three).
The two host CPU baselines apply to macOS arm64; on Linux the counter is `perf_event_open`
(user-space instructions, needs `perf_event_paranoid` <= 2) and the baselines are
`tests/cpu_baseline_<os>_<arch>_<compiler>_<version>_<build-id>[_os].txt`, skipped with a reason
when absent or when any counter is unavailable. See [docs/performance.md](docs/performance.md).

### MIDI and arithmetic reliability

After a fresh target build, `python3 tests/run_midi_dsp_focused.py` runs optimized
and fatal ASan/UBSan fixtures without general DSP sanitizer exclusions. It covers
nested TRS scheduling, UART events/register widths, signed arithmetic, all stored
tempo values and the real stress-event publisher. Run the long-run clock fixture
with `cc -O1 -w -Ibuild/gen -Ifirmware/src tests/midi_drift_test.c -lm -o build/host/midi_drift_test`
then `build/host/midi_drift_test`. These checks also run in the full suite.
Their host timing tolerance and hardware boundaries are documented in the
[reliability guide](docs/midi-dsp-reliability.md).

### Host stress matrix

For reproducible host stress workloads, run `python3 tests/stress_matrix.py` after
a fresh build. The [stress replay guide](tests/stress_matrix.md) describes the five
data-driven scenarios, exact repeat checks and retained WAV/JSON evidence under
`build/stress/`. This first increment uses direct host musical input; emulator/device
adapters and instruction counts remain follow-ups. The full host runner includes it.

### Emulator partition regression

With Node and generated assets, the runner rebuilds the real browser bridge natively;
with `emcc`, it also rebuilds the same fixture as test-only WebAssembly. The test compares
every float32 PCM bit, musical/transport state and event-publication position for
1024-frame drains, irregular `1/23/37/257/19/512` drains and the worklet's 128-frame drains.
The real audio ISR still renders 128-frame halves in `CTL=32` blocks.
Both the full host runner and focused `tools/ci.py emulator-tests` use
`sh web/emu/partition_test.sh`; focused CI requires Wasm and fails on missing tooling.

Each scheduled event is submitted after draining the same output-frame timestamp, in
stable order. The audio producer can lead that timestamp: the recorded `ring_w` is
the first unrendered frame where the queued event can become available. Both partitions
must observe the same producer position and device clock. This is equivalent input
publication, not an external MIDI sample-accuracy or arrival-jitter claim. The fixture
covers channel notes, bend, wheel, expression, level and sustain through `web_midi`,
and stop/restart through held PLAY presses. The browser bridge ignores MIDI realtime
messages; real USB/TRS clock/start/stop and fragmentation stay in the host partition test.

Fixtures start in fresh runtimes with erased NOR, seeds `0x87/1/2/3`, fixed ANALOG presets
and no sample dependency. Non-silent windows, pedal-held/released gates, ownership and
transport checkpoints are required. Dropped/reordered input and deliberately later
arrival must change PCM; unchanged CC repetitions must preserve it. Native/Wasm output
is exact signed DAC24 divided by `2^23`, represented without rounding in float32. Exact
within-runtime equality is checked separately from cross-runtime equality. These are
simulated browser/native checks; FM-1 hardware transport timing remains separate.

After a runner build, reproduce a failure with its printed seed:

```sh
node web/emu/partition_test.mjs build/host/emu_partition_native build/host/emu_partition.wasm 0x87
```

Without Emscripten, omit the Wasm path (the test reports that skip). Details and first
differing PCM/state word appear in the output; fixture code is in
`web/emu/partition_test.c` and `web/emu/partition_test.mjs`.

## Device diagnostics

For repeatable read-only CDC diagnostics captures, see [Collecting device diagnostics](docs/diagnostics.md).
The client needs Python 3 on macOS/Linux and an explicitly selected serial port; it does not install firmware.

For an existing private flash dump or `.fwsc` package, the standard-library
[offline boot-area survey](docs/boot-area-survey.md) checks bounded boot records,
SPL CRCs, chip key and declared clock fields without opening a device. Use
`python3 tools/fm1_bootarea.py --raw FILE` or `--package FILE` for the known saved
format; no firmware build is needed. Format hints are not authentication,
installer permission, a complete backup or live clock measurements.

For static native HOME/menu PNGs, the opt-in `FELUCCA_SCREEN_CAPTURE=1` development build
and standard-library host CLI are described in [screen capture](docs/screen-capture.md).
Normal builds leave it disabled; release packaging rejects the diagnostic flag.

## Test a pull request on hardware

`tools/fm1_pr.py` snapshots a PR's current head commit, requests or reuses a CI
build of that exact revision (full validation by default), downloads its firmware artifact, verifies the
recorded revision, SHA-256 and package structure, then starts the existing
Python USB-MIDI installer (`tools/fm1_install.py`). After the installer succeeds, the helper
prints the PR title and GitHub link so you can open its **User test instructions**.
You do not need the JieLi toolchain, SDK or Docker locally.
Normal automatic PR CI builds the merge with the target branch. By default,
this helper requests a separate, exact-commit build; `--automatic` reuses a
successful automatic PR merge build instead, without requesting another build.

Install [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS) and the
[GitHub CLI](https://cli.github.com/), sign in with `gh auth login`, and get this
fork's sources. Run the commands below from a trusted caller checkout. The
`midi` group automatically supplies the locked `mido` and `python-rtmidi`
dependencies; no manual environment activation or pip install is needed.

The helper checks those imports before preparing sources or starting firmware CI.
It uses `tools/fm1_install.py` from the trusted checkout running the helper,
never an installer from the PR being tested. No native updater binary, Cargo/Rust
build or m-flasher artifact download is needed.

Connect one FM-1 with running firmware using a USB data cable. Close other
applications using its MIDI ports; do not enter ROM download mode. From the checkout:

```sh
# Replace 123 with the intended PR number.
uv run --locked --group midi tools/fm1_pr.py 123

# Reuse the existing automatic PR build and install its merge firmware:
uv run --locked --group midi tools/fm1_pr.py 123 --automatic

# Faster firmware for hardware iteration, with isolated PR sources:
uv run --locked --group midi tools/fm1_pr.py 123 --validation target --worktree-dir ../Felucca-pr123
```

Use `--profile NAME` to opt into an engine profile defined in that exact PR
commit; the default remains `standard`, including automatic PR/main/release CI.
For example, to download a MACRO test package without accessing hardware:

```sh
uv run --locked tools/fm1_pr.py 123 --commit FULL_40_CHARACTER_SHA --profile macro \
  --workflow-ref feat/macro27-current-main --download-only
```

The workflow branch must support the `profile` input. Nonstandard profiles require
an exact verified manual PR revision and cannot create releases. The helper checks
the pinned profile definition, keeps profile run/artifact identities separate, and
verifies the downloaded profile against provenance before installation. Resume with
the same commit, profile, validation mode and workflow branch. `--automatic` supports
only `standard`; omit `--download-only` when ready to use the normal installer.
For MACRO device checks, the full macro-profile artifact also contains the
[project/song and MIDI test pack](docs/macro-hardware-test.md#prepare-the-project-and-song-pack).
It prepares four importable project files and a deterministic MIDI workload;
importing them and recording physical results remain separate user actions.

`--validation target` uses the same target build and flags as full validation:
it checks the pinned SDK/toolchain, source and Engines identity, app/loader and
resource guards, static target instruction budgets, FWSC structure/CRCs and
SHA-256. It omits host goldens, sanitizers, web/emulator/browser tests and the
second clean-checkout build. Those tests still belong to full PR validation;
**target-only success is for hardware iteration, not merge/release readiness**.
It does not install a different firmware variant. Build defaults still come from
the chosen revision; the validation scope is printed before CI/install and
recorded in the target artifact's `provenance.json`.
Historical sources without build-identity/pinned-engine provenance APIs cannot
use target-only mode; the helper reports this explicitly. Use `--validation full`
for those revisions. Existing full builds remain supported without those newer APIs.
The selected sources must still contain the tests required by the chosen workflow.
Full validation reports a missing browser harness before building or running host
tests; rebase the PR or select a compatible workflow if it predates that harness.
Full requests retain the original dispatch inputs, so older compatible maintainer
workflow branches can still be selected with `--workflow-ref BRANCH`.

Use `--validation full` (the default) for the complete pipeline. Modes have
separate run titles, concurrency groups and artifact names; a target-only run
can never satisfy a full request. Older fully validated artifacts remain usable.
Manual Actions checks have separate names from automatic PR/main checks, so a
manual target or exact-PR build cannot stand in for the required PR validation.
The helper reuses a live successful or running exact-commit build only for the
requested mode and workflow branch, avoiding repeat builds. Full validation
never cancels a target run, or vice versa. Both can also be requested manually
under **Actions > CI > Run workflow**, selecting `validation` and filling in
`pr` and `commit`; target-only mode requires both fields and cannot make a release.

Before source preparation or any firmware CI request, the helper checks the
Python MIDI dependencies without discovering or opening ports. `--download-only`,
`--prepare-only`, cleanup and resolve-only modes skip that check entirely. These
standard-library-only modes can use `uv run --locked` without a dependency group,
or plain `python3`, without installing MIDI packages.
The former `--installer python` spelling is accepted for existing commands;
native backend selection and `--m-flasher` have been removed.

The Python updater validates the package, stages its selected loader and checks
the final application identity. It creates no raw backup or verified preboot
checkpoint and has no automatic fallback to ROM USB. Package/loader compatibility,
backups and pending hardware qualification are documented in the
[recovery guide](docs/usb-rescue.md). The previously observed native updater
exchange remains historical evidence in `m-flasher-legacy`, not validation of
this Python handoff.

The command prints the fixed commit and Actions run URL, waits for all selected
validation to pass, and downloads into a fresh directory under
`build/pr-123/COMMIT/`. Keep the provenance and license files with the package.
The installer asks for confirmation before flashing; `--yes` explicitly skips
that confirmation and `--port NAME` selects its USB-MIDI port. The installer
checks the device identity after reboot. Development builds may share a display
version: retain the printed commit and run URL to identify the tested firmware.

To pin an older state, supply its complete, lowercase 40-character SHA with
`--commit SHA`. It must be reachable from the PR's current head; commits removed
by a force-push are rejected. A subsequent push does not change the selected
commit. The firmware and build defaults come from that revision.

```sh
# Build/download/verify without an FM-1 or MIDI dependencies.
uv run --locked tools/fm1_pr.py 123 --download-only

# Reuse a successful or running exact-commit build without requesting a new one.
uv run --locked tools/fm1_pr.py 123 --commit FULL_40_CHARACTER_SHA --no-build --download-only

# Download/verify the automatic PR merge build without installer setup or MIDI.
uv run --locked tools/fm1_pr.py 123 --automatic --download-only
```

`--automatic` requires an open PR and full, successful automatic CI with a live
`firmware-RUN_ID` artifact. It snapshots the current PR head, base and merge SHA,
checks that the merge's parents match that base/head, and selects a successful
run associated with the same PR and base/head. The package provenance must match
the **merge SHA**, rather than the PR head. All three SHAs and the Actions run URL
are printed; downloads are stored under the merge SHA. A later push does not
change that snapshot. Changed base/head, failed or running CI, missing/expired
artifacts and provenance/checksum mismatches prevent installation.
Documentation-only CI has no firmware artifact and cannot be used this way.

Automatic mode never dispatches a build; `--no-build` is allowed but redundant.
It does not wait for running CI: retry after the automatic build finishes.
An optional `--commit SHA` must equal the current PR head; use the default
exact-commit mode for historical revisions. Automatic mode cannot be combined
with target validation, `--workflow-ref`, worktree or source-only options.
It uses the same Python installer, confirmation, `--port`, `--yes` and
`--download-only` behavior as exact-commit mode.

GitHub sign-in and artifact read access are required. Requesting a missing build
also requires Actions write access (typically a maintainer or collaborator).
Read-only testers use `--no-build` after a maintainer starts **Actions > CI >
Run workflow** on the default branch, with `pr` and `commit` filled in, or use
`--automatic` for an already successful automatic PR merge build. Leave
both empty and select `full` for ordinary manual CI. Firmware artifacts expire after 30 days;
an expired or failed build requires a fresh run. The helper retains full CI
validation in the default mode; select `target` explicitly for faster hardware iteration.
See [CI delivery details](.github/CI.md#exact-pr-revision-builds).

The default wait is one hour; `--timeout SECONDS` changes it. Interrupting or
timing out does not cancel CI: rerun with the printed `--commit` and the same `--validation` to resume.
`--out DIRECTORY` changes the download parent and `--repo OWNER/NAME` selects
another fork with this workflow. Maintainers can use `--workflow-ref BRANCH`
to rehearse workflow changes before merging; normally omit it.

### Optional isolated PR sources

The CI install path above needs no local checkout change. To also inspect or work
on the matching sources, add `--worktree`; Git must be installed and this helper
must be run from a Git clone. It fetches the PR into a temporary private ref,
creates a **detached worktree at the selected commit**, and runs
`git submodule update --init --recursive --checkout` there. Submodules use the
committed pins, rather than their latest branches. CI still builds the selected
commit remotely; preparing sources does not build local edits or change which
firmware is installed. Local builds need the toolchain and SDK described above.

```sh
# Prepare sources, then continue through CI/download/confirmed install.
uv run --locked --group midi tools/fm1_pr.py 123 --worktree

# Only prepare sources: no CI build, download or MIDI access.
uv run --locked tools/fm1_pr.py 123 --prepare-only --worktree-dir ../Felucca-pr-123
```

The default directory is a sibling named `CHECKOUT-pr-123-FULL_SHA`. A new PR
revision gets a different directory; `--worktree-dir PATH` chooses a fixed path
and implies `--worktree`. An existing directory is reused only if this helper
created it for the same PR/revision and its detached HEAD and local files are
unchanged. Failed preparation retains the worktree for inspection or retry;
build/download/install do not proceed if source preparation fails.

The original branch, index, staged/unstaged edits and untracked/ignored files
stay in their original checkout, including local submodule edits. There is no
automatic stash, reset or branch switch. Worktrees share Git objects, refs and
repository configuration; their files, indexes and detached HEADs are separate.
The helper prints `cd` commands to enter the PR directory and return to the
original directory. A Python child process cannot change your shell's directory.
To retain edits made in the PR worktree, create a branch there with
`git switch -c my-pr-experiment` and commit them. Switching branches or changing
HEAD prevents helper reuse/removal until you explicitly resolve that state.

By comparison, `gh pr checkout 123` switches the current checkout's branch.
Compatible staged/unstaged edits may follow that switch; Git normally refuses
when it would overwrite local edits or untracked files. Uncommitted edits do
not belong to a branch. Existing commits stay reachable through their branches.
Use the isolated worktree when your current checkout has ongoing work.

From the **original checkout**, remove a finished helper-created worktree with:

```sh
uv run --locked tools/fm1_pr.py 123 --remove-worktree ../Felucca-pr-123
```

Removal needs no GitHub access and does not contact CI or MIDI. It refuses foreign
worktrees, changed HEADs, local edits, and additional files, including ignored
build output and files inside nested submodules. Preserve or remove those files
yourself before retrying; it does not automatically clean or stash them. Keep
firmware artifacts outside the disposable worktree if you need them later.
Returning to your original directory or removing PR sources does **not** revert
the FM-1: reinstall the previously saved firmware package to restore that build.

### Hardware verification after installing a PR

A successful CI build or download is not an FM-1 hardware test. A successful
installer run checks the update and reported device identity, but it does not
test sound, controls or the PR's behavior. **Hardware validation remains pending
until the chosen revision and scenarios have been exercised on a real FM-1.**

1. Read the selected PR's **User test instructions** before installing. They
   should identify the starting device state, required host/MIDI/audio setup,
   exact panel actions, expected results and any backup or downgrade constraints.
   If those instructions are missing, request them from the PR author before
   treating that PR as ready for user hardware testing.
2. Record the printed PR commit, Actions run URL, host OS, FM-1 model and downloaded
   `provenance.json`. Flash the verified `.fwsc`; require the installer to finish
   successfully and the FM-1 to restart. Run
   `uv run --locked --group midi tools/fm1_install.py --info`
   to record its device identity. That identity/display version alone does not
   identify the source commit; retain the build provenance as well.
3. Follow the PR's numbered hardware scenarios on the FM-1. Check each stated
   expected result, including sound, physical controls or USB/MIDI behavior where
   relevant. CI, simulated-device installer tests and the browser emulator do
   not establish those results. Follow the PR's cleanup/restore instructions.
4. Report the commit/run, host and device identity, scenarios performed and
   observed versus expected results in the PR. Label unperformed scenarios
   **Pending hardware validation**. For failed updates, retain the installer
   error and follow [installation recovery](#install); for performance scenarios,
   use the PR's workload and [diagnostics guide](docs/diagnostics.md).

## Install

Use the web installer in Chrome or Edge:
<https://kmplngj.github.io/Felucca/webapp/installer/>. It offers the last successfully
published full `main` build; use a downloaded release or PR `.fwsc` for another revision.

From a trusted checkout with uv installed (the locked `midi` group is synchronized automatically):

```
uv run --locked --group midi tools/fm1_install.py build/felucca.fwsc
uv run --locked --group midi tools/fm1_install.py --info          # identity of the connected FM-1
```

Or, to install your own build from the web installer, make a local copy of the site and open it from `localhost`
(Web MIDI needs a secure context):

```
python3 web/make_site.py build/felucca.fwsc dev /tmp/felucca-site
cd /tmp/felucca-site && python3 -m http.server 8000
# open http://localhost:8000/webapp/installer/
```

On a build with early USB rescue, hold OCT− while powering on to reach the
MIDI-only updater before settings/projects and audio initialize. Use the same
reviewed `.fwsc` and supported installer. See [early USB rescue](docs/usb-rescue.md)
for the accepted PR #487 entry result, loader matrix and remaining qualification.
If application rescue cannot start, the [existing M-Flasher ROM path](docs/usb-rescue.md#rom-recovery-with-existing-m-flasher)
provides saved-file inspection and a separate device backup/recovery procedure.
File-only checks open no device; live ROM sessions may upload a RAM loader and
need host permissions. A unit with no reachable USB route can still need
[FM-1-transporter](https://github.com/kurogedelic/FM-1-transporter).

The standalone RAM loader displays waiting, package validation, verified app-sector
progress, completion/restart and native-error retry guidance. Its writing percentage
is verified application work, not confirmation of a complete install. If it reports
**UPDATE STOPPED**, keep power and USB connected and retry the same reviewed
compatible package with the supported installer after the host operation returns.
A display failure may leave a stale image while USB/retry continues. Check the
host's final application identity; see [loader screen meanings and limits](docs/usb-rescue.md#standalone-ram-loader-screen).
Physical FM-1 qualification of the new loader screen remains pending.

### Package validation and file errors

When given a package, the command-line installer validates its identity, UFW structure,
file extents, sizes, CRCs and loader headers before opening MIDI ports or sending update
data. A damaged or unsupported file is a local package error (exit code 2): obtain an
intact copy of the intended package, or rebuild it with the supported toolchain and SDK
from [Build](#build). See the [download and checksum guide](.github/CI.md#downloads-and-checksums)
for release files. Package acceptance alone does not establish compatibility with your
FM-1 or a successful installation; the installer still checks the device and final identity.

`--force` is a deprecated compatibility option with no effect. Unknown package loader
families are rejected with exit code 2 before MIDI discovery or an installation prompt,
including with `--force`. The exact unmodified official V15 file is accepted through its
pinned SHA-256 digest without `--force`; this exception does not cover arbitrary vendor files.
The selected package also determines the accepted running loader: current Felucca
requires `ota-FM-1_900`, verified original V15 requires `ota-FM-1_015` through
Python/the maintained browser. Unknown/crossed pairs fail before the loader's
writing phase. `--force` cannot override this contract.

Device discovery and connection errors occur later: exit code 3 means the FM-1 was not
found (check the USB data cable and other apps using MIDI), 4 means the connection was lost
or the device stopped, 5 means a timeout, and 6 means a model or installed-identity mismatch.
Run `uv run --locked --group midi tools/fm1_install.py --help` for the options and complete exit-code list.

If package generation reports `app area is ... B, available ... B`, the app region plus
the SDK configuration files and headers exceeds the flash boundary. The app fitting its
own slot is not enough: use the supported SDK files and review the reported sizes under
[Measuring and optimizing Felucca](docs/performance.md). Keep the package guard enabled.

### Engine build profiles

Plain `uv run --locked --group build ./build.sh` uses the frozen `standard` profile
in `profiles/standard.json`:
all thirteen current engines, stable reserved DIGITAL slot 1, unchanged display order
and boot sounds.
`FELUCCA_PROFILE=reduced-lofi uv run --locked --group build ./build.sh` omits portable LOFI (id 3),
including its wave RAM and factory presets, and writes `felucca-reduced-lofi.fwsc`.
No engine ID moves. Stored LOFI projects, user presets and favourites survive; the
sound shows N/A and is silent until standard firmware is restored. Selecting another
sound explicitly replaces it. The existing editor INFO prefix and availability bitmap
remain unchanged; custom sparse catalogs still require the FM-1/client gates in
[the modularity guide](docs/modularity.md). This profile adds no usage mode or storage.

`tools/profile.py` validates the firmware-owned `profiles/catalog.json` registry and
resolves sources, metadata, shared generators/assets, tests and licence inputs to
`build/gen/resolved-profile.json` plus the generated C selection. Target, host and
browser builds consume those same includes. `python3 tools/profile.py --check` rejects
stale files, a different profile/feature selection, source hashes or engine pin; host and
emulator entry points run it before compiling. Use the same `FELUCCA_PROFILE` and
`FELUCCA_SLICE`/`FELUCCA_FM4` environment for those entry points as for the target build.
Freshness checks accept only the supported M8Stealth font; rebuild older alternate
font artifacts. An explicit `FELUCCA_FONT=m8stealth` override must match.
Do not override `FELUCCA_PROFILE_ENGINE_*`
compiler macros; they are generated.
Existing host-only DIGITAL, test14 and omit fixtures remain supported.

`FELUCCA_CPU2` stays independent, including its OFF runtime default. Native effects,
UI providers and arena allocation are retained in both initial profiles. The resolver
rejects removing those owners; further native pruning needs explicit dependency work.
Measured costs and pending device checks are in [the profile evidence](docs/build-profiles.md).
`tests/profile_integration_test.py` builds isolated host selections and verifies actual
standard → reduced → standard project/preset/backup records without rewriting goldens.
The full runner qualifies standard; the reduced profile uses that focused test and the
same emulator partition suite, with a fresh target and target budgets.

Non-standard **release** profiles require a distinct `--product` identity; their profile
name also appears in the package/release filenames. Releases carry `resolved-profile.json`
with source pins, file hashes and selection. Target disassembly carries `felucca.dis.profile.json`, binding its selection to the
listing's SHA256; preserve both files for later budget comparisons. Development
`felucca.bin`/ELF/disassembly remain scratch outputs overwritten by the next build, so preserve them before comparisons.
Complete verified source archives can resolve/build without a Git checkout. The bundled
`tools/source_archive.py` verifies `SOURCE-PINS.json` before either the resolver or build
uses archive inputs. Ordinary GitHub source ZIPs still lack the pinned dependency.

### Profile contract and exact resource reports

Export the versioned firmware-owned registry/validation contract without building firmware:

```sh
python3 tools/profile.py --export-contract build/profile-contract.json
python3 tools/profile.py --export-contract build/profile-contract.json --check
```

This exports canonical `standard`, `reduced-lofi` and opt-in `macro` recipes,
including reserved stable IDs, the exact MIT engine pin, dependency inclusion reasons,
assets, licence hashes and boot defaults. Developer environment overrides do not alter
these canonical recipes. It does not enable arbitrary selections or the planned GPL
collection. The [profile guide](docs/build-profiles.md#machine-readable-build-evidence)
describes the version 1 contracts and their limits.

Every successful target build also writes `build/resource-report.json`, bound to the
actual source/generated inputs, effective configuration and output artifacts. It records
app, RAM, POOL, RAMTEXT and NOINIT used/spare bytes, enforced minimum spare and remaining
margin, plus static stack reservations. Existing build/linker guards remain authoritative.
Schema version 2 adds the checked native font manifest and separate named UI resource
groups; verification retains support for schema version 1 reports without those fields.
The report is removed at the start of the next attempted build, including failed attempts.
To recheck matching artifacts and sources, retain the build directory and use the same
profile/font/feature environment and toolchain/SDK:

```sh
python3 tools/build_report.py --verify build/resource-report.json
```

The verifier uses the same default dependency locations as `build.sh`
(`~/.jieli/toolchain` and `~/fw-AC79_AIoT_SDK`). Nonempty `JIELI_TOOLCHAIN`
and `AC79_SDK` values override those defaults; unset or empty values use them.

Initial input capture refuses unsupported compiler search/configuration variables
for native target builds, including `CPATH`, `LIBRARY_PATH` and `SDKROOT`. Docker
does not forward these host values, so Docker target builds ignore them. Host loader
injection (`LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`) remains refused
with either backend because generators still run on the host. `LD_LIBRARY_PATH`
is allowed and bound only by a value hash, not by the selected library contents.
The optional paired Wasm build runs on the host and still refuses compiler-search
overrides even when its target used Docker. See [build-input identity and limits](docs/build-bundles.md#identity-and-immutability).

Verification hashes all required artifacts and input files, recomputes effective compiler
macros and resource/stack figures from the ELF, and rejects stale or mismatched evidence.
It needs the configured target tools and SDK but does not compile firmware. Source and
artifact hashes bind actual working bytes; a recorded dirty checkout is not identified
by its commit alone. Releases and CI artifacts include both JSON sidecars; local release
`SHA256SUMS` covers them. These reports do not measure live stack use or FM-1 deadlines.
