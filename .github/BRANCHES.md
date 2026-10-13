<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Merged branch cleanup

For this fork, GitHub's **Settings > General > Pull Requests > Automatically
delete head branches** is enabled (`delete_branch_on_merge: true`). This removes
PR head branches after future merges without a bot, extra secret or privileged
PR workflow. The setting is repository configuration, so another fork must
enable it separately. Protect any permanent integration/release branches with
branch rules; the keep patterns below apply only to the sweep.

GitHub documents both [automatic deletion](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-the-automatic-deletion-of-branches)
and [deletion/restoration through merged PRs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/deleting-and-restoring-branches-in-a-pull-request).
Native deletion plus protected permanent branches is the simplest scalable
policy. This fork adds a sweep for historical leftovers and merged branches
that did not go through a PR. It does not remove branches merely because they
are old. Contributors' fork branches remain under their owners' control.

## Weekly and manual sweep

`Merged branch cleanup` runs every Monday at 04:23 UTC. Scheduled runs delete
verified candidates. **Actions > Merged branch cleanup > Run workflow** defaults
to an audit; select `apply` only to delete, using the default branch. Nondefault
refs can run audits to validate the implementation before merging; apply on
those refs fails. The schedule becomes active when the workflow is merged into
the default branch. GitHub may delay scheduled runs or disable them in inactive
public repositories; native deletion does not depend on the schedule.

The helper uses GitHub CLI (`gh`), Git and Python 3's standard library. A local
audit only needs repository read access; deletion needs contents write access
and an existing Git checkout:

```sh
python3 tools/branch_cleanup.py --repo kmplngj/Felucca --report build/branch-cleanup/audit.json
python3 tools/branch_cleanup.py --repo kmplngj/Felucca --apply --report build/branch-cleanup/deleted.json
python3 -m unittest discover -s tests -p branch_cleanup_test.py -v
```

GitHub Actions uses its scoped `GITHUB_TOKEN` (`contents: write`,
`pull-requests: read`), pinned checkout/upload actions, no retained checkout
credentials, and a 15-minute timeout. It has no PR trigger. Existing read-only
PR CI runs the helper's safety tests and validates workflow syntax. Cleanup runs
are serialized; their summary and 30-day JSON artifact record every branch,
commit and decision, including partial results if a deletion fails.

## What qualifies

A branch is eligible only if its **current head** is reachable from the current
default-branch commit, or if its name and current head match a merged PR into
that default branch and the PR's resulting merge commit remains reachable
there. The second check handles squash/rebase merges; a commit pushed after
such a merge is preserved unless it too is reachable from the default branch.
An old merged PR with a reused name, a foreign fork, an unmerged closed PR, or
a PR merged into another feature branch cannot establish eligibility.

The sweep always preserves the default branch, branches marked protected by
GitHub, and both source and target branches of open PRs. It also preserves:

- `main`, `master`, `dev`, `develop`, `development`, `stable`, `staging`,
  `production`, `gh-pages`, `release`, `releases`, `maintenance`, `support`;
- `release/*`, `releases/*`, `maintenance/*`, `support/*`, `stable/*`, `v[0-9]*`.

Pass repeatable `--keep 'branch/glob*'` arguments for additional permanent names;
add them to the workflow invocation if they should apply to every sweep.

Immediately before each deletion, the helper reads the branch's protection and
SHA, open PRs, and the default branch again. If the default branch changes, the
run aborts and must be repeated. A changed head, new protection or new open PR
keeps the branch. Git's explicit `--force-with-lease=refs/heads/NAME:SHA` enforces
the audited SHA atomically, preventing a concurrent push from being discarded.
GitHub enforces repository deletion rules as well. Protection and PR checks are
API snapshots; unlike the SHA lease, they are not an atomic transaction with
deletion. Avoid opening/rebasing dependent PRs during a cleanup run.

API or Git failures fail the job instead of silently treating an unknown merge
state as safe. Deletion removes the branch reference, not merged history.
Merged PR heads can be restored from GitHub's PR page; the audit also records
their original SHAs. Locally, `git fetch --prune origin` removes stale remote
tracking references after a cleanup.
