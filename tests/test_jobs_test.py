#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise real shell workers: overlap, shared outputs, failures and cancellation."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import test_jobs

RUNNER = Path(test_jobs.__file__).resolve()
SHELL = Path(__file__).with_name("run_tests.sh")


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = self.root / "units.sh"
        self.env = dict(os.environ, TEST_JOBS="2")
        for name in ("GOLDEN_UPDATE", "BUDGET_UPDATE", "UI_SCREEN_DIR", "MENU_JSON", "TRACKS", "JOBS"):
            self.env.pop(name, None)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, plan, body):
        self.script.write_text("#!/bin/sh\nset -e\n"
                               "if [ \"$1\" = --plan ]; then\ncat <<'PLAN'\n" + plan +
                               "\nPLAN\nexit 0\nfi\n" + body + "\n")

    def launch(self, env=None, ai_output=False, preflight=False):
        args = (["--ai-output"] if ai_output else []) + (["--preflight"] if preflight else [])
        return subprocess.Popen([sys.executable, str(RUNNER), str(self.script), *args], cwd=self.root,
                                env=env or self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)

    def finish(self, process):
        try:
            output = process.communicate(timeout=15)[0]
        except subprocess.TimeoutExpired:
            process.terminate()
            output = process.communicate(timeout=5)[0]
            self.fail("scheduler did not finish:\n" + output)
        summaries = list(self.root.glob("build/host/test-run-*/summary.json"))
        self.assertEqual(len(summaries), 1, output)
        return process.returncode, output, json.loads(summaries[0].read_text())

    def wait_file(self, name):
        deadline = time.monotonic() + 8
        while not (self.root / name).exists():
            if time.monotonic() > deadline:
                self.fail(f"worker did not create {name}")
            time.sleep(0.01)

    def test_rejected_concurrent_production_run_preserves_explicit_report(self):
        output = self.root / 'host'
        output.mkdir()
        report = self.root / 'coverage.json'
        original = b'{"run_id":"active-owner","status":"complete"}\n'
        report.write_bytes(original)
        env = dict(self.env, FELUCCA_COVERAGE_REPORT=str(report))
        with (output / '.test-run.lock').open('a+') as lock:
            test_jobs.fcntl.flock(lock, test_jobs.fcntl.LOCK_EX | test_jobs.fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'another host suite'):
                test_jobs.execute(SHELL, output, env)
            self.assertEqual(report.read_bytes(), original)

    def test_shards_cover_every_unit_once_and_keep_dependency_components(self):
        plan = test_jobs.parse_plan('a\t\techo\nb\ta\techo\nc\t\techo\nd\tc\techo\ne\t\techo')
        shards = test_jobs.coverage.shard_plan(plan)
        self.assertEqual(shards, test_jobs.coverage.shard_plan(plan))
        self.assertEqual(sorted(n for shard in shards for n in shard), sorted(u['name'] for u in plan))
        self.assertFalse(set(shards[0]) & set(shards[1]))
        for shard in shards:
            for unit in plan:
                if unit['name'] in shard:
                    self.assertTrue(set(unit['dependencies']) <= set(shard))
        focused = test_jobs.coverage.select_plan(plan, dict(kind='focused', selected=['b']))
        self.assertEqual([u['name'] for u in focused], ['a', 'b'])
        with self.assertRaises(ValueError):
            test_jobs.coverage.select_plan(plan, dict(kind='focused', selected=['unknown']))

    def test_real_runner_shard_and_focus_execute_only_declared_closure(self):
        self.fixture('a\t\techo\nb\ta\techo\nc\t\techo', 'echo actual-$2')
        for args, expected in ((['--shard', '1/2', '--cohort', 'ci-fresh'], ['a', 'b']),
                               (['--select', 'b'], ['a', 'b'])):
            process = subprocess.run([sys.executable, str(RUNNER), str(self.script), *args],
                                     cwd=self.root, env=self.env, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            summaries = sorted(self.root.glob('build/host/test-run-*/summary.json'), key=lambda p: p.stat().st_mtime_ns)
            summary = json.loads(summaries[-1].read_text())
            self.assertEqual([u['name'] for u in summary['units']], expected)
            self.assertNotEqual(summary['scope']['kind'], 'full')
            self.assertNotIn('ALL HOST TESTS PASSED', process.stdout)
            self.assertNotIn('actual-c', process.stdout)

    def test_overlap_dependencies_bound_and_ordered_output(self):
        # a and b must overlap to release one another; c reads their shared result.
        self.fixture("a\t\techo a\nb\t\techo b\nc\ta b\techo c", r'''
case "$2" in
 a) touch a; while [ ! -f b ]; do sleep .01; done; echo first; touch result_a ;;
 b) touch b; while [ ! -f a ]; do sleep .01; done; echo second; touch result_b ;;
 c) test -f result_a; test -f result_b; echo third ;;
esac
''')
        code, output, summary = self.finish(self.launch())
        self.assertEqual(code, 0, output)
        self.assertLess(output.index("first"), output.index("second"))
        self.assertLess(output.index("second"), output.index("third"))
        units = {u["name"]: u for u in summary["units"]}
        for name in ("a", "b"):
            self.assertLessEqual(units["c"]["started"], summary["seconds"])
            self.assertGreaterEqual(units["c"]["started"], units[name]["started"] + units[name]["seconds"])
        self.assertEqual(summary["inner_jobs"], "1")

    def test_worker_limit_and_explicit_inner_jobs(self):
        self.fixture("\n".join(f"u{i}\t\techo u{i}" for i in range(6)), r'''
python3 - <<'PY'
import fcntl, json, os, time
from pathlib import Path
def change(delta):
    with open('counter.lock', 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = Path('counter.json')
        state = json.loads(path.read_text()) if path.exists() else {'active':0,'peak':0}
        state['active'] += delta
        state['peak'] = max(state['peak'], state['active'])
        path.write_text(json.dumps(state))
        return state
change(1)
while change(0)['peak'] < 2:
    time.sleep(.01)
time.sleep(.05)
change(-1)
assert os.environ['JOBS'] == '3'
PY
''')
        self.env["JOBS"] = "3"
        code, output, _ = self.finish(self.launch())
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads((self.root / "counter.json").read_text()), dict(active=0, peak=2))

    def test_serial_mode_and_baseline_writers_never_overlap(self):
        self.fixture("a\t\techo a\nb\t\techo b", r'''
case "$2" in
 a) mkdir busy; echo first; rmdir busy; touch finished ;;
 b) test -f finished; test ! -d busy; echo second ;;
esac
''')
        self.env["TEST_JOBS"] = "1"
        code, output, summary = self.finish(self.launch())
        self.assertEqual(code, 0, output)
        self.assertEqual(summary["jobs"], 1)
        self.assertEqual(summary["inner_jobs"], "default")
        for name in ("GOLDEN_UPDATE", "BUDGET_UPDATE", "UI_SCREEN_DIR", "MENU_JSON", "TRACKS"):
            for value in ("1", ""):
                self.assertEqual(test_jobs.job_count(dict(TEST_JOBS="4", **{name: value})), 1)

    def test_shell_compile_failure_blocks_consumers_and_preserves_other_failures(self):
        self.fixture("compile\t\techo a\nconsumer\tcompile\techo b\nindependent\t\techo c", r'''
case "$2" in
 compile) echo compiler-failed; false; echo must-not-run ;;
 consumer) touch stale-result-consumed ;;
 independent) echo independent-failed; exit 7 ;;
esac
''')
        code, output, summary = self.finish(self.launch())
        self.assertEqual(code, 1, output)
        self.assertNotIn("ALL HOST TESTS PASSED", output)
        self.assertNotIn("must-not-run", output)
        self.assertIn("compiler-failed", output)
        self.assertIn("independent-failed", output)
        self.assertFalse((self.root / "stale-result-consumed").exists())
        self.assertEqual([u["status"] for u in summary["units"]], ["failed", "blocked", "failed"])

    def test_cancellation_kills_grandchildren_and_releases_checkout_lock(self):
        self.fixture("long\t\techo long", r'''
python3 -c 'import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); open("grandchild", "w").write(str(os.getpid())); time.sleep(60)' &
wait
''')
        process = self.launch()
        try:
            self.wait_file("grandchild")
            second = self.launch()
            second_output = second.communicate(timeout=5)[0]
            self.assertNotEqual(second.returncode, 0, second_output)
            self.assertIn("another host suite", second_output)
            process.send_signal(signal.SIGTERM)
            code, output, summary = self.finish(process)
            self.assertEqual(code, 128 + signal.SIGTERM, output)
            self.assertEqual(summary["status"], "cancelled")
            pid = int((self.root / "grandchild").read_text())
            # A killed orphan may remain as a zombie briefly under a container init.
            state = Path(f"/proc/{pid}/stat")
            if state.exists():
                self.assertEqual(state.read_text().split()[2], "Z")
            else:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            with (self.root / "build/host/.test-run.lock").open("a+") as lock:
                test_jobs.fcntl.flock(lock, test_jobs.fcntl.LOCK_EX | test_jobs.fcntl.LOCK_NB)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)

    def test_bad_plans_and_job_counts_fail_before_running_workers(self):
        for value in ("0", "-1", "4.5", "", "x", "33"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                test_jobs.job_count(dict(TEST_JOBS=value))
        for plan in ("", "bad", "a\tmissing\techo", "a\t\techo\na\t\techo", "../x\t\techo"):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                test_jobs.parse_plan(plan)

    def test_ai_output_reduces_transcript_without_changing_execution_or_logs(self):
        self.fixture("noise\t\techo noise\nnotices\t\techo notices", r'''
echo "$2" >> calls
case "$2" in
 noise) python3 -c 'print("ordinary passing detail " * 4000)' ;;
 notices)
    echo '== test descriptions mention skipped negative fixtures'
    echo 'compiler.c:12: warning: example warning'
    echo '== skip reference (no DaisySP)'
    echo 'regress: CPU: 32 counts unavailable; the budget is not checked'
    ;;
esac
''')
        code, full, normal = self.finish(self.launch())
        self.assertEqual(code, 0, full)
        baseline = self.root / "baseline"
        next(self.root.glob("build/host/test-run-*")).rename(baseline)
        code, compact, summary = self.finish(self.launch(ai_output=True))
        self.assertEqual(code, 0, compact)
        self.assertLess(len(compact.encode()), len(full.encode()) // 20)
        self.assertNotIn("ordinary passing detail", compact)
        self.assertIn("warning: example warning", compact)
        self.assertIn("skip reference (no DaisySP)", compact)
        self.assertIn("budget is not checked", compact)
        self.assertIn("PASSED units: passed=2 failed=0 blocked=0 cancelled=0", compact)
        self.assertEqual(sorted((self.root / "calls").read_text().splitlines()),
                         ["noise", "noise", "notices", "notices"])
        logs = next(self.root.glob("build/host/test-run-*"))
        for before, after in zip(normal["units"], summary["units"]):
            self.assertEqual(before["status"], after["status"])
            self.assertEqual((baseline / before["log"]).read_bytes(), (logs / after["log"]).read_bytes())
        self.assertEqual(summary["units"][1]["diagnostics"]["warning_lines"], 1)
        self.assertEqual(summary["units"][1]["diagnostics"]["skip_lines"], 2)

    def test_ai_output_keeps_failure_identity_early_error_tail_and_blocking(self):
        self.fixture("compile\t\techo a\nconsumer\tcompile\techo b\nindependent\t\techo c", r'''
case "$2" in
 compile)
    echo 'fatal error: original compiler failure'
    python3 -c 'print("later noise\n" * 3000)'
    echo final-detail
    exit 7 ;;
 consumer) touch stale-result-consumed ;;
 independent) echo independent-success ;;
esac
''')
        code, output, summary = self.finish(self.launch(ai_output=True))
        self.assertEqual(code, 1, output)
        self.assertIn("compile failed exit=7", output)
        self.assertIn("consumer blocked", output)
        self.assertIn("fatal error: original compiler failure", output)
        self.assertIn("final-detail", output)
        self.assertNotIn("independent-success", output)
        self.assertNotIn("PASSED", output)
        self.assertLess(len(output), 2500)
        self.assertFalse((self.root / "stale-result-consumed").exists())
        self.assertEqual([u["status"] for u in summary["units"]], ["failed", "blocked", "passed"])
        self.assertTrue(summary["units"][0]["excerpt_limited"])
        log = next(self.root.glob("build/host/test-run-*/001-compile.log"))
        self.assertEqual(log.read_text().count("later noise"), 3000)

    def test_ai_output_preserves_preflight_failure_exit_code_and_raw_output(self):
        self.script.write_text('''#!/bin/sh
if [ "$1" = --preflight ]; then
    echo preflight-stdout
    echo 'error: missing prerequisite' >&2
    exit 7
fi
touch must-not-plan
''')
        code, output, summary = self.finish(self.launch(ai_output=True, preflight=True))
        self.assertEqual(code, 7, output)
        self.assertIn("preflight failed exit=7", output)
        self.assertIn("missing prerequisite", output)
        self.assertFalse((self.root / "must-not-plan").exists())
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["units"], [])
        self.assertEqual(next(self.root.glob("build/host/test-run-*/preflight.log")).read_text(),
                         "preflight-stdout\nerror: missing prerequisite\n")

    def test_ai_output_bounds_planning_failure_and_retains_both_streams(self):
        self.script.write_text('''#!/bin/sh
python3 -c 'print("invalid plan detail " * 4000)'
echo 'error: planner failed' >&2
exit 9
''')
        code, output, summary = self.finish(self.launch(ai_output=True))
        self.assertEqual(code, 1, output)
        self.assertIn("plan failed exit=9", output)
        self.assertIn("planner failed", output)
        self.assertLess(len(output), 2500)
        self.assertEqual(summary["plan"]["returncode"], 9)
        log = next(self.root.glob("build/host/test-run-*/plan.stdout.log"))
        self.assertGreater(log.stat().st_size, 50000)

    def test_ai_output_planning_failure_shows_reason_written_to_stdout(self):
        self.script.write_text("#!/bin/sh\nprintf 'input\\t\\tu_input\\n'\necho 'run ./build.sh first'\nexit 1\n")
        code, output, summary = self.finish(self.launch(ai_output=True))
        self.assertEqual(code, 1, output)
        self.assertIn("run ./build.sh first", output)
        self.assertEqual(summary["units"], [])

    def test_ai_output_preflight_keeps_caller_environment_and_warnings(self):
        self.script.write_text('''#!/bin/sh
set -e
case "$1" in
 --preflight)
    test "${JOBS-unset}" = unset
    echo 'DeprecationWarning: example preflight warning' >&2 ;;
 --plan) printf 'worker\t\techo worker\n' ;;
 --unit) test "$JOBS" = 1; touch worker-ran ;;
esac
''')
        code, output, summary = self.finish(self.launch(ai_output=True, preflight=True))
        self.assertEqual(code, 0, output)
        self.assertTrue((self.root / "worker-ran").exists())
        self.assertIn("DeprecationWarning", output)
        self.assertEqual(summary["diagnostic_counts"], dict(warning_lines=1, skip_lines=0))
        self.assertEqual(summary["preflight"]["status"], "passed")

    def test_ai_output_cancellation_during_preflight_remains_cancelled(self):
        self.script.write_text('''#!/bin/sh
echo preflight-started
touch ready
sleep 60
''')
        process = self.launch(ai_output=True, preflight=True)
        try:
            self.wait_file("ready")
            process.send_signal(signal.SIGTERM)
            code, output, summary = self.finish(process)
            self.assertEqual(code, 128 + signal.SIGTERM, output)
            self.assertEqual(summary["status"], "cancelled")
            self.assertEqual(summary["preflight"]["status"], "cancelled")
            self.assertIn("preflight-started", output)
            self.assertNotIn("PASSED", output)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)

    def test_ai_output_rejects_large_invalid_plan_with_successful_planner_exit(self):
        self.script.write_text("#!/bin/sh\npython3 -c 'print(\"invalid plan \" * 4000)'\n")
        code, output, summary = self.finish(self.launch(ai_output=True))
        self.assertEqual(code, 1, output)
        self.assertIn("invalid host-test plan", output)
        self.assertLess(len(output), 2000)
        self.assertEqual(summary["plan"]["status"], "failed")
        self.assertEqual(summary["plan"]["returncode"], 0)
        self.assertEqual(summary["units"], [])

    def test_real_worker_keeps_errexit_and_aggregates_run_failures(self):
        # Use the actual shell dispatch and run() rather than another implementation.
        source = SHELL.read_text()
        helper = source[source.index("fail=0\n"):source.index("HALF=$(", source.index("fail=0\n"))]
        self.script.write_text("set -e\nMODE=--unit\nSELECTED_UNIT=fixture\n" + helper + r'''
u_fixture() {
    run intentional-failure false
    echo after-test-failure
    false
    echo after-compile-failure
}
unit fixture "" u_fixture
''')
        result = subprocess.run(["sh", str(self.script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("after-test-failure", result.stdout)
        self.assertNotIn("after-compile-failure", result.stdout)

        # No compile failure may mask a lost run() failure or an incorrect unit
        # exit status: the aggregate alone must make this worker fail.
        self.script.write_text("set -e\nMODE=--unit\nSELECTED_UNIT=fixture\n" + helper + r'''
u_fixture() {
    run intentional-failure false
    echo after-test-failure
}
unit fixture "" u_fixture
''')
        result = subprocess.run(["sh", str(self.script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("after-test-failure", result.stdout)

    def test_real_plan_has_valid_shared_output_dependencies(self):
        # Planning needs package presence and HALF_FRAMES, not actual firmware.
        (self.root / "tests").mkdir()
        (self.root / "tests/run_tests.sh").write_text(SHELL.read_text())
        (self.root / 'tools').mkdir()
        (self.root / 'tools/test_coverage.py').write_text((SHELL.parent.parent / 'tools/test_coverage.py').read_text())
        (self.root / "firmware/src").mkdir(parents=True)
        (self.root / "firmware/src/core.h").write_text("#define HALF_FRAMES 128\n")
        (self.root / "firmware/src/felucca.c").write_text('#define FELUCCA_VERSION "fixture"\n')
        (self.root / "build/gen").mkdir(parents=True)
        (self.root / "build/gen/felucca_tables.h").touch()
        (self.root / "build/felucca.fwsc").touch()
        # Planning only checks node's presence. Keep this fixture independent
        # of the host's optional web tooling; no JavaScript is executed here.
        (self.root / "bin").mkdir()
        node = self.root / "bin/node"
        node.write_text("#!/bin/sh\nexit 0\n")
        node.chmod(0o755)
        env = dict(self.env, SANITIZE="0", CC="false", FELUCCA_PROFILE="standard")
        env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", os.defpath)
        result = subprocess.run(["sh", "tests/run_tests.sh", "--plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=True)
        plan = {unit["name"]: unit for unit in test_jobs.parse_plan(result.stdout)}
        shards = test_jobs.coverage.shard_plan(list(plan.values()))
        self.assertEqual(sorted(name for shard in shards for name in shard), sorted(plan))
        for shard in shards:
            self.assertTrue(all(set(plan[name]['dependencies']) <= set(shard) for name in shard))
        self.assertEqual(plan["web"]["dependencies"], ["editor", "descriptors"])
        self.assertEqual(plan["ui_fm4"]["dependencies"], ["ui_render"])
        self.assertEqual(plan["reverb"]["dependencies"], ["perform"])
        self.assertEqual(plan["stress_replay"]["dependencies"], ["replay"])
        self.assertEqual({f"catalog_{i}" for i in (10, 11, 12, 13)} & plan.keys(),
                         {f"catalog_{i}" for i in (10, 11, 12, 13)})
        self.assertEqual(plan['adpcm']['needs'], ['assets', 'adpcm-assets'])
        self.assertEqual(plan['adpcm']['capabilities'], ['adpcm-reference'])
        self.assertEqual(plan['asan_adpcm']['needs'], ['assets', 'adpcm-assets', 'sanitizer'])
        self.assertIn('asan_fuzz_ed', plan)
        self.assertIn('sanitizer', plan['asan_fuzz_ed']['needs'])
        self.assertEqual(plan['diagnostics']['needs'], [])
        self.assertEqual(plan['asan_boot_clock']['dependencies'], [])
        self.assertEqual(plan['asan_boot_clock']['needs'], ['assets', 'sanitizer'])
        self.assertEqual([unit['name'] for unit in test_jobs.coverage.select_plan(
            list(plan.values()), dict(kind='focused', selected=['asan_boot_clock']))],
            ['asan_boot_clock'])
        for name in ('adsr_sync', 'adsr_sync_fm4'):
            self.assertIn(name, plan)
            self.assertEqual(plan[name]['needs'], ['assets'])
            self.assertEqual(plan[name]['dependencies'], [])
        self.assertEqual(plan['regression']['producers'],
                         ['regress', 'regress_os', 'regress_cpu2_0', 'regress_c1',
                          'tests/regress_counter_test.py'])
        declared = [p for unit in plan.values() for p in unit['producers']]
        for producer in test_jobs.coverage.PRODUCERS:
            self.assertEqual(declared.count(producer), 1, producer)
        expected = result.stdout

        # A compiler without sanitizer support must select and execute the same
        # explicit skip unit; workers do not repeat the availability probe.
        env["SANITIZE"] = "1"
        result = subprocess.run(["sh", "tests/run_tests.sh", "--plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=True)
        plan = {unit["name"]: unit for unit in test_jobs.parse_plan(result.stdout)}
        self.assertEqual(result.stdout, expected)

        # Missing generated tables still permit a valid partial plan. In
        # particular, web cannot depend on absent editor/descriptor units.
        (self.root / "build/gen/felucca_tables.h").unlink()
        result = subprocess.run(["sh", "tests/run_tests.sh", "--plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=True)
        plan = {unit["name"]: unit for unit in test_jobs.parse_plan(result.stdout)}
        self.assertEqual(result.stdout, expected)
        self.assertEqual(plan['web']['needs'], ['assets', 'node'])

    def test_outer_ai_flag_preserves_successful_preflight_and_shell_worker(self):
        (self.root / "tests").mkdir()
        (self.root / "tools").mkdir()
        for name in ("tools/profile.py", "tests/build_identity_test.py", "tests/profile_test.py",
                     "tests/test_jobs_test.py"):
            (self.root / name).write_text(
                "from pathlib import Path\n"
                f"print({name!r})\n"
                f"with Path('events').open('a') as f: f.write({name!r} + '\\n')\n")
        (self.root / "tests/test_jobs.py").write_text(RUNNER.read_text())
        (self.root / 'tools/test_coverage.py').write_text((SHELL.parent.parent / 'tools/test_coverage.py').read_text())
        # Keep the actual entry-point/preflight dispatch and real scheduler.
        # Replace the firmware-dependent catalog with one deterministic worker.
        source = SHELL.read_text().split('eval "$(python3 tools/test_coverage.py host-config', 1)[0]
        source += '''
if [ "$MODE" = --plan ]; then
    printf 'fixture\t\techo fixture\n'
    exit 0
fi
test "$MODE" = --unit
test "$SELECTED_UNIT" = fixture
echo worker >> events
echo deterministic-worker-output
'''
        (self.root / "tests/run_tests.sh").write_text(source)
        process = subprocess.Popen(["sh", "tests/run_tests.sh"], cwd=self.root, env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        code, full, normal = self.finish(process)
        self.assertEqual(code, 0, full)
        baseline = self.root / "baseline"
        next(self.root.glob("build/host/test-run-*")).rename(baseline)
        process = subprocess.Popen(["sh", "tests/run_tests.sh", "--ai-output"], cwd=self.root,
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        code, compact, summary = self.finish(process)
        self.assertEqual(code, 0, compact)
        expected = ["tools/profile.py", "tests/build_identity_test.py", "tests/profile_test.py",
                    "tests/test_jobs_test.py", "worker"]
        self.assertEqual((self.root / "events").read_text().splitlines(), expected * 2)
        self.assertEqual(summary["preflight"]["status"], "passed")
        self.assertEqual(summary["unit_counts"], normal["unit_counts"])
        self.assertIn("ALL HOST TESTS PASSED", full)
        self.assertNotIn("deterministic-worker-output", compact)
        self.assertIn("PASSED units: passed=1", compact)
        logs = next(self.root.glob("build/host/test-run-*"))
        self.assertEqual((baseline / normal["units"][0]["log"]).read_bytes(),
                         (logs / summary["units"][0]["log"]).read_bytes())

    def test_outer_runner_resolves_script_after_changing_directory(self):
        (self.root / "tests").mkdir()
        (self.root / "tools").mkdir()
        (self.root / "tests/run_tests.sh").write_text(SHELL.read_text())
        for name in ("tools/profile.py", "tests/build_identity_test.py", "tests/profile_test.py",
                     "tests/test_jobs_test.py"):
            (self.root / name).touch()
        (self.root / "tests/test_jobs.py").write_text(
            "from pathlib import Path\nimport sys,subprocess\n"
            "assert Path(sys.argv[1]).resolve() == Path(__file__).with_name('run_tests.sh').resolve()\n"
            "Path('args').write_text(' '.join(sys.argv[2:]))\n"
            "if '--preflight' in sys.argv: subprocess.run(['sh',sys.argv[1],'--preflight'],check=True)\n"
            "Path('started').touch()\n")
        for cwd, path in ((self.root, "tests/run_tests.sh"),
                          (self.root.parent, self.root.name + "/tests/run_tests.sh")):
            subprocess.run(["sh", path], cwd=cwd, env=self.env, check=True, capture_output=True)
            self.assertEqual((self.root / "args").read_text(), "--preflight")
            subprocess.run(["sh", path, "--ai-output"], cwd=cwd, env=self.env, check=True, capture_output=True)
            self.assertEqual((self.root / "args").read_text(), "--ai-output --preflight")
        (self.root / "started").unlink()
        (self.root / "tools/profile.py").write_text("raise SystemExit(1)\n")
        result = subprocess.run(["sh", "tests/run_tests.sh"], cwd=self.root, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / "started").exists())

        # The real compact runner must also stop before planning on preflight
        # failure, after the outer shell has changed directory.
        (self.root / 'tools/test_coverage.py').write_text((SHELL.parent.parent / 'tools/test_coverage.py').read_text())
        (self.root / "tests/test_jobs.py").write_text(RUNNER.read_text())
        result = subprocess.run(["sh", "tests/run_tests.sh", "--ai-output"], cwd=self.root,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("preflight failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
