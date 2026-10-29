---
name: firmware-watch
description: Review registered firmware sources and their complete older history for justified Felucca adaptations; maintain the repository JSON/JSONL ledger and link actionable GitHub issues without routine issue-journal updates.
---
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Firmware source watch

Read [the ledger guide](../../../docs/firmware-watch.md) and current
[AGENTS.md](../../../AGENTS.md).

## Start and inventory

1. In the original clone, resolve one shared absolute lease directory under its Git
   common directory (see the guide); retain that path before creating a worktree.
   Acquire `lease` with `--lease-dir` set to that shared path before fetch, inventory
   or reconciliation and hold it through final push. Helper locks protect individual
   mutations, not an entire review session. Do not overlap runs or steal an active lock.
2. Fetch `origin/main` and `origin/automation/firmware-watch`. Use isolated worktrees:
   current main supplies code/instructions and the state branch supplies only the
   canonical ledger. Keep the user's checkout untouched. Do not merge main's whole
   tree into the state branch. Reconcile the registry using the guide's guarded
   procedure, then validate the candidate; stop on rejected reconciliation without
   overwriting either ledger. Validate the complete canonical ledger with the helper
   and inspect its summary and selected records. Main's initial ledger files are a
   bootstrap snapshot, never current scan evidence.
3. Record the freshly fetched full `origin/main` SHA as the Felucca comparison revision.
   Fetch registered sources with the helper's `sync` command. Only initialize pending
   registrations after identity, branch, immutable pin and full-DAG checks succeed.
   Keep existing frozen intervals; preserve failed entries and explicit blockers.
4. Inspect all open and closed issues, their relevant comments and merged PRs in
   **kmplngj/Felucca, kmplngj/Felucca-Engines, kmplngj/Felucca-Engines-GPL and
   kmplngj/Felucca-WebApp**, with full pagination wherever Issues is enabled. Check
   each repository's live Issues setting/access. Build an ignored local inventory
   keyed by existing `felucca-upstream` markers and canonical issue URLs. Follow
   transferred URLs and deduplicate across all four repos; search indexing alone
   cannot prove absence. Refresh issue state before a new write. Do not execute
   unreviewed donor scripts.

## Context and evidence

Keep the canonical ledger in the tracked `automation/firmware-watch` state worktree
for helper validation, commit and push. Ignored local files may hold ledger copies
and the paginated issue/comment inventory used for context filtering.
Use helper validation for complete journal integrity, then inspect the summary,
bounded queue and records matching the selected repository/full SHA or issue.
Refresh the local issue inventory before writes as required above; query that
inventory for deduplication and interrupted-write recovery. Keep complete source
and native diffs/callers/tests in review scope; page large diffs until fully read.
Workers return proposed records, evidence paths/URLs and blockers rather than
repeating raw logs or the coordinator's instructions. Context filtering never
changes the full-DAG, pagination, evidence or publication requirements.

## Select and review

Use `queue --limit 50` for a bounded round-robin batch. Allocate about 60% recent
and 40% historical work while both exist; continue other repositories when one is
blocked. Stop at 60 minutes or 50 completed assessments, whichever comes first.
Never replace complete topology with dates, first-parent logs or API page limits.
Roots, side branches and merge-resolution differences all belong to coverage.

Read the complete actual diff and the necessary source/native callers and tests.
Commit messages, snapshots and upstream performance claims are leads, not assessment
evidence. For each repository/full SHA, record parents, branch membership, queue,
title, changed paths, full native comparison SHA, disposition, rationale, source
and native evidence URLs, linked issue URLs and run ID. One commit on two branches
gets one assessment. Similar patches in two repositories require separate explicit
applicability decisions; shared evidence alone does not transfer coverage.

Use the established dispositions: `bug`, `optimization`, `feature`, `backport`,
`already_present`, `existing_issue`, `not_applicable`, `needs_input`, `pending`.
The last two grant no completed coverage. A source snapshot grants no individual
commit coverage. Completed records must explain the decision even when no issue
is warranted. Existing decisions remain historical evidence against their recorded
native SHA; changed applicability can require new linked work, never fabricated
new coverage or replacement of an earlier decision.

- A bug requires evidence that the defect exists in current native Felucca.
- An optimization needs a bounded unchanged-baseline/A-B plan, sound/arithmetic
  invariants, actual JieLi Clang 4.0.1 constraints and all relevant app/RAM/POOL/
  RAMTEXT/NOINIT/stack/audio deadline budgets. Source estimates are not device gains.
- A feature/backport needs a native integration design, stable IDs, serializer and
  editor/protocol compatibility, acceptance criteria, licensing and hardware gates.
- Tools, tests, platform work, documentation and generated publishing changes also
  receive reasoned decisions. Explain board-specific incompatibility explicitly.

## Issues and durable recovery

Before any issue write, apply [repository ownership](../../../docs/repository-ownership.md)
to the actual source/dependency/asset licence closure, and check live repository
access and Issues settings. That section owns collection placement, the WebApp
fallback and blocked destinations; its requirements apply to scan findings too.

