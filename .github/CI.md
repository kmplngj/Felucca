<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Firmware CI and releases

`CI` runs on pull requests, pushes to `main` and manual dispatch. Its reusable
`Firmware validation` job runs natively on Ubuntu 24.04 x86-64 with Clang for the
host harness and JieLi Clang 4.0.1 for pi32v2. No repository secrets are required.
Build jobs have `contents: read`, checkout does not retain credentials, Actions
are pinned to commit SHAs, jobs time out after 60 minutes, and superseded PR runs
are canceled. Fork PRs use `pull_request`; there is no `pull_request_target` job.
Actions artifact reads use read-only `actions: read` permission for verified
receipt lookup; no write token or repository secret is needed.
Repository Actions policy may require maintainer approval for first-time fork
contributors. This change does not alter branch protection or repository settings.

## Change-based validation

Every PR and `main` push starts CI, including documentation changes. Workflow
syntax, CI helper failure cases and change-selection regressions always run.
The existing `firmware / Target, host and emulator` check aggregates the selected
focused, target/host and full-browser jobs. Every selected job must succeed; a
failed, canceled or unexpectedly skipped selected job cannot turn into a successful
check. Canceled workflows stop their running jobs instead of waiting for an
unconditional aggregate. There are no workflow-level path filters
that could leave a required check pending. Existing check names are preserved.

| Changed inputs | Validation |
| --- | --- |
| Known documentation, documentation images, `AGENTS.md`, Markdown under `.agents/skills/`, review configuration and issue templates | Workflow/helper checks; no firmware build or test dependency downloads |
| Exact selector/helper-contract inputs in `WORKFLOW_CHECK_INPUTS` (`tools/ci_changes.py` and the CI/selector/coverage/scheduler contract tests) | Unconditional workflow/helper checks, including the real scheduler plan and failure/coverage contracts; no firmware, audio or browser builds |
| Portable fixture tests listed in `tools/ci_changes.py`, `tools/fm1_diagnostics.py`, `tests/console_diagnostics.c`, `tests/ui_compare.py` | Portable Python suite with pinned Python/image dependencies; no target SDK, firmware or emulator |
| `tools/firmware_watch.py`, its tests and `data/firmware-watch/**` | Portable Python suite, including ledger migration/integrity and offline Git-DAG recovery tests; no firmware build |
| `web/fm1backup.js`, `web/test_backup.mjs` | Standalone Node backup suite |
| `web/emu/**` | Fresh generated assets, pinned Emscripten build and freshly compiled native/WASM song equality and emulator checks; no target package, DaisySP or unrelated host/sanitizer suites |
| Firmware, build scripts/generators, package/installer/editor inputs, shared host/scheduler/coverage implementations, goldens/budgets, assets, licenses, workflow YAML, or unfamiliar files | Complete existing target, host, sanitizer, web, emulator and reproducibility pipeline |
| Manual CI dispatch, releases, or unavailable change comparison | Complete pipeline regardless of changed paths |

The diagnostics fixture compiles the real `firmware/src/console.c` with bounded
host state stubs, then feeds its CDC command output to the collector parser. It
requires a C99 host compiler (`CC`, default `cc`) in addition to Python; Ubuntu
runners provide one. It checks all counter names, with and without UART/UAC,
without generated firmware assets or a connected device. Changes to `console.c`
continue to select full firmware validation.

Independent selections combine when a PR changes several independent areas.
Selector/helper-contract-only changes use the same lightweight plan in draft,
ready PRs and `main` pushes. The existing workflow/helper job always runs and must
succeed for the required aggregate to pass. Its fixtures exercise selector Git
diffs, the real unit plan, scheduler behavior and refusal of incomplete coverage;
running DSP goldens adds no direct coverage of those changes. Combining these
inputs with firmware retains complete validation, including while draft. Workflow
YAML and the scheduler/coverage implementations are deliberately outside this
exception. Manual/release and unavailable-diff fallbacks remain complete.
Skill scripts, non-Markdown assets and unfamiliar files still require full validation;
mixing skill instructions with firmware changes also selects full validation.
Full validation includes the focused suites, so their separate focused jobs are
not duplicated. Its target/host work and Chromium UI/AudioWorklet checks run on
independent runners. The browser job builds a fresh emulator at the same selected
revision and profile; native/WASM parity checks remain in the host suite.
Firmware is a single translation unit, and host/emulator harnesses
include shared sources: changing an engine or a firmware UI file still runs the
complete suite. Changes to the Python build/package tools still require real
target/package validation even when portable mocked fixtures exist.
`LICENSING.md`, `LICENSES/` and sample attribution are distributed build inputs,
so they require full validation rather than being treated as ordinary prose.

