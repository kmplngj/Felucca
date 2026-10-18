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
   Fetch `origin/main` and `origin/automation/firmware-watch`. Use an isolated worktree
   on the latter branch for the canonical ledger. Keep the user's checkout untouched.
   Merge current main into the state branch before a run when needed; stop on conflicts
   without overwriting either ledger. Initial ledger files also live on main for bootstrap.
2. Acquire `lease` with `--lease-dir` set to that shared path and hold it through fetch, assessment and final
   push. Helper locks protect individual mutations, not an entire review session.
   Do not overlap runs or steal an active lock. Read and validate the complete ledger.
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

Route findings before writing using [AGENTS repository ownership](../../../AGENTS.md#choose-the-repository-before-implementation-or-issue-creation):

- **Felucca-Engines (MIT):** portable engines/DSP/interface, exclusive content,
  generators and engine tests whose actual source/dependency closure permits this
  collection. An upstream MIT core does not make a GPL wrapper or asset MIT.
- **Felucca-Engines-GPL:** GPL-derived portable engines and their exclusive
  content/generators/tests. Preserve per-file and asset licenses; restricted data
  still blocks copying. Do not default all engines to GPL just because the host is GPL.
- **Felucca:** stable global IDs, profiles/registration, exact pins, voice/arena or
  service hooks, native UI/MOD, effects/hardware, persistence, producer protocol,
  emulator/runtime, integration/hardware qualification and mixed adoption plans.
  Existing firmware-native code stays here until an explicitly scoped extraction.
- **Felucca-WebApp:** editor/installer client implementation and tests. Create the
  issue there when enabled. While Issues is disabled, use a `Felucca-WebApp:` issue
  in Felucca with an explicit implementation repo and firmware producer dependency;
  do not enable Issues as part of a scan. Inaccessible/disabled engine destinations
  are blockers, not permission to dump engine tickets in Felucca.

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
to main, then merge into the state branch. Preserve all pending registrations.

## Coordinator and workers

Preferred coordinator: GPT-6.1 Sol with medium reasoning. Use at most two GPT-6.1
Sol workers: low reasoning for metadata/inventory tasks, medium for substantive
diff/applicability review. If the runner cannot select models, report that limitation;
writing a model preference in a prompt does not configure the model.

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
