<!-- SPDX-License-Identifier: GPL-3.0-only -->
# User-facing documentation policy

Apply this policy before completing a change and when preparing its PR. Each section
ends in an assessment recorded in the PR description (or completion report when there
is no PR). The [PR template](../.github/pull_request_template.md) has a field for the
README assessment; record the changelog and diagnostic-guide assessments beside it.

## README

During development, read [README.md](../README.md) and assess whether the change affects
the fork's purpose, overall progress, available engines, installation or compatibility.
This is a personal integration fork collecting features, engines and optimizations
from upstream and other forks, with a focus on CPU, RAM and firmware-size improvements.
Keep that purpose clear and distinguish implemented capabilities from plans and experiments.

Update the README in the same PR for meaningful milestones or changes to that overview.
Summarize the resulting capability or development stage, not each commit, small fix or
internal optimization. Put detailed controls, defaults, limitations and compatibility
instructions in [the fork feature guide](fork-features.md) or the relevant focused guide,
and link from the README when discoverability requires it. Keep performance claims tied
to documented measurements and their validation scope.

**Assessment:** name the sections updated, or explain specifically why the existing
README already covers the resulting behavior. If a broader README change would be
useful but depends on unresolved scope or direction, propose the concrete wording in
that report and identify the open decision. Apply clear, factual documentation updates
directly without waiting for a separate request.

## Changelog

Assess [docs/changelog.md](changelog.md) in the same PR. Update it when the work
adds a meaningful capability, fixes a significant bug, changes behavior or compatibility,
or delivers a noteworthy optimization. Group related work under Added, Fixed, Changed
or Optimized and describe the outcome; summarize rather than listing every commit, small
fix or internal adjustment. Link focused guides or evidence instead of duplicating them,
and keep pending hardware qualification explicit. Prepare entries in the implementation
PR; the published main-branch overview covers merged capabilities, while plans and other
open PRs stay in issues and roadmaps. Use only existing release versions and performance
claims backed by documented measurements.

**Assessment:** identify the entries updated, or explain why the change does not
warrant an entry.

## Diagnostic capabilities

Apply the same assessment to diagnostic capabilities. Keep the linked
[capability overview](diagnostics.md#diagnostic-capabilities) and the usage/protocol
guide current in the same PR, including activation/defaults, transport and output,
resource or workload impact, and validation limits. Detailed command inventories
belong in those guides rather than in `AGENTS.md`.

**Assessment:** record the affected guides alongside the README and changelog
assessments.
