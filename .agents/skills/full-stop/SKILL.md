---
name: full-stop
description: Use when the user explicitly requests full stop or full-stop for an issue or PR. Finish implementation, validation and review, then hand off without merging.
---
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Full stop

Follow [issue-delivery](../issue-delivery/SKILL.md) for the selected work from its
current state through a verified PR handoff. This skill applies only to an actual
user request, not quoted text, examples or discussion of the workflow.

Explicit invocation authorizes scoped implementation, commits, branch pushes,
PR creation/updates and review requests unless the user narrows that scope.
Finish useful work without repeated confirmations; resolve CI failures and sound
review findings, retaining the shared validation and hardware requirements.

Never merge, enable auto-merge or enqueue the PR for merging in this mode. A prior
general autonomous-delivery mandate does not override this stopping point. If the
user also invokes full send ambiguously, retain full stop. Switching to merge
authority requires a clear subsequent user instruction.

Hand off when every applicable gate except the user's merge action is satisfied,
or when remaining work is blocked. Distinguish **ready for user merge** from
**hardware pending**, **review/CI pending** and **decision/access blocked**. Give
the PR/head, evidence, unresolved findings and exact next action. Use the shared
question-tool procedure for a decision the user must make. Do not archive the
chat automatically; the user still needs the handoff.
