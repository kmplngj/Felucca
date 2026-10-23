<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Batch related issues for one hardware handoff

Prefer one bounded PR for two or three related issues that share a subsystem and
device test setup. Extend an existing relevant draft PR when appropriate. The goal
is fewer firmware builds, installations and repeated hardware setups, while keeping
each change reviewable and diagnosable.

- Check current source, merged PRs and existing tests before selecting work: an open
  issue may already be implemented. Complete missing evidence instead of rewriting it.
- Declare the batch's issue list, scope and acceptance checks before implementation.
  Keep changes in separate logical commits and map each issue to its focused tests.
  Leave unrelated features, large experiments and independent storage/protocol/boot
  migrations for another batch. Freeze scope before final validation; new ideas go
  into the next round rather than continually invalidating a hardware candidate.
- Capture one clean shared baseline. Reuse existing artifacts only when revision,
  relevant source/asset hashes, engine pins, toolchain, profile and flags match; retain
  their provenance. Preserve per-issue isolated comparisons when measuring one cause,
  and report the integrated resource delta separately. Do not add overlapping savings.
- During implementation, rebuild and run focused host regressions for each issue.
  When delegating, assign file/region ownership and use isolated test outputs; one
  coordinator owns shared generated assets and target/emulator builds. Do not run a
  complete firmware build or full suite independently in every subtask. Target-only
  probes remain appropriate when needed to decide a compiler or resource tradeoff.
- Include affected cross-feature reference tests in those focused checks: for DSP
  changes, trace preset/engine-switch and mixed-effect audio oracles as well as the
  new feature's tests. Resolve intended transition differences before the long
  integrated run; retain historical goldens when the existing contract can be isolated.
- At the frozen integrated revision, run the full applicable validation once and
  produce one fresh target artifact per required build variant, with aggregate budget
  checks. Reuse successful CI evidence for that exact revision/variant where it covers
  the required checks. Fix failures and rerun affected checks; finish with the required
  integrated CI checks passing on the final head. Batching does not waive sound,
  compatibility, deadline or hardware requirements.
- Provide one combined hardware procedure: backup and install once per required
  artifact, reuse the same known project/MIDI/audio setup, run each issue's targeted
  checks, then one shared mixed-load regression. Where A/B evidence is necessary,
  compare the baseline with the combined candidate and retain per-issue observations.
  Name the exact commit/package, defaults, variants and expected results. Do not ask
  for a new flash after each issue. Unperformed device checks remain pending; do not
  flash, merge or publish beyond the user's authorization.

Apply the [firmware invariants](../AGENTS.md#invariants-that-changes-must-preserve)
and [validation requirements](../AGENTS.md#build-and-validate) throughout.