Selection uses a local, complete NUL-delimited Git diff, with no API file limit.
PRs compare their base/head using the merge base, covering all commits in the PR;
main pushes compare event `before`/`after`, covering all pushed commits. Rename
detection is disabled so both old and new paths are considered. Missing history,
new-branch zero SHAs and unsupported events select full validation. The selection
summary and `selection.json` workflow artifact record the suites, reason and paths.
Full history is fetched only for selection and builds that need it.

## Feedback and merge stages

Create development PRs as **drafts**. Run affected local units during edits rather
than the full host suite on every change or merely to open the PR. When the package
is frozen, mark it **ready for review**; complete applicable validation must pass
before merge. Testing only after merge would allow a broken candidate onto `main`.

Known firmware UI, graphics/icons, native engine/effect and selected DSP-helper
changes in a draft PR can run focused host regressions with fresh target/resource/package
guards. Exact matching test entry points also get focused feedback, so adding a
regression alongside its source change does not alone force the full suite.
`tools/ci_changes.py` records the audited source/test paths and units; the scheduler
adds prerequisite closure. UI and engine filename prefixes do not admit unfamiliar
new files. Graphics changes include text, icon decoder/sanitizer and rendering
checks; FM6 and PHYS helpers include their engine-specific fixtures. Shared test
harnesses such as `ui_test.c`, `ui_render.c` and `hostsim.c` retain full validation.
The workflow summary records the stage and focused units. This is not an AI choice
of which tests to omit. Shared contracts, persistence, protocol, build inputs, dependency
pins, unfamiliar paths and mixed independent suites retain full validation even
while draft. Documentation, exact selector/helper-contract and independent-tool selections keep their existing
lightweight checks.

Partial runs use the **Draft feedback** caller. They never report the required
`firmware / Workflow and CI helper checks` or `firmware / Target, host and emulator`
names. A successful focused run therefore cannot establish merge acceptance.
Both ready-for-review and converted-to-draft transitions trigger classification;
ready PRs always run their complete applicable plan. Later code pushes refresh
that candidate. Manual target-only builds remain explicit, and releases always
run full validation.

Successful CI can supply final host/target/browser evidence without an identical
local rerun when revision, inputs, toolchain, profile and flags match. New code
pushes require refreshed validation; failed or incomplete runs remain incomplete.
Early device iteration can explicitly request a target-only exact-PR build; final
standard-profile testing can reuse an automatic PR merge artifact with
`tools/fm1_pr.py NUMBER --automatic` when that merge revision is intended. Neither
a focused run nor a target-only package replaces complete pre-merge validation.

Full host validation partitions the source-derived dependency graph across two
independent target/host runners. It retains every existing golden, sanitizer,
reference, compatibility and profile-applicability obligation. Each shard has a
fresh invocation ID within a run/attempt cohort and exports complete logs, required
outputs and its source/configuration-bound receipt. The aggregate restores the
same generated inputs and compiler identity, independently reconstructs the full
plan and verifies every unit exactly once. It refuses missing, duplicate, stale,
failed, canceled or unapproved skipped work. Matching target/Wasm prerequisite
bytes are required across runners. A single shard or focused report cannot pass
ordinary full-suite verification. Historical exact-PR sources without this interface
retain their original complete single-runner path and verifier.

Only shard 1 reproduces and stages the package/site. Candidate artifacts become
validated artifacts after successful combined host and browser validation. The
browser job continues independently of host work.

## Verified evidence reuse

The standalone backup fixture is the first audited identity-independent scope.
It can reuse a successful automatic CI receipt from this repository when all
tracked inputs, clean recursive engine pins, workflow/helper bytes, Node binary
and runtime versions, platform, locale and relevant configuration match. The
fingerprint includes actual file bytes and modes. A bounded artifact lookup uses
that exact fingerprint, verifies the original successful run/repository/job and
evidence hashes, and reports the original run and revision as **reused**.

Missing, unavailable, expired, malformed or mismatching evidence runs the fixture
fresh. Fork origins and other workflows cannot supply a reusable receipt. ZIP
members, paths and sizes are bounded; reused results are never relabeled as fresh
invocations. Newly executed fixtures alone publish new receipts.

Firmware and browser builds embed Git/PR identity, which changes across merges
even when the tree is identical. They continue to run fresh, as do target/identity
checks and releases. Reuse is not keyed by a branch name or an unqualified green
status, and does not substitute an older package for the current build.

