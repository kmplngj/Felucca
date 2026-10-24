#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded host-test units, ordered transcripts and process-group cancellation."""
import argparse
from collections import deque
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
if (Path(__file__).resolve().parents[1] / 'SOURCE-PINS.json').is_file():
    # Match the verified archive build entry points before importing local modules.
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import test_coverage as coverage


def report_log(logs, unit, ai_output):
    path = logs / unit["log"]
    if not ai_output:
        with path.open("rb") as stream:
            sys.stdout.flush()
            shutil.copyfileobj(stream, sys.stdout.buffer)
        return

    # These are diagnostic line hints, not parsed test/skip counts. The original
    # bytes remain in the log; bounded samples only decide what to open next.
    notices = dict(warning_lines=0, skip_lines=0, samples=[])
    tail, errors = deque(maxlen=6), []
    lines, notice_lines = 0, 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).rstrip()
            lines += 1
            sample = line[:240] + ("..." if len(line) > 240 else "")
            tail.append(sample)
            if len(errors) < 3 and re.search(r"\b(error|failed|failure|traceback|assertionerror|fatal)\b",
                                              line, re.IGNORECASE):
                errors.append(sample)
            # Test descriptions can mention skips/negative fixtures; they are
            # not results. Explicit shell skip notes are the exception.
            if line.startswith("== ") and not line.startswith("== skip "):
                continue
            warning = bool(re.search(r"\b(?:[A-Za-z]+Warning|warning)(?:\s+[A-Z0-9-]+)?:",
                                     line, re.IGNORECASE))
            skipped = bool(re.search(r"\b(skip|skipped|skipping|unavailable)\b|\bnot checked\b",
                                     line, re.IGNORECASE))
            notices["warning_lines"] += warning
            notices["skip_lines"] += skipped
            if warning or skipped:
                notice_lines += 1
                if len(notices["samples"]) < 3:
                    notices["samples"].append(sample)
    notices["samples_limited"] = (notice_lines > len(notices["samples"])
                                  or any(len(s) > 240 for s in notices["samples"]))
    unit["diagnostics"] = notices
    if unit["status"] != "passed" or notices["warning_lines"] or notices["skip_lines"]:
        code = f" exit={unit['returncode']}" if "returncode" in unit else ""
        print(f"host: {unit['name']} {unit['status']}{code}; "
              f"warning_lines={notices['warning_lines']} skip_lines={notices['skip_lines']}; log={path}")
        for sample in notices["samples"]:
            print(f"  notice: {sample}")
        if unit["status"] != "passed":
            excerpt = list(dict.fromkeys(errors + list(tail)))
            unit["excerpt"] = excerpt
            unit["excerpt_limited"] = lines > len(excerpt) or any(len(s) > 240 for s in excerpt)
            print("  excerpt (full log retained):")
            for sample in excerpt:
                print(f"    {sample}")


def job_count(env):
    value = env.get("TEST_JOBS", str(min(4, os.cpu_count() or 1)))
    if not re.fullmatch(r"[1-9][0-9]*", value) or int(value) > 32:
        raise ValueError("TEST_JOBS must be an integer from 1 to 32")
    # Legacy baseline/output overrides are shared across several harnesses. C's
    # getenv() considers even an empty value enabled, so check presence here too.
    shared = ("GOLDEN_UPDATE", "BUDGET_UPDATE", "UI_SCREEN_DIR", "MENU_JSON", "TRACKS")
    return 1 if any(name in env for name in shared) else int(value)


