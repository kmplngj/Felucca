#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Audit merged GitHub branches; deletion requires --apply and an exact-head lease."""
import argparse
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote


KEEP = (
    "main", "master", "dev", "develop", "development", "stable", "staging",
    "production", "gh-pages", "release", "releases", "maintenance", "support",
    "release/*", "releases/*", "maintenance/*", "support/*", "stable/*", "v[0-9]*",
)


def api(endpoint):
    result = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def items(endpoint):
    # gh follows Link headers; one compact JSON object per line works across pages
    # even with the older gh versions used by development environments.
    result = subprocess.run(
        ["gh", "api", "--paginate", f"{endpoint}{'&' if '?' in endpoint else '?'}per_page=100", "--jq", ".[]"],
        check=True, capture_output=True, text=True,
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def active_branches(pulls, repository):
    active = set()
    for pull in pulls:
        if pull["state"] == "open":
            for side in ("head", "base"):
                ref = pull[side]
                if (ref.get("repo") or {}).get("full_name") == repository:
                    active.add(ref["ref"])
    return active


def eligibility(branch, metadata, pulls, ancestor, keep=()):
    name, sha = branch["name"], branch["commit"]["sha"]
    repository, default = metadata["full_name"], metadata["default_branch"]
    if name == default or branch["protected"] or any(
            fnmatchcase(name, pattern) for pattern in (*KEEP, *keep)):
        return False, "default, protected or permanent branch"
    if name in active_branches(pulls, repository):
        return False, "head or base of an open PR"
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"invalid branch SHA: {name}")
    if ancestor(sha):
        return True, "current head is reachable from the default branch"
    for pull in pulls:
        head, base = pull["head"], pull["base"]
        if (pull.get("merged_at") and head["ref"] == name and head["sha"] == sha
                and (head.get("repo") or {}).get("full_name") == repository
                and (base.get("repo") or {}).get("full_name") == repository
                and base["ref"] == default and pull.get("merge_commit_sha")
                and ancestor(pull["merge_commit_sha"])):
            return True, f"unchanged head of merged PR #{pull['number']} (including squash/rebase)"
    return False, "current head has no verified merge into the default branch"


def delete_branch(repository, name, sha):
    # GitHub's delete-ref API has no expected-SHA precondition. A Git lease
    # atomically refuses deletion if somebody pushes after our last API check.
    subprocess.run([
        "git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
        "push", f"--force-with-lease=refs/heads/{name}:{sha}",
        f"https://github.com/{repository}.git", f":refs/heads/{name}",
    ], check=True, capture_output=True, text=True)


def audit(repository, apply=False, keep=(), report=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    endpoint = f"repos/{repository}"
    metadata = api(endpoint)
    default = api(f"{endpoint}/branches/{quote(metadata['default_branch'], safe='')}")
    base_sha = default["commit"]["sha"]
    cache = {}

    def ancestor(sha):
        if sha not in cache:
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("invalid comparison SHA")
            comparison = api(f"{endpoint}/compare/{base_sha}...{sha}")
            cache[sha] = comparison["status"] in ("identical", "behind")
        return cache[sha]

    pulls = items(f"{endpoint}/pulls")  # Default state=open, for head AND base guards.
    pulls += items(f"{endpoint}/pulls?state=closed")
    rows = []
    completed = False
    try:
        for branch in items(f"{endpoint}/branches"):
            eligible, reason = eligibility(branch, metadata, pulls, ancestor, keep)
            row = {"branch": branch["name"], "sha": branch["commit"]["sha"],
                   "result": "candidate" if eligible else "keep", "reason": reason}
            rows.append(row)
            if eligible and apply:
                # Protection and PRs can change independently of a branch commit.
                current_meta = api(endpoint)
                current = api(f"{endpoint}/branches/{quote(branch['name'], safe='')}")
                live_pulls = items(f"{endpoint}/pulls")
                live_default = api(f"{endpoint}/branches/{quote(metadata['default_branch'], safe='')}")
                if (current_meta["default_branch"] != metadata["default_branch"]
                        or live_default["commit"]["sha"] != base_sha):
                    row.update(result="failed", reason="default branch changed during cleanup")
                    raise ValueError("default branch changed during cleanup; rerun the audit")
                if current["commit"]["sha"] != row["sha"]:
                    row.update(result="keep", reason="head changed during cleanup")
                elif current["protected"] or branch["name"] in active_branches(live_pulls, repository):
                    row.update(result="keep", reason="new protection or open PR during cleanup")
                else:
                    try:
                        delete_branch(repository, branch["name"], row["sha"])
                    except subprocess.CalledProcessError as error:
                        row.update(result="failed", reason="Git lease or repository policy refused deletion")
                        raise RuntimeError(f"deletion refused for {branch['name']}: {error.stderr}") from error
                    row["result"] = "deleted"
            print(json.dumps(row), flush=True)
        completed = True
    finally:
        result = {"repository": repository, "default_branch": metadata["default_branch"],
                  "default_sha": base_sha, "apply": apply, "completed": completed, "branches": rows}
        if report:
            Path(report).parent.mkdir(parents=True, exist_ok=True)
            Path(report).write_text(json.dumps(result, indent=2) + "\n")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a") as stream:
                stream.write("### Merged branch cleanup\n\n")
                stream.write(f"Mode: {'apply' if apply else 'dry-run'}. Default commit: `{base_sha}`.\n\n")
                stream.write(f"Audit completed: {completed}.\n\n")
                stream.write("Full branch names, SHAs and decisions are in the audit artifact.\n\n")
                for state in ("candidate", "deleted", "keep", "failed"):
                    stream.write(f"- {state}: {sum(r['result'] == state for r in rows)}\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/name")
    parser.add_argument("--apply", action="store_true", help="delete audited branches; default is dry-run")
    parser.add_argument("--keep", action="append", default=[], help="additional branch glob to preserve")
    parser.add_argument("--report", help="write full JSON audit, including partial results on failure")
    args = parser.parse_args()
    audit(args.repo, args.apply, args.keep, args.report)


if __name__ == "__main__":
    main()
