<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Autonomous backlog loop

Read this only for an explicitly requested autonomous backlog run. For a single
issue/PR, use the scoped workflow in [SKILL.md](../SKILL.md).

## Establish one working inventory

Resolve the requested repository and issue filters. When the task asks for company
repository discovery, use available organizations, remotes and checkouts to establish
ownership; ask before including an ambiguous destination. Felucca's four-repository
ownership map determines where selected work belongs; it does not automatically add
every issue from those repositories to the queue.

Retrieve the full selected issue set and relevant open/closed PRs, following API
pagination. Record access failures and partial results as incomplete inventory.
Inspect existing branches, worktrees and concurrent work before assigning packages.
Keep one compact working table rather than re-inventorizing on every step:

| Repository / issue | Current relevance and evidence | Dependencies / active PR | Priority / next step | Required validation / blockers | State |
| --- | --- | --- | --- | --- | --- |

Use states such as queued, investigating, implementing, review/CI pending, hardware
pending, decision blocked, ready, merged, already done and superseded. Keep issue,
PR and exact head identities with the evidence; an assessed item is not necessarily
resolved. State changes need a reason, not just a timestamp. An item is assessed
only after its relevance and evidence, dependencies, next step, required validation
or explicit blockers, and state are recorded. `investigating` alone is insufficient.

Keep local recovery notes under ignored `build/issue-delivery/` when useful. Record
the selected scope, inventory limits, active packages/branches, validation/review
SHAs, pending gates, remote-write results and next action. These local notes may
not survive another checkout; GitHub and actual Git state remain authoritative.
On resumption, reconcile the recorded items with live state before repeating a
write or trusting prior results. Do not commit transient queue snapshots.

## Advance packages to an outcome

1. Reassess the highest-value unblocked items against current code and linked work.
   Select one bounded package using the main skill and the repository batch rules.
2. Implement and perform focused checks. Delegate only independent work using the
   main skill's model/effort policy and explicit file/region ownership.
3. Freeze the candidate and complete integrated validation, documentation and PR
   user-test instructions. Obtain reviews and inspect current-head CI.
4. Resolve findings and recheck the updated candidate. Merge only if authorized and
   every gate in the main skill passes. Otherwise retain the exact pending gate and
   a reviewable handoff, then advance another independent package.
5. Update the working inventory and affected issues/PRs for material outcomes. Discover
   new follow-up work through deduplication and repository ownership; queue it without
   continually expanding the package under validation. Refresh inventory for material
   changes or resumption, rather than repeating a full scan after every commit.

Finish started packages before opening more when practical. Use bounded waits for
CI/reviews and continue useful independent work; missing external results remain
pending. Give concise updates on findings, completed packages and changed blockers.

Stop only when every selected item is assessed and either no actionable work remains
or every remaining item has an explicit blocker. Report what merged, what is ready
for review, which issues were already done/superseded and the precise hardware,
access, review or decision blockers. Preserve the next action for each unresolved item.
An exhausted actionable queue is a stopping condition, not evidence that all issues
are solved. Never close blocked work to make the inventory appear complete.
