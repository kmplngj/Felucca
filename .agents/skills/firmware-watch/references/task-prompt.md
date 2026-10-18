<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Scheduled task prompt

Review registered firmware sources for kmplngj/Felucca using the current repository's
`.agents/skills/firmware-watch/SKILL.md` and `docs/firmware-watch.md`. Fetch current
main and the canonical `automation/firmware-watch` state branch into an isolated
worktree; preserve the user's working files. Resolve a shared absolute lease directory
from the original clone's Git common directory before creating a worktree and pass it
with `--lease-dir` when acquiring/releasing the whole-run lease. Serialize this task;
filesystem leases coordinate worktrees of one clone, not independent machines. Use
`tools/firmware_watch.py` to validate, synchronize sources, select bounded recent/history
work, record actual evidence-based assessments and checkpoint complete intervals.
Initialize pending sources only after all required checks succeed. Import no new
coverage from snapshots, cached counts or commit messages.

Prefer GPT-6.1 Sol with medium reasoning for coordination. Where model selection and
delegation are supported, use at most two disjoint GPT-6.1 Sol workers: low for metadata
and medium for substantive diff review. Workers return proposed records only; the
coordinator owns the canonical journal, issue deduplication, checkpointing and Git writes.
Report inability to configure the requested model instead of claiming that a prompt
configured it.

Stop after 60 minutes or 50 completed assessments; allocate approximately 60% recent
and 40% historical work round-robin when both queues exist. Read full source diffs and
relevant native callers/tests against freshly fetched Felucca main. Inspect all relevant
open/closed issues, comments and merged PRs before creating actionable work, using stable
source markers to recover interrupted issue writes. Link existing issues whenever they
already own the finding. Create/update GitHub findings only for justified new work or
material evidence; routine progress and negative findings belong in the repository.

Validate and commit/push only the ledger to the canonical state branch at bounded
intervals and before stopping, verifying the remote commit. Never force-push or skip
history holes. Preserve pending registrations, immutable targets, old review evidence
and explicit source blockers. Retain unpushed commits for recovery and report a failed
push. Release the lease on completion. Do not change firmware, regenerate baselines,
flash devices, publish releases or modify unrelated repositories. Stay quiet on ordinary
progress; notify only for actionable findings, meaningful blockers, completion of
historical coverage or required user input.
