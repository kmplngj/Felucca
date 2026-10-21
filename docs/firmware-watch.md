<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Firmware source watch

The [firmware-watch skill](../.agents/skills/firmware-watch/SKILL.md) reviews
registered source commits against current Felucca, including gradual complete-history
backfill. It records why a change is useful, already present, owned by an existing
issue or inapplicable. Scanning never implements firmware or claims device validation.

## Canonical files and branch

The [Optimist adoption review](optimist-adoption-2026-10-19.md) registers
`w0ts/optimist` main as a pending source, pinned initially at
`5fc3ee51a4aa64fd22cef217c8498c9be567eb69` (2,018 reachable commits, zero reviewed
by the snapshot). After this registration reaches main and the state branch, the
next audit verifies identity, branch, immutable pin and complete history before
initializing it. Pending registration is not active or completed review coverage.
The existing daily task reads this registry; its schedule does not need changing.

Routine scan state lives on the repository's
[`automation/firmware-watch` branch](https://github.com/kmplngj/Felucca/tree/automation/firmware-watch/data/firmware-watch).
The initial migration also lives on main. Read the state branch for current progress;
do not treat main's bootstrap snapshot as the latest scan. Changes to the skill,
helper, schema or registered scope use ordinary PRs to main. The runner merges
main into its isolated state worktree before scanning and stops on conflicts.

| File under `data/firmware-watch/` | Purpose |
| --- | --- |
| `sources.json` | Primary destination, allowed issue repositories, registered source IDs, immutable historical targets, source metadata and pending registrations |
| `state.json` | Recent frontiers, frozen targets, observed tips, blockers and derived progress; legacy fields retain their dated meaning |
| `summary.json` | Derived complete/partial Git-DAG inventory after checkpointing; absent before the first checkpoint |
| `reviews.jsonl` | Append-only structured assessments with source/native evidence and issue/PR links; one JSON object per line |
| `legacy-issue-152.json` | Lossless original body/comment export for audit and migration recovery |
| `migration-report.json` | Migration provenance, counts and source snapshot digest |

Objects use `schema_version: 1`. Sources and runtime state each have a `repositories`
array keyed by `repository`; runtime entries own `recent_frontiers` and
`pinned_recent_targets`. Historical targets stay in source configuration. Journal
records use `repository` plus full `source_sha` as their identity; branch membership
does not duplicate a review. An imported record's `provenance` links its original
comment. Source IDs protect against an owner/name being reused by another repository.

The journal defines completed coverage. `pending` and `needs_input` are nonterminal;
cached totals or a high frontier cannot create completed assessments. Runtime
checkpointing recomputes progress from full source DAGs and confirmed records.
Fresh derived totals live in `state.current_summary` and `summary.json`; legacy
top-level counters retain their original dated meaning. Missing source caches or
blocked/pending sources make aggregate remaining counts unknown (`null`), with
separate `known_remaining_*` totals for the successfully enumerated sources.
The journal can retain an earlier pending attempt followed by a terminal result;
conflicting terminal decisions require investigation. Retain the imported pending
record even if it predates later successful source initialization.

## Issue destinations and implementation boundaries

Follow the [AGENTS ownership table](../AGENTS.md#choose-the-repository-before-implementation-or-issue-creation)
for both issue placement and subsequent implementation. Portable MIT-compatible
engine code/content/generators/tests go to `kmplngj/Felucca-Engines`; GPL-derived
portable ports go to `kmplngj/Felucca-Engines-GPL`. Felucca owns firmware IDs,
profiles/pins, voices/services, native UI, effects/hardware, persistence, producer
protocol, emulator/runtime and integration/qualification. Editor/installer client
code and tests belong to `kmplngj/Felucca-WebApp`.

Check live repository access and Issues settings. While WebApp Issues is disabled,
track client work in Felucca with a `Felucca-WebApp:` title, explicit implementation
repo and linked firmware producer dependency. When enabled, file directly in WebApp.
The watch does not change repository settings. An inaccessible/disabled engine
destination is an explicit blocker, not a firmware fallback.

Inventory open/closed issues, relevant comments, stable markers, transferred URLs
and merged PRs across all four repositories with full pagination before creating work.
Keep source markers on transfers; use returned canonical URLs for new assessments.
Reuse linked collection/host/client owners; the [instrument routing review](instrument-issue-routing.md)
records the initial transfer decisions. Read current main in each affected repo and
include pinned implementation evidence as well as the full host comparison SHA.
The scan authorizes justified issue/evidence writes across these repositories, not
engine, firmware or client implementation.

`destination_repo` remains the primary host and preserves migration identity.
Optional `issue_repositories` is a nonempty, unique list of allowed destinations
including that host; this repository configures all four above. The helper validates
new records and the complete journal against it. An older configuration without the
field accepts only `destination_repo`. This is an additive schema-v1 setting, not a
change to registered donor scope or immutable coverage. Preserve existing journal
URLs and the lossless migration archive; old issue URLs redirect after a transfer.

## Commands and queries

Use Python 3.10+, Git and an authenticated `gh` CLI for source synchronization.
Validation, summaries and queries need no GitHub credentials or device access.
No third-party Python package is required.

```sh
python3 tools/firmware_watch.py validate
python3 tools/firmware_watch.py summary
python3 tools/firmware_watch.py sync
python3 tools/firmware_watch.py queue --limit 50 > build/firmware-watch-batch.json
python3 tools/firmware_watch.py record --input build/firmware-watch-assessment.json
python3 tools/firmware_watch.py checkpoint
python3 tests/firmware_watch_test.py
```

The assessment file holds a structured proposed review from the skill's process;
the helper does not generate a reasoned review from commit messages. Source bare
caches and temporary analysis live under ignored `build/firmware-watch/`. To select
one configured source, use `sync --repository owner/name`. Global `--data-dir` and
`--cache-dir` options go before the command when working with fixture copies.
Unknown repositories and unregistered branches are not implicitly added to scope.

```sh
# Completed optimization candidates and their linked work.
jq -c 'select(.disposition == "optimization") |
  {repository, source_sha, issue_urls}' data/firmware-watch/reviews.jsonl

# All evidence already linked to an issue, including historical decisions.
jq -c 'select(any(.issue_urls[]?; endswith("/119")))' \
  data/firmware-watch/reviews.jsonl

# Pending scope registrations.
jq '.pending_source_additions' data/firmware-watch/sources.json
```

Synchronization checks GitHub repository IDs, fetches explicit branches and verifies
complete non-shallow Git graphs. Historical pins never move. A frozen recent interval
stays frozen until every reachable commit in it has a terminal record. Only then can
checkpointing advance the frontier and admit newly observed tips. Full oldest-first
topological enumeration includes roots and merge-side history; merges still require
reviewing resolution changes. Missing old objects, missing branches and rewritten
history are visible blockers, not permission to reset coverage. Independent sources
can continue. An authorized reconciliation preserves old targets and old-only commits.

## Migration and recovery

To reproduce the import into a disposable directory, use the retained original export:

```sh
python3 tools/firmware_watch.py \
  --data-dir build/firmware-watch-migration-check \
  --cache-dir build/firmware-watch-migration-cache \
  migrate --snapshot data/firmware-watch/legacy-issue-152.json
python3 tools/firmware_watch.py --data-dir build/firmware-watch-migration-check validate
```

Migration rejects malformed journal JSON and conflicting terminal records rather
than silently dropping history. Repeated identical imports are idempotent. All source
registrations and reconciliation comments remain available in the raw export even
when they are not assessment records. Cached legacy queue counts remain historical
values until a fresh complete-DAG checkpoint rebuilds them.

For interrupted issue creation, recover the issue by its stable
`felucca-upstream:<repository>@<sha>:<topic>` marker, then append the assessment
with that issue URL. For interrupted checkpointing, validate the journal and rerun
`checkpoint`; it reconstructs derived progress. A torn/corrupt journal is an explicit
failure: preserve it for inspection and recover the verified Git version, never
silently truncate lines or credit work from cached counts.

Hold a single whole-run lease before inventory or assessment and through final push;
the helper's per-command mutation lock is not a substitute. Never remove another
run's lease merely because a command is taking time. Before Git publication, check
that the remote state branch still matches the fetched base. Use ordinary fast-forward
pushes and stop on rejection; never force-push the ledger. Only the coordinator writes
canonical records and issues. Separate worker results remain in ignored scratch files.
Commit and push valid ledger checkpoints at bounded intervals and before stopping;
verify the remote SHA. If a push fails, retain the local commit and report its SHA
and blocker so the next run can recover it. Do not emit timestamp-only commits on
an unchanged run.

Acquire/release the helper's lease with one unique run ID, keeping it for the whole
multi-command session (replace the example ID for each run):

```sh
# Resolve this in the original clone before creating an isolated worktree.
watch_lease_dir="$(git rev-parse --path-format=absolute --git-common-dir)/firmware-watch"
python3 tools/firmware_watch.py --lease-dir "$watch_lease_dir" \
  lease acquire --owner run-2026-10-18-example
# Inventory, sync, review, checkpoint and verified Git publication happen here.
python3 tools/firmware_watch.py --lease-dir "$watch_lease_dir" \
  lease release --owner run-2026-10-18-example
```

The shared lease cannot be released with another owner ID. A worktree-relative
cache alone cannot coordinate two isolated worktrees; `--lease-dir` prevents those
worktrees from acquiring separate run leases. A standalone helper defaults to its
cache directory. Independent clones/machines require a single serialized scheduled
runner; a local lease does not claim distributed locking. A stale lease requires confirming its previous run has stopped before
explicit operator cleanup. Helpers also acquire a short per-command writer lock.

## Scheduled Codex task

The requested schedule is daily at **09:00 Europe/Berlin**. The task prompt is in
[the skill reference](../.agents/skills/firmware-watch/references/task-prompt.md).
Preferred execution is GPT-6.1 Sol with medium reasoning, with up to two disjoint
workers: low for metadata and medium for substantive source review. Model selection
must be supported by the scheduler; a model name inside a prompt is a preference,
not a configured setting.

One run stops at 60 minutes or 50 completed assessments. New work and history share
the budget approximately 60/40 while both exist, round-robin across sources. A source
with thousands of historical commits must not starve smaller sources. Refresh current
native implementation and existing open/closed issues before creating a finding.
Routine progress stays in Git; notify only for actionable findings, material blockers,
completed historical coverage or required input. Firmware implementation, flashing,
release publication and unrelated writes remain outside this maintenance task.

Keep a single active runner for the published state branch. Disable an existing
runner before enabling a replacement so both cannot process the same queues.

## Release-specific adoption reviews

The [Araminta v2.8 review](araminta-v2.8-review-2026-10-21.md) refreshes
the existing adoption and experimental instrument issues against the immutable
release commit. Araminta main is already registered; normal source synchronization
discovers the new tip. The release snapshot does not reset historical targets,
advance commit-review coverage or create another runner.
