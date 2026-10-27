#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in executable causal proof; requires a clean pinned donor and Rust 1.99.1."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import emulator_trace as helper

BASE = 0x02000000


def mov(register, value):
    # r_mov_i: register in bits 0..3, 32-bit immediate in bits 16..47.
    return (0xffc0 | register | value << 16).to_bytes(6, "little")


def sreg(number, register):
    return (0xe064 | 0x80 << 16 | number << 24 | register << 28).to_bytes(4, "little")


def write(address, value):
    return mov(0, address) + sreg(14, 0) + mov(1, value) + bytes.fromhex("81 20")


def irq_image(enabled):
    # IRQ120's vector, priority/enable nibble and software-pending latch; all are
    # written by guest instructions through the real CPU and SoC MMIO path.
    image = (write(0x01c7ffe0, BASE + 0x100) + write(0x01eef13c, 3)
             + write(0x01eef1a0, 1) + mov(0, 0x300 if enabled else 0x100)
             + sreg(11, 0) + mov(2, 0x77))
    return image.ljust(0x120, b"\0")


def execute(binary, out, name, image, steps, extra=(), trace="1:100"):
    path = out / f"{name}.bin"
    path.write_bytes(image)
    env = {k: v for k, v in os.environ.items() if not k.startswith("FM1_")}
    env.update(FM1_TRACE_RANGE=trace, FM1_IRQ_TRACE="1")
    args = [str(binary), "--bin", str(path), "--steps", str(steps), *extra]
    # Every terminal fixture has a wall-clock bound and finite guest step limit.
    result = subprocess.run(args, cwd=out, env=env, timeout=10, capture_output=True, text=True)
    (out / f"{name}.stdout").write_text(result.stdout)
    (out / f"{name}.stderr").write_text(result.stderr)
    rows = [line for line in result.stdout.splitlines() if line.startswith("T ")]
    (out / f"{name}.process.json").write_text(json.dumps({
        "args": args, "returncode": result.returncode, "rows": len(rows), "timeout_seconds": 10}, indent=2))
    return result, rows


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cargo", default="cargo")
    args = p.parse_args()
    source, out = helper.ignored_path(args.source), helper.ignored_path(args.out)
    pin = helper.read_pin()
    helper.check_checkout(source, pin)
    require(not out.exists(), "output must be new")
    out.mkdir(parents=True)
    checkout = out / "patched-checkout"
    helper.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", source, checkout])
    helper.run(["git", "-C", checkout, "checkout", "--quiet", "--detach", pin["commit"]])
    receipt_path = helper.build(checkout, out / "candidate", args.cargo)
    receipt = helper.verify(receipt_path)
    candidate = Path(receipt["binary"])
    refusals = []
    try:
        helper.build(checkout, out / "already-patched", args.cargo)
    except ValueError as error:
        require("must be clean" in str(error), "already-patched source failed for the wrong reason")
        refusals.append("already-patched donor")
    else:
        raise AssertionError("already-patched donor accepted")
    # Tamper one retained input at a time; restore it without rebuilding and require
    # successful verification again. Never mutate the shared Rust installation.
    for label, path in (("binary", candidate),
                        ("snapshot", out / "candidate/source/crates/fm1-emu/src/main.rs"),
                        ("external source", checkout / "crates/fm1-emu/src/main.rs"),
                        ("build log", out / "candidate/build.stdout")):
        original_bytes = path.read_bytes()
        try:
            path.write_bytes(original_bytes + b"\nchanged\n")
            try:
                helper.verify(receipt_path)
            except ValueError:
                refusals.append(label)
            else:
                raise AssertionError(f"altered {label} accepted")
        finally:
            path.write_bytes(original_bytes)
        helper.verify(receipt_path)
    original_receipt = receipt_path.read_text()
    try:
        damaged = dict(receipt, compiler_sha256="0" * 64)
        receipt_path.write_text(json.dumps(damaged))
        try:
            helper.verify(receipt_path)
        except ValueError:
            refusals.append("compiler binding")
        else:
            raise AssertionError("altered compiler binding accepted")
    finally:
        receipt_path.write_text(original_receipt)
    helper.verify(receipt_path)
    baseline_source = out / "baseline/source"
    shutil.copytree(out / "candidate/source", baseline_source)
    original = helper.run(["git", "-C", source, "show", pin["commit"] + ":crates/fm1-emu/src/main.rs"])
    (baseline_source / "crates/fm1-emu/src/main.rs").write_bytes(original)
    baseline_out = out / "baseline"
    env = helper.build_environment(baseline_out, pin["rust_toolchain"])
    env["CARGO_HOME"] = str(baseline_out / "cargo-home")
    env["RUSTC"] = receipt["rustc_path"]
    env["PATH"] = str(Path(receipt["rustc_path"]).parent) + os.pathsep + env.get("PATH", "")
    command = [receipt["cargo_path"], "build", "--offline", "--locked", "--release", "--manifest-path", str(baseline_source / "Cargo.toml")]
    result = subprocess.run(command, cwd=baseline_out, env=env, timeout=180, capture_output=True)
    (baseline_out / "build.stdout").write_bytes(result.stdout)
    (baseline_out / "build.stderr").write_bytes(result.stderr)
    require(result.returncode == 0, "baseline build failed; inspect retained logs")
    baseline = baseline_out / "target/release/fm1-emu"
    fixtures = out / "fixtures"
    fixtures.mkdir()
    checks = []
    for label, binary in (("baseline", baseline), ("candidate", candidate)):
        disabled, no_irq = execute(binary, fixtures, label + "-no-irq", irq_image(False), 16)
        enabled, irq = execute(binary, fixtures, label + "-irq", irq_image(True), 16)
        require(disabled.returncode == enabled.returncode == 0, "bounded normal run failed")
        require(len(no_irq) == len(irq) == 16, "normal row count differs from retirement")
        require(no_irq[14].startswith("T 15 c0 0x02000040 r_mov_i irq=[] ie=false"), "no-IRQ control changed")
        require("c0 irq 120 prio 1 -> 0x02000100" in enabled.stdout, "IRQ not dispatched")
        actual = irq[14].startswith("T 15 c0 0x02000100 nop irq=[1] ie=true")
        require(actual == (label == "candidate"), "IRQ negative control did not distinguish the correction")
        failed, failed_rows = execute(binary, fixtures, label + "-failed", mov(2, 0x77) + b"\xff" * 16, 8)
        require("stopped after 1 instructions (halt" in failed.stdout, "failed instruction unexpectedly retired")
        require((failed.returncode != 0 and len(failed_rows) == 1) == (label == "candidate"), "failed-step negative control did not distinguish the correction")
        # Class names must use the same raw-family overrides as Cpu::step.
        require(("sreg_mov_craw" in irq[13]) == (label == "candidate"), "CPU decoder class override mismatch")
        checks.append({"binary": label, "sha256": helper.sha(binary.read_bytes()),
                       "irq_row_15": irq[14], "failed_step_exit": failed.returncode,
                       "failed_step_rows": len(failed_rows)})
    # Retained entry state must precede execution, even though publication follows it.
    state, rows = execute(candidate, fixtures, "entry-state", mov(0, 7) + mov(0, 9) + b"\0" * 8, 2)
    require(state.returncode == 0 and rows[1].endswith("r0=0x7 r1=0x0"), "trace lost instruction entry register state")
    for name, image, entry, steps, count in (
        ("wild-jump", b"\0" * 8, "0", 1, 0),
        ("nop-slide", b"\0" * 64, hex(BASE), 40, 24),
        ("quiet-failed", b"\xff" * 16, hex(BASE), 1, 0),
    ):
        result, rows = execute(candidate, fixtures, name, image, steps, ("--entry", entry, "--quiet"))
        require(result.returncode != 0 and len(rows) == count, f"{name} reported success or an unretired row")
    result, rows = execute(candidate, fixtures, "window", b"\0" * 64, 8, trace="3:6")
    require(result.returncode == 0 and [int(row.split()[1]) for row in rows] == [3, 4, 5], "half-open scheduling-slot window changed")
    result, rows = execute(candidate, fixtures, "zero-slots", b"\0" * 8, 0)
    require(result.returncode == 0 and not rows, "zero-slot CLI behavior changed")
    # Any eventual profile adapter must reject this successful empty run itself.
    repeated, repeat_rows = execute(candidate, fixtures, "irq-repeat", irq_image(True), 16)
    require(repeated.returncode == 0 and repeat_rows == [line for line in (fixtures / "candidate-irq.stdout").read_text().splitlines() if line.startswith("T ")], "synthetic IRQ trace is not deterministic")
    (out / "summary.json").write_text(json.dumps({"status": "passed", "scope": "synthetic guest CPU/SoC CLI, no native firmware or device claims", "causal_controls": checks, "candidate_receipt": str(receipt_path), "receipt_refusals": refusals, "terminal_cases": ["step-limit", "failed-step", "wild-jump", "nop-slide", "quiet-failed", "zero-slots"], "window": "slots [3,6)", "repeat": "identical 16-row IRQ trace"}, indent=2) + "\n")
    print(f"PASS executable trace correction: {out / 'summary.json'}")


if __name__ == "__main__":
    main()
