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
`94d221d4fcc8fcd621200a64fb5e5be096fe341e`, before the profile/metadata adapter.
These measurements use the same Linux x86-64, JieLi Clang 4.0.1/pi32v2, pinned SDK,
M8Stealth and selective minsize configuration, with only `FELUCCA_CPU2` varied.
The historical table above remains evidence for the initial profile implementation;
it does not include these later DSP review fixes.

| Region (bytes) | Reviewed #343, CPU2=1 | Reviewed #343, CPU2=0 |
| --- | ---: | ---: |
| App | 475912 | 472228 |
| Allocated RAM | 61800 | 55412 |
| POOL | 336436 | 336436 |
| RAMTEXT `.ram_text` | 2924 | 2924 |
| RAMTEXT `.c1_text` | 160 | 0 |
| NOINIT | 15568 | 15564 |

PHASE's render scratch is now owned by each part when the second core is compiled,
adding 768 B of allocated RAM to CPU2=1. The reviewed CPU2=1 app adds 100 B relative
to its matched pre-review baseline. CPU2=0 retains its single-core scratch and its app
is byte-identical to its matched pre-review baseline. These changes are separate from
the historical 728 B app cost of the profile/metadata adapter. The combined reviewed
standard/reduced profile sizes require their own direct integration measurements;
no combined value is inferred from those deltas here.

Both reviewed targets passed the existing render budgets and RAMTEXT no-call check
(916 instructions). CPU2=1 retains the 50-instruction worker text; CPU2=0 contains no
second-core code, stack or mailbox. Allocated RAM margins are 11928/18316 B for
CPU2=1/0; POOL and NOINIT allocations stay as reported above. These are target static
measurements, not live stack, deadline or FM-1 reliability observations.

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
Keep #305/#306 client catalog delivery and #44 dual-core device reliability open; these
host/Wasm/static checks do not qualify FM-1 deadlines, cache publication, flash quiescence
or hardware recovery. CPU2 remains independent and OFF at runtime by default.

README assessment: the Build link now exposes profiles. The thirteen-engine feature list
still describes the default standard release; the profile guide explains custom omissions,
compatibility, defaults and limitations. Contributor ownership/workflow is documented in
[extending.md](extending.md#two-repository-profile-workflow) and [BUILDING.md](../BUILDING.md#engine-build-profiles).
