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
    "firmware_watch_test.py", "bootarea_test.py", "update_records_test.py",
    "build_identity_test.py",
    "bitmap_font_test.py", "build_guard_test.py", "build_report_test.py", "profile_contract_test.py", "build_product_test.py",
    "build_manifest_test.py", "wasm_report_test.py", "maintainer_bundle_test.py", "emulator_trace_test.py",
    "native_emulator_replay_test.py", "native_hotspots_test.py", "native_audio_window_test.py",
    "cpu_baseline_test.py", "diagnostics_test.py", "gen_samples_test.py", "fm1pkg_test.py", "fm1_pr_test.py", "replay_validation_test.py",
    "size_fns_test.py", "target_budget_test.py", "ui_compare_test.py",
)
PYTHON_INPUTS = {f"tests/{name}" for name in PORTABLE_TESTS} | {
    "tools/firmware_watch.py", "tools/fm1_bootarea.py", "tools/fm1_update_records.py",
    "tools/fm1_diagnostics.py", "tools/fm1_pr.py", "tests/console_diagnostics.c", "tests/ui_compare.py",
}
BACKUP_INPUTS = {"web/fm1backup.js", "web/test_backup.mjs"}
REVIEW_INPUTS = {"AGENTS.md", ".coderabbit.yaml", ".github/CODERABBIT.md",
                 ".agents/skills/firmware-watch/SKILL.md"}
# These exact inputs are exercised by the unconditional workflow/helper job.
# Scheduler/coverage implementations and workflow YAML remain shared inputs.
WORKFLOW_CHECK_INPUTS = {
    'tools/ci_changes.py', 'tests/ci_changes_test.py', 'tests/ci_test.py',
    'tests/coverage_contract_test.py', 'tests/test_jobs_test.py',
}

# Draft feedback is deliberately narrower than acceptance. Shared contracts,
# persistence, protocol, build inputs and unfamiliar paths retain full validation.
UI_FEEDBACK = ('ui', 'ui_render', 'ui_compare', 'settings', 'boot_splash', 'frame')
DSP_FEEDBACK = ('regression', 'sound_install', 'engines', 'union', 'arena')
FX_FEEDBACK = ('regression', 'fx_rest', 'audio_transitions', 'insert', 'chorus', 'sends')

# Exact audited paths: a new ui_*/eng_* file must not silently inherit a partial
# plan. The scheduler expands prerequisites; ready candidates still use select().
DRAFT_INPUTS = {
    **{f'firmware/src/{name}.c': UI_FEEDBACK for name in (
        'ui', 'ui_bank', 'ui_draw', 'ui_events', 'ui_fm6op', 'ui_graph',
        'ui_help', 'ui_input', 'ui_knob', 'ui_layer', 'ui_menu',
        'ui_menu_reading', 'ui_name', 'ui_slice', 'ui_tools')},
    **{f'firmware/src/{name}.c': UI_FEEDBACK + (
        'text', 'icon_streams', 'asan_icon_streams', 'screen_capture_ui',
        'identity_ui', 'settings_identity', 'ui_fm4') for name in ('gfx', 'icons')},
    **{f'firmware/src/eng_{name}.c': DSP_FEEDBACK + extra for name, extra in (
        ('digital', ('digital', 'fm4', 'fm4_div0')),
        ('drum', ('drum', 'tom_tail')),
        ('fm6', ('fm6', 'fm6_effective', 'fm6bank')),
        ('formant', ()), ('grain', ()), ('phase', ()),
        ('phys', ('phys', 'phys_ref')),
        ('sample', ('sample',)), ('slice', ('slice',)))},
    'firmware/src/fm6_core.c': DSP_FEEDBACK + ('fm6', 'fm6_effective', 'fm6bank'),
    'firmware/src/phys_dsp.c': DSP_FEEDBACK + ('phys', 'phys_ref'),
    'firmware/src/phys_symp.c': DSP_FEEDBACK + ('phys', 'phys_ref'),
    'firmware/src/fx.c': FX_FEEDBACK,
    # Direct test entry points only. ui_test.c, ui_render.c and hostsim.c are
    # shared by other harnesses and deliberately retain complete validation.
    **{f'tests/{name}_test.c': (unit,) for name, unit in (
        ('theme', 'text'), ('text_ref', 'text'),
        ('lcd_typography', 'ui'), ('lcd_readability', 'ui'), ('track_badge', 'ui'),
        ('boot_splash', 'boot_splash'), ('frame', 'frame'),
        ('sound_install', 'sound_install'), ('phys', 'phys'), ('drum', 'drum'),
        ('noise', 'noise'), ('fm6', 'fm6'), ('fm6_eff', 'fm6_effective'),
        ('slice', 'slice'), ('tom_tail', 'tom_tail'))},
    'tests/frame_source_test.py': ('frame',),
    'tests/fx_rest_parser_test.py': ('fx_rest',),
    # The chorus fixture imports mutation helpers from fx_rest_test.py.
    'tests/fx_rest_test.py': ('fx_rest', 'chorus'),
    'tests/audio_transition_test.py': ('audio_transitions',),
    'tests/chorus_depth_test.py': ('chorus',),
    'tests/send_gain_test.py': ('sends',),
}


def feedback(event_name, event, selection, release=False):
    pr = event.get('pull_request', {})
    if (release or event_name != 'pull_request' or not isinstance(pr, dict) or pr.get('draft') is not True
            or not selection['suites']['full']):
        return 'full', []
    if any(path in WORKFLOW_CHECK_INPUTS for path in selection['paths']):
        return 'full', []  # Selector/contract edits mixed with firmware need full acceptance.
    units = set()
    for path in selection['paths']:
        suites = select([path])
        if not any(suites.values()):
            continue
        if not suites['full']:
            return 'full', []  # Mixed independent suites need their normal gates.
        if path not in DRAFT_INPUTS:
            return 'full', []
        units.update(DRAFT_INPUTS[path])
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
        elif (path in WORKFLOW_CHECK_INPUTS or path in REVIEW_INPUTS or path.startswith(".github/ISSUE_TEMPLATE/")
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
            stream.write(f"Stage: {stage}. " + (
                "Focused draft feedback; full validation is required before merge.\n\n"
                if stage == 'quick' else "Complete applicable validation plan.\n\n"))
            if units:
                stream.write(f"Focused units (plus prerequisites): {', '.join(units)}\n\n")
            if not any(result['suites'].values()):
                stream.write("Scope: workflow/helper checks only; firmware, host and browser suites are not needed.\n\n")
            for suite, enabled in result["suites"].items():
                stream.write(f"- {suite}: {'run' if enabled else 'not needed'}\n")
            stream.write("\nSee selection.json in workflow diagnostics for the comparison and paths.\n")


if __name__ == "__main__":
    main()
