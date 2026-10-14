#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build/download an exact PR revision and install its FWSC over USB-MIDI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import fm1_install


DEFAULT_REPO = "kmplngj/Felucca"
WORKFLOW = "ci.yml"


def gh(*args, payload=None):
    result = subprocess.run(
        ["gh", *args], input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError(f"GitHub CLI failed: {result.stderr.strip()}")
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


def resolve_revision(repository, number, revision=None):
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or any(part in (".", "..") for part in repository.split("/"))):
        raise ValueError("--repo must be owner/name")
    if not re.fullmatch(r"[1-9][0-9]*", str(number)):
        raise ValueError("PR must be a positive number")
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("--commit must be a full lowercase 40-character commit SHA")
    pull = api(f"repos/{repository}/pulls/{number}")
    head = pull["head"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("GitHub returned an invalid PR head SHA")
    revision = revision or head
    if revision != head:
        comparison = api(f"repos/{repository}/compare/{revision}...{head}")
        if comparison["status"] not in ("ahead", "identical"):
            raise ValueError("Requested commit is not reachable from the current PR head")
    return revision


def run_title(number, revision):
    return f"PR firmware #{number} @ {revision}"


def matching_runs(repository, number, revision, workflow_ref):
    runs = pages(f"repos/{repository}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch",
                 "workflow_runs")
    return sorted((run for run in runs
                   if run["display_title"] == run_title(number, revision)
                   and run["head_branch"] == workflow_ref), key=lambda run: run["id"], reverse=True)


def firmware_artifact(repository, run):
    artifacts = pages(f"repos/{repository}/actions/runs/{run['id']}/artifacts", "artifacts")
    live = [item for item in artifacts
            if item["name"] == f"firmware-{run['id']}" and not item["expired"]]
    return live[0] if len(live) == 1 else None


def ensure_run(repository, number, revision, workflow_ref, timeout, no_build=False):
    endpoint = f"repos/{repository}/actions/workflows/{WORKFLOW}/dispatches"
    runs = matching_runs(repository, number, revision, workflow_ref)
    run = next((item for item in runs if item["status"] != "completed" or
                (item["conclusion"] == "success" and firmware_artifact(repository, item))), None)
    existing = {item["id"] for item in runs}
    if run is None:
        if no_build:
            raise ValueError("No successful exact-commit build with a live firmware artifact. "
                             "Ask a maintainer to run CI with the printed PR/commit, or omit --no-build "
                             "if you have Actions write access.")
        print("Requesting full validation (requires Actions write access)...", flush=True)
        gh("api", "--method", "POST", endpoint, "--input", "-", payload={
            "ref": workflow_ref, "inputs": {"pr": str(number), "commit": revision},
        })
    deadline = time.monotonic() + timeout
    last_status = None
    while True:
        if run is None:
            run = next((item for item in matching_runs(repository, number, revision, workflow_ref)
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
                if not firmware_artifact(repository, run):
                    raise ValueError("Successful run has no live firmware artifact; request a fresh build")
                return run
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Timed out waiting for CI; rerun with the same --commit to resume. "
                             "The remote build was not canceled.")
        time.sleep(min(15, remaining))


def unique_file(root, pattern):
    matches = list(root.rglob(pattern))
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"Artifact must contain exactly one {pattern}")
    return matches[0]


def verify_download(root, revision):
    provenance = json.loads(unique_file(root, "provenance.json").read_text())
    if provenance["revision"] != revision:
        raise ValueError("Firmware provenance does not match the requested commit")
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


def download(repository, run, revision, output):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"run-{run['id']}-", dir=output)).resolve()
    try:
        gh("run", "download", str(run["id"]), "--repo", repository,
           "--name", f"firmware-{run['id']}", "--dir", str(root))
        package = verify_download(root, revision)
    except Exception:
        shutil.rmtree(root)
        raise
    print(f"Verified firmware: {package}", flush=True)
    return package


def install(package, port=None, yes=False):
    command = [sys.executable, str(Path(__file__).with_name("fm1_install.py")), str(package)]
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
    parser.add_argument("--download-only", action="store_true", help="verify without accessing MIDI")
    parser.add_argument("--no-build", action="store_true", help="reuse a run without dispatching a build")
    parser.add_argument("--out", type=Path, help="download parent; default build/pr-PR/SHA")
    parser.add_argument("--port", help="USB-MIDI port name passed to the installer")
    parser.add_argument("--yes", action="store_true", help="skip the installer's flash confirmation")
    parser.add_argument("--timeout", type=int, default=3600, help="maximum CI wait in seconds")
    parser.add_argument("--workflow-ref", help="maintainer workflow branch; default repository default branch")
    parser.add_argument("--resolve-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        revision = resolve_revision(args.repo, args.pr, args.commit)
        if args.resolve_only:
            print(revision)
            return 0
        print(f"Repository: {args.repo}\nPR: #{args.pr}\nCommit: {revision}", flush=True)
        workflow_ref = args.workflow_ref or api(f"repos/{args.repo}")["default_branch"]
        run = ensure_run(args.repo, args.pr, revision, workflow_ref, args.timeout, args.no_build)
        output = args.out or Path(__file__).resolve().parents[1] / "build" / f"pr-{args.pr}" / revision
        package = download(args.repo, run, revision, output)
        if args.download_only:
            print("Download verified; no hardware was accessed.")
            return 0
        result = install(package, args.port, args.yes)
        if result == 0:
            print("Installation complete. Follow the PR's User test instructions on the FM-1; "
                  "sound, controls and PR behavior still require hardware validation.")
        return result
    except KeyboardInterrupt:
        print("Interrupted; the remote build was not canceled. Resume using --commit.", file=sys.stderr)
        return 130
    except (ValueError, KeyError, OSError, fm1_install.InstallError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
