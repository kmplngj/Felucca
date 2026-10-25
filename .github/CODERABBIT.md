<!-- SPDX-License-Identifier: GPL-3.0-only -->
# CodeRabbit reviews

[.coderabbit.yaml](../.coderabbit.yaml) configures reviews for this public
repository. CodeRabbit's [open-source plan](https://docs.coderabbit.ai/management/plans)
provides Team features without a paid subscription. This differs from the ordinary
Free plan, which provides PR summaries. Configuration cannot upgrade a plan or
remove the service's [rate limits](https://docs.coderabbit.ai/management/rate-limits).

## Merge policy

Codex Review is the required AI review in the
[issue-delivery workflow](../.agents/skills/issue-delivery/SKILL.md). CodeRabbit
provides advisory feedback; automatic reviews remain enabled. Its availability,
quota reset or completion is not a merge prerequisite.

Inspect available CodeRabbit findings against the code and requirements. Resolve
confirmed correctness issues before merging and explain inapplicable suggestions
with evidence. Advisory status does not excuse a known defect. Required Codex
coverage, CI and physical hardware acceptance still apply.

A successful CodeRabbit status can accompany a skipped or rate-limited review.
Record that as unperformed review, not as reviewed or approved.

## Review coverage

Ready PRs targeting the default branch (`main`) receive an automatic review and
incremental reviews on subsequent pushes. Drafts and titles containing
`[skip review]` skip automatic review. Reviews pause after five reviewed commits;
a maintainer can resume when the next batch is ready. Batch small fixes into one
push, and keep unfinished work in draft to conserve the review allowance.

The assertive profile, path instructions and guideline documents direct reviews
toward interrupt deadlines, fixed-point arithmetic, RAM/flash bounds, persistence
and protocol compatibility. Applicable bundled linters, static analysis, secret
scanning, linked-issue assessment and repository-local context remain enabled.
Generated build outputs and dependency caches are excluded; source assets,
attribution and test baselines remain in scope. Default guideline discovery also
loads `AGENTS.md` when that file is committed.

Summaries stay in the collapsed walkthrough instead of editing the PR description.
Review details expose ignored files and context, while fortunes, poems and chat
art are disabled. The validation-evidence check warns about missing evidence;
CodeRabbit does not automatically approve changes through this configuration.
Its static analyzers do not replace the JieLi target build, host regressions or
real FM-1 validation required for firmware changes.

## Comments and automation

`chat.auto_reply: false` requires an explicit CodeRabbit mention before chat
responds. Ordinary CI reports, agent progress comments and other reviewer comments
without a mention must not start unsolicited CodeRabbit conversations. Automatic
reviews still run on eligible PR events and new code pushes.

Explicit mentions, commands and interactive review checkboxes remain actionable.
The current schema has no comment-author denylist: `auto_review.ignore_usernames`
filters **PR authors**, not commenters. It is intentionally empty so useful
dependency or agent-authored PRs are not excluded from review.

Automation that posts comments must omit the CodeRabbit handle and review commands,
including when quoting another review or copying command examples. Avoid toggling
CodeRabbit's interactive checkboxes or posting commands in response to bot output.
An automation that deliberately addresses CodeRabbit can still trigger it; this
YAML is not a guarantee against explicit commands. There are currently no
repository GitHub Actions workflows that post such comments.

Maintainers can deliberately use the documented
[review commands](https://docs.coderabbit.ai/reference/review-commands):

- `@coderabbitai review`: review new changes; do not send it after every CI report.
- `@coderabbitai full review`: start a complete review only when needed.
- `@coderabbitai pause` / `@coderabbitai resume`: control reviews during fix batches.
- `@coderabbitai configuration`: inspect the effective configuration.

On-demand autofix, unit-test generation and other Team finishing touches remain
available through the service defaults. Use them deliberately and review their
changes with the same target, regression and device evidence as human changes.

## Configuration validation

Validate YAML syntax and every setting against the current
[official schema](https://storage.googleapis.com/coderabbit_public_assets/schema.v2.json)
before merging configuration changes. The
[YAML validator](https://docs.coderabbit.ai/configuration/yaml-validator) and
`cr config validate` in the [CodeRabbit CLI](https://docs.coderabbit.ai/cli/reference)
provide service-maintained validation. For branches in this repository, CodeRabbit
reads configuration from the PR branch, so a configuration PR can exercise its own
settings before merge. PRs from forks use the target branch's configuration.
