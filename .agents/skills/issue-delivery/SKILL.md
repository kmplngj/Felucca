---
name: issue-delivery
description: Deliver individual issues or pull requests, or autonomously work through an explicitly requested backlog. Use for issue implementation, PR follow-up, and backlog triage through validation, review and handoff; preserve review-only requests as read-only.
---
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Issue and PR delivery

Produce changes the owner can verify and accept efficiently. Reassess the current
problem and take the shortest supported path to a testable candidate. Finish bounded
work, and keep implementation progress separate from review and hardware acceptance.

## Select the scope and authority

| Request | Working scope | Completion |
| --- | --- | --- |
| Individual issue | That issue and necessary prerequisites; inspect linked work before implementing | Resolved with evidence, or a reviewable candidate with explicit remaining gates |
| Individual PR | The requested review, fixes, CI or review follow-up on its current head | Findings delivered or requested fixes validated; handoff/merge only within authorization |
| Autonomous backlog | The explicitly selected repository/repositories and issue set | Continue across independent packages until all selected work is assessed and eligible work is finished, or only blocked work remains |

For backlog mode, also read [the backlog loop](references/backlog.md). A repository
being accessible does not put it in scope. Establish company ownership from remotes,
organization access and local checkouts only when the request asks for discovery;
ask about ambiguous ownership before including it.

The current request controls permissions. A review-only request remains read-only.
Automatic skill loading does not start backlog processing or grant remote writes.
An explicit autonomous-delivery request using this workflow authorizes scoped
implementation, commits, branch pushes, PR creation, review requests, material
issue/PR updates, justified follow-up issues and merges that pass the gate below,
unless the user narrows that mandate. In individual issue/PR mode, use only the
actions requested or clearly implied. Continue routine authorized work without
repeated permission requests. A request to commit to main is not a request to push.
An explicitly requested local commit to main is distinct from accepting or merging
a PR; report its remaining validation/review gates without claiming acceptance.

Production deployment, destructive data changes, device flashing, releases and
repository-setting changes need separate explicit scope. Preserve repository
protections. Prepare a concrete result before asking for a necessary decision.

## Establish current facts

1. Read the implementation repository's instructions. Inspect branch, HEAD,
   worktrees, dirty files, active work and open PRs. Preserve unrelated changes;
   isolate overlapping work rather than overwriting it.
2. Read the complete issue/PR, relevant comments, linked issues and open/merged
   PRs. Record the base and current head. Follow transfers and redirects. Use the
   [repository ownership rules](../../../docs/repository-ownership.md)
   before choosing the implementation or filing follow-up work; consult current
   issues, comments and PRs across all four Felucca repositories for ownership and
   duplicates. Check live access and Issues settings before issue creation.
3. Inspect current source, callers and tests; use CodeGraph first if indexed.
   Reproduce the relevant behavior where practical. Classify the work as current,
   partially done, already done, superseded, in progress elsewhere or unresolved.
   An issue description is a hypothesis, not proof that a defect remains.
4. State the acceptance checks and remaining gap. Reuse an existing implementation
   or PR when appropriate. Close an issue only with unambiguous completion evidence
   and authorized issue writes; otherwise record the remaining question. Merged
   code alone does not establish pending hardware acceptance.

Proceed when the implementation owner, current gap, active work and required
validation are known; research further when a concrete unresolved question affects
correctness or acceptance. Reuse context and evidence already established in the
run, refreshing facts affected by new commits, changed scope or external state.
Keep adjacent ideas in the existing queue rather than expanding the investigation
or writing another adoption plan. For research-only requests, deliver the requested
analysis. If access or a decision blocks one package, keep its status explicit and
continue independent work within scope.

## Choose a bounded package

Prioritize relevant regressions, impactful bugs and enabling prerequisites using
impact, dependencies, risk and verification effort. For related issues, read the
[batch procedure](../../../docs/development-batches.md); prefer two or three that
share a subsystem and test setup. Keep independent changes in separate PRs and
freeze each package's issue list, scope and acceptance checks before final testing.
Prefer finishing an active package to starting another. Resolve routine implementation
choices within the established contracts; escalate actual product, design or hardware
decisions with a concrete recommendation. Queue unrelated discoveries for a later batch.

