#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Stage the fork's tested web site and verify its deployment source."""
import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def select_run(run, artifacts, repository):
    """Only this repository's successful main CI may supply a Pages artifact."""
    if (run.get("repository", {}).get("full_name") != repository
            or run.get("head_repository", {}).get("full_name") != repository
            or run.get("path") != ".github/workflows/ci.yml"
            or run.get("head_branch") != "main"
            or run.get("event") not in {"push", "workflow_dispatch"}
            or run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise ValueError("Pages requires successful main CI from this repository")
    name = f"site-{run['id']}"
    matches = [a for a in artifacts["artifacts"] if a["name"] == name and not a["expired"]]
    if len(matches) > 1:
        raise ValueError("ambiguous site artifact")
    return matches[0] if matches else None  # Documentation/focused CI does not produce a site.


def check_site(site, run, repository):
    data = json.loads((Path(site) / "provenance.json").read_text())
    if (data["firmware"]["repository"] != repository
            or data["firmware"]["revision"] != run["head_sha"]
            or data["run_id"] != str(run["id"])):
        raise ValueError("site provenance does not match the validated main CI run")


def stage(webapp, out):
    webapp, out = Path(webapp).resolve(), Path(out).resolve()
    identity = json.loads((ROOT / "build/build-identity.json").read_text())
    revision = git(ROOT, "rev-parse", "HEAD")
    if identity["revision"] != revision or identity["dirty"] or identity.get("pr"):
        raise ValueError("site requires a clean, matching non-PR firmware build")
    if git(webapp, "status", "--porcelain"):
        raise ValueError("WebApp source must be clean")
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    version = f"{identity['version']}-fork.{revision[:8]}"
    subprocess.run(["python3", str(webapp / "make_site.py"), str(ROOT / "build/felucca.fwsc"),
                    version, str(out), "--licences", str(ROOT),
                    "--try", str(ROOT / "build/emu")], check=True)
    shutil.copy(ROOT / "assets/samples-cc0/ATTRIBUTION.txt", out / "firmware/ATTRIBUTION.txt")
    sources = {
        "firmware": {"repository": repository, "revision": revision},
        "webapp": {"repository": "kmplngj/Felucca-WebApp", "revision": git(webapp, "rev-parse", "HEAD")},
        "engines": {"repository": "kmplngj/Felucca-Engines",
                    "revision": git(ROOT, "ls-tree", "HEAD", "firmware/engines").split()[2]},
    }
    data = {**sources, "version": version, "run_id": os.environ["GITHUB_RUN_ID"]}
    (out / "provenance.json").write_text(json.dumps(data, indent=2) + "\n")
    links = "".join(f'<li>{html.escape(name)}: <a href="https://github.com/{s["repository"]}/tree/{s["revision"]}">'
                    f'{s["repository"]} @ {s["revision"]}</a></li>' for name, s in sources.items())
    (out / "sources.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Felucca fork sources</title>'
        f'<h1>Felucca personal fork</h1><p>{html.escape(version)}</p><ul>{links}</ul>'
        '<p><a href="firmware/LICENSE">GPL-3.0-only</a> · '
        '<a href="firmware/LICENSING.md">Third-party licensing</a> · '
        '<a href="firmware/LICENSES/">Licence texts</a> · '
        '<a href="firmware/ATTRIBUTION.txt">Sample attribution</a> · '
        '<a href="provenance.json">Build provenance</a></p>'
        '<p><a href="webapp/try/">Browser demo</a> · <a href="webapp/editor/">Editor</a> · '
        '<a href="webapp/installer/">Installer</a></p></html>\n')
    for name in ("try", "installer"):
        page = out / "webapp" / name / "index.html"
        text = page.read_text().replace('href="https://github.com/hugelton/Felucca"',
                                       'href="../../sources.html"')
        text = text.replace('>Source</a>', '>Fork sources</a>').replace(
            '>github.com/hugelton/Felucca</a>', '>Fork sources</a>')
        if name == "try":
            text = text.replace('<small class="version">', f'<small class="version">Personal fork {revision[:8]} · ')
        page.write_text(text)
    (out / ".nojekyll").touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("stage")
    build.add_argument("webapp")
    build.add_argument("out")
    select = commands.add_parser("select-run")
    select.add_argument("run")
    select.add_argument("artifacts")
    select.add_argument("repository")
    check = commands.add_parser("check-site")
    check.add_argument("site")
    check.add_argument("run")
    check.add_argument("repository")
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.webapp, args.out)
    elif args.command == "select-run":
        run = json.loads(Path(args.run).read_text())
        artifact = select_run(run, json.loads(Path(args.artifacts).read_text()), args.repository)
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"available={str(artifact is not None).lower()}\nrun_id={run['id']}\n")
    else:
        check_site(args.site, json.loads(Path(args.run).read_text()), args.repository)


if __name__ == "__main__":
    main()
