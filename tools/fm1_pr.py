#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build/download PR firmware and install its verified FWSC over USB-MIDI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import fm1_install
import m_flasher


DEFAULT_REPO = "kmplngj/Felucca"
WORKFLOW = "ci.yml"
SOURCE = Path(__file__).resolve().parents[1]


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *map(str, args)],
                            capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or f"{args[0]} exited with status {result.returncode}"
        raise ValueError(f"Git failed: {detail}")
    return result.stdout.rstrip("\n")


def worktree_record(source, path):
    # Each linked worktree has a private Git directory; never mark the main one.
    common = Path(git(source, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    private = Path(git(path, "rev-parse", "--absolute-git-dir"))
    if (private == common or
            Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")) != common or
            Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path):
        raise ValueError("Path is not a linked worktree of this repository")
    return private / "felucca-pr.json"


def check_worktree(source, path, repository, number, revision=None, removing=False):
    record = worktree_record(source, path)
    if not record.is_file():
        raise ValueError("Worktree was not created by this helper")
    data = json.loads(record.read_text())
    if (data.get("path") != str(path) or data.get("repo") != repository or
            data.get("pr") != str(number) or
            (revision is not None and data.get("revision") != revision)):
        raise ValueError("Worktree belongs to another path, repository, PR or revision")
    head = git(path, "rev-parse", "HEAD")
    if (head != data.get("revision") or
            git(path, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD"):
        raise ValueError("Worktree HEAD changed; keep or move your commits before cleanup/reuse")
    status = ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"]
    if removing:
        status.append("--ignored=matching")
        # Status deliberately hides files flagged assume-unchanged/skip-worktree.
        # Refuse such indexes, and submodule-only refs/stashes that removal would lose.
        indexes = git(path, "ls-files", "-v") + "\n" + git(
            path, "submodule", "foreach", "--quiet", "--recursive", "git ls-files -v")
        local_refs = git(path, "submodule", "foreach", "--quiet", "--recursive",
                         "git rev-list --all --not --remotes HEAD")
        if any(line and (line[0].islower() or line[0] == "S") for line in indexes.splitlines()) or local_refs:
            raise ValueError("Worktree has hidden index entries or local submodule commits/stashes; preserve them first")
    # The parent status omits ignored files inside submodules. Inspect those too.
    nested = git(path, "submodule", "foreach", "--quiet", "--recursive",
                 "git " + " ".join(status))
    if git(path, *status) or nested:
        raise ValueError("Worktree has local changes or extra files; preserve/remove them before cleanup/reuse")
    return record


def prepare_worktree(repository, number, revision, destination=None, source=SOURCE):
    source = source.resolve()
    path = (destination if destination is not None else
            source.parent / f"{source.name}-pr-{number}-{revision}").expanduser().resolve()
    if path == source or path in source.parents or source in path.parents:
        raise ValueError("Use a separate directory outside the current checkout")
    if path.exists():
        check_worktree(source, path, repository, number, revision)
    else:
        # A private temporary ref leaves branches, index and FETCH_HEAD untouched.
        ref = f"refs/felucca-pr/{uuid.uuid4().hex}"
        try:
            git(source, "fetch", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules",
                f"https://github.com/{repository}.git", f"refs/pull/{number}/head:{ref}")
            try:
                git(source, "merge-base", "--is-ancestor", revision, ref)
            except ValueError as error:
                raise ValueError("Selected commit is not reachable from the fetched PR head; "
                                 "the PR may have been force-pushed. No revision was substituted.") from error
            git(source, "worktree", "add", "--detach", path, revision)
            worktree_record(source, path).write_text(json.dumps({
                "path": str(path), "repo": repository, "pr": str(number), "revision": revision,
            }) + "\n")
        finally:
            git(source, "update-ref", "-d", ref)
    print(f"Source worktree: {path}\nEnter: cd {shlex.quote(str(path))}\n"
          f"Return: cd {shlex.quote(str(source))}", flush=True)
    # Explicit --checkout respects gitlink pins even if shared config requests rebase/merge.
    # Never run the PR's helper: the caller's installer and CI verification stay in control.
    print("Initializing pinned submodules (a failed preparation leaves the worktree for inspection)...",
          flush=True)
    git(path, "submodule", "update", "--init", "--recursive", "--checkout")
    if any(line and line[0] != " " for line in
           git(path, "submodule", "status", "--recursive").splitlines()):
        raise ValueError("Submodule revisions do not match the selected commit")
    return path


def remove_worktree(repository, number, path, source=SOURCE):
    source, path = source.resolve(), path.expanduser().resolve()
    if path == source:
        raise ValueError("Cannot remove the current source checkout")
    check_worktree(source, path, repository, number, removing=True)
    # Git requires one --force for initialized submodules, even when entirely clean.
    # The ownership and recursive checks above also reject ignored build/user files.
    git(source, "worktree", "remove", "--force", path)
    print(f"Removed source worktree: {path}; installed firmware was not changed.")


def gh(*args, payload=None):
    result = subprocess.run(
        ["gh", *args], input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True,
    )
    if result.returncode:
        # Download failures can contain signed artifact URLs. Keep their query
        # credentials out of terminal output and shared test reports.
        message = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[query redacted]", result.stderr.strip())
        raise ValueError(f"GitHub CLI failed: {message}")
    return result.stdout


def api(endpoint):
    return json.loads(gh("api", endpoint))


def pages(endpoint, key):
    result = []
    for page in range(1, 1001):
        data = api(f"{endpoint}{'&' if '?' in endpoint else '?'}per_page=100&page={page}")[key]
        result.extend(data)
        if len(data) < 100:
            return result
    raise ValueError("GitHub result exceeds pagination limit")


def validate_selection(repository, number, revision=None):
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or any(part in (".", "..") for part in repository.split("/"))):
        raise ValueError("--repo must be owner/name")
    if not re.fullmatch(r"[1-9][0-9]*", str(number)):
        raise ValueError("PR must be a positive number")
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("--commit must be a full lowercase 40-character commit SHA")


def resolve_pr(repository, number, revision=None):
    validate_selection(repository, number, revision)
    pull = api(f"repos/{repository}/pulls/{number}")
    head = pull["head"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("GitHub returned an invalid PR head SHA")
    revision = revision or head
    if revision != head:
        comparison = api(f"repos/{repository}/compare/{revision}...{head}")
        if comparison["status"] not in ("ahead", "identical"):
            raise ValueError("Requested commit is not reachable from the current PR head")
    return revision, pull["title"]


def resolve_automatic_pr(repository, number, revision=None):
    validate_selection(repository, number, revision)
    pull = api(f"repos/{repository}/pulls/{number}")
    head, base, merge = pull["head"]["sha"], pull["base"]["sha"], pull.get("merge_commit_sha")
    if pull["state"] != "open" or not all(
            isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
            for sha in (head, base, merge)):
        raise ValueError("--automatic requires an open PR with an available merge commit")
    if revision is not None and revision != head:
        raise ValueError("--automatic --commit must match the current PR head; "
                         "omit --automatic for historical exact-commit builds")
    commit = api(f"repos/{repository}/git/commits/{merge}")
    if commit["sha"] != merge or [parent["sha"] for parent in commit["parents"]] != [base, head]:
        raise ValueError("PR merge commit does not match the current base/head; retry after GitHub updates it")
    return head, base, merge, pull["title"]


def automatic_run(repository, number, head, base):
    runs = pages(f"repos/{repository}/actions/workflows/{WORKFLOW}/runs"
                 f"?event=pull_request&head_sha={head}", "workflow_runs")
    matches = sorted((run for run in runs
                      if run["event"] == "pull_request" and run["head_sha"] == head
                      and run["status"] == "completed" and run["conclusion"] == "success"
                      and any(pull["number"] == int(number)
                              and pull["url"] == f"https://api.github.com/repos/{repository}/pulls/{number}"
                              and pull["head"]["sha"] == head and pull["base"]["sha"] == base
                              for pull in run["pull_requests"])),
                     key=lambda run: run["id"], reverse=True)
    run = next((item for item in matches if firmware_artifact(repository, item)), None)
    if run is None:
        raise ValueError("No successful automatic PR build for the current base/head with a live firmware artifact. "
                         "Wait for full PR CI or rerun it; no build was requested.")
    print(f"{run['html_url']} — automatic PR merge build", flush=True)
    return run


def run_title(number, revision, validation="full"):
    return f"PR firmware #{number} @ {revision}" + (" (target)" if validation == "target" else "")


def matching_runs(repository, number, revision, workflow_ref, validation="full"):
    runs = pages(f"repos/{repository}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch",
                 "workflow_runs")
    return sorted((run for run in runs
                   if run["display_title"] == run_title(number, revision, validation)
                   and run["head_branch"] == workflow_ref), key=lambda run: run["id"], reverse=True)


def artifact_name(run, validation="full"):
    return f"firmware-{'target-' if validation == 'target' else ''}{run['id']}"


def firmware_artifact(repository, run, validation="full"):
    artifacts = pages(f"repos/{repository}/actions/runs/{run['id']}/artifacts", "artifacts")
    live = [item for item in artifacts
            if item["name"] == artifact_name(run, validation) and not item["expired"]]
    return live[0] if len(live) == 1 else None


def ensure_run(repository, number, revision, workflow_ref, timeout, no_build=False, validation="full"):
    endpoint = f"repos/{repository}/actions/workflows/{WORKFLOW}/dispatches"
    runs = matching_runs(repository, number, revision, workflow_ref, validation)
    run = next((item for item in runs if item["status"] != "completed" or
                (item["conclusion"] == "success" and firmware_artifact(repository, item, validation))), None)
    existing = {item["id"] for item in runs}
    if run is None:
        if no_build:
            raise ValueError("No successful exact-commit build with a live firmware artifact. "
                             "Use --automatic to reuse an automatic PR merge build. "
                             "Ask a maintainer to run CI with the printed PR/commit, or omit --no-build "
                             "if you have Actions write access.")
        print(f"Requesting {validation} validation (requires Actions write access)...", flush=True)
        inputs = {"pr": str(number), "commit": revision}
        # Full is the default in both new and historical workflows. Older
        # maintainer workflow refs reject unknown dispatch inputs.
        if validation == "target":
            inputs["validation"] = "target"
        gh("api", "--method", "POST", endpoint, "--input", "-", payload={
            "ref": workflow_ref, "inputs": inputs,
        })
    deadline = time.monotonic() + timeout
    last_status = None
    while True:
        if run is None:
            run = next((item for item in matching_runs(repository, number, revision, workflow_ref, validation)
                        if item["id"] not in existing), None)
        else:
            run = api(f"repos/{repository}/actions/runs/{run['id']}")
        if run is not None:
            status = (run["id"], run["status"], run.get("conclusion"))
            if status != last_status:
                print(f"{run['html_url']} — {run['status']} {run.get('conclusion') or ''}", flush=True)
                last_status = status
            if run["status"] == "completed":
                if run["conclusion"] != "success":
                    raise ValueError(f"Build {run['conclusion']}; no firmware installed. {run['html_url']}")
                if not firmware_artifact(repository, run, validation):
                    raise ValueError("Successful run has no live firmware artifact; request a fresh build")
                return run
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Timed out waiting for CI; rerun with the same --commit and --validation to resume. "
                             "The remote build was not canceled.")
        time.sleep(min(15, remaining))


def unique_file(root, pattern):
    matches = list(root.rglob(pattern))
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"Artifact must contain exactly one {pattern}")
    return matches[0]


def verify_download(root, revision, validation="full"):
    provenance = json.loads(unique_file(root, "provenance.json").read_text())
    if provenance["revision"] != revision:
        raise ValueError("Firmware provenance does not match the requested commit")
    # Legacy full runs predate the scope field. Target artifacts must declare it.
    validation_record = provenance.get("validation", {})
    if not isinstance(validation_record, dict):
        raise ValueError("Invalid firmware validation scope record")
    scope = validation_record.get("scope", "full")
    if scope != validation:
        raise ValueError("Firmware validation scope does not match the requested mode")
    package = unique_file(root, "*.fwsc")
    checksum = unique_file(root, "package.sha256").read_text().strip().split()
    if (len(checksum) != 2 or not re.fullmatch(r"[0-9a-f]{64}", checksum[0])
            or Path(checksum[1].lstrip("*")).name != package.name):
        raise ValueError("Invalid package SHA-256 manifest")
    if hashlib.sha256(package.read_bytes()).hexdigest() != checksum[0]:
        raise ValueError("Firmware SHA-256 mismatch")
    # This preflight opens no MIDI ports. Retain the existing installer checks.
    fm1_install.load_package(package, False)
    return package


def download(repository, run, revision, output, validation="full"):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"run-{run['id']}-", dir=output)).resolve()
    try:
        gh("run", "download", str(run["id"]), "--repo", repository,
           "--name", artifact_name(run, validation), "--dir", str(root))
        package = verify_download(root, revision, validation)
    except Exception:
        shutil.rmtree(root)
        raise
    print(f"Verified firmware: {package}", flush=True)
    return package