Implement bounded UI defects and necessary functional improvements. For unresolved
design foundations or major visual changes, prepare options, a recommendation and
the decision needed. Keep experiments in isolated prototypes, branches or draft
PRs with a hypothesis, check method and open decision. Adopting experimental
behavior as a product default requires an explicit decision.

## Reuse upstream implementations before redesigning

When a selected feature or fix already exists in upstream or another firmware fork,
prefer adopting its implementation over recreating it from a description. Inspect
the relevant current donor source and dependencies; reuse existing source reviews
when they cover the exact revision and files. Broad donor surveys belong to a
requested research/watch task or a specific unresolved source-selection question.

Pin the donor repository and full commit, retain attribution and notices, and check
the copied files, assets and transitive dependencies under
[CONTRIBUTING](../../../CONTRIBUTING.md), [LICENSING](../../../LICENSING.md) and the
repository ownership rules above. Unresolved provenance or incompatible licensing
blocks copying; a donor's root licence alone is insufficient.

Start with the smallest faithful port and the glue Felucca needs: target compiler
and HAL, part/voice ownership, memory and interrupt limits, stable IDs, persistence,
protocol and native controls. Preserve donor DSP behavior where compatible and
record necessary deviations. Reuse donor tests and fixtures where applicable, then
cover Felucca's integration contracts. Donor success does not establish FM-1 acceptance.

Optimize when measurements show a budget/deadline problem, a reproduced defect
requires it, or optimization is explicitly in scope. Otherwise retain the adopted
implementation and queue optional improvements. Keep a working port as the baseline
for subsequent optimization; change one measured cause at a time. If it cannot run
within the target's limits, make only the adaptations needed to establish that
baseline and record the limitation. Avoid combining adoption with speculative DSP
rewrites, new abstractions or unrelated cleanup.

## Delegate with the requested models

Delegate useful independent investigation, implementation or review tasks. Keep a
small task local when delegation adds no value. Select model and effort through
the runner's actual configuration or spawn parameters, not just the worker prompt.

| Runner | Task complexity | Worker model | Reasoning / effort |
| --- | --- | --- | --- |
| Codex | Bounded investigation, ordinary implementation or focused review | GPT-6.1 Sol (`gpt-6.1-sol`) | `medium` |
| Codex | Difficult diagnosis, cross-module changes, DSP/arithmetic, concurrency or persistence contracts | GPT-6.1 Sol (`gpt-6.1-sol`) | `high` |
| Claude Code | Bounded investigation, straightforward fixes or focused checks | Claude Sonnet 5.5 | `medium` |
| Claude Code | Substantial implementation or review with several interacting paths | Claude Sonnet 5.5 | `high` |
| Claude Code | Difficult root cause, architectural decisions or high-risk cross-cutting work | Claude Opus 5.5 | `medium` |

Resolve Claude model IDs against the runner's available models and confirm the
requested version. Use an alias only when it resolves to that exact version.
Configure each worker's effort as well as its model; inherited defaults or a
generic `opus`/`sonnet` alias alone do not establish the requested selection.
For Codex, use `model="gpt-6.1-sol"` and `reasoning_effort="medium"` or `"high"`
where those spawn fields are exposed. If an override requires a fresh context,
start the worker without inherited history and supply a self-contained assignment.

If the requested model/effort cannot be selected or delegation is unavailable,
report the limitation and do useful work serially in the current session. Do not
silently substitute another model/version or claim a prompt configured the runner.
Include actual selections in the completion evidence when the runner exposes them.

Give each worker the repository/base revision, objective, acceptance checks,
relevant instructions, owned files/regions, forbidden overlaps and expected result.
Parallelize only disjoint edits and independent tests. Use isolated outputs; one
coordinator owns shared generation, integrated builds, GitHub writes and merges.
Workers return changes, evidence, skips and open questions. Integrate and inspect
their work before claiming completion.

## Implement and validate

Keep logical commits and focused diffs. Read [BUILDING](../../../BUILDING.md) and
the subsystem guides required by AGENTS before building, testing or changing
behavior. Add tests when they meaningfully protect the changed behavior. Preserve
unrelated work and existing compatibility contracts.

