#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise selection and real PR/push diffs, including conservative fallbacks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ci_changes as changes


class SelectionTest(unittest.TestCase):
    def suites(self, paths):
        return {key for key, value in changes.select(paths).items() if value}

    def test_documentation_and_review_only(self):
        self.assertEqual(self.suites([
            "README.md", "BUILDING.md", "CONTRIBUTING.md", "AGENTS.md",
            ".github/CI.md", ".github/CODERABBIT.md", ".coderabbit.yaml",
            ".github/ISSUE_TEMPLATE/bug_report.yml", "docs/performance.md",
            "docs/felucca-1.0.png", "tests/build_guard_fixtures/README.md",
            "assets/fonts/m8stealth/README.md", "web/EDITOR_PROTOCOL.md",
        ]), set())

    def test_skill_markdown_needs_no_firmware_validation(self):
        for path in (".agents/skills/issue-delivery/SKILL.md",
                     ".agents/skills/issue-delivery/references/backlog.md",
                     ".agents/skills/new-skill/references/guide.md"):
            with self.subTest(path=path):
                self.assertEqual(self.suites([path]), set())
        self.assertEqual(self.suites([".agents/skills/issue-delivery/SKILL.md",
                                      "tests/diagnostics_test.py"]), {"python"})

    def test_skill_scripts_assets_and_firmware_mixtures_keep_full_validation(self):
        for path in (".agents/skills/new-skill/scripts/helper.py",
                     ".agents/skills/new-skill/assets/sound.wav",
                     ".agents/skills/new-skill/agents/openai.yaml",
                     ".agents/skills-other/new.md"):
            with self.subTest(path=path):
                self.assertEqual(self.suites([path]), {"full"})
        self.assertEqual(self.suites([".agents/skills/issue-delivery/SKILL.md",
                                      "firmware/src/audio.c"]), {"full"})

    def test_independent_suites_and_mixed_changes(self):
        for path in changes.PYTHON_INPUTS:
            with self.subTest(path=path):
                self.assertEqual(self.suites([path]), {"python"})
        for path in changes.BACKUP_INPUTS:
            with self.subTest(path=path):
                self.assertEqual(self.suites([path]), {"backup"})
        for path in ("web/emu/felucca_web.c", "web/emu/build.sh", "web/emu/emu_test.mjs",
                     "web/emu/native_check.c", "web/emu/worklet.js", "web/emu/index.html",
                     "web/emu/fonts/DotGothic16-subset.woff", "web/emu/browser_test.mjs",
                     "web/emu/browser_probe.js", "web/emu/package.json", "web/emu/package-lock.json"):
            with self.subTest(path=path):
                self.assertEqual(self.suites([path]), {"emulator"})
        self.assertEqual(self.suites(["README.md", "tests/diagnostics_test.py",
                                      "web/fm1backup.js", "web/emu/index.html"]),
                         {"python", "backup", "emulator"})

    def test_console_parser_contract_inputs(self):
        self.assertEqual(self.suites(["firmware/src/console.c"]), {"full"})
        for path in ("tools/fm1_diagnostics.py", "tests/diagnostics_test.py", "tests/console_diagnostics.c"):
            with self.subTest(path=path):
                self.assertEqual(self.suites([path]), {"python"})

    def test_firmware_watch_ledger_uses_portable_validation(self):
        for path in ("data/firmware-watch/sources.json", "data/firmware-watch/state.json",
                     "data/firmware-watch/reviews.jsonl", "data/firmware-watch/migration-report.json",
                     "data/firmware-watch/legacy-issue-152.json"):
            self.assertEqual(self.suites([path]), {"python"})
        self.assertEqual(self.suites([".agents/skills/firmware-watch/SKILL.md"]), set())
        self.assertEqual(self.suites(["data/firmware-watch/state.json", "firmware/src/audio.c"]),
                         {"full"})

    def test_shared_inputs_and_unknown_files_run_full(self):
        for path in ("firmware/src/eng_fm6.c", "firmware/hal/regs.h", "firmware/app.ld",
                     "firmware/loader/start.s", "build.sh", "tools/build.py",
                     "tools/gen_bitmap_font.py", "tools/sampleio.py", "tools/fm1_install.py",
                     "tools/ci.py", "tools/ci_changes.py", "pyproject.toml", "uv.lock", ".python-version",
                     "tools/get_toolchain.sh", "assets/fonts/Control.ttf",
                     "assets/samples-cc0/PIANO/sample.wav", "LICENSE", "LICENSING.md",
                     "LICENSES/Apache-2.0.txt", "web/editor.html", "web/fm1pkg.js",
                     "web/fm1ota.js", "web/package.json", "web/test_web.mjs",
                     "tests/hostsim.c", "tests/ui_render.py", "tests/cpu_baseline.py",
                     "tests/target_budget.py", "tests/golden.txt", "tests/union_golden.txt",
                     "tests/run_tests.sh", "tests/build_guard_target_test.py",
                     "tools/replay_native.c", "tools/fm1_replay.py", "tests/replay_test.py",
                     "tests/scenarios/interaction.json", "tests/scenarios/metronome-fixed.json",
                     "tests/size_fns_target_test.py", "tests/install_test.py",
                     "tests/regress_counter_test.py", ".github/workflows/ci.yml",
                     ".github/workflows/build.yml", ".github/workflows/release.yml",
                     "new-code.py", "docs/new-code.py", "firmware/embedded.md"):
            with self.subTest(path=path):
                self.assertEqual(self.suites([path, "web/fm1backup.js"]), {"full"})

    def test_large_diff_is_not_truncated(self):
        self.assertEqual(self.suites(["docs/change.md"] * 4000 + ["firmware/src/audio.c"]), {"full"})

    def test_draft_feedback_is_explicitly_partial_and_ready_requires_full(self):
        selection = {'suites': changes.select(['firmware/src/ui_draw.c']),
                     'paths': ['firmware/src/ui_draw.c', 'README.md']}
        stage, units = changes.feedback('pull_request', {'pull_request': {'draft': True}}, selection)
        self.assertEqual(stage, 'quick')
        self.assertIn('ui_render', units)
        for event, payload, release in (
                ('pull_request', {'pull_request': {'draft': False}}, False),
                ('pull_request', {}, False), ('push', {}, False),
                ('pull_request', {'pull_request': None}, False),
                ('workflow_dispatch', {}, False),
                ('pull_request', {'pull_request': {'draft': True}}, True)):
            self.assertEqual(changes.feedback(event, payload, selection, release), ('full', []))

    def test_high_risk_unknown_and_mixed_draft_changes_keep_full_validation(self):
        for extra in ('firmware/src/core.h', 'firmware/src/storage.c',
                      'firmware/src/console.c', 'firmware/src/voice.c',
                      'firmware/engines', 'firmware/src/eng_macro.c',
                      'firmware/src/ui_new.c', 'firmware/src/eng_new.c',
                      'tests/ui_test.c', 'tests/ui_render.c', 'tests/hostsim.c',
                      'tests/golden.txt', 'tests/target_budget.txt',
                      'tools/ci_changes.py', '.github/workflows/ci.yml',
                      'unknown.c', 'tools/fm1_diagnostics.py',
                      'web/fm1backup.js', 'web/emu/index.html'):
            paths = ['firmware/src/ui_draw.c', extra]
            with self.subTest(path=extra):
                self.assertEqual(changes.feedback('pull_request',
                    {'pull_request': {'draft': True}},
                    {'suites': changes.select(paths), 'paths': paths}), ('full', []))

    def test_audited_test_edits_get_focused_draft_feedback(self):
        paths = ['firmware/src/fx.c', 'tests/chorus_depth_test.py',
                 'tests/fm6_eff_test.c', 'docs/change.md']
        selection = {'suites': changes.select(paths), 'paths': paths}
        self.assertEqual(changes.feedback('pull_request',
            {'pull_request': {'draft': True}}, selection),
            ('quick', sorted(set(changes.FX_FEEDBACK) | {'fm6_effective'})))
        # A test-only PR also stays partial until it is ready for review.
        paths = ['tests/fm6_eff_test.c']
        selection = {'suites': changes.select(paths), 'paths': paths}
        self.assertEqual(changes.feedback('pull_request',
            {'pull_request': {'draft': True}}, selection), ('quick', ['fm6_effective']))
        self.assertEqual(changes.feedback('pull_request',
            {'pull_request': {'draft': False}}, selection), ('full', []))
        paths = ['tests/fx_rest_test.py']
        self.assertEqual(changes.feedback('pull_request',
            {'pull_request': {'draft': True}},
            {'suites': changes.select(paths), 'paths': paths}),
            ('quick', ['chorus', 'fx_rest']))

    def test_graphics_and_engine_helpers_include_specific_regressions(self):
        for path, required in (
                ('firmware/src/gfx.c', {'text', 'icon_streams', 'asan_icon_streams'}),
                ('firmware/src/icons.c', {'screen_capture_ui', 'identity_ui'}),
                ('firmware/src/fm6_core.c', {'fm6', 'fm6_effective', 'fm6bank'}),
                ('firmware/src/phys_dsp.c', {'phys', 'phys_ref'}),
                ('firmware/src/phys_symp.c', {'phys', 'phys_ref'}),
                ('firmware/src/eng_sample.c', {'regression', 'sample'}),
                ('firmware/src/eng_digital.c', {'digital', 'fm4', 'fm4_div0'})):
            with self.subTest(path=path):
                stage, units = changes.feedback('pull_request',
                    {'pull_request': {'draft': True}},
                    {'suites': changes.select([path]), 'paths': [path]})
                self.assertEqual(stage, 'quick')
                self.assertTrue(required <= set(units))

    def test_all_draft_mappings_exist_and_resolve_in_real_scheduler_plan(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / 'tests'))
        import test_jobs
        plan = test_jobs.parse_plan(subprocess.check_output(
            ['sh', 'tests/run_tests.sh', '--plan'], cwd=root, text=True))
        for path, units in changes.DRAFT_INPUTS.items():
            with self.subTest(path=path):
                self.assertTrue((root / path).is_file(), path)
                selection = {'suites': changes.select([path]), 'paths': [path]}
                self.assertEqual(changes.feedback('pull_request',
                    {'pull_request': {'draft': True}}, selection), ('quick', sorted(units)))
                selected = test_jobs.coverage.select_plan(plan,
                    {'kind': 'focused', 'selected': units})
                self.assertTrue(set(units) <= {u['name'] for u in selected})
                for event, payload, release in (
                        ('pull_request', {'pull_request': {'draft': False}}, False),
                        ('push', {}, False), ('workflow_dispatch', {}, False),
                        ('pull_request', {'pull_request': {'draft': True}}, True)):
                    self.assertEqual(changes.feedback(event, payload, selection, release), ('full', []))

    def test_manual_release_and_unknown_events_force_full(self):
        for event in ("workflow_dispatch", "schedule", "", "pull_request_target"):
            self.assertTrue(changes.plan(event, {})["suites"]["full"])
        self.assertTrue(changes.plan("pull_request", {}, release=True)["suites"]["full"])

    def test_bad_or_missing_revisions_force_full(self):
        for revision in ("0" * 40, "bad", "--help", None):
            event = {"ref": "refs/heads/main", "before": revision, "after": "1" * 40}
            self.assertTrue(changes.plan("push", event)["suites"]["full"])
        self.assertTrue(changes.plan("pull_request", {})["suites"]["full"])
        event = {"ref": "refs/heads/main", "before": "1" * 40, "after": "2" * 40}
        with patch.object(changes.subprocess, "run", side_effect=subprocess.CalledProcessError(128, "git")):
            self.assertTrue(changes.plan("push", event)["suites"]["full"])

    def test_cli_emits_full_outputs_for_unreadable_event(self):
        with tempfile.TemporaryDirectory() as directory:
            output, summary = Path(directory) / "output", Path(directory) / "summary"
            env = dict(os.environ, GITHUB_EVENT_PATH=str(Path(directory) / "missing"),
                       GITHUB_EVENT_NAME="push", GITHUB_OUTPUT=str(output),
                       GITHUB_STEP_SUMMARY=str(summary))
            result = subprocess.run([sys.executable, str(Path(changes.__file__))],
                                    env=env, capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(result.stdout)["suites"]["full"])
            self.assertTrue(output.read_text().startswith("full=true\npython=false\nbackup=false\nemulator=false\n"))
            self.assertEqual(json.loads(result.stdout)['stage'], 'full')
            self.assertIn('stage=full\nfocus=\nmatrix=', output.read_text())
            self.assertIn("full: run", summary.read_text())


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "ci-test@example.invalid")
        self.git("config", "user.name", "CI fixtures")
        self.write("README.md")
        self.base = self.commit()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def plan(self, event, payload):
        real_run = subprocess.run
        with patch.object(changes.subprocess, "run") as run:
            # Execute the production command in our actual Git fixture.
            run.side_effect = lambda *args, **kwargs: real_run(*args, cwd=self.root, **kwargs)
            return changes.plan(event, payload)

    def pr(self, head):
        return self.plan("pull_request", {"pull_request": {
            "base": {"sha": self.base}, "head": {"sha": head}}})

    def test_pr_includes_earlier_commits(self):
        self.write("firmware/src/audio.c")
        self.commit()
        self.write("docs/change.md")
        result = self.pr(self.commit())
        self.assertTrue(result["suites"]["full"])
        self.assertIn("firmware/src/audio.c", result["paths"])

    def test_skill_instruction_only_pr_uses_lightweight_checks(self):
        self.write(".agents/skills/issue-delivery/SKILL.md")
        self.commit()
        self.write(".agents/skills/issue-delivery/references/backlog.md")
        result = self.pr(self.commit())
        self.assertEqual(set(result["paths"]), {
            ".agents/skills/issue-delivery/SKILL.md",
            ".agents/skills/issue-delivery/references/backlog.md",
        })
        self.assertFalse(any(result["suites"].values()))

    def test_pr_excludes_unrelated_base_branch_changes(self):
        self.git("switch", "-c", "feature")
        self.write("docs/change.md")
        head = self.commit()
        self.git("switch", "main")
        self.write("firmware/src/audio.c")
        self.base = self.commit()
        result = self.pr(head)
        self.assertEqual(result["paths"], ["docs/change.md"])
        self.assertFalse(result["suites"]["full"])

    def test_push_includes_all_pushed_commits(self):
        self.write("web/fm1backup.js")
        self.commit()
        self.write("docs/change.md")
        result = self.plan("push", {"ref": "refs/heads/main", "before": self.base, "after": self.commit()})
        self.assertTrue(result["suites"]["backup"])
        self.assertFalse(result["suites"]["full"])

    def test_rename_out_of_code_and_deletions_are_not_lost(self):
        self.write("firmware/src/audio.c")
        self.base = self.commit()
        (self.root / "docs").mkdir()
        self.git("mv", "firmware/src/audio.c", "docs/audio.md")
        (self.root / "README.md").unlink()
        result = self.pr(self.commit())
        self.assertTrue(result["suites"]["full"])
        self.assertEqual(set(result["paths"]), {"firmware/src/audio.c", "docs/audio.md", "README.md"})

    def test_paths_with_spaces_and_newlines_are_preserved(self):
        names = ["docs/a space.md", "docs/a\nnewline.md", "new\ncode.c"]
        for name in names:
            self.write(name)
        result = self.pr(self.commit())
        self.assertEqual(set(result["paths"]), set(names))
        self.assertTrue(result["suites"]["full"])

    def test_force_push_uses_before_after_without_merge_base(self):
        self.git("switch", "--orphan", "replacement")
        self.write("docs/replaced.md")
        result = self.plan("push", {"ref": "refs/heads/main", "before": self.base, "after": self.commit()})
        self.assertEqual(set(result["paths"]), {"README.md", "docs/replaced.md"})
        self.assertFalse(result["suites"]["full"])


