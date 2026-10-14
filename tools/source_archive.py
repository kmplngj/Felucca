#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Export and verify complete, reproducible Felucca source distributions."""
# A verifier invoked inside an extracted archive must load stdlib from outside it.
import os as _source_os
import sys as _source_sys

_source_import_paths = None
_source_root = _source_os.path.dirname(_source_os.path.dirname(_source_os.path.realpath(__file__)))
if _source_os.path.isfile(_source_os.path.join(_source_root, "SOURCE-PINS.json")):
    _source_sys.dont_write_bytecode = True
    _source_os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    _source_import_paths = _source_sys.path[:]
    _source_sys.path = [p for p in _source_import_paths
                        if not (_source_os.path.realpath(p or _source_os.getcwd()) == _source_root
                                or _source_os.path.realpath(p or _source_os.getcwd()).startswith(_source_root + _source_os.sep))]

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

if _source_import_paths is not None:
    _source_sys.path = _source_import_paths

MANIFEST = "SOURCE-PINS.json"
ENGINE = "firmware/engines"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def safe_path(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name
            or any(part in {".", "..", ".git"} for part in path.parts)
            or "\\" in name or any(ord(char) < 32 for char in name)
            or path.parts[0] == "build" or path.suffix.lower() in {".pyc", ".pyo"}):
        raise ValueError(f"unsafe source path: {name!r}")
    return path


def tracked(root):
    rows = git(root, "ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0")
    for row in rows:
        if row:
            metadata, name = row.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            name = name.decode("utf-8")
            safe_path(name)
            yield mode, kind, oid, name


def engine_pin(root):
    rows = [row for row in tracked(root) if row[3] == ENGINE]
    if len(rows) != 1 or rows[0][:2] != ("160000", "commit"):
        raise ValueError("missing committed Felucca-Engines gitlink")
    path = root / ENGINE
    # Without .git, git -C would resolve the parent's HEAD instead of the submodule.
    if not (path / ".git").exists() or not (path / "src/felucca_engine.h").is_file():
        raise ValueError("Felucca-Engines is uninitialized; run git submodule update --init --recursive")
    revision = git(path, "rev-parse", "HEAD").decode().strip()
    dirty = git(path, "status", "--porcelain", "--untracked-files=all").decode().strip()
    if revision != rows[0][2] or dirty:
        raise ValueError("Felucca-Engines differs from the committed pin or has local changes")
    url = git(root, "config", "-f", ".gitmodules", "submodule.firmware/engines.url").decode().strip()
    return {"path": ENGINE, "repository": url, "revision": revision, "license": "MIT"}


def source_files(root):
    """Read committed blobs, preserving only Git's executable bit; never copy local files."""
    engine = engine_pin(root)
    dirty = git(root, "status", "--porcelain", "--untracked-files=no").decode().strip()
    if dirty:
        raise ValueError("source export requires clean committed firmware sources (tracked changes present)")
    files = {}
    for repo, prefix in ((root, ""), (root / ENGINE, ENGINE + "/")):
        for mode, kind, oid, name in tracked(repo):
            if not prefix and name == ENGINE:
                continue
            name = prefix + name
            safe_path(name)
            if name == MANIFEST or kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError(f"unsupported source entry (symlink, nested submodule or reserved manifest): {name}")
            files[name] = (0o755 if mode == "100755" else 0o644, git(repo, "cat-file", "blob", oid))
    return engine, files


def manifest_bytes(metadata):
    return (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()


def export(root, destination, version):
    if not re.fullmatch(r"[0-9]\.[0-9](?:\.[0-9]){0,2}(?:-[A-Za-z0-9]+)?", version):
        raise ValueError("invalid source archive version")
    root, destination = Path(root), Path(destination)
    engine, files = source_files(root)
    files = dict(files)
    epoch = int(git(root, "show", "-s", "--format=%ct", "HEAD"))
    metadata = {"schema_version": 1, "version": version,
                "firmware_revision": git(root, "rev-parse", "HEAD").decode().strip(),
                "source_date_epoch": epoch, "engines": engine,
                "files": {name: {"mode": mode, "sha256": hashlib.sha256(data).hexdigest()}
                          for name, (mode, data) in sorted(files.items())}}
    marker = manifest_bytes(metadata)
    files[MANIFEST] = (0o644, marker)
    prefix = f"felucca-{version}-source"
    directories = {prefix}
    for name in files:
        parent = PurePosixPath(prefix, name).parent
        directories.update(str(path) for path in [parent, *parent.parents] if str(path) != ".")
    members = {name: (0o755, None) for name in directories}
    members.update({f"{prefix}/{name}": item for name, item in files.items()})
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with temporary.open("wb") as output, gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, (mode, data) in sorted(members.items()):
                    info = tarfile.TarInfo(name)
                    info.mode, info.mtime = mode, epoch
                    info.type = tarfile.DIRTYPE if data is None else tarfile.REGTYPE
                    info.size = 0 if data is None else len(data)
                    archive.addfile(info, None if data is None else io.BytesIO(data))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest}  {destination.name}\n")
    return {"archive": destination.name, "sha256": digest,
            "manifest_sha256": hashlib.sha256(marker).hexdigest(),
            "firmware_revision": metadata["firmware_revision"], "engines": engine,
            "source_date_epoch": epoch}