def parse_plan(text):
    plan, names = [], set()
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            raise ValueError(f"invalid host-test plan row: {line!r}")
        name, dependencies, *command = fields
        needs, capabilities, producers = [], [], []
        if command[-1].startswith('@coverage='):
            metadata = json.loads(command.pop().split('=', 1)[1])
            needs, capabilities = metadata['needs'], metadata['capabilities']
            producers = metadata.get('producers', [])
            if (set(metadata) not in ({'needs', 'capabilities'}, {'needs', 'capabilities', 'producers'}) or
                any(not isinstance(values, list) or len(values) != len(set(values)) or
                    any(not isinstance(v, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', v) for v in values)
                    for values in (needs, capabilities)) or
                not isinstance(producers, list) or len(producers) != len(set(producers)) or
                any(not isinstance(p, str) or p not in coverage.PRODUCERS and p not in
                    ('regress', 'regress_os', 'regress_cpu2_0', 'regress_c1') for p in producers)):
                raise ValueError('invalid coverage metadata')
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in names:
            raise ValueError(f"invalid or duplicate unit: {name!r}")
        dependencies = dependencies.split()
        if not set(dependencies) <= names:
            raise ValueError(f"{name}: dependencies must name earlier units")
        names.add(name)
        plan.append(dict(name=name, dependencies=dependencies, command=command, status="pending",
                         needs=needs, capabilities=capabilities, producers=producers))
    if not plan:
        raise ValueError("empty host-test plan")
    return plan


def kill_group(process, sig):
    try:
        os.killpg(process.pid, sig)
        return True
    except ProcessLookupError:
        return False


def stop(processes):
    # Kill the group even if its leader exits on TERM: a grandchild can ignore it.
    remaining = [process for process in processes if kill_group(process, signal.SIGTERM)]
    if remaining:
        time.sleep(0.2)
    for process in remaining:
        # Reap an exited leader before signaling again. macOS can report EPERM
        # for a group containing only its unreaped zombie; live grandchildren
        # remain in the group and must still receive KILL.
        process.poll()
        kill_group(process, signal.SIGKILL)
    for process in processes:
        process.wait()


def execute(script, output, env, ai_output=False, preflight=False):
    # Generic scheduler fixtures also copy this CLI outside a firmware checkout.
    # They have no firmware evidence contract and can never satisfy verify-tests.
    production = (script.resolve() == Path(__file__).with_name('run_tests.sh').resolve()
                  and any((script.parent.parent / marker).exists() for marker in ('.git', 'SOURCE-PINS.json')))
    output.mkdir(parents=True, exist_ok=True)
    logs = Path(tempfile.mkdtemp(prefix="test-run-", dir=output))
    contract_env = dict(env)
    contract_env.setdefault('FELUCCA_COVERAGE_REPORT', str((logs / 'coverage.json').resolve()))
    contract = coverage.Coverage(script.parent.parent, contract_env) if production else None
    count = job_count(env)
    with (output / ".test-run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another host suite is using this checkout; use a separate worktree")
        return run_locked(script, output, env, count, ai_output, preflight, contract, logs)


def run_locked(script, output, env, count, ai_output=False, preflight=False, contract=None, logs=None):
    worker_env = dict(contract.worker_env if contract else env)
    if count > 1:
        # Bound inner render fan-out, while preflight keeps the caller's environment.
        worker_env.setdefault("JOBS", "1")
    logs = logs or Path(tempfile.mkdtemp(prefix="test-run-", dir=output))
    interrupted = 0

    def on_signal(number, _frame):
        nonlocal interrupted
        interrupted = number

    handlers = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM)}
    active, plan = {}, []
    flushed = 0
    start = time.monotonic()
    summary = dict(jobs=count, inner_jobs=worker_env.get("JOBS", "default"), status="failed", units=plan,
                   output_mode="ai" if ai_output else "full")
    if ai_output:
        print(f"host: running; logs={logs}", flush=True)

    def flush():
        nonlocal flushed
        while flushed < len(plan) and plan[flushed]["status"] not in ("pending", "running"):
            report_log(logs, plan[flushed], ai_output)
            flushed += 1
        sys.stdout.flush()

    try:
        if preflight:
            unit = dict(name="preflight", log="preflight.log", status="running")
            summary["preflight"] = unit
            with (logs / unit["log"]).open("wb") as stream:
                process = subprocess.Popen(["sh", str(script), "--preflight"], env=env,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           start_new_session=True)
            active[process] = None
            while process.poll() is None:
                if interrupted:
                    summary["status"] = "cancelled"
                    return 128 + interrupted
                time.sleep(0.05)
            result = process.returncode
            stop([process])
            active.pop(process)
            unit.update(status="passed" if result == 0 else "failed", returncode=result)
            if not ai_output:
                report_log(logs, unit, False)
                unit['printed'] = True
            if result:
                return result if result > 0 else 128 - result
        # The plan may probe sanitizer availability, but never executes test units.
        planner = dict(name="plan", log="plan.stderr.log", stdout_log="plan.stdout.log", status="running")
        summary["plan"] = planner
        with (logs / planner["stdout_log"]).open("wb") as stdout_log, (logs / planner["log"]).open("wb") as stderr_log:
            process = subprocess.Popen(["sh", str(script), "--plan"], env=worker_env,
                                       stdout=stdout_log, stderr=stderr_log, start_new_session=True)
        active[process] = None
        while process.poll() is None:
            if interrupted:
                summary["status"] = "cancelled"
                return 128 + interrupted
            time.sleep(0.05)
        active.pop(process)
        planner.update(status="passed" if process.returncode == 0 else "failed", returncode=process.returncode)
        stdout = (logs / planner["stdout_log"]).read_text()
        stderr = (logs / planner["log"]).read_text()
        if process.returncode:
            if ai_output:
                raise ValueError(f"host-test planning failed ({process.returncode}); "
                                 f"logs: {logs / planner['stdout_log']}, {logs / planner['log']}")
            raise ValueError(f"host-test planning failed ({process.returncode}):\n{stderr}{stdout}")
        if stderr and not ai_output:
            print(stderr, file=sys.stderr, end="")
        try:
            plan.extend(parse_plan(stdout))
        except ValueError as error:
            planner["status"] = "failed"
            planner["error"] = "invalid host-test plan"
            if ai_output:
                raise ValueError(f"invalid host-test plan; log: {logs / planner['stdout_log']}") from error
            raise
        by_name = {unit["name"]: unit for unit in plan}
        availability = {}
        for i, unit in enumerate(plan):
            unit["log"] = f"{i + 1:03d}-{unit['name']}.log"
            (logs / unit["log"]).touch()
            if contract:
                if unit['name'] == 'tsan' and not env.get('TSAN'):
                    unit.update(status='not_applicable', reason='not-requested')
                elif unit['name'] in ('macro', 'asan_macro') and 14 not in contract.engine_ids:
                    unit.update(status='not_applicable', reason='profile-excluded')
                else:
                    key = tuple(unit['needs'])
                    if key not in availability:
                        availability[key] = coverage.requirements(unit['needs'], worker_env)
                    missing = availability[key]
                    if missing:
                        unit.update(status='skipped', reason=missing)
                        (logs / unit['log']).write_text('== skip ' + unit['name'] + ': ' + ', '.join(missing) + '\n')
        if not ai_output:
            print(f"== host runner: {count} concurrent units; logs and timings: {logs}", flush=True)
        while any(unit["status"] in ("pending", "running") for unit in plan):
            if interrupted:
                summary["status"] = "cancelled"
                return 128 + interrupted
            for unit in plan:
                if unit["status"] != "pending":
                    continue
                dependencies = [by_name[name] for name in unit["dependencies"]]
                if any(dep["status"] in ("failed", "blocked") for dep in dependencies):
                    unit["status"] = "blocked"
                    (logs / unit["log"]).write_text(f"== host unit {unit['name']}: prerequisite failed\n")
                elif any(dep['status'] in ('skipped', 'not_applicable') for dep in dependencies):
                    unit.update(status='skipped', reason=['prerequisite-unavailable'])
                    (logs / unit['log']).write_text(f"== skip {unit['name']}: prerequisite unavailable\n")
                elif len(active) < count and all(dep["status"] == "passed" for dep in dependencies):
                    unit_env = dict(worker_env)
                    if contract:
                        unit_env['FELUCCA_COVERAGE_UNIT'] = str((logs / (unit['name'] + '.coverage')).resolve())
                    with (logs / unit["log"]).open("wb") as stream:
                        process = subprocess.Popen(["sh", str(script), "--unit", unit["name"]],
                                                   env=unit_env, stdout=stream, stderr=subprocess.STDOUT,
                                                   start_new_session=True)
                    active[process] = unit
                    unit.update(status="running", started=time.monotonic() - start)
            for process, unit in list(active.items()):
                result = process.poll()
                if result is not None:
                    # Also remove background descendants left by a failed shell.
                    stop([process])
                    active.pop(process)
                    unit.update(status="passed" if result == 0 else "failed", returncode=result,
                                seconds=time.monotonic() - start - unit["started"])
            flush()
            if active:
                time.sleep(0.05)
        success = all(unit["status"] in ("passed", "skipped", "not_applicable") for unit in plan)
        summary["status"] = "passed" if success else "failed"
        return 0 if success else 1
    finally:
        stop(list(active))
        for key in ("preflight", "plan"):
            if key in summary:
                unit = summary[key]
                if unit["status"] == "running":
                    unit["status"] = "cancelled" if interrupted else "failed"
                if ai_output and key == "plan" and unit["status"] != "passed":
                    # A planner may print its failure reason to stdout after
                    # partial plan rows. Keep both raw streams and excerpt both.
                    unit["stderr_log"] = unit["log"]
                    unit["log"] = "plan.failure.log"
                    with (logs / unit["log"]).open("wb") as combined:
                        for label, name in (("stdout", unit["stdout_log"]), ("stderr", unit["stderr_log"])):
                            combined.write(f"--- planner {label} ---\n".encode())
                            with (logs / name).open("rb") as source:
                                shutil.copyfileobj(source, combined)
                if ai_output or (key == "preflight" and not unit.get('printed')):
                    report_log(logs, unit, ai_output)
        for unit in plan:
            if unit["status"] in ("pending", "running"):
                unit["status"] = "cancelled" if interrupted else "blocked"
        flush()
        summary["seconds"] = time.monotonic() - start
        summary["signal"] = interrupted or None
        summary["unit_counts"] = {status: sum(u["status"] == status for u in plan)
                                  for status in ("passed", "failed", "blocked", "cancelled", "skipped", "not_applicable")}
        if ai_output:
            entries = plan + [summary[key] for key in ("preflight", "plan") if key in summary]
            summary["diagnostic_counts"] = {key: sum(u["diagnostics"][key] for u in entries)
                                            for key in ("warning_lines", "skip_lines")}
        changed = contract is not None and not contract.finish(summary, logs)
        (logs / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if ai_output:
            counts = " ".join(f"{key}={value}" for key, value in summary["unit_counts"].items())
            diagnostics = " ".join(f"{key}={value}" for key, value in summary["diagnostic_counts"].items())
            print(f"host: {summary['status'].upper()} units: {counts}; {summary['seconds']:.1f}s; "
                  f"{diagnostics}; summary={logs}/summary.json", flush=True)
        else:
            print(f"== host runner: {summary['status']}, {summary['seconds']:.1f}s; {logs}/summary.json", flush=True)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if changed:
            raise ValueError('coverage inputs/configuration changed during the run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--ai-output", action="store_true", help="compact results; retain complete logs")
    parser.add_argument("--preflight", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        code = execute(args.script.resolve(), Path("build/host"), os.environ, args.ai_output, args.preflight)
    except (ValueError, OSError) as error:
        print(f"host runner: {error}", file=sys.stderr)
        code = 1
    if not args.ai_output:
        print("ALL HOST TESTS PASSED" if code == 0 else "HOST TESTS FAILED", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
