<!-- SPDX-License-Identifier: GPL-3.0-only -->
# AI-assisted firmware workflows

These repository workflows can be adapted to other firmware projects. Start with
the [developer index](changelog.md#for-firmware-developers) for the DSP, fixes and
measurement tools they support. AI assistance uses the same source, licensing,
validation and hardware requirements as other development work.

## Load context when it is needed

[AGENTS.md](../AGENTS.md) holds the task routes and firmware invariants. Read the
guide for the affected subsystem, then the actual implementation and callers.
Load the [batch procedure](development-batches.md) when combining issues and the
[PR-testing skill](../.agents/skills/pr-testing/SKILL.md) when preparing a handoff.
Keep specialist procedures behind explicit task pointers instead of repeating
them in every prompt. Reuse material already read in the current run; refresh
when its revision changes or the task reaches a new subsystem.

Use CodeGraph first in a checkout with an existing index; otherwise use targeted
source searches. Start with file names or symbols and bounded line ranges. Keep
large command output in ignored `build/` files and read the relevant sections.
If output is truncated, narrow or page the query until all required evidence is
read. A smaller context must still include the complete relevant diff, callers
and compatibility contracts.

## Read results before opening raw evidence

Use `uv run --locked --group build tests/run_tests.sh --ai-output` for local
AI-run host suites, including runs from skills and scheduled tasks. It retains
complete logs and unchanged test selection and failure exit codes, including
preflight. The final line names the report and unit/diagnostic counts; inspect
failed, skipped, blocked or cancelled paths before claiming acceptance.
Warning/skip detection is a text hint, not a complete inventory of test cases.
See [the output contract](../BUILDING.md#tests) for fields and limitations.

CI keeps the normal full transcript for `tools/ci.py verify-tests`; compact output
is not that verifier's input format. The browser gate already reports a compact
summary and uses its existing command without this flag.

| Task | First read | Expand when needed |
| --- | --- | --- |
| Host suite | Run status and `build/host/test-run-*/summary.json` ([format](../BUILDING.md#tests)) | Logs for failed, blocked or cancelled units; affected prerequisite output |
| Browser UI/audio | One-line result and `build/browser/run-*/summary.json` ([gate](cloud-testing.md#keep-agent-context-small)) | The failed check's log, screenshot or WAV; media is retained only on failure by default |
| Target resources | `build/resource-report.json` ([contract and verification](build-profiles.md#machine-readable-build-evidence)) | Matching map/disassembly, source inputs and guard failures |
| Device collection | `summary.json` ([interpretation](diagnostics.md#interpreting-a-report)) | Relevant `samples.jsonl` windows and `console.raw` replies, including invalid intervals |
| Firmware watch | Helper validation and summary, then the bounded queue ([commands](firmware-watch.md#commands-and-queries)) | Journal records for the selected repository/SHA or issue; complete source diffs and native evidence |

These summaries organize evidence; they do not grant a pass by themselves. Missing
prerequisites, skips, stale build identity and invalid collection remain visible.
Host/browser results do not establish FM-1 deadlines, transport reliability,
physical display quality or listening acceptance. Static resource reports measure
linked allocations and stack reservations, not live stack watermarks.

## Reuse review work without losing coverage

The [firmware-watch skill](../.agents/skills/firmware-watch/SKILL.md),
[ledger helper](../tools/firmware_watch.py) and
[scheduled entry prompt](../.agents/skills/firmware-watch/references/task-prompt.md)
separate durable evidence from the next run's context. The helper validates the
complete append-only journal; the reviewer loads selected records and full diffs.
Repository/full-SHA identity, immutable comparison revisions and stable issue
markers support deduplication and recovery. Summaries and commit messages do not
create review coverage. Only an explicitly invoked watch run authorizes its
documented ledger/issue writes; reading this guide does not start a scan.

[CodeRabbit configuration](../.coderabbit.yaml) and its
[review guide](../.github/CODERABBIT.md) show firmware-specific review priorities
and how ordinary bot comments avoid starting unsolicited review conversations.
Static/AI review still needs the target compiler, regressions and applicable
device checks. Batch focused fixes before requesting another review.

## Evaluate context savings

Compare the same task, revision, evidence scope and completion requirements.
Record model/tokenizer and actual input/output token usage when the runner exposes
them; otherwise report text bytes or words explicitly as a proxy. Moving a
procedure out of the always-loaded guide reduces input for unrelated tasks;
tasks that need it still read it. Shorter prompts alone do not establish lower
total run cost or unchanged review quality. Keep required validation and full
evidence coverage when assessing any savings.