def validate_manifest(metadata):
    try:
        if (metadata["schema_version"] != 1
                or not re.fullmatch(r"[0-9a-f]{40}", metadata["firmware_revision"])
                or not re.fullmatch(r"[0-9a-f]{40}", metadata["engines"]["revision"])
                or metadata["engines"]["path"] != ENGINE
                or not isinstance(metadata["source_date_epoch"], int)
                or metadata["source_date_epoch"] < 0 or not metadata["files"]):
            raise ValueError("invalid source pin manifest")
        for name, entry in metadata["files"].items():
            safe_path(name)
            if (name == MANIFEST or entry["mode"] not in {0o644, 0o755}
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
                raise ValueError(f"invalid source manifest entry: {name}")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid source pin manifest") from error
    return metadata


def verify_tree(root):
    """Check archive sources before building; generated build outputs are permitted."""
    root = Path(root)
    try:
        metadata = validate_manifest(json.loads((root / MANIFEST).read_text()))
        # Glob-based asset generators can consume files absent from the manifest.
        # Permit known generated outputs, but never importable bytecode caches.
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError(f"source path is a symlink: {name}")
            if path.suffix.lower() in {".pyc", ".pyo"}:
                raise ValueError(f"Python bytecode cache is not a verified source input: {name}")
            if name in metadata["files"] or name == MANIFEST:
                continue
            parts = path.relative_to(root).parts
            generated = parts[0] == "build" or parts[:3] == ("firmware", "engines", "build")
            if generated:
                continue
            safe_path(name)
            if path.is_dir():
                continue
            raise ValueError(f"unmanifested source file: {name}")
        for name, entry in metadata["files"].items():
            path = root / name
            parent = path
            while True:
                if parent.is_symlink():
                    raise ValueError(f"source path is a symlink: {name}")
                if parent == root:
                    break
                parent = parent.parent
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"source file missing or changed: {name}")
            if bool(path.stat().st_mode & 0o111) != (entry["mode"] == 0o755):
                raise ValueError(f"source executable mode changed: {name}")
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot verify source pin manifest: {error}") from error
    return metadata


def verify_archive(path, expected=None):
    """Validate all source members without extracting paths or following links."""
    path = Path(path)
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if not members or len(names) != len(set(names)) or names != sorted(names):
                raise ValueError("source archive members must be unique and ordered")
            prefix = names[0]
            safe_path(prefix)
            if "/" in prefix or not members[0].isdir():
                raise ValueError("source archive needs one top-level directory")
            files = {}
            for info in members:
                safe_path(info.name)
                if not (info.name == prefix or info.name.startswith(prefix + "/")):
                    raise ValueError("source archive member escapes its source directory")
                if (info.uid != 0 or info.gid != 0 or info.uname or info.gname
                        or set(info.pax_headers) - {"path"}
                        or info.pax_headers.get("path", info.name) != info.name
                        or not (info.isdir() or info.isfile())):
                    raise ValueError(f"unsafe or non-normalized source archive member: {info.name}")
                if info.isfile():
                    files[info.name[len(prefix) + 1:]] = (info, archive.extractfile(info).read())
            marker = files.pop(MANIFEST)[1]
            metadata = validate_manifest(json.loads(marker))
            if prefix != f"felucca-{metadata['version']}-source" or set(files) != set(metadata["files"]):
                raise ValueError("source archive does not match its file manifest")
            directories = {prefix}
            for name in [MANIFEST, *files]:
                parent = PurePosixPath(prefix, name).parent
                directories.update(str(p) for p in [parent, *parent.parents] if str(p) != ".")
            if {info.name for info in members if info.isdir()} != directories:
                raise ValueError("source archive contains unexpected directories")
            for info in members:
                if info.mtime != metadata["source_date_epoch"] or info.mode != (0o755 if info.isdir() else
                        0o644 if info.name == f"{prefix}/{MANIFEST}" else metadata["files"][info.name[len(prefix) + 1:]]["mode"]):
                    raise ValueError(f"non-normalized source archive metadata: {info.name}")
            for name, (_, data) in files.items():
                if hashlib.sha256(data).hexdigest() != metadata["files"][name]["sha256"]:
                    raise ValueError(f"source archive checksum mismatch: {name}")
        if expected and (expected["archive"] != path.name
                         or expected["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()
                         or expected["manifest_sha256"] != hashlib.sha256(marker).hexdigest()
                         or expected["firmware_revision"] != metadata["firmware_revision"]
                         or expected["engines"] != metadata["engines"]
                         or expected["source_date_epoch"] != metadata["source_date_epoch"]):
            raise ValueError("source archive does not match build provenance")
    except (OSError, tarfile.TarError, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid source archive: {error}") from error
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("version")
    exporter.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    exporter.add_argument("--output", type=Path)
    verifier = commands.add_parser("verify")
    verifier.add_argument("path", type=Path, help="extracted source directory or source tar.gz")
    args = parser.parse_args()
    if args.command == "export":
        output = args.output or args.root / f"build/felucca-{args.version}-source.tar.gz"
        print(json.dumps(export(args.root, output, args.version), indent=2, sort_keys=True))
    else:
        metadata = verify_tree(args.path) if args.path.is_dir() else verify_archive(args.path)
        print(f"verified firmware {metadata['firmware_revision']}; Engines {metadata['engines']['revision']}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
