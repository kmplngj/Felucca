<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Initial engine profiles and evidence

The firmware-owned registry is `profiles/catalog.json`. Standard is explicitly frozen on
backport `037d2c6f7f0c1ce7dcac9dbdec5786f0e2f6dc99`, with upstream firmware source
`a53ecf428c29c780108fd70a31b71a32a6b5c313`. Its five portable engines are ANALOG 0,
LOFI 3, TRIO 6, WHEEL 7 and NOISE 11; PHASE 2, SAMPLE 4, VOICE 5, GRAIN 8,
PHYS 9, DRUM 10, FM6 12 and SLICE 13 remain firmware-native. DIGITAL 1 is reserved
and retains its historical FM6 migration. Boot sounds remain ids 0, 12, 4 and 10;
display order remains ANALOG, FM6, PHASE, LOFI, SAMPLE, VOICE, TRIO, WHEEL, GRAIN,
PHYS, NOISE, SLICE, DRUM. Standard does not discover or enable new engines automatically.

The actual consumed Engines gitlink and firmware revision are recorded in each
`resolved-profile.json`, along with generator/asset/source hashes, tests, licence inputs
and selection SHA256. The resolver rejects a checkout at a different engine revision.
Portable engines/shared DSP/types/generator retain MIT ownership; firmware registration,
identity metadata, UI, voices, effects, persistence and platform remain GPL-owned, with
existing third-party attribution retained. The metadata adapter adds const data only to
the firmware; it does not alter the portable `engine_t`. Existing arena sizing and fixed
FX order stay with their native owners. No usage mode, retained object or storage sector
is allocated by this work.

`reduced-lofi` removes LOFI's implementation at id 3. Its engine table slot becomes
`ENG_NONE`; editor INFO reports the same 14-slot prefix with a '-' name and cleared
availability bit for 3. Factory LOFI presets and WRAM data are absent. Stored projects,
user presets and favourites retain id, preset and parameter bytes, and become playable
again when standard is restored. Direct activation/import requests for unavailable
engines retain the existing refusal behavior. Native/UI owners remain mandatory in
these initial profiles; further native pruning is a separate dependency/asset exercise.

## Measurements

### Historical initial qualification

Measured on Linux x86-64, JieLi Clang 4.0.1/pi32v2 and the pinned AC79 SDK, M8Stealth,
default flags and selective minsize enabled. Baseline is unchanged `037d2c6`; candidate
is the initial #341 implementation over that base with Engines `c46e0086f69bdc26df1cd144dca9e683cc4531dd`.
This evidence is distinct from the later portable API pin integration and its final checks.
App bytes include RAMTEXT/data load images. Section sizes come from fresh objdump output;
RAM is the build guard's allocated span, including alignment gaps.

| Region (bytes) | Baseline, CPU2=1 | Standard, CPU2=1 | Reduced LOFI, CPU2=1 | Reduced LOFI, CPU2=0 |
| --- | ---: | ---: | ---: | ---: |
| App | 475812 | 476540 | 474192 | 470704 |
| RAM | 61032 | 61032 | 61032 | 55412 |
| POOL | 336436 | 336436 | 336436 | 336436 |
| RAMTEXT `.ram_text` | 2924 | 2924 | 2924 | 2924 |
| RAMTEXT `.c1_text` | 160 | 160 | 160 | 0 |
| NOINIT | 15568 | 15568 | 15568 | 15564 |

Standard adds 728 app bytes for the registry/adapter. Reduced removes 2348 app bytes
from standard. RAM/POOL allocation is unchanged because LOFI used per-voice state in
existing voice objects; arena allocation is retained. RAM margins are 12696/18316 B
(CPU2=1/0), POOL 32204 B, RAMTEXT 21492/21652 B and NOINIT 128/132 B.
Main stack windows stay 24320 B user and 7936 B supervisor with their 256 B guards.
CPU2's 4096 B user stack array (including its 256 B guard) and 256 B exception stack array remain part
of the CPU2=1 RAM cost and disappear at CPU2=0. No live stack watermark was measured.
Fresh target symbol tables confirm `lofi_render`, `LOFI_PRESETS` and `WRAM` absent in reduced;
shared SINE and other providers remain. Both reduced target variants passed the existing
static render budgets without baseline updates. Target estimates are not device timing.

Focused host evidence: standard -O2 and -Os retained all 98 PCM goldens; all 720 engine
switch hashes were unchanged after deriving state consumers from `engine_t.mem`;
arena ownership negative fixtures and four fixed-seed random runs passed. Default MIDI
control tests passed; descriptor JSON was byte-identical to baseline; all baseline and
candidate UI PPM images were pixel-identical. Resolver fixtures cover malformed IDs,
metadata, dependency cycles/exclusions, defaults, deterministic outputs, stale output,
feature mismatch and render budget coverage. Standard and reduced metadata/engine-ID
fixtures passed, including INFO availability, favourites and unavailable-sound refusal.
Separately compiled standard → reduced → standard processes preserved real project,
user-preset and backup-favourite records byte-identically (SHA256
`a7622e320e1c0b3a99cee403eea0983dbb9c824b6c9da82e21a4a9e4a95eb4fa`). Reduced native and
Wasm emulator partition suites retained exact PCM, state, event publication and checkpoints.
Host CPU instruction budgets were not measured in this focused pass; no CPU speed claim
is made. Full combined portable/firmware suites and source-archive reproduction are
integration checks recorded in the implementation PR, without golden/budget regeneration.