Run selector regressions locally with:

```sh
python3 -m unittest discover -s tests -p ci_changes_test.py -v
uv run --locked --group build tools/ci.py portable-tests
node web/test_backup.mjs
uv run --locked --group build tools/ci.py emulator-tests  # needs the pinned Python deps, clang, emcc and Node
```

The emulator command regenerates assets and compiles both peers. It does not
reuse a previous firmware build. The normal `tests/run_tests.sh` and release
pipeline retain full coverage and strict optional-suite verification.

Emulator-only and full validation also run the [Chromium UI/audio gate](../docs/cloud-testing.md)
once, using the pinned Playwright lockfile under `web/emu/`. It tests the actual
page, AudioWorklet, LCD, keyboard/pointer/encoder input, portrait layout and browser
saves. `build/browser/run-*/summary.json` is the first file an agent should read;
screenshots and a bounded PCM WAV are retained only on failure by default. Browser
diagnostics join the existing 14-day artifacts. No model/API calls are needed.

## Required checks and evidence

| Check | Required evidence |
| --- | --- |
| Target build | Fresh FWSC, app and disassembly; existing HAL, flash-safe loader/RAMTEXT, app/RAM/POOL guards |
| Host regression | Sound goldens, release tails, engine switches, persistence, MIDI, USB and UI checks; both existing O2 and Os/no-SIMD harnesses |
| Robustness | ASan/UBSan and fixed-seed parser/storage/sample fuzz runs |
| References | Pinned DaisySP comparison and checked-in CC0 samples |
| Web/emulator | Node tests and Emscripten build, followed by native/WASM song equality and emulator checks |
| Delivery | Package byte equality from a second clean checkout; firmware and source archive equality for release builds; identical package from unpacked complete source without Git; no tracked changes or baseline updates |
| Release | Required files, attribution and every license, SHA-256 coverage of every bundle/asset file, firmware/source archive checksums and source pin/content verification |

`tools/ci.py verify-tests` requires the schema-versioned report and fresh invocation
ID selected before the full runner starts (`FELUCCA_COVERAGE_REPORT` and
`FELUCCA_COVERAGE_ID`). It verifies the source-derived expected plan, prerequisites
and applicability independently of installed dependencies. Missing sanitizer,
Pillow, DaisySP, sample assets, Node or Wasm coverage cannot disappear from that
plan or be satisfied by a successful process printing a skip. Required nested
producers and Python unittest completion/skips are structured outcomes, including
the Chorus/Send/audio-transition sanitizer variants. Normal/compact output and
serial/parallel scheduling use the same contract; regex diagnostic hints have no
acceptance authority. The verifier rejects absent/failed/blocked/cancelled work,
unapproved or unknown skips, stale identities, changed inputs/configuration,
missing child completion and altered/empty required outputs or adjacent logs.

