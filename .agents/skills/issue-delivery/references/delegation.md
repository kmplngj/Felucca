<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Delegate by task and available runner

Delegate useful independent investigation, implementation, test execution or review tasks. Keep a
small task local when delegation adds no value; use existing tools for mechanical
inventory and validation. Honor an explicit user model choice. Otherwise select
by the task's contracts and uncertainty, not its diff size. Configure model and
effort through the runner's actual configuration or spawn parameters.

| Runner | Task complexity | Worker model | Reasoning / effort |
| --- | --- | --- | --- |
| Codex | Execute an already defined test plan, collect summaries/artifacts, inspect bounded failures and report results | GPT-6.1 Terra (`gpt-6.1-terra`) | `medium` |
| Codex | Documentation from supplied evidence, bounded screenshot/UI inspection or a trial of an isolated low-risk fix with explicit acceptance checks | GPT-6.1 Terra (`gpt-6.1-terra`) | `medium` |
| Codex | Bounded investigation, ordinary implementation, focused review or test-plan interpretation | GPT-6.1 Sol (`gpt-6.1-sol`) | `medium` |
| Codex | Complex coverage/results interpretation, difficult diagnosis, cross-module changes, DSP/arithmetic, concurrency or persistence contracts | GPT-6.1 Sol (`gpt-6.1-sol`) | `high` |
| Claude Code | Defined test execution, bounded investigation, straightforward fixes or focused checks | Claude Sonnet 5.5 | `medium` |
| Claude Code | Substantial implementation or review with several interacting paths | Claude Sonnet 5.5 | `high` |
| Claude Code | Complex test interpretation, difficult root cause, architectural decisions or high-risk cross-cutting work | Claude Opus 5.5 | `medium` |

Separate execution from interpretation. Terra/Sonnet can run an agreed test even
when it exercises high-risk firmware. Defining missing acceptance contracts,
explaining conflicting results or deciding coverage for that firmware takes the
Sol/Opus route. A routine passing run needs only coordinator verification of its
identity, coverage and skips, not another model pass. Give a failed/ambiguous run
to the interpreter with its summary and relevant raw evidence; escalate to `high`
for interacting timing, arithmetic, persistence or protocol behavior. Reuse the
same execution worker for follow-ups instead of spawning one per command.

For Terra, provide the relevant source/evidence and verify the actual result.
A visual inspection does not establish physical LCD readability or device behavior.
Keep implementation and acceptance reasoning for DSP/arithmetic, interrupts/deadlines,
concurrency, persistence, stable IDs and protocol compatibility on the higher-risk
route even for a one-line fix.
Treat Terra's code-fix route as a trial: retain the same acceptance checks and
review bar as Sol. Compare representative tasks before making it the default.
If scope expands, evidence conflicts, a required contract is unclear, or one
focused correction still fails acceptance, return the evidence and escalate to
Sol `high` or the Claude Code difficult-work route. The coordinator can use
Astra for unresolved difficult reasoning when the runner exposes that model.

Resolve Claude model IDs against the runner's available models and confirm the
requested version. Use an alias only when it resolves to that exact version.
Configure each worker's effort as well as its model; inherited defaults or a
generic `opus`/`sonnet` alias alone do not establish the requested selection.
If the user specifies only a model, use its listed effort unless the task requires
a higher listed effort for that model.
For Codex, use the selected exact model ID and `reasoning_effort` from the table
where those spawn fields are exposed. Claude models require a runner that actually
exposes them; a Codex-only model list does not imply Claude Code availability.
If an override requires a fresh context, start the worker without inherited history
and supply a self-contained assignment.

If the requested model/effort cannot be selected or delegation is unavailable,
report the limitation and do useful work serially in the current session. Do not
silently substitute another model/version or claim a prompt configured the runner.
Include actual selections in the completion evidence when the runner exposes them.
When comparing routes, keep inputs and acceptance checks fixed and include review
and repair time; report cost/token savings only when the runner measures them.

Give each worker the repository/candidate identity (including dirty inputs), objective,
acceptance checks, relevant instructions, owned files/regions and expected result.
For a test worker, include exact commands, prerequisites, output ownership, timeout/
stop condition and existing evidence to reuse. Return statuses, identity, command,
elapsed time, summary/artifact paths, skips and the next unresolved question;
keep full logs/media on disk. Test execution alone grants no code/baseline edits,
new acceptance criteria, device writes or publication authority.
Parallelize only disjoint edits and independent tests. Use isolated outputs; one
coordinator assigns ownership of shared generation and integrated builds and owns
authorized GitHub writes/merges. Workers in the same checkout serialize build/test
commands that share `build/`, generated assets or locks; independent readers may
run in parallel. A frozen source tree stays unchanged during a run. Give one worker
exclusive transport/device ownership for an authorized hardware block.
Workers return changes, evidence, skips and open questions. Integrate and inspect
their work before claiming completion.
