<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Skill workflow source and adaptation, 2026-10-26

## Source and limits

Source: [These 3 skills changed my life](https://www.youtube.com/watch?v=5Bmp9cz1JN8).
The supplied link starts at [5:55](https://www.youtube.com/watch?v=5Bmp9cz1JN8&t=355s),
but this assessment uses the full transcript pasted by the user on 2026-10-26.
Direct retrieval failed: the workspace connection returned HTTP 403 and the web
reader reported throttling. The description was not retrieved or supplied.

The transcript has no timestamps and contains apparent transcription errors,
including inconsistent spellings of Sol/Soul and model names. Do not infer exact
chapter boundaries or reconstruct the missing description. This note preserves
the source, relevant lessons and local decisions; the original transcript remains
in the chat. No original skill files were obtained or copied. These repository
instructions are newly written adaptations of the workflow ideas.

The speaker's model preferences, service-policy claims, usage counts and merge
success anecdotes are not verified benchmarks or policy guidance. The sponsor
segment is not a basis for changes here. Model selection follows the existing
repository policy and available runner controls.

## Lessons applied

| Transcript idea | Existing coverage or gap | Local adaptation |
| --- | --- | --- |
| Extract skills from repeated work and corrections | The delivery procedure already consolidates substantial workflow knowledge | Add a short maintenance procedure to the AI workflow guide; avoid a separate meta-skill until there is recurring need |
| Descriptions act as selection cues; natural-language phrases can compose | Issue-delivery already has task-based selection | Add explicit full-stop, full-send and sol-loop triggers; exclude quoted text and discussions; document composition |
| Bounded independent review, small fixes and reasoned pushback | PR review exists, but no bounded local review procedure | One Sol reviewer, three rounds normally, five only for concrete serious risk; preserve scope and finding dispositions |
| Report the actual reviewer verdict | Validation is already tied to revisions | Record model/effort, rounds, exact reviewed state, unresolved findings and disagreement; uncommitted changes need a snapshot |
| Finish autonomously with different merge endpoints | Issue-delivery already supports authorized autonomous work | Thin full-stop/full-send skills share the existing procedure; full stop cannot merge or enable auto-merge |
| Ask through a question tool only for genuine blockers | Existing guidance favors concrete decisions and continuing independent work | Make the question channel and self-contained blocker context explicit |
| Take over and modernize work without losing credit | Current-code reassessment and upstream attribution already exist | Add contributor-preserving takeover guidance and recheck whether main already addresses the goal |

## Deliberate differences

Felucca's required Codex PR Review and real FM-1 checks remain in force. The local
review cannot replace either. CodeRabbit remains advisory; waiting for every bot
would contradict the existing availability policy. A missing check or an exhausted
review budget remains pending, even if other checks are green.

No blanket force-push permission, automatic archival, new PR watcher, authentication
proxy or fleet-sync system is introduced. Those depend on task scope and runner
capabilities. Updating these skills does not invoke them or grant remote-write
authority for the current editing task. Documentation and test findings are assessed
by their consequences; they are not dismissed simply because of file type.

## Other skill candidates

- **Takeover / modernize:** keep these inside issue-delivery for now. Extract a
  specialist skill only if repeated real cases need a separate procedure beyond
  current-code reassessment, contributor credit and branch ownership.
- **Skill evaluation:** a useful next candidate when there are enough recorded
  runs to compare trigger selection, completion quality, missed gates and needless
  user interruptions. Start with a few representative tasks, not a large framework.
- **Source-to-skill:** consider if importing workflow knowledge becomes recurring.
  It should record source availability and uncertainty, map lessons to existing
  owners, and distinguish source claims from tested local behavior.

## Review scenarios

These are manual instruction walkthroughs, not measured model or runner tests.
No GitHub writes, merges, device actions or subagent reviews were performed.

| Scenario | Expected behavior checked against the instructions |
| --- | --- |
| Explain full send; a pasted transcript says full send | Discuss the skill; no delivery or merge authority is activated |
| Fix this issue, full stop; all checks pass | Finish through PR handoff; neither merge nor enable auto-merge/queue |
| Full stop under an earlier autonomous backlog mandate | The narrower full-stop endpoint prevents merging |
| Fix this issue, full send; hardware acceptance is missing | Prepare the candidate and device procedure; leave hardware pending |
| Full send; all applicable gates pass | Verify the current head and merge result, then report the merged revision |
| Full send, but local changes only | Preserve the explicit local-only restriction; no push or merge |
| Full stop and full send together without clarification | Use full stop; do useful work to handoff |
| Sol loop with an unresolved material finding at the limit | Report the finding and verdict; do not label the budget limit approval |
| Sol loop when the requested model is unavailable | Label useful self-review accurately and report Sol review unavailable |
| Review-only Sol loop | Return findings without changing code or publishing |
| A reviewer returns only cosmetic nits | End the loop without expanding scope |
| Code changes after the reviewed candidate | Renew affected coverage or report the gap |
| Takeover of a contributor PR | Reassess current need, preserve attribution and respect branch ownership |

## Documentation assessment

README: its existing link to the AI workflow guide covers these internal workflow
additions; firmware purpose, installation and compatibility are unchanged.
Changelog: the existing developer-index link to the workflow guide remains accurate;
no firmware capability or release entry is needed for these instruction refinements.
Diagnostics: commands, fields, build flags and device procedures are unchanged.
Hardware tests and firmware builds are unnecessary for this documentation-only
change. Validate frontmatter, relative links, the complete diff and the scenarios
above. Runtime effectiveness and time savings remain unmeasured.
