---
name: pr-testing
description: Plan and run PR validation with host, emulator and WebApp tests, then prepare actionable user checks for remaining gaps. Use for PR testing, PR descriptions and test handoffs.
---
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# PR testing

Cover each changed behavior with the cheapest faithful test and leave the owner
only the checks that need their device or judgment. Preserve the current request's
scope: preparing instructions does not authorize test execution, flashing or publishing.

## Plan coverage

1. Establish the candidate's repository, base/head, dirty changes, engine pin,
   profile and flags; for a merge artifact record its base/head and merge SHA.
   Read the relevant changed sources, callers, tests and setup guides. Load the
   [software test routes](references/software.md) when selecting or running checks.
2. In the existing task/PR record, map every changed behavior and relevant regression
   to a check, observable pass condition, evidence/artifact identity, result and
   residual gap. Use **passed**, **failed**, **skipped/unavailable** or **pending**.
   Reuse matching evidence; a generic smoke pass covers only its named assertions.
3. Delegate substantial execution using the shared
   [worker rules](../issue-delivery/references/delegation.md): Terra runs defined
   tests; Sol handles complex coverage decisions and interpretation. Keep shared
   builds under one owner. Read that reference when dispatching workers.

The plan is ready when every changed behavior has a covering check or an explicit
gap. A missing simulator path stays pending; it never becomes an inferred pass.

## Execute within scope

During edits, run affected named units with prerequisite closure and keep development
PRs in draft. At the frozen candidate require the complete applicable
[CI plan](../../../.github/CI.md#feedback-and-merge-stages) before merge; focused
passes remain partial. Reuse successful matching CI instead of duplicating it locally.
Fresh relevant inputs, failures or unresolved concerns determine reruns.

Follow [BUILDING](../../../BUILDING.md#tests) and the local storage wrapper for
builds/tests. Rebuild affected harnesses after source changes. Read compact summaries
first and inspect warnings, skips and relevant failure evidence using the
[evidence workflow](../../../docs/ai-workflows.md#read-results-before-opening-raw-evidence).
Keep raw logs/media under ignored `build/`; return outcomes and evidence paths.

Execution is complete when each selected check has a result and provenance,
including incomplete/blocked runs and skips. Escalate unexpected failures with
their evidence before changing code, baselines or the acceptance scope.

## Prepare the handoff

Use the [PR template](../../../.github/pull_request_template.md) and link the originating
issue. Keep **Validation
performed** separate from **User test instructions** and update both for the final
implementation. Report host, target/static, emulator, WebApp mock/browser and real
FM-1 evidence separately. State exactly what remains and why its software coverage
is insufficient; do not ask the owner to repeat completed software checks by default.

When a [Sol loop](../sol-loop/SKILL.md) was run, include its actual model/effort,
round count, reviewed candidate and final reviewer verdict in **Validation
performed**. Retain unresolved findings, disagreements and later coverage gaps;
an exhausted review budget is not approval. A local review is separate from
required PR review and physical hardware acceptance.

For remaining FM-1 checks, read the [hardware procedure](references/hardware.md).
Keep the complete repeatable route available, but guide a live/resumed session
through only the unfinished checks. Mark unperformed device scenarios **Pending
hardware validation**. Emulator/mock results do not establish physical LCD/panel,
codec sound, USB/TRS reliability, update/recovery or target deadlines.

For software-only checks, give the exact candidate/client identity, setup, command
or local URL, actions and expected results. Documentation-only changes need link
and instruction checks; explain why hardware is unnecessary. Tooling that touches
a device retains its applicable device checks.

The handoff is complete when the user can reproduce each remaining scenario
without guessing prerequisites, actions or success conditions; all template prompts
are resolved, hardware status is explicit and the
[README/changelog/diagnostic assessments](../../../docs/documentation-policy.md)
are recorded. Instructions grant no additional execution or publication authority.
