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

Route implementation findings by the skill and AGENTS repository-ownership table:
portable MIT-compatible engines/DSP/assets/generators/tests to kmplngj/Felucca-Engines;
GPL-derived portable engine work to kmplngj/Felucca-Engines-GPL; host IDs/profiles/pins,
voices/services, native UI, persistence/producer protocol, emulator and qualification
to kmplngj/Felucca; editor/installer client work to kmplngj/Felucca-WebApp. Check actual
file/dependency/asset licenses and live Issues settings. While WebApp Issues is disabled,
use an explicitly prefixed `Felucca-WebApp:` fallback ticket in Felucca naming the client
implementation repo and producer dependency. Do not change settings. Inventory and
deduplicate open/closed issues, comments, markers, transfers and relevant PRs across all
four repositories before writes. Link collection/host/client owners without duplicates;
record the returned destination URLs accepted by sources.json.issue_repositories.
Preserve historical journal evidence/URLs. Read each affected implementation repo's
current main and pin its comparison evidence, retaining the Felucca comparison SHA.

Validate and commit/push only the ledger to the canonical state branch at bounded
intervals and before stopping, verifying the remote commit. Never force-push or skip
history holes. Preserve pending registrations, immutable targets, old review evidence
and explicit source blockers. Retain unpushed commits for recovery and report a failed
push. Release the lease on completion. Justified issue writes in the four named repos
are in scope; implementation and repository-setting changes are not. Do not change
engine, firmware or client code, regenerate baselines,
flash devices, publish releases or modify unrelated repositories. Stay quiet on ordinary
progress; notify only for actionable findings, meaningful blockers, completion of
historical coverage or required user input.
