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

    def launch(self, env=None):
        return subprocess.Popen([sys.executable, str(RUNNER), str(self.script)], cwd=self.root,
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
        env = dict(self.env, SANITIZE="0", CC="false")
        env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", os.defpath)
        result = subprocess.run(["sh", "tests/run_tests.sh", "--plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=True)
        plan = {unit["name"]: unit for unit in test_jobs.parse_plan(result.stdout)}
        self.assertEqual(plan["web"]["dependencies"], ["editor", "descriptors"])
        self.assertEqual(plan["ui_fm4"]["dependencies"], ["ui_render"])
        self.assertEqual(plan["reverb"]["dependencies"], ["perform"])
        self.assertEqual(plan["stress_replay"]["dependencies"], ["replay"])
        self.assertEqual({f"catalog_{i}" for i in (10, 11, 12, 13)} & plan.keys(),
                         {f"catalog_{i}" for i in (10, 11, 12, 13)})
        self.assertTrue(all(not unit["name"].startswith("asan_") for unit in plan.values()))

        # A compiler without sanitizer support must select and execute the same
        # explicit skip unit; workers do not repeat the availability probe.
        env["SANITIZE"] = "1"
        result = subprocess.run(["sh", "tests/run_tests.sh", "--plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=True)
        plan = {unit["name"]: unit for unit in test_jobs.parse_plan(result.stdout)}
        self.assertIn("sanitizer_unavailable", plan)
        result = subprocess.run(["sh", "tests/run_tests.sh", "--unit", "sanitizer_unavailable"],
                                cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("the compiler has no ASan / UBSan", result.stdout)

        # Missing generated tables still permit a valid partial plan. In
        # particular, web cannot depend on absent editor/descriptor units.
        (self.root / "build/gen/felucca_tables.h").unlink()
        result = subprocess.run(["sh", "tests/run_tests.sh", "--plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=True)
        plan = {unit["name"]: unit for unit in test_jobs.parse_plan(result.stdout)}
        self.assertNotIn("web", plan)
        self.assertIn("web_no_assets", plan)
        result = subprocess.run(["sh", "tests/run_tests.sh", "--unit", "web_no_assets"],
                                cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("== skip web tests (needs build/gen", result.stdout)

    def test_outer_runner_resolves_script_after_changing_directory(self):
        (self.root / "tests").mkdir()
        (self.root / "tools").mkdir()
        (self.root / "tests/run_tests.sh").write_text(SHELL.read_text())
        for name in ("tools/profile.py", "tests/build_identity_test.py", "tests/profile_test.py",
                     "tests/test_jobs_test.py"):
            (self.root / name).touch()
        (self.root / "tests/test_jobs.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "assert Path(sys.argv[1]).resolve() == Path(__file__).with_name('run_tests.sh').resolve()\n"
            "Path('started').touch()\n")
        for cwd, path in ((self.root, "tests/run_tests.sh"),
                          (self.root.parent, self.root.name + "/tests/run_tests.sh")):
            subprocess.run(["sh", path], cwd=cwd, env=self.env, check=True, capture_output=True)
        (self.root / "started").unlink()
        (self.root / "tools/profile.py").write_text("raise SystemExit(1)\n")
        result = subprocess.run(["sh", "tests/run_tests.sh"], cwd=self.root, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / "started").exists())


if __name__ == "__main__":
    unittest.main()