The diagnostic report binds before/after tracked and untracked source content,
generated inputs, revision/dirty state, exact clean Engines pin, profile/config,
resolved compilers and observed effective argv. O2 and Os/no-vectorization regression
compiles and actual selected baseline arguments are checked explicitly. Invocation
IDs, compiler shim paths and timings stay out of reproducible release provenance.
See [runner instructions](../BUILDING.md#tests) for strict local reproduction.
Linux uses `perf_event_open` to count user-space instructions of each regression
worker's calling thread. Both host CPU budgets are checked when every count and
the matching platform/compiler baseline are available. A denied or unavailable
counter, invalid count interval, or absent matching host baseline permits a whole
CPU-budget skip, with the exact reason and selected paths retained in the test log
and Actions summary. An available budget with missing entries fails the gate;
CI never creates baselines or changes PMU access policy. Host wall time is
informational; pi32v2 disassembly cost is a static heuristic. See
[host measurement policy](../docs/performance.md#host-regression) for counter and
baseline details. Real FM-1 audio
deadlines, scanning, USB/MIDI, listening and update/recovery remain device checks.
This infrastructure change does not change firmware, flags or test baselines.
The only permitted fixture skip is the official V15 restore comparison: that
requires the vendor firmware, which is deliberately not redistributed here.

Disabled opt-in TSAN is explicitly not requested; MACRO-specific units are excluded
only when the resolved source/profile omits engine 14. Available CPU comparisons
must contain every required budget entry; C1_HOST retains its explicitly unqualified
CPU comparison while its sound/state checks run.
The MACRO pack's separately opt-in `--webapp PATH` parser check is also explicitly
not requested when that actual argument is absent; native pack/serializer/MIDI
checks remain required. Supplying it requires successful real client parsing.

Current sources require the FX rest regression with `--require-rest`. Historical
exact-source builds run their own selected runner/verifier and retain that source's
FX dependency policy. The Actions summary labels sources predating this contract as
legacy transcript verification, never structured qualification. Target-only scope
still explicitly omits host coverage; no new fallback in the current verifier accepts
legacy banners. Source/archive and release reproduction retain their existing
selected-source behavior and stable provenance.
Current verified no-Git source archives bind identity through the existing
`SOURCE-PINS.json` full-tree verifier, retaining its extra-file/mode/symlink checks
and external-uv-environment/no-bytecode rules. A missing Git directory never enables
a transcript-only acceptance fallback.

## Dependencies and provenance

Python 3.12 and Node 22 are selected explicitly. Pillow, fontTools and Brotli versions
are locked in `uv.lock` from the `pyproject.toml` `build` group; Raqm is mandatory
and Brotli decodes the M8Stealth WOFF2 inputs. CI synchronizes this group with uv
and keeps its environment outside the source checkout, including for verified
source-archive reproduction. Exact-PR builds retain the trusted workflow
revision's dependency project before selecting historical firmware sources.
Provenance records all three versions and the selected UI font. Emscripten 6.0.11 and DaisySP
are fetched from fixed source commits. The target cache contains only JieLi's
`jieli-linux-toolchains-20260730.1` and the three AC79 SDK files. Its key includes
runner OS/architecture, actual toolchain/SDK pins, expected SDK hashes and the
toolchain installer recipe, so unrelated build/checker edits do not invalidate it. Every cache hit rechecks the
compiler/package identity and SDK SHA-256 values from `tools/build.py`.

uv and npm download caches use their respective dependency/lock files.
Emscripten caches are keyed by runner OS/architecture, emsdk source commit and
SDK version; DaisySP uses its exact source commit. Restored reference checkouts
must match their pins and tracked files must be clean; emsdk install/activate
still runs to establish the current environment. Playwright's browser download
cache uses OS/architecture and the emulator's package lock. Browser system
dependencies are still installed; locked uv synchronization and npm install
verify/install the requested packages. Cache misses remain supported normal operation. GitHub's
branch/PR cache scoping applies; a PR cache is not promoted to the default branch.
No firmware objects, generated assets, test binaries/results, goldens or build
directories are cached. Target builds and all selected tests always execute.

The SDK downloader first tries JieLi's pinned Gitee SDK commit, then a pinned
[ChoralRoot mirror](https://github.com/Quixotic7/ChoralRootFM1/tree/d09c687d8ee1850fc1360c080aca41763be998ca/tools/sdk)
of the same three Apache-2.0 files. Both sources must match Felucca's reference
hashes. Downloaded files are verified before replacement. No SDK binary is added
to this repository. The existing toolchain downloader uses a moving vendor URL:
CI rejects a different package/compiler identity, but no vendor archive checksum
is available here. Provenance includes the downloaded compiler's SHA-256; this
does not establish an independently authenticated vendor archive.

`build/ci/provenance.json` records the actual checkout revision/date, runner,
Python/font dependencies, target compiler/hash, SDK hashes, default target flags,
host compiler/platform, both regression flag sets and selected baseline paths, Emscripten,
Node, DaisySP and sample hashes. Action inputs pin Python/Node minor versions,
not every runner OS package or patch update. Reproducibility is checked between
two checkouts in one run; cross-runner byte identity is not promised. Updates to
these pins must pass the same goldens and package checks without blanket updates.
Diagnostics keep the actual `built_at_utc` clock. Release provenance omits that
clock; tar/gzip metadata uses the source commit timestamp, with normalized
ownership and permissions. Complete source preserves each committed executable bit
and hashes every tracked firmware/Engines file in `SOURCE-PINS.json`; provenance
records the source archive and manifest hashes plus both revisions. With profile
definitions present, provenance resolves the selected profile directly from current
inputs before building and records its IDs, source/asset/license selections and
input hashes; it never reuses a previous generated profile manifest. Rebuilding
unchanged content in the same environment
therefore produces the same release archive even when local file metadata changes.

## Debug artifacts and cost

The full host runner schedules independent compile-and-test units concurrently,
with at most four workers by default. Shared FX/UI outputs and web fixture
consumers have explicit dependencies. Every existing compiler configuration,
golden, sanitizer and coverage check still runs. `TEST_JOBS=1` uses the same unit
plan serially for debugging and comparisons; see [host runner controls](../BUILDING.md#tests).
Each unique `build/host/test-run-*/summary.json` records unit timings, dependencies
and results. Its adjacent unit logs are retained in diagnostics even on failure,
and the merged test log remains ordered. `coverage.json` binds its plan and unit
logs and required output hashes; per-unit coverage directories retain observed
compiler and child diagnostics. An
unsuccessful dependency unit, failing compile/test or interrupted runner cannot
produce the success banner. Optional local skips remain explicit and CI still
rejects them through its coverage verifier. The runner's process groups are terminated on
cancellation; a killed runner still has the upload limits described below.

Each run uploads available diagnostics with `if: always()`, including failures:
setup/build/test/reproduction logs, provenance, target ELF/map/disassembly,
loader ELF/disassembly, UI PNGs, host WAVs and selected FM6/reverb examples.
The host stress matrix retains its scenario inputs, JSON reports, replay logs and
raw PCM/WAVs under `build/stress/` in the same diagnostics artifact, including failures.
Setup failures may have only checkout details; the complete Actions step logs
remain on the run page. A canceled job can upload available diagnostics while
its runner remains alive; a killed runner cannot guarantee an upload.

Target/host validation stages candidate firmware and release artifacts. The final
required check promotes them under the existing `firmware-*` and `release-*` names
only after all selected validation, including full-browser checks, succeeds.
Candidate artifacts are not accepted firmware; device checks remain separate.

Diagnostics expire after 14 days; successful firmware/release artifacts after
30 days (subject to repository policy). Download them from the Actions run's
Artifacts section. Artifact access follows repository permissions and may
require sign-in. Only explicit build paths are uploaded, never an environment
dump, credentials or dependency caches. Public GitHub-hosted runner use follows
GitHub's plan; private forks can consume minutes and artifact storage. There is
two target/host shards and one parallel browser job for a full run, with focused
independent jobs when applicable, and no recurring nightly schedule. Focused emulator diagnostics include its fresh
WASM, copied browser files and native song output; focused checks do not upload a
validated firmware package. Documentation-only runs upload workflow diagnostics.

### Host runner measurement (2026-10-18)

One before/after comparison used firmware revision `2a8221a929a127fe4a155e31e1dd78658fd45ecf`
and Engines pin `9630426f5c4a34a209ca851356fbe8ba3c4c6d19` in separate fresh worktrees:

| Full host runner | Elapsed |
| --- | ---: |
| Original serial script | 1,825.95 s (30:26) |
| Concurrent units, `TEST_JOBS=4` | 514.21 s (8:34) |

That pair is **3.55 times faster, with 71.84% less elapsed time**. Measurements
include runner preflight and all host/sanitizer/web/native-Wasm tests, excluding
dependency setup, target builds and the separate Chromium gate. The Linux x86-64
cloud host had a four-CPU quota and 16 GiB RAM; Python 3.12.14, Clang 19.1.7,
GCC/G++ 14.2.0, Node 24.19.0 and Emscripten 6.0.11 were identical for both runs.
Target builds used the pinned JieLi Clang 4.0.1 package and SDK inputs above,
default standard profile/M8Stealth, checked-in samples and selective minsize.
This is a local cloud comparison, not a measured post-change GitHub Actions time.

Both complete logs pass `tools/ci.py verify-tests`. All 208 runtime headings match
in order; all 151 original `run` labels and 107 compiler-command lines are retained.
All 116 scheduled units pass. Nine scheduler fixtures cover overlap and limits,
dependency ordering, compile/test failure propagation, cancellation including
grandchildren, checkout locking, serial overrides and invocation from another
directory. CI helper/source-archive/selection fixtures and actionlint pass. The
fresh emulator also passes all seven Chromium UI/AudioWorklet smoke checks.

Normalizing both builds to the same commit and dirty display identity gives
byte-identical app (485,924 B), loader (6,934 B) and FWSC (610,090 B), with zero
firmware/RAM/POOL/NOINIT delta. RAM is 62,024 B, POOL 336,440 B and NOINIT 15,568 B;
all existing target guards pass. The original timed baseline used its clean
identity (485,916 B app); the extra eight bytes in the dirty identity are metadata.
No sound, CPU, target or union baselines were updated. Host instruction counts
are unavailable through `perf_event_open`, and C1_HOST does not check CPU budgets;
both runs retain those explicit exceptions. The only fixture skip is the
unredistributed official V15 package. No physical FM-1 was needed for this runner
change, and no device performance claim follows from the host elapsed times.

## Downloads and checksums

For published packages, open this fork's [Releases](https://github.com/kmplngj/Felucca/releases)
and choose the intended version, checking whether it is marked as a prerelease. Download
the complete `felucca-VERSION-release.tar.gz` archive and its matching `.sha256` sidecar
into a fresh directory. The archive includes the installable `.fwsc`, raw app `.bin`,
`BUILD-PROVENANCE.json`, sample attribution, `LICENSE`, `LICENSING.md`, third-party
`LICENSES/` and its own `SHA256SUMS`. Retain attribution and license files when distributing
the package. Pass the `.fwsc` to the [installer](../BUILDING.md#install); the raw app and
diagnostic files are build/debug material.

Replace `1.6-rc1` below with the version shown on the chosen release. Run one block from
the directory containing both downloaded files. Each `&&` continues only after the
preceding command succeeds.

On macOS:

```sh
shasum -a 256 -c felucca-1.6-rc1-release.tar.gz.sha256 &&
tar -xzf felucca-1.6-rc1-release.tar.gz &&
cd felucca-1.6-rc1 &&
shasum -a 256 -c SHA256SUMS
```

On Linux with GNU Coreutils:

```sh
sha256sum -c felucca-1.6-rc1-release.tar.gz.sha256 &&
tar -xzf felucca-1.6-rc1-release.tar.gz &&
cd felucca-1.6-rc1 &&
sha256sum -c SHA256SUMS
```

Require every listed file to report `OK` before installation. A missing file or a checksum
mismatch fails the check: obtain an intact download and verify again. These checks detect
download corruption; they do not establish publisher authenticity or device compatibility.

If downloading individual release assets instead, save the complete asset set and the
release-page `SHA256SUMS` together in a fresh directory, then run `shasum -a 256 -c SHA256SUMS`
(macOS) or `sha256sum -c SHA256SUMS` (Linux) there. That manifest uses GitHub's flat asset
filenames, including standalone license texts, both firmware/source archives and
their sidecars. The manifest inside the firmware archive instead uses its unpacked directory structure, including `LICENSES/`
paths. Keep each manifest with the files it describes; the sidecar checks the archive itself.

For development builds, open a successful run in [Actions](https://github.com/kmplngj/Felucca/actions)
and use its Artifacts section. These ZIP downloads are temporary build output, separate
from published tag releases; access and retention are described under
[Debug artifacts and cost](#debug-artifacts-and-cost). Firmware artifacts contain the
`.fwsc`, raw app, provenance and license material; diagnostics contain logs and debugging evidence.
The package digest in `build/ci/package.sha256` names the CI build path, so compare it with the
digest of the downloaded `.fwsc` rather than use the release-manifest commands unchanged.

Manual `Release` dispatch produces artifacts without publishing. Tag release publication
does not flash a device or deploy the Pages site. Fork-site publication follows the
separate process below.

## Fork site deployment

The fork's [installer](https://kmplngj.github.io/Felucca/webapp/installer/),
[browser demo](https://kmplngj.github.io/Felucca/webapp/try/) and
[editor](https://kmplngj.github.io/Felucca/webapp/editor/) are hosted together on
GitHub Pages. Configure this repository's Pages source as **GitHub Actions**.

After a full successful `main` build, CI tests a pinned
[Felucca-WebApp fork](https://github.com/kmplngj/Felucca-WebApp) and stages the site
with that run's firmware, emulator, licences and attribution. The WebApp checkout's
full commit is pinned in `.github/workflows/build.yml`; update it deliberately to
adopt editor changes. The installer offers a development build from `main`, not
necessarily the latest tagged release. The demo retains its preview label.

The `Fork Pages` workflow downloads only the matching `site-RUN_ID` artifact from
successful CI in this repository on `main`, verifies its firmware revision and run
provenance, then deploys it. PR runs, failed CI, target-only PR builds and focused/docs
runs cannot supply a deployment. Documentation-only changes leave the live site intact.
Deployment permissions exist only in the separate Pages deploy job.

To republish an existing artifact, dispatch `Fork Pages` on `main` with its original
successful main CI run ID. If no site artifact exists, run full `CI` on `main` with
the PR/commit inputs empty first. Site artifacts are retained for 30 days.

Check [sources.html](https://kmplngj.github.io/Felucca/sources.html) or
[provenance.json](https://kmplngj.github.io/Felucca/provenance.json) for the deployed
firmware, engine and WebApp revisions. The wiki remains upstream documentation;
the hosted site may lag behind local or PR sources. Browser checks do not establish
FM-1 update/recovery, Web MIDI or device audio reliability.

## Exact PR revision builds

The [PR firmware helper](../BUILDING.md#test-a-pull-request-on-hardware) uses
manual `CI` dispatch with `pr` and a full `commit` SHA by default. A short resolver job
checks the PR and verifies that the commit is reachable from its current head.
The reusable validation workflow checks out that SHA in every job; manual
dispatch defaults to the complete pipeline, including target guards, host,
sanitizer, emulator and clean-checkout package reproducibility. Ordinary PR
events keep the GitHub merge checkout and existing check names; ordinary manual
CI remains available with empty inputs. Exact-revision requests have separate
concurrency groups from automatic PR and main runs.

An explicit `validation: target` dispatch is allowed only with a verified PR and
commit, with no release version. It uses the same target-build step, app/loader
resource checks and build flags, adds the selected source's static target-budget
and FWSC structure/CRC checks, and uploads immediately after those checks pass.
Host/sanitizer, emulator/browser and clean-checkout reproducibility steps and
their dependencies are omitted. This is a hardware-iteration artifact, not full
validation or a release. Automatic PR/main checks and releases retain their
existing validation selection and cannot opt into target-only mode.

Run titles append ` (target)` and target artifacts are named
`firmware-target-RUN_ID`; full names remain backward-compatible. Mode-specific
concurrency groups prevent the two modes canceling each other. The helper never
substitutes a target run for full validation and checks the scope recorded in
target provenance. `--no-build` and resume must use the same mode.

Manual CI validation jobs use distinct `Manual target / …` / `Manual full / …`
check prefixes set by the reusable-workflow caller; child job names stay static,
including when skipped. Automatic PR/main check names stay unchanged. GitHub attaches manual
checks to the workflow branch commit, which can differ from the selected firmware
commit; reusing the automatic required-check names here could incorrectly satisfy
a PR check with a build of another revision or validation scope.

The workflow retains `tools/ci_target.py` from its own revision outside the source
checkout before checking out the selected SHA. Thus older PRs can use target-only
delivery without modifying their sources, provided their CI exposes build-identity
and pinned-engine provenance APIs (as #392 does). Earlier revisions fail target
preflight with an explicit `--validation full` instruction; full delivery retains
their original provenance format and checks without requiring these newer APIs.
Full validation checks for the selected source's browser package/lock files before
building, so historical revisions lacking that required harness fail promptly
instead of after the host suite. Use compatible sources/workflows; tests are not
silently skipped to make such a full request succeed.
Their firmware, build tools and budgets
still come from that selected revision. This helper records only target dependencies
and limitations; full/release provenance and reproducibility remain unchanged.

Run titles include `PR firmware #NUMBER @ SHA`. The helper matches that title
and the workflow branch, requires a successful run and a nonexpired
`firmware-RUN_ID` artifact, then verifies `provenance.json`, `package.sha256` and
the FWSC structure before invoking the existing installer. Failed validation,
missing artifacts or mismatched provenance/checksums prevent installation.
Checksums detect corruption, not trustworthiness of PR code; choose the revision
you intend to run. Both current and reachable historical PR revisions use their
own firmware sources and build defaults.

The resolver has only `contents: read` and `pull-requests: read`, uses the job token only in its GitHub
API step, and does not retain checkout credentials. Build jobs retain existing
permissions and pinned dependencies. Dispatch requires Actions write access;
artifact reads require sign-in and appropriate repository access. No release,
Pages deployment or remote flashing occurs. The helper runs on the computer
connected to the FM-1 and preserves the installer's interactive confirmation.

### Reuse an automatic PR merge build

From a trusted caller checkout with uv installed (`brew install uv` on macOS),
`uv run --locked --group midi tools/fm1_pr.py NUMBER --automatic` downloads and installs an existing
automatic PR artifact without dispatching CI. Add `--download-only` to verify
without installer setup or hardware access. `--no-build` is accepted but redundant.

The helper snapshots an open PR's head, base and GitHub merge commit, verifies the
merge's ordered parents against that base/head, and searches the `ci.yml`
`pull_request` runs for that head. It requires a successful run associated with
the same repository PR and base/head, with one live `firmware-RUN_ID` artifact.
The existing provenance, SHA-256 and package checks must then verify the merge
revision. The printed firmware commit and download directory use that merge SHA;
the PR head and base SHA are also printed. Failed, running, stale or artifactless
runs cannot be installed. A later push does not change the selected snapshot.

This mode installs the PR merged with its target branch. Exact-head and reachable
historical builds remain the default mode; automatic mode's optional `--commit`
must pin the current PR head. Target-only validation, custom workflow branches
and source worktree operations are rejected with `--automatic`. No workflow or
required-check behavior changes, and no new firmware build is requested.

## Releasing

Push a `vX.Y`, `vX.Y.Z`, `vX.Y.Z.W` or `vX.Y-suffix` tag; each numeric component
must be one digit because the existing package product identity has that limit.
The workflow validates the version, builds the versioned target, exercises that
exact FWSC with the existing loader/update tests, reproduces the package, then
verifies the complete release directory. No tag is created by CI.

A separate job downloads and checks the validated bundle before receiving
`contents: write` publication privileges. It publishes the FWSC, app,
`SHA256SUMS`, provenance, attribution, license documents and a tar.gz containing
all files and third-party license texts. The archive has its own `.sha256` file.
Every third-party license is also uploaded as a standalone release asset. GitHub
flattens asset filenames, so the release-page `SHA256SUMS` covers those flat names,
including the archive and sidecar. The manifest inside the archive instead covers
the unpacked directory structure, including `LICENSES/` paths.
Suffix versions become prereleases; an existing release is preserved without
replacing its assets. Nothing flashes a device or publishes an installer/Pages.

To rehearse, manually dispatch `Release` with a version such as `1.6-rc1` from
the desired source branch. It runs all checks and produces release artifacts
without executing the publisher. Do not push a tag merely to test CI.

## Sources of the design

- [Jangada](https://github.com/zednaked/jangada/blob/db41fd9845af6c8ebfbc348dafc33d98ef83a27d/.github/workflows/ci.yml): native target CI, full suite and second-checkout byte comparison.
- [ChoralRoot](https://github.com/Quixotic7/ChoralRootFM1/blob/d09c687d8ee1850fc1360c080aca41763be998ca/.github/workflows/release.yml): dependency/layout checks, licensing and separate read-only build/write publisher.
- [Melodee](https://github.com/keremimo/melodee/blob/1673b244fe1dbd2cb771b828da230d09a6db6fb9/.github/workflows/nightly.yml): downloadable artifacts and source/compiler provenance.
- [Ghoulbox](https://github.com/jasonpersinger/ghoulbox-fm1-dungeon-synth/blob/8081206b951353b8d04886eeae615feb18123ef5/.github/workflows/host-tests.yml): bounded/read-only CI. Felucca retains target/image checks instead of host-only omissions.

Failure diagnostics and strict optional-suite coverage improve on these examples.
Nightlies, extra firmware variants, reviewed Linux CPU baselines and Pages
deployment are separate follow-ups rather than prerequisites for this gate.

### Pinned synthesis engines (1.6.1)

Every build/test checkout initializes `firmware/engines` recursively at the committed gitlink;
the second clean checkout does the same. Provenance includes the Engines repository, exact
revision and MIT license, and refuses missing, mismatched or dirty dependency sources.
The full runner checks its standalone goldens and the same engine host against Felucca's tables.
GitHub-generated source ZIP/tar files omit submodule contents. Tagged and manual
release builds now provide `felucca-VERSION-source.tar.gz` and its `.sha256`
sidecar in the release artifact; tagged publication adds both to release assets.
Use that complete source asset or a recursive Git clone. It exports only committed
firmware blobs and the exact initialized, clean Engines gitlink, including all
build generators/assets, profile definitions, tests and license texts. Firmware
tracked changes and missing/wrong/dirty Engines sources fail export; local Git
metadata, build output and untracked files never enter it.

To verify and build the complete source, follow
[Get the source](../BUILDING.md#get-the-source). `SOURCE-PINS.json` records both
commits, the firmware commit timestamp, and each source file's SHA-256/executable
mode. Builds of the extracted tree verify this manifest before generating outputs,
without Git or a submodule fetch. Source verification rejects Python bytecode
anywhere in the tree before loading repository helpers; archive build/CI tools
load the verifier from source and suppress cache writes in child generators.
Repeated archive builds remain valid. Toolchain/SDK prerequisites remain external.
Release CI compares the source archive across two clean checkouts and rebuilds its
unpacked contents to require byte equality with the original `.fwsc`. Publishing
requires the source archive/manifest to match `BUILD-PROVENANCE.json` and checks the
source sidecar before creating the flat `SHA256SUMS` asset. Existing firmware archive
contents and nested licensing paths are retained.