Split collection, firmware-host and client findings into linked issues only where
each represents justified new work; reuse existing owners. Collection issues define
portable controls/services/tests, while Felucca owns global IDs and integration.
Read current main in each affected implementation repo and include immutable native
evidence URLs there; retain the required full `felucca_comparison_sha` for host fit.
Collection PRs land before a host updates an exact pin. GPL collection consumption
is still pending Felucca #360. Issue creation during this watch does not authorize
implementation in any of the four repositories.

Create an issue only for a justified actionable finding not owned by existing work.
Use `<!-- felucca-upstream:<repository>@<full-sha>:<stable-topic> -->` in its body.
Prefer linking existing issues; update one only for material new evidence, changed
requirements, a blocker or a resolved decision. Do not post routine scan progress,
negative findings or one journal comment per commit to GitHub issues.

For actionable findings, create/recover the issue first, verify its returned URL,
then submit the structured assessment through `record --input FILE`. On interruption,
search the full four-repository issue/comment marker inventory, including redirects,
before retrying creation. Record the actual returned destination URL(s), not a guessed
Felucca issue number. `sources.json.issue_repositories` explicitly permits companion
destinations; `destination_repo` remains the primary/legacy host. Preserve historical
journal URLs and source markers after transfers; redirects are recovery evidence,
not a reason to rewrite old assessments. The append-only
journal is authoritative; cached counters and frontiers are derived. Retry an identical
record safely; investigate conflicting terminal decisions rather than overwrite them.
Use `checkpoint` to rebuild counts and advance only fully completed frozen intervals.
Missing objects, rewritten history, removed branches and authentication failures are
explicit blockers. Keep old targets and historical evidence; never reset/rebase a cursor
to make an incomplete interval look complete. Authorized reconciliation must preserve
old-only commits and document the changed graph before admitting new targets.

Persist after each assessment locally. At bounded intervals and before stopping,
validate, commit and push only the ledger to `automation/firmware-watch`; fetch first
and fail on an unexpected remote advance. A local checkpoint is not durable across
fresh environments until pushed. Verify the remote commit SHA. Retain unpushed work
and report a blocker if publication fails. No-op runs should not create timestamp-only
commits. Skill/helper changes and new source registrations use ordinary reviewed PRs
to main; execute current-main code against the isolated state ledger. Preserve all pending registrations.

## Coordinator and workers

Preferred coordinator: GPT-6.1 Sol with medium reasoning. Use at most two concurrent
workers across runners; honor explicit user model choices.
Use the ledger helper and local inventory queries for mechanical extraction.

| Runner | Worker task | Model | Reasoning / effort |
| --- | --- | --- | --- |
| Codex | Evidence organization, metadata interpretation or bounded documentation/UI pre-screening | GPT-6.1 Terra (`gpt-6.1-terra`) | `medium` |
| Codex | Substantive diff/applicability review | GPT-6.1 Sol (`gpt-6.1-sol`) | `medium` |
| Codex | DSP/arithmetic, interrupts/deadlines, concurrency, persistence or protocol/ID contracts | GPT-6.1 Sol (`gpt-6.1-sol`) | `high` |
| Claude Code | Evidence organization or bounded diff/applicability review | Claude Sonnet 5.5 | `medium` |
| Claude Code | Substantial review with several interacting paths | Claude Sonnet 5.5 | `high` |
| Claude Code | Difficult root cause or high-risk cross-cutting assessment | Claude Opus 5.5 | `medium` |

Terra pre-screening proposes evidence and questions; it grants no completed commit
coverage or final applicability decision. The coordinator checks the complete diff,
necessary native callers/tests and evidence before accepting any worker proposal.
Escalate to the higher-risk route when contracts are unclear, evidence conflicts,
or scope expands, regardless of patch size. For unresolved difficult reasoning,
the coordinator can use Astra when available.

Configure the selected model and effort in the runner, resolving Claude IDs to the
exact requested version; aliases or prompt text alone do not establish selection.
For a user-specified model without an effort, use its listed effort, increasing to
a higher listed effort for that model when the task requires it.
If the requested model/effort or delegation is unavailable, report the limitation
and continue serially without claiming an independent review or silently changing
models. Record actual selections when exposed. Compare new routes on the same
evidence and acceptance criteria, including coordinator review and repair time;
claim cost/token savings only when measured.

Delegate disjoint repository/SHA batches. Workers return structured proposed records
and evidence; they do not write the canonical ledger, advance frontiers, create issues
or push Git refs. One coordinator checks evidence and deduplication and owns all writes.
If delegation is unavailable, execute the same bounded process serially.

Notify the user only for actionable findings, meaningful blockers, completed historical
coverage or required input. Stay quiet when only ordinary scan progress changes.
This task authorizes review, ledger commits/pushes and justified issue creation/evidence
updates in the four repositories above, subject to the WebApp fallback. Engine,
firmware or client implementation, baseline regeneration, device flashing, releases,
deployment, repository-setting changes and unrelated writes require their own task scope.
