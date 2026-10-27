#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Apply/build the reviewed #662 tracer prerequisite in an ignored external checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tools/emulator_trace"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_pin():
    pin = json.loads((DATA / "pin.json").read_text())
    if sha((DATA / "retired-trace.patch").read_bytes()) != pin["patch_sha256"]:
        raise ValueError("reviewed patch hash does not match pin.json")
    return pin


def run(argv, *, cwd=None, env=None, timeout=120):
    return subprocess.run(list(map(str, argv)), cwd=cwd, env=env, timeout=timeout,
                          capture_output=True, check=True).stdout


def git(source, *args):
    return run(["git", "-C", source, *args]).decode().strip()


def ignored_path(path):
    path = path.resolve()
    if not path.is_relative_to(ROOT / "build"):
        raise ValueError("source and output must be inside this checkout's ignored build/")
    if subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", path]).returncode:
        raise ValueError("path is not ignored")
    return path


def inventory(source, paths):
    result = {}
    for name in paths:
        p = source / name
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"missing or symlinked source input: {name}")
        result[name] = sha(p.read_bytes())
    return result


def check_checkout(source, pin):
    if Path(git(source, "rev-parse", "--show-toplevel")).resolve() != source.resolve():
        raise ValueError("source must be the external checkout root")
    if git(source, "rev-parse", "HEAD") != pin["commit"]:
        raise ValueError("unsupported emulator commit")
    if git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("external checkout must be clean (already patched is refused)")
    if inventory(source, pin["source_sha256"]) != pin["source_sha256"]:
        raise ValueError("pinned source bytes differ")


def workspace_manifest(source, pin):
    """Retain package/release settings; omit unrelated registry-dependent members."""
    manifest = tomllib.loads(source)
    if manifest["workspace"]["package"] != {"version": "0.2.0", "edition": "2021", "license": "MIT"}:
        raise ValueError("unreviewed workspace package settings")
    if manifest["profile"] != {"release": {"opt-level": 3, "lto": True}}:
        raise ValueError("unreviewed build profile")
    members = ", ".join(json.dumps("crates/" + c) for c in pin["crates"])
    return (f'[workspace]\nresolver = "2"\nmembers = [{members}]\n'
            '[workspace.package]\nversion = "0.2.0"\nedition = "2021"\nlicense = "MIT"\n'
            '[profile.release]\nopt-level = 3\nlto = true\n')


def build_environment(out, toolchain):
    env = dict(os.environ)
    # The receipt describes this fixed build, never caller-injected flags/wrappers.
    for name in list(env):
        if name.startswith(("CARGO_BUILD_", "CARGO_TARGET_", "CARGO_PROFILE_")) or name in {
            "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTDOC", "RUSTC_WRAPPER",
            "RUSTC_WORKSPACE_WRAPPER", "RUSTC_BOOTSTRAP", "RUSTDOCFLAGS"}:
            env.pop(name)
    env["RUSTUP_TOOLCHAIN"] = toolchain
    env["CARGO_TARGET_DIR"] = str(out / "target")
    # Cargo configuration is checked separately; never inherit registry credentials here.
    env["GIT_CEILING_DIRECTORIES"] = str(out.parent)
    return env