For optimization, compare an unchanged baseline with one changed cause using the
same toolchain, profile, flags and workload. Follow
[performance requirements](../../../docs/performance.md); retain exact revision
and resource provenance, including integrated deltas for a batch.

Run affected checks during implementation, then the full applicable integrated
validation and fresh target build at the frozen firmware candidate, following the
batch procedure. Rebuild affected harnesses after source edits. One coordinator
owns integrated builds; workers use focused checks and isolated outputs. Reuse
successful evidence only when its revision, inputs, toolchain, profile and flags
match the candidate and it covers the required checks. Repeat checks for changed
inputs, failures or unresolved concerns. Use emulator/simulator checks where useful
and exercise browser flows and relevant errors yourself where available, following
the repository's browser gate. Inspect warnings, skip hints and failure logs. Verify
CI for the current PR head, not a superseded commit.

Report each check as passed, failed, unavailable/skipped or pending manual/device
validation. Separate host regressions, target static budgets, browser behavior and
real FM-1 evidence. Device audio, timing, panel/LCD, USB/TRS and recovery checks
remain pending wherever host/browser coverage is insufficient. Unrelated baseline
failures must be identified with evidence, not presented as a passing suite.

## Complete the review loop

For an implementation-ready PR with authorized remote writes, obtain Codex Review.
Automatic CodeRabbit feedback is advisory under
[the CodeRabbit guide](../../../.github/CODERABBIT.md). Inspect available relevant
feedback without waiting for CodeRabbit to run or its quota to reset. Check existing
reviews and repository review configuration first; reuse current coverage and
request deliberately rather than posting repeated commands.
Review requests belong to the authorized delivery workflow; ordinary status comments
must not accidentally address bots or copy their command handles.

Wait for required review results and inspect all relevant findings and threads
against the current code and requirement. Apply sound corrections; explain inaccurate or inapplicable
suggestions with evidence. Rerun affected checks, verify CI on the new head and
batch related corrections before requesting fresh review after material changes.
Retain coverage identity: a review of an earlier head does not automatically cover
subsequent changes.

When required review/CI is unavailable, failing or persistently pending, record
the exact missing gate and move to independent work. Missing results are not approval;
avoid polling or requesting reviews indefinitely without new evidence.
Codex unavailability leaves the required review pending unless an explicit
repository/user policy accepts an alternative. CodeRabbit availability is not a
merge prerequisite.

## Merge gate and hardware handoff

Merge only when authorized by the current request or explicit autonomous-delivery
mandate, and all of these conditions hold for the final candidate:

- Acceptance checks establish the requested behavior and compatibility.
- Relevant tests/builds and required CI pass for that revision and required variants.
- Required reviews cover the candidate, their feedback has been examined and
  material findings resolved. Apply the review availability policy above; never
  waive missing review on your own.
- Product/design decisions are settled and repository rules/protections are met.
- Required physical hardware acceptance is complete for the candidate. CI,
  simulation and emulation cannot replace checks that require a real FM-1.

Otherwise leave a ready-to-review or hardware-pending PR with exact remaining
checks. Use [the PR-testing skill](../pr-testing/SKILL.md) for PR descriptions and
any user-test handoff, including documentation/tooling work. Provide a combined
device procedure for a batch, from a known state through exact buttons, gestures,
pages, knobs and expected results. Mark unperformed checks pending. Preparing an
installation procedure does not authorize the agent to flash.

## Record the result

Keep each PR description current with the problem and linked issues, final behavior,
revision/build identity, validation performed, limitations and actionable **User
test instructions**. Record README/changelog assessments as required by AGENTS;
update focused guides and diagnostic documentation when affected.

Use material issue/PR updates to link commits/PRs, outcomes, checks and remaining
gates. Check duplicates and ownership before filing concrete follow-up issues.
Avoid repeated journal comments without new evidence. If remote writes are outside
scope, provide the same evidence in the local completion report.

Report merged work, reviewable PRs, hardware/decision blockers, completed or
superseded issues and the next useful package. Ask a concrete question with a
recommendation and consequences only when a decision is necessary; continue
independent authorized work while waiting. Stop an autonomous run only after every
selected item has a recorded assessment and no unblocked action remains; preserve
enough state for a later run. Favor verified outcomes over closure counts.
