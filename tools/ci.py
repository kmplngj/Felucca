#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Strict CI input, coverage and release checks; no device access or baseline updates."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build
import fm1_install
import source_archive

SDK_REF = "d179b4484759423312073f5fbb232501aa491047"
SDK_MIRROR = "https://raw.githubusercontent.com/Quixotic7/ChoralRootFM1/d09c687d8ee1850fc1360c080aca41763be998ca/tools/sdk"
TOOLCHAIN = "jieli-linux-toolchains-20260730.1"


def version(value):
    # Match build.py's actual package-identity limit, before using a version in paths.
    if not re.fullmatch(r"[0-9]\.[0-9](?:\.[0-9]){0,2}(?:-[A-Za-z0-9]+)?", value):
        raise ValueError("version must be X.Y, X.Y.Z, X.Y.Z.W or X.Y-suffix (one digit each)")
    return value


def check_sdk(root):
    for rel, digest in build.SDK_SHA256.items():
        path = root / "cpu/wl82/tools" / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"missing or incorrect SDK file: {path}")


def fetch_sdk(root):
    base = f"https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK/raw/{SDK_REF}"
    for rel, digest in build.SDK_SHA256.items():
        path = root / "cpu/wl82/tools" / rel
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        for source in (base, SDK_MIRROR):
            url = f"{source}/cpu/wl82/tools/{rel}"
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    data = response.read()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("SHA-256 mismatch")
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_bytes(data)
                temporary.replace(path)
                print(f"SDK {rel}: verified from {url}")
                break
            except (OSError, ValueError, urllib.error.URLError) as error:
                print(f"SDK {url}: {error}", file=sys.stderr)
        else:
            raise ValueError(f"cannot fetch verified SDK file: {rel}")
    check_sdk(root)  # Cache hits must pass the same checks as downloads.


def verify_tests(log):
    text = log.read_text()
    # Optional local suites become required here. Whole host CPU budgets may be
    # unavailable (counter or matching host baseline); individual missing entries
    # in an available budget are coverage failures.
    allowed = "official V15 restore: skipped (needs FM-1_v15.fwsc in the repo root)"
    forbidden = [line for line in text.splitlines() if line != allowed
                 and re.search(r"^== skip |^target: skip |: skipped \(|no budget \(BUDGET_UPDATE|no baseline \(BUDGET_UPDATE", line)]
    if forbidden or "ALL HOST TESTS PASSED" not in text:
        raise ValueError("incomplete test coverage:\n" + "\n".join(forbidden))
    for path in ("build/felucca.dis", "build/emu/felucca.wasm", "build/host/asan/fuzz_ed",
                 "build/host/phys_ref", "build/host/regress", "build/host/regress_os"):
        if not Path(path).is_file():
            raise ValueError(f"required test output missing: {path}")


def portable_tests():
    from ci_changes import PORTABLE_TESTS
    for name in PORTABLE_TESTS:
        subprocess.run([sys.executable, str(build.SRC / "tests" / name)], check=True)
    subprocess.run([sys.executable, "-O", str(build.SRC / "tests/fm1pkg_test.py")], check=True)


def emulator_tests():
    # The emulator needs generated assets, not a pi32v2 app or an SDK package.
    # Regenerate them even if local outputs exist; compare freshly compiled peers.
    build.generate()
    host = build.OUT / "host"
    host.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sh", "web/emu/build.sh"], check=True)
    subprocess.run(["clang", "-O2", "-ffp-contract=off", "-w", "-Ibuild/gen",
                    "-Ifirmware/src", "-o", str(host / "emu_native"),
                    "web/emu/native_check.c", "-lm"], check=True)
    subprocess.run([str(host / "emu_native"), str(host / "emu_native.f32")], check=True)
    subprocess.run(["node", "web/emu/emu_test.mjs", "build/emu/felucca.wasm",
                    str(host / "emu_native.f32")], check=True)
    subprocess.run(["sh", "web/emu/partition_test.sh", "--require-wasm"], check=True)
    # The replay adapter includes the emulator's DSP/UI/event integration, so
    # emulator-only changes must exercise its native capture contract as well.
    subprocess.run([sys.executable, str(build.SRC / "tests/replay_test.py"),
                    "NativeReplayTests"], check=True)


def host_cpu_provenance():
    """Record the host compiler and the runner's baseline/flag selection before tests."""
    cc = shlex.split(os.environ.get("CC", "cc"))
    common = ["-O1", "-Wall", "-Wno-unused-function"]
    novec = ["-fno-vectorize", "-fno-slp-vectorize"]
    probe = subprocess.run(cc + common + novec + ["-x", "c", "-c", "-o", os.devnull, "-"],
                           input="int x;", text=True, capture_output=True)
    if probe.returncode:
        novec = ["-fno-tree-vectorize", "-fno-tree-slp-vectorize"]
    paths = subprocess.check_output([sys.executable, str(build.SRC / "tests/cpu_baseline.py"),
                                     *cc, *common], text=True).splitlines()
    return {
        "compiler_command": cc,
        "compiler": subprocess.check_output(cc + ["--version"], text=True).strip(),
        "platform": platform.system(), "architecture": platform.machine(),
        "harnesses": {
            name: {"flags": common + flags + ["-w", "-Ibuild/gen", "-Ifirmware/src"],
                   "baseline": path, "baseline_present": (build.SRC / path).is_file()}
            for name, flags, path in zip(("regress", "regress_os"), (["-O2"], ["-Os", *novec]), paths)
        },
        "counter_policy": "Available counter and matching host baseline required; actual outcomes in tests.log",
    }


