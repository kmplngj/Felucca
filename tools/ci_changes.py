#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Select CI suites from complete Git diffs; unfamiliar inputs require full CI."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


SUITES = ("full", "python", "backup", "emulator")
PORTABLE_TESTS = (
    "firmware_watch_test.py",
    "build_identity_test.py",
    "bitmap_font_test.py", "build_guard_test.py", "build_report_test.py", "profile_contract_test.py", "build_product_test.py",
    "build_manifest_test.py", "wasm_report_test.py",
    "cpu_baseline_test.py", "diagnostics_test.py", "gen_samples_test.py", "fm1pkg_test.py", "fm1_pr_test.py", "replay_validation_test.py",
    "size_fns_test.py", "target_budget_test.py", "ui_compare_test.py",
)
PYTHON_INPUTS = {f"tests/{name}" for name in PORTABLE_TESTS} | {
    "tools/firmware_watch.py",
    "tools/fm1_diagnostics.py", "tools/fm1_pr.py", "tests/console_diagnostics.c", "tests/ui_compare.py",
}
BACKUP_INPUTS = {"web/fm1backup.js", "web/test_backup.mjs"}
REVIEW_INPUTS = {"AGENTS.md", ".coderabbit.yaml", ".github/CODERABBIT.md",
                 ".agents/skills/firmware-watch/SKILL.md"}

# Draft feedback is deliberately narrower than acceptance. Shared contracts,
# persistence, protocol, build inputs and unfamiliar paths retain full validation.
UI_FEEDBACK = ('ui', 'ui_render', 'ui_compare', 'settings', 'boot_splash', 'frame')
DSP_FEEDBACK = ('regression', 'sound_install', 'engines', 'union', 'arena')


def feedback(event_name, event, selection, release=False):
    pr = event.get('pull_request', {})
    if (release or event_name != 'pull_request' or not isinstance(pr, dict) or pr.get('draft') is not True
            or not selection['suites']['full']):
        return 'full', []
    units = set()
    for path in selection['paths']:
        suites = select([path])
        if not any(suites.values()):
            continue
        if not suites['full']:
            return 'full', []  # Mixed independent suites need their normal gates.
        if path.startswith('firmware/src/ui') and path.endswith('.c'):
            units.update(UI_FEEDBACK)
        elif (path.startswith('firmware/src/eng_') and path.endswith('.c')
              and path != 'firmware/src/eng_macro.c'):
            units.update(DSP_FEEDBACK)
            engine = Path(path).stem.removeprefix('eng_')
            if engine in {'phys', 'drum', 'noise', 'fm6', 'slice'}:
                units.add(engine)
        elif path == 'firmware/src/fx.c':
            units.update(('regression', 'fx_rest', 'audio_transitions', 'insert', 'chorus', 'sends'))
        else:
            return 'full', []
    return ('quick', sorted(units)) if units else ('full', [])


def select(paths, force=False):
    selected = dict.fromkeys(SUITES, False)
    if force:
        selected["full"] = True
    for path in paths:
        # Match only known independent inputs. New code defaults to full coverage.
        if path in PYTHON_INPUTS or path.startswith("data/firmware-watch/"):
            selected["python"] = True
        elif path in BACKUP_INPUTS:
            selected["backup"] = True
        elif path.startswith("web/emu/"):
            selected["emulator"] = True
        elif (path in REVIEW_INPUTS or path.startswith(".github/ISSUE_TEMPLATE/")
              or (path.startswith(".agents/skills/") and path.endswith(".md"))):
            continue
        elif path.endswith(".md") and (
                path in {"README.md", "BUILDING.md", "CONTRIBUTING.md", ".github/CI.md"}
                or path.startswith(("docs/", "tests/", "assets/fonts/"))
                or path == "web/EDITOR_PROTOCOL.md"):
            continue
        elif path.startswith("docs/") and Path(path).suffix in {".png", ".jpg", ".svg"}:
            continue
        else:
            selected["full"] = True
    # The existing full runner already includes these suites.
    if selected["full"]:
        return dict.fromkeys(SUITES, False) | {"full": True}
    return selected


def changed_paths(event_name, event):
    if event_name == "pull_request":
        pr = event["pull_request"]
        base, head, separator = pr["base"]["sha"], pr["head"]["sha"], "..."
    elif event_name == "push" and event.get("ref") == "refs/heads/main":
        base, head, separator = event["before"], event["after"], ".."
    else:
        raise ValueError("manual, release or unsupported event requires complete validation")
    for revision in (base, head):
        if not re.fullmatch(r"[0-9a-f]{40}", revision) or revision == "0" * 40:
            raise ValueError("missing comparison revision requires complete validation")
    # Disable rename detection so both old and new paths participate in selection.
    # NUL delimiting handles spaces/newlines; Git has no API file-count cutoff.
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", f"{base}{separator}{head}", "--"],
        check=True, capture_output=True,
    )
    return [p.decode("utf-8", errors="surrogateescape") for p in result.stdout.split(b"\0") if p]


def plan(event_name, event, release=False):
    try:
        if release:
            raise ValueError("release validation always runs all suites")
        paths = changed_paths(event_name, event)
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        return {"suites": select([], force=True), "reason": str(error), "paths": []}
    return {"suites": select(paths), "reason": "complete Git diff", "paths": paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    except (KeyError, OSError, ValueError) as error:
        result = {"suites": select([], force=True), "reason": str(error), "paths": []}
    else:
        result = plan(os.environ.get("GITHUB_EVENT_NAME", ""), event, args.release)
    stage, units = feedback(os.environ.get('GITHUB_EVENT_NAME', ''),
                            event if 'event' in locals() and isinstance(event, dict) else {},
                            result, args.release)
    result['stage'], result['focus'] = stage, units
    matrix = {'include': [{'shard': 1, 'total': 1}]} if stage == 'quick' else {
        'include': [{'shard': 1, 'total': 2}, {'shard': 2, 'total': 2}]}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            for suite, enabled in result["suites"].items():
                stream.write(f"{suite}={str(enabled).lower()}\n")
            stream.write(f'stage={stage}\nfocus={",".join(units)}\n')
            stream.write('matrix=' + json.dumps(matrix, separators=(',', ':')) + '\n')
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as stream:
            stream.write("### CI selection\n\n")
            for suite, enabled in result["suites"].items():
                stream.write(f"- {suite}: {'run' if enabled else 'not needed'}\n")
            stream.write("\nSee selection.json in workflow diagnostics for the comparison and paths.\n")


if __name__ == "__main__":
    main()
