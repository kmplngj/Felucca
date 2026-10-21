#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded host-test units, ordered transcripts and process-group cancellation."""
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
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in names:
            raise ValueError(f"invalid or duplicate unit: {name!r}")
        dependencies = dependencies.split()
        if not set(dependencies) <= names:
            raise ValueError(f"{name}: dependencies must name earlier units")
        names.add(name)
        plan.append(dict(name=name, dependencies=dependencies, command=command, status="pending"))
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
        kill_group(process, signal.SIGKILL)
    for process in processes:
        process.wait()


def execute(script, output, env):
    count = job_count(env)
    worker_env = dict(env)
    if count > 1:
        # Several units can each fork regress.c workers. Bound that inner fan-out
        # too; an explicit JOBS setting still belongs to the caller.
        worker_env.setdefault("JOBS", "1")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".test-run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another host suite is using this checkout; use a separate worktree")
        return run_locked(script, output, worker_env, count)


def run_locked(script, output, env, count):
    logs = Path(tempfile.mkdtemp(prefix="test-run-", dir=output))
    interrupted = 0

    def on_signal(number, _frame):
        nonlocal interrupted
        interrupted = number

    handlers = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM)}
    active, plan = {}, []
    flushed = 0
    start = time.monotonic()
    summary = dict(jobs=count, inner_jobs=env.get("JOBS", "default"), status="failed", units=plan)

    def flush():
        nonlocal flushed
        while flushed < len(plan) and plan[flushed]["status"] not in ("pending", "running"):
            with (logs / plan[flushed]["log"]).open("rb") as stream:
                sys.stdout.flush()
                shutil.copyfileobj(stream, sys.stdout.buffer)
            flushed += 1
        sys.stdout.flush()

    try:
        # The plan may probe sanitizer availability, but never executes test units.
        process = subprocess.Popen(["sh", str(script), "--plan"], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        active[process] = None
        while True:
            if interrupted:
                summary["status"] = "cancelled"
                return 128 + interrupted
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
        active.pop(process)
        if process.returncode:
            raise ValueError(f"host-test planning failed ({process.returncode}):\n{stderr}{stdout}")
        if stderr:
            print(stderr, file=sys.stderr, end="")
        plan.extend(parse_plan(stdout))
        by_name = {unit["name"]: unit for unit in plan}
        for i, unit in enumerate(plan):
            unit["log"] = f"{i + 1:03d}-{unit['name']}.log"
            (logs / unit["log"]).touch()
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
                elif len(active) < count and all(dep["status"] == "passed" for dep in dependencies):
                    with (logs / unit["log"]).open("wb") as stream:
                        process = subprocess.Popen(["sh", str(script), "--unit", unit["name"]],
                                                   env=env, stdout=stream, stderr=subprocess.STDOUT,
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
        success = all(unit["status"] == "passed" for unit in plan)
        summary["status"] = "passed" if success else "failed"
        return 0 if success else 1
    finally:
        stop(list(active))
        for unit in plan:
            if unit["status"] in ("pending", "running"):
                unit["status"] = "cancelled" if interrupted else "blocked"
        flush()
        summary["seconds"] = time.monotonic() - start
        summary["signal"] = interrupted or None
        (logs / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"== host runner: {summary['status']}, {summary['seconds']:.1f}s; {logs}/summary.json", flush=True)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main():
    try:
        code = execute(Path(sys.argv[1]).resolve(), Path("build/host"), os.environ)
    except (ValueError, OSError) as error:
        print(f"host runner: {error}", file=sys.stderr)
        code = 1
    print("ALL HOST TESTS PASSED" if code == 0 else "HOST TESTS FAILED", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