def engine_provenance():
    """Require the exact committed, clean engine source used by this build."""
    root = build.SRC
    path = root / "firmware/engines"
    row = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "HEAD", "firmware/engines"], text=True).split()
    if len(row) != 4 or row[:2] != ["160000", "commit"]:
        raise ValueError("missing committed Felucca-Engines gitlink")
    if not (path / "src/felucca_engine.h").is_file():
        raise ValueError("Felucca-Engines is uninitialized; run git submodule update --init --recursive")
    revision = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(path), "status", "--porcelain"], text=True).strip()
    if revision != row[2] or dirty:
        raise ValueError("Felucca-Engines differs from the committed pin or has local changes")
    url = subprocess.check_output(
        ["git", "-C", str(root), "config", "-f", ".gitmodules", "submodule.firmware/engines.url"],
        text=True).strip()
    return {"path": "firmware/engines", "repository": url, "revision": revision, "license": "MIT"}


def provenance(out):
    from PIL import features
    import PIL
    import fontTools
    import brotli
    tc = build.toolchain()
    data = {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_date": subprocess.check_output(["git", "show", "-s", "--format=%cI", "HEAD"], text=True).strip(),
        "runner": platform.platform(), "python": sys.version,
        "Pillow": PIL.__version__, "fontTools": fontTools.__version__,
        "Brotli": brotli.__version__,
        "ui_font": os.environ.get("FELUCCA_FONT", "m8stealth"),
        "raqm": features.version("raqm"), "freetype": features.version("freetype2"),
        "toolchain": tc.name, "compiler": build.tc("pi32v2/bin/clang", "--version").strip(),
        "compiler_sha256": hashlib.sha256((tc / "pi32v2/bin/clang").read_bytes()).hexdigest(),
        "sdk_reference": SDK_REF, "sdk_sha256": build.SDK_SHA256,
        "build_flags": build.CFLAGS, "selective_minsize": "tools/size_fns.py defaults",
        "host_cpu": host_cpu_provenance(),
        "engines": engine_provenance(),
        "version": os.environ.get("VERSION", ""),
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "emscripten": subprocess.check_output(["emcc", "--version"], text=True).splitlines()[0],
        "daisysp_revision": subprocess.check_output(["git", "-C", os.environ["DAISYSP"], "rev-parse", "HEAD"], text=True).strip(),
        "sample_sha256": {str(p.relative_to(build.SRC)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((build.SRC / "assets/samples-cc0").rglob("*.wav"))},
        "limitations": ["Host instruction budgets may be skipped if the counter or matching baseline is unavailable; ns/sample is informational",
                        "Target instruction budget is static, not FM-1 cycle timing",
                        "No real-device audio, panel, USB/MIDI or flashing validation"],
    }
    if (build.SRC / "profiles/catalog.json").is_file():
        import profile
        # Resolve before the target build; never reuse stale generated profile outputs.
        data["profile"] = json.loads(profile.generated(
            build.SRC, os.environ.get("FELUCCA_PROFILE", "standard"))["resolved-profile.json"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")


def preflight():
    from PIL import features
    if not features.check("raqm"):
        raise ValueError("Pillow needs Raqm for the reference font layout")
    tc = build.toolchain()
    if tc.name != TOOLCHAIN or "clang version 4.0.1" not in build.tc("pi32v2/bin/clang", "--version"):
        raise ValueError(f"expected {TOOLCHAIN}, JieLi Clang 4.0.1")
    check_sdk(Path(os.environ["AC79_SDK"]))
    for command in ("clang", "c++", "node", "emcc"):
        if not shutil.which(command):
            raise ValueError(f"required CI command missing: {command}")
    if not (Path(os.environ["DAISYSP"]) / "Source/PhysicalModeling/modalvoice.cpp").is_file():
        raise ValueError("required DaisySP reference checkout missing")
    if not list((build.SRC / "assets/samples-cc0/PIANO").glob("*.wav")):
        raise ValueError("required checked-in CC0 piano samples missing")
    if os.environ.get("GOLDEN_UPDATE") or os.environ.get("BUDGET_UPDATE"):
        raise ValueError("CI must never update goldens or budgets")


def write_checksums(root):
    files = sorted(p for p in root.rglob("*") if p.is_file() and p != root / "SHA256SUMS")
    (root / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n" for p in files))


def verify_checksums(root):
    # Recompute every checksum, and require every distributable file to be covered.
    expected = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                      if p.is_file() and p != root / "SHA256SUMS")
    entries = []
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not name or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"malformed release checksum line: {line!r}")
        if name not in expected or hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"invalid release checksum: {name}")
        entries.append(name)
    if sorted(entries) != expected:
        raise ValueError("release checksums do not cover exactly all distributed files")


def package(root, value):
    version(value)
    required = [f"felucca-{value}.fwsc", f"felucca-{value}-app.bin", "LICENSE", "LICENSING.md",
                "ATTRIBUTION.txt", "BUILD-PROVENANCE.json", "SHA256SUMS"]
    required += [str(p.relative_to(build.SRC)) for p in sorted((build.SRC / "LICENSES").glob("*.txt"))]
    for name in required:
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise ValueError(f"release file missing or empty: {name}")
    verify_checksums(root)
    metadata = json.loads((root / "BUILD-PROVENANCE.json").read_text())
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if metadata.get("revision") != revision or metadata.get("version") != value:
        raise ValueError("release provenance does not match the checkout and version")
    pin = subprocess.check_output(["git", "ls-tree", "HEAD", "firmware/engines"], text=True).split()
    if (len(pin) != 4 or pin[:2] != ["160000", "commit"]
            or metadata.get("engines", {}).get("revision") != pin[2]):
        raise ValueError("release Engines provenance does not match the committed gitlink")
    source = metadata.get("source_distribution", {})
    if (source.get("archive") != f"felucca-{value}-source.tar.gz"
            or source.get("firmware_revision") != metadata.get("revision")
            or source.get("engines") != metadata.get("engines")
            or not re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", source.get("manifest_sha256", ""))):
        raise ValueError("release source distribution provenance missing or inconsistent")
    raw = (root / f"felucca-{value}.fwsc").read_bytes()
    if len(raw) < fm1_install.BLOCKS * fm1_install.BLK:
        raise ValueError("release package is truncated")
    product = f"FM-1_9{value[0]}{value[2]}"
    if fm1_install.LOADER_MARK not in raw:
        raise ValueError("release package has no Felucca update loader")
    actual = fm1_install.product_of(raw)
    if actual != product:
        raise ValueError(f"release product {actual} does not match {product}")


def finalize(value):
    version(value)
    root = build.OUT / f"release-{value}"
    metadata = json.loads((build.OUT / "ci/provenance.json").read_text())
    # Keep the real build clock in diagnostics, outside reproducible release content.
    metadata.pop("built_at_utc", None)
    metadata["source_distribution"] = source_archive.export(
        build.SRC, build.OUT / f"felucca-{value}-source.tar.gz", value)
    (root / "BUILD-PROVENANCE.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_checksums(root)
    package(root, value)
    epoch = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], text=True))

    def normalize(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = epoch
        info.mode = 0o755 if info.isdir() else 0o644
        info.pax_headers = {}
        return info

    bundle = build.OUT / f"felucca-{value}-release.tar.gz"
    with bundle.open("wb") as output, gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path in [root, *sorted(root.rglob("*"))]:
                archive.add(path, arcname=str(Path(f"felucca-{value}") / path.relative_to(root)),
                            recursive=False, filter=normalize)
    bundle.with_suffix(bundle.suffix + ".sha256").write_text(
        f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n")


def stage_release(root, bundles, destination, value):
    """Match GitHub's flat release asset names, including every third-party license."""
    package(root, value)
    bundle = bundles / f"felucca-{value}-release.tar.gz"
    sidecar = bundle.with_suffix(bundle.suffix + ".sha256")
    expected = f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n"
    if sidecar.read_text() != expected:
        raise ValueError("invalid release archive checksum")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p != root / "SHA256SUMS")
    source = bundles / f"felucca-{value}-source.tar.gz"
    source_sidecar = source.with_suffix(source.suffix + ".sha256")
    metadata = json.loads((root / "BUILD-PROVENANCE.json").read_text())
    source_archive.verify_archive(source, metadata["source_distribution"])
    expected_source = f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}\n"
    if not source_sidecar.is_file() or source_sidecar.read_text() != expected_source:
        raise ValueError("invalid source archive checksum")
    files += [bundle, sidecar, source, source_sidecar]
    if len({p.name for p in files}) != len(files) or any(p.name == "SHA256SUMS" for p in files):
        raise ValueError("release asset filenames collide after flattening")
    destination.mkdir()
    for path in files:
        shutil.copyfile(path, destination / path.name)
    write_checksums(destination)
    verify_checksums(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["version", "sdk", "preflight", "provenance", "verify-tests", "portable-tests", "emulator-tests", "finalize", "package", "stage-release"])
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    if args.command == "version":
        print(version(args.value))
    elif args.command == "sdk":
        fetch_sdk(Path(os.environ["AC79_SDK"]))
    elif args.command == "preflight":
        preflight()
    elif args.command == "provenance":
        provenance(build.OUT / "ci/provenance.json")
    elif args.command == "verify-tests":
        verify_tests(Path(args.value))
    elif args.command == "portable-tests":
        portable_tests()
    elif args.command == "emulator-tests":
        emulator_tests()
    elif args.command == "finalize":
        finalize(args.value)
    elif args.command == "package":
        package(Path("release"), args.value)
    elif args.command == "stage-release":
        stage_release(Path("release"), Path("downloaded"), Path("release-assets"), args.value)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as error:
        raise SystemExit(str(error))