def prepare_installer(installer, executable=None):
    if installer == "native":
        return [str(m_flasher.ensure(executable)), "midi", "firmware"]
    if executable:
        raise ValueError("--m-flasher requires --installer native")
    check = subprocess.run([sys.executable, "-c", "import mido, rtmidi"], capture_output=True, text=True)
    if check.returncode:
        raise ValueError("Python MIDI installer needs mido and python-rtmidi in this interpreter. "
                         "Use --installer native or install them in a virtual environment before starting CI.")
    return [sys.executable, str(Path(__file__).with_name("fm1_install.py"))]


def install(package, port=None, yes=False, command=None):
    command = [*(command if command is not None else
                 [sys.executable, str(Path(__file__).with_name("fm1_install.py"))]), str(package)]
    if port:
        command.extend(["--port", port])
    if yes:
        command.append("--yes")
    return subprocess.run(command).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", help="PR number")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub owner/name")
    parser.add_argument("--commit", help="full SHA; default snapshots the current PR head")
    parser.add_argument("--automatic", action="store_true",
                        help="reuse successful automatic CI for the current PR merge; never dispatch a build")
    parser.add_argument("--validation", choices=("full", "target"), default="full",
                        help="full (default), or faster target-only checks for hardware iteration")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true", help="verify without accessing MIDI")
    mode.add_argument("--prepare-only", action="store_true",
                      help="prepare a source worktree only; no CI build, download or MIDI")
    mode.add_argument("--remove-worktree", type=Path, metavar="PATH",
                      help="remove a helper-created clean worktree; no CI or MIDI")
    mode.add_argument("--resolve-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worktree", action="store_true",
                        help="also prepare isolated PR sources with pinned recursive submodules")
    parser.add_argument("--worktree-dir", type=Path, metavar="PATH",
                        help="source worktree destination (implies --worktree); default sibling PR/SHA directory")
    parser.add_argument("--no-build", action="store_true", help="reuse a run without dispatching a build")
    parser.add_argument("--out", type=Path, help="download parent; default build/pr-PR/SHA")
    parser.add_argument("--installer", choices=("native", "python"), default="native",
                        help="native m-flasher MIDI OTA (default), or the Python MIDI installer")
    parser.add_argument("--m-flasher", type=Path, metavar="PATH",
                        help="explicit MIDI-capable executable; default installs/reuses the pinned user-local CLI")
    parser.add_argument("--port", help="USB-MIDI port name passed to the installer")
    parser.add_argument("--yes", action="store_true", help="skip the installer's flash confirmation")
    parser.add_argument("--timeout", type=int, default=3600, help="maximum CI wait in seconds")
    parser.add_argument("--workflow-ref", help="maintainer workflow branch; default repository default branch")
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        if args.automatic and (args.validation != "full" or args.workflow_ref is not None
                               or args.worktree or args.worktree_dir is not None
                               or args.prepare_only or args.remove_worktree or args.resolve_only):
            raise ValueError("--automatic supports full validation and install/download-only; "
                             "omit worktree, source-only and --workflow-ref options")
        if args.remove_worktree:
            validate_selection(args.repo, args.pr, args.commit)
            remove_worktree(args.repo, args.pr, args.remove_worktree)
            return 0
        validate_selection(args.repo, args.pr, args.commit)
        installer_command = None
        if not (args.download_only or args.prepare_only or args.resolve_only):
            installer_command = prepare_installer(args.installer, args.m_flasher)
        if args.automatic:
            head, base, revision, title = resolve_automatic_pr(args.repo, args.pr, args.commit)
        else:
            revision, title = resolve_pr(args.repo, args.pr, args.commit)
        if args.resolve_only:
            print(revision)
            return 0
        print(f"Repository: {args.repo}\nPR: #{args.pr}\nCommit: {revision}", flush=True)
        if args.automatic:
            print(f"PR head: {head}\nBase commit: {base}\n"
                  "Firmware contains the PR merged with its base branch.", flush=True)
        if args.worktree or args.worktree_dir is not None or args.prepare_only:
            prepare_worktree(args.repo, args.pr, revision, args.worktree_dir)
        if args.prepare_only:
            print("Sources prepared; no CI build, download or hardware access.")
            return 0
        print(f"Validation: {args.validation}", flush=True)
        if args.validation == "target":
            print("Target-only build: host, sanitizer, browser and reproducibility tests are omitted; "
                  "this does not replace full PR validation.", flush=True)
        if args.automatic:
            run = automatic_run(args.repo, args.pr, head, base)
        else:
            workflow_ref = args.workflow_ref or api(f"repos/{args.repo}")["default_branch"]
            run = ensure_run(args.repo, args.pr, revision, workflow_ref, args.timeout, args.no_build, args.validation)
        output = args.out or Path(__file__).resolve().parents[1] / "build" / f"pr-{args.pr}" / revision
        package = download(args.repo, run, revision, output, args.validation)
        if args.download_only:
            print("Download verified; no hardware was accessed.")
            return 0
        result = install(package, args.port, args.yes, command=installer_command)
        if result == 0:
            print("Installer finished. Verify the installed build commit in ABOUT and follow the PR's User test instructions on the FM-1; "
                  "sound, controls and PR behavior still require hardware validation.")
            print(f"PR #{args.pr}: {title}\nhttps://github.com/{args.repo}/pull/{args.pr}")
        return result
    except KeyboardInterrupt:
        print("Interrupted; the remote build was not canceled. Resume using --commit.", file=sys.stderr)
        return 130
    except (ValueError, KeyError, OSError, fm1_install.InstallError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