class RequiredCheckTest(unittest.TestCase):
    def test_actual_workflow_gate_rejects_failed_canceled_and_skipped_selected_jobs(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/build.yml"
        # Exercise the script actually used by the preserved required check.
        block = workflow.read_text().split("      - name: Check selected validation results\n", 1)[1]
        script = textwrap.dedent(block.split("        run: |\n", 1)[1].split("      - ", 1)[0])
        env = dict(os.environ, WORKFLOW_RESULT="success", FULL_SELECTED="false",
                   VALIDATION_RESULT="skipped")
        for suite in ("PYTHON", "BACKUP", "EMULATOR", "BROWSER"):
            env[suite + "_SELECTED"] = "false"
            env[suite + "_RESULT"] = "skipped"

        def run(overrides):
            return subprocess.run(["bash", "-e", "-c", script], env=env | overrides,
                                  capture_output=True, text=True).returncode

        self.assertEqual(run({}), 0)  # Docs-only still completes the required check.
        for result in ("failure", "cancelled", "skipped"):
            with self.subTest(workflow=result):
                self.assertNotEqual(run({"WORKFLOW_RESULT": result}), 0)
            with self.subTest(validation=result):
                self.assertNotEqual(run({"FULL_SELECTED": "true", "VALIDATION_RESULT": result,
                                         "BROWSER_SELECTED": "true", "BROWSER_RESULT": "success"}), 0)
            for suite in ("PYTHON", "BACKUP", "EMULATOR", "BROWSER"):
                with self.subTest(suite=suite, result=result):
                    self.assertNotEqual(run({suite + "_SELECTED": "true", suite + "_RESULT": result}), 0)
        for suite in ("PYTHON", "BACKUP", "EMULATOR", "BROWSER"):
            self.assertEqual(run({suite + "_SELECTED": "true", suite + "_RESULT": "success"}), 0)
        self.assertEqual(run({"FULL_SELECTED": "true", "VALIDATION_RESULT": "success",
                              "BROWSER_SELECTED": "true", "BROWSER_RESULT": "success"}), 0)
        # Explicit target-only builds still require target validation, not browser work.
        self.assertEqual(run({"FULL_SELECTED": "true", "VALIDATION_RESULT": "success"}), 0)


if __name__ == "__main__":
    unittest.main()