def build(source, out, cargo="cargo"):
    pin = read_pin()
    source, out = ignored_path(source), ignored_path(out)
    if out.exists() or out.is_relative_to(source) or source.is_relative_to(out):
        raise ValueError("output must be new and separate from external source")
    check_checkout(source, pin)
    # Probe the selected compiler before mutating even this disposable checkout.
    env = build_environment(out, pin["rust_toolchain"])
    cargo_path = shutil.which(cargo)
    if cargo_path is None:
        raise ValueError("cargo is unavailable; install the pinned Rust toolchain separately")
    rustc = str(Path(cargo_path).parent / "rustc")
    compiler = run([rustc, "-vV"], env=env).decode()
    if f'release: {pin["rust_toolchain"]}\n' not in compiler:
        raise ValueError("unsupported Rust compiler")
    cargo_version = run([cargo_path, "--version"], env=env).decode().strip()
    for ancestor in (out, *out.parents):
        if any((ancestor / ".cargo" / name).exists() for name in ("config", "config.toml")):
            raise ValueError("ancestor Cargo configuration is unsupported for this fixed build")
    out.mkdir(parents=True)
    receipt = {"schema_version": 1, "kind": "felucca-emulator-trace-build", "status": "incomplete",
               "source": str(source), "upstream_repository": pin["repository"], "upstream_commit": pin["commit"],
               "pin_sha256": sha((DATA / "pin.json").read_bytes()), "patch_sha256": pin["patch_sha256"],
               "helper_sha256": sha(Path(__file__).read_bytes()), "rustc": compiler, "cargo": cargo_version,
               "toolchain": pin["rust_toolchain"], "licenses": pin["licenses"],
               "upstream_source_sha256": pin["source_sha256"]}
    receipt_path = out / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    run(["git", "-C", source, "apply", "--check", DATA / "retired-trace.patch"])
    run(["git", "-C", source, "apply", DATA / "retired-trace.patch"])
    effective = inventory(source, pin["source_sha256"])
    expected = dict(pin["source_sha256"])
    expected["crates/fm1-emu/src/main.rs"] = pin["effective_main_sha256"]
    if effective != expected:
        raise ValueError("patch effect differs from reviewed source")
    snapshot = out / "source"
    snapshot.mkdir()
    for name in effective:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    (snapshot / "Cargo.toml").write_text(workspace_manifest((snapshot / "Cargo.toml").read_text(), pin))
    # An empty Cargo home prevents global config and guarantees no registry dependencies.
    # Resolve the compiler first: rustup proxies still need their configured home.
    actual_rustc = run([str(Path(cargo_path).parent / "rustup"), "which", "rustc"], env=env).decode().strip()
    actual_cargo = run([str(Path(cargo_path).parent / "rustup"), "which", "cargo"], env=env).decode().strip()
    env["CARGO_HOME"] = str(out / "cargo-home")
    env["RUSTC"] = actual_rustc
    env["PATH"] = str(Path(actual_rustc).parent) + os.pathsep + env.get("PATH", "")
    command = [actual_cargo, "build", "--offline", "--release", "--manifest-path", str(snapshot / "Cargo.toml")]
    # Running from the isolated output also avoids local Cargo configuration discovery.
    try:
        result = subprocess.run(command, cwd=out, env=env, capture_output=True, timeout=180)
        (out / "build.stdout").write_bytes(result.stdout)
        (out / "build.stderr").write_bytes(result.stderr)
        if result.returncode:
            raise ValueError(f"emulator build failed ({result.returncode}); see {out / 'build.stderr'}")
        binary = out / "target/release" / ("fm1-emu.exe" if os.name == "nt" else "fm1-emu")
        paths = [*effective, "Cargo.lock"]
        if inventory(source, pin["source_sha256"]) != effective:
            raise ValueError("external source changed during build")
        receipt.update(status="complete", command=command, effective_source_sha256=effective,
                       build_source_sha256=inventory(snapshot, paths), binary=str(binary),
                       binary_sha256=sha(binary.read_bytes()),
                       compiler_sha256=sha(Path(actual_rustc).read_bytes()),
                       cargo_sha256=sha(Path(actual_cargo).read_bytes()),
                       rustc_path=actual_rustc, cargo_path=actual_cargo,
                       build_stdout_sha256=sha(result.stdout), build_stderr_sha256=sha(result.stderr))
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    except BaseException:
        # Leave an explicitly incomplete receipt; never a stale successful one.
        raise
    return receipt_path


def verify(receipt_path):
    pin = read_pin()
    receipt_path = ignored_path(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("schema_version") != 1 or receipt.get("kind") != "felucca-emulator-trace-build"
            or receipt.get("status") != "complete" or receipt.get("upstream_commit") != pin["commit"]
            or receipt.get("patch_sha256") != pin["patch_sha256"]
            or receipt.get("pin_sha256") != sha((DATA / "pin.json").read_bytes())
            or receipt.get("helper_sha256") != sha(Path(__file__).read_bytes())):
        raise ValueError("unsupported or incomplete build receipt")
    out = receipt_path.parent
    expected = dict(pin["source_sha256"])
    expected["crates/fm1-emu/src/main.rs"] = pin["effective_main_sha256"]
    if receipt["effective_source_sha256"] != expected:
        raise ValueError("receipt does not identify the reviewed patch effect")
    if git(Path(receipt["source"]), "rev-parse", "HEAD") != pin["commit"]:
        raise ValueError("external checkout revision changed")
    for field, path in (("binary_sha256", Path(receipt["binary"])),
                        ("compiler_sha256", Path(receipt["rustc_path"])),
                        ("cargo_sha256", Path(receipt["cargo_path"])),
                        ("build_stdout_sha256", out / "build.stdout"),
                        ("build_stderr_sha256", out / "build.stderr")):
        if path.is_symlink() or sha(path.read_bytes()) != receipt[field]:
            raise ValueError(f"changed receipt input: {field}")
    if inventory(out / "source", receipt["build_source_sha256"]) != receipt["build_source_sha256"]:
        raise ValueError("changed effective build source")
    if inventory(Path(receipt["source"]), receipt["effective_source_sha256"]) != receipt["effective_source_sha256"]:
        raise ValueError("changed patched external source")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("build")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--cargo", default="cargo")
    check = commands.add_parser("verify")
    check.add_argument("receipt", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build(args.source, args.out, args.cargo))
        else:
            receipt = verify(args.receipt)
            print(f'verified {receipt["binary_sha256"]} {receipt["binary"]}')
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f"emulator trace: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