### Review fixes qualification

The later #343 review fixes were measured independently at firmware commit
`d43860e290f122e7b7bba3448110711f494de231`, before the profile/metadata adapter.
These measurements use the same Linux x86-64, JieLi Clang 4.0.1/pi32v2, pinned SDK,
M8Stealth and selective minsize configuration, with only `FELUCCA_CPU2` varied.
The historical table above remains evidence for the initial profile implementation;
it does not include these later DSP review fixes.

| Region (bytes) | Reviewed #343, CPU2=1 | Reviewed #343, CPU2=0 |
| --- | ---: | ---: |
| App | 476132 | 472260 |
| Allocated RAM | 61928 | 55412 |
| POOL | 336436 | 336436 |
| RAMTEXT `.ram_text` | 2924 | 2924 |
| RAMTEXT `.c1_text` | 160 | 0 |
| NOINIT | 15568 | 15564 |

The reviewed CPU2=1 target adds 320 app bytes and 896 B of allocated RAM over the
initial `037d2c6` baseline. FORMANT, PHYS and PHASE review fixes account for 100 app
bytes; PHASE's render scratch is now owned by each part when the second core is
compiled, adding 768 B of allocated RAM. Worker-timeout recovery retains a canonical
state snapshot in 120 B of storage, plus 8 B of alignment in the allocated RAM span.
The remaining code changes include that recovery and complete crash-record
initialization/publication: worker diagnostics unavailable on that core are cleared,
and the main core preserves its diagnostic registers before holding the worker and
replacing their shared retained record. CPU2=0 retains its single-core scratch and
adds 32 app bytes for the cold fault path relative to its matched pre-review baseline
(472228 B); it is no longer byte-identical to that baseline. These changes are separate
from the historical 728 B app cost of the profile/metadata adapter. The combined reviewed
standard/reduced profile sizes require their own direct integration measurements;
no combined value is inferred from those deltas here.

Both reviewed targets passed the existing render budgets and RAMTEXT no-call check
(916 instructions). CPU2=1 retains the 50-instruction worker text; CPU2=0 contains no
second-core code, stack or mailbox. Allocated RAM margins are 11800/18316 B for
CPU2=1/0; POOL and NOINIT allocations stay as reported above. The worker exception
path uses 164 B of its 256 B stack window: 104 B for the assembly save and 60 B for
the compiled C frame, with no calls on that path and 92 B spare. This is a static
target estimate, not a physical stack watermark. These measurements do not establish
live deadlines or FM-1 reliability.

## User test instructions and remaining gates

Real FM-1 and hosted-editor checks are pending. Save a backup using standard firmware.
On track 2, choose LOFI via PRESETS, pick ARP 8BIT, star it and save the sound as a user
preset and in a project. Install the distinct reduced development package with the usual
installer. Load the saved project and user preset: LOFI must show N/A and play silence;
the other tracks must still play their original engines. The editor INFO list must show
LOFI unavailable while keeping all remaining IDs. Restore standard, load the same project
and preset, and confirm the original LOFI sound and star return. Compare PRESETS tags,
icons, categories and CC74/CC71 controls across all installed engines with standard.
Exercise saves/backups through the actual editor before promoting sparse releases.
Keep #305/#306 client catalog delivery separate from CPU2. The independent #44 dual-core
experiment is retired in favor of the integrated upstream 1.6.1 approach. These
host/Wasm/static checks do not qualify FM-1 deadlines, cache publication, flash quiescence
or hardware recovery; that hardware evidence remains unverified. CPU2 remains independent
and OFF at runtime by default.

