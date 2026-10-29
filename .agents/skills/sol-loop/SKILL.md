---
name: sol-loop
description: Use when the user explicitly asks for sol loop, sol-loop or soul loop, or an authorized workflow explicitly calls it. Run a bounded local code review with GPT-6.1 Sol.
---
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Sol review loop

Use one reviewer to find material defects in the selected change and verify focused
corrections. Keep the original goal and acceptance checks fixed. This is a local
review procedure, not authorization to publish, merge or expand the task. In a
review-only request, return findings without editing the code. Reading this skill
to discuss or edit it does not start a review.

## Set up the review

1. Record the repository, base and candidate revision, working-tree changes,
   requested behavior, owned paths, compatibility contracts and available evidence.
   For uncommitted work, retain a diff snapshot and identify untracked inputs under
   ignored `build/issue-delivery/`; HEAD alone does not identify the reviewed state.
2. Use the runner's actual model selector: GPT-6.1 Sol (`gpt-6.1-sol`), medium
   reasoning for ordinary changes, high for DSP/arithmetic, concurrency, persistence
   or cross-module risk. Give a fresh-context worker a self-contained assignment
   and the relevant repository instructions. Do not claim a prompt selected a model.
3. Allow one reviewer at a time, with no reviewer-spawned agents. The reviewer is
   read-only: no edits, Git writes, external comments or shared build mutations.
   It may run focused checks with isolated outputs. The coordinator owns fixes,
   integrated validation and any separately authorized remote writes.
4. If the required model or delegation is unavailable, report that limitation.
   Continue useful self-review, clearly labelled; do not report a completed Sol
   review or substitute another model silently.

## Review, resolve and stop

Budget three review rounds total. The first covers the complete relevant diff,
callers and contracts. Later rounds cover changed code, its affected callers and
open findings, retaining enough context to catch regressions from the fixes.
Extend to at most five rounds only for a concrete unresolved security, permission,
data-loss or comparable serious correctness risk; record the reason.

Require each finding to identify a location, failure scenario, consequence and
supporting evidence. Keep a compact record of finding IDs, accepted/declined/open
status, rationale, fix identity and validation. Apply the smallest justified fix
within the authorized scope. Challenge unsupported findings using source or test
evidence. Queue unrelated improvements rather than growing the candidate.
Documentation and test defects count when they break a real contract or handoff;
cosmetic preferences alone do not justify another round.

After fixes, run the affected checks and return the changed evidence to the
reviewer. A coordinator's disagreement does not erase the reviewer's verdict;
retain unresolved disagreement explicitly. Stop early when no material findings
remain, or when only non-blocking nits remain. At the round limit, stop reviewing
and report any unresolved findings as pending; exhaustion is not approval.
In review-only mode, end after the initial findings unless the candidate changes
or a concrete finding requires clarification.

## Record the verdict

In the authorized PR update or local handoff, include:

- Actual reviewer model/effort, number of rounds and reviewed candidate identity.
- Reviewer verdict: **no material findings**, **material findings remain**, or
  **incomplete/unavailable**, with finding dispositions and any disagreement.
- Validation actually observed, skipped checks and review coverage gaps.

Use the reviewer's actual final result, not a verdict inferred from silence or
from the coordinator's fixes. Material changes after review need renewed coverage;
if the budget is spent, report that gap. Local review does not replace required
Codex PR Review, CI, human review or hardware acceptance in
[issue-delivery](../issue-delivery/SKILL.md#merge-gate-and-hardware-handoff).