README assessment: the Build link now exposes profiles. The thirteen-engine feature list
still describes the default standard release; the profile guide explains custom omissions,
compatibility, defaults and limitations. Contributor ownership/workflow is documented in
[extending.md](extending.md#two-repository-profile-workflow) and [BUILDING.md](../BUILDING.md#engine-build-profiles).

## Machine-readable build evidence

`python3 tools/profile.py --export-contract build/profile-contract.json` exports schema
version 1, kind `felucca-supported-profile-contract`. It calls the existing resolver for
each explicitly supported recipe: `standard`, `reduced-lofi` and experimental opt-in
`macro` (native engine 14/Braids). The registry preserves the retired DIGITAL slot 1,
all current identity metadata, provider requirements, generator/asset/test/license inputs,
fixed owners and boot defaults. `supported_profiles` contains each canonical recipe,
resolved selection and `provider_reasons`: explicit profile roots, engine requirements
and transitive provider requirements. `validation` describes the production resolver's
stable-ID, default, dependency, exclusion and exact-pin constraints. It is descriptive;
`tools/profile.py` remains the executable validation authority. `source_pins` includes the
exact consumed MIT gitlink, and `license_sha256` binds every declared licence input.
Canonical feature values are FM4=0, SLICE=1 and M8Stealth regardless of the caller's
environment. `--check` compares an existing export byte for byte and rejects stale data.

The export describes today's supported build contract. It supplies no arbitrary custom
selection API, per-engine marginal cost estimates, browser builder, new engine pin or
GPL collection integration. Those later parts of [#465](https://github.com/kmplngj/Felucca/issues/465)
remain open. Exporting a recipe does not establish its hardware qualification.

Every successful target build writes schema version 1, kind
`felucca-post-link-resource-report`, to `build/resource-report.json` and copies the
canonical contract beside it. `resources` records each region's origin, capacity,
allocated span, spare bytes, enforced minimum spare and margin after that minimum.
App bytes include load images and alignment. RAM is the existing `.data+.bss` span;
POOL is its linker span. NOINIT uses the larger section/symbol extent, including anonymous
tail padding. Those measurements come from the same production `check()` call used by
the build guard. RAM and POOL retain their 4,096/8,192 B minimum spare; NOINIT retains
100 B, or the existing 24 B diagnostic floor for `FELUCCA_CRASH_CTX=1`. App and RAMTEXT
have zero additional spare minimum; their capacity limits remain the package guard and
linker region. RAMTEXT includes both `.ram_text` and `.c1_text`, with separate section
sizes. The report does not introduce another fit evaluator or weaken an existing guard.

`stack_reservations` records main user/supervisor windows and their guard bands from
linked symbols. CPU2 builds also record the worker's user array (including its guard)
and exception array; these are already included in RAM and must not be added again.
Reservations are not live stack watermarks. RAM and POOL share SRAM; changing their
boundary reallocates the budget rather than increasing it.

`configuration` contains exact C compiler flags, effective `FELUCCA_*` macros obtained
by preprocessing with those flags, selective minsize state, compiler version/hash,
linker/objdump/objcopy hashes, the installed compiler header inventories, build-time
generator versions/lock hash, loader-environment hashes, logical constants and actual SDK file hashes. The compiler's host-specific
`InstalledDir` line is omitted. There is no timestamp or absolute workspace path in the
report. `build_identity` preserves clean/dirty status and revision. `input_sha256` hashes
the entire tracked source inventory, recursive engine sources, nonignored untracked
inputs and generated header/include/JSON inputs. This deliberately supersets the compile
closure, so a documentation or test edit also invalidates evidence. Complete verified
source archives use their verified source inventory instead of Git. Actual bytes, not
HEAD alone, identify dirty builds. Source and tool/SDK file fingerprints are captured before loader/asset jobs and checked
again after those jobs; this early inventory excludes the generated files those jobs
are expected to replace. The full source/generated inventory and effective compiler
configuration are then captured before the app compile/link and checked again before
report publication. A mismatch in either phase fails the build.

`artifact_sha256` requires the app, ELF, disassembly, profile sidecar, resolved profile,
generated identity, canonical contract, loader and installable package. The verifier
requires that complete set, checks the input/configuration inventories and hashes,
and recomputes measurements from the actual ELF through the existing build guards.
Missing or changed resources, stack bounds and build identity are refused as well.
Retain the complete matching build directory and run, with the original build environment:

```sh
python3 tools/build_report.py --verify build/resource-report.json
```

The verifier needs the target tools/SDK but performs no compilation or device access.
It uses `build.sh`'s default locations (`~/.jieli/toolchain` and
`~/fw-AC79_AIoT_SDK`) when `JIELI_TOOLCHAIN` or `AC79_SDK` is unset or empty,
and preserves nonempty overrides.
Changing an artifact, generated input, source, compiler, profile/font or feature option
requires a fresh build. An attempted build first deletes the previous success report;
failed build checks cannot leave an older report appearing current. CI verifies and
uploads both sidecars; releases include them under `SHA256SUMS`. A release folder alone
is a distribution, not the complete ELF/source/toolchain verification workspace.

User checks for this tooling change: export the contract twice and compare bytes; run
`--check`; inspect the three supported recipes and unchanged boot IDs; build a chosen
supported variant using [BUILDING](../BUILDING.md) and verify its report. Copy
`build/resource-report.json` to `build/resource-report-copy.json`, change one resource
value in that copied JSON, then run
`python3 tools/build_report.py --verify build/resource-report-copy.json`: verification
must fail while the original report and artifacts remain intact. No device installation
is required because this work changes build metadata only; live timing,
stack headroom and existing profile hardware qualification remain separate gates.

## Immutable maintainer bundles

[Build bundles and paired runtime receipts](build-bundles.md) bind an existing canonical
profile build to its exact native report/package, complete source archive and actual
Git-free reproduction. An optional build-time Wasm receipt binds the simulator files to
that native build; absent or failed runtime output stays unavailable. This is local
maintainer staging, with no public builder, deployment, installation approval or new
profile/default. Full host/browser/device acceptance remains separate.
