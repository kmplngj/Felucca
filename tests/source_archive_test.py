#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real Git fixtures for complete source export, integrity and Git-free rebuilding."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import source_archive as source


class Archives(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.engine = self.base / "engine"
        self.repo = self.base / "firmware"
        for repo in (self.engine, self.repo):
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.name", "Source fixture")
            self.git(repo, "config", "user.email", "fixture@example.invalid")
        self.write(self.engine, "src/felucca_engine.h", "/* MIT fixture */\n")
        self.write(self.engine, "src/dsp.c", "int engine_source = 42;\n")
        self.write(self.engine, "LICENSE", "MIT license fixture\n")
        self.commit(self.engine)
        self.git(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(self.engine), source.ENGINE)
        self.write(self.repo, ".gitignore", "build/\n*.secret\n")
        self.write(self.repo, "firmware/src/felucca.c", "int firmware_source = 7;\n")
        self.write(self.repo, "LICENSE", "GPL-3.0-only fixture\n")
        self.write(self.repo, "LICENSES/Apache-2.0.txt", "SDK license fixture\n")
        self.write(self.repo, "profiles/standard.json", '{"name":"standard"}\n')
        self.write(self.repo, "assets/samples-cc0/ATTRIBUTION.txt", "CC0 sample fixture\n")
        self.write(self.repo, "assets/fonts/font.bin", b"font input\0\xff")
        self.write(self.repo, "tools/source_archive.py", Path(source.__file__).read_bytes())
        # This fixture builds the tracked firmware+engine input, with the same
        # early source manifest guard as the real target build (tested in release CI).
        self.write(self.repo, "tools/build.py", '''from pathlib import Path
import hashlib
import source_archive
root = Path(__file__).resolve().parents[1]
source_archive.verify_tree(root)
inputs = [root / "firmware/src/felucca.c", root / "firmware/engines/src/dsp.c"]
(root / "build").mkdir(exist_ok=True)
(root / "build/app.bin").write_bytes(hashlib.sha256(b"".join(p.read_bytes() for p in inputs)).digest())
''')
        self.write(self.repo, "build.sh", '#!/bin/sh\nexec python3 "$(dirname "$0")/tools/build.py"\n')
        (self.repo / "build.sh").chmod(0o755)
        self.commit(self.repo)
        self.bundle = self.base / "felucca-1.6-source.tar.gz"

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT)

    def write(self, root, name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())

    def commit(self, root):
        self.git(root, "add", "--all")
        self.git(root, "commit", "-qm", "source fixture")

    def export(self):
        return source.export(self.repo, self.bundle, "1.6")

    def unpack(self):
        self.export()
        with tarfile.open(self.bundle) as archive:
            archive.extractall(self.base / "unpacked", filter="data")
        return self.base / "unpacked/felucca-1.6-source"

    def rewrite(self, callback):
        with tarfile.open(self.bundle) as archive:
            members = [(info, archive.extractfile(info).read() if info.isfile() else None)
                       for info in archive.getmembers()]
        members = callback(members)
        with tarfile.open(self.bundle, "w:gz") as archive:
            for info, data in members:
                info.size = 0 if data is None else len(data)
                archive.addfile(info, None if data is None else io.BytesIO(data))

    def test_exact_committed_sources_and_licenses_without_local_files(self):
        self.write(self.repo, "build/credentials.secret", "never ship")
        self.write(self.repo, "untracked.txt", "never ship")
        self.write(self.repo, "local.secret", "never ship")
        info = self.export()
        metadata = source.verify_archive(self.bundle, info)
        self.assertEqual(metadata["firmware_revision"], self.git(self.repo, "rev-parse", "HEAD").decode().strip())
        self.assertEqual(metadata["engines"]["revision"], self.git(self.engine, "rev-parse", "HEAD").decode().strip())
        expected = {row[3] for row in source.tracked(self.repo) if row[3] != source.ENGINE}
        expected |= {source.ENGINE + "/" + row[3] for row in source.tracked(self.engine)}
        self.assertEqual(set(metadata["files"]), expected)
        with tarfile.open(self.bundle) as archive:
            for name in expected:
                repo, local = (self.repo / source.ENGINE, name[len(source.ENGINE) + 1:]) if name.startswith(source.ENGINE + "/") else (self.repo, name)
                self.assertEqual(archive.extractfile("felucca-1.6-source/" + name).read(), self.git(repo, "show", "HEAD:" + local))
            self.assertEqual(archive.getmember("felucca-1.6-source/build.sh").mode, 0o755)
        self.assertEqual(self.bundle.with_suffix(".gz.sha256").read_text(), f"{info['sha256']}  {self.bundle.name}\n")

    def test_deterministic_despite_metadata_untracked_files_and_git_directory(self):
        self.export()
        original = self.bundle.read_bytes()
        self.git(self.repo, "config", "core.filemode", "false")
        self.git(self.repo / source.ENGINE, "config", "core.filemode", "false")
        for root in (self.repo, self.repo / source.ENGINE):
            for _, kind, _, name in source.tracked(root):
                if kind == "blob":
                    os.utime(root / name, (1234567, 1234567))
                    (root / name).chmod(0o600)
        self.write(self.repo, "build/random", os.urandom(64))
        self.export()
        self.assertEqual(original, self.bundle.read_bytes())
        epoch = int(self.git(self.repo, "show", "-s", "--format=%ct", "HEAD"))
        self.assertEqual(int.from_bytes(original[4:8], "little"), epoch)
        self.assertEqual(original[3], 0)  # No gzip filename or optional metadata.
        with tarfile.open(self.bundle) as archive:
            self.assertEqual(archive.getnames(), sorted(archive.getnames()))
            for info in archive.getmembers():
                self.assertEqual((info.uid, info.gid, info.uname, info.gname, info.mtime), (0, 0, "", "", epoch))

    def test_dirty_tracked_firmware_staged_or_unstaged_is_rejected(self):
        for staged in (False, True):
            self.write(self.repo, "firmware/src/felucca.c", "dirty source")
            if staged:
                self.git(self.repo, "add", "firmware/src/felucca.c")
            with self.subTest(staged=staged), self.assertRaisesRegex(ValueError, "clean committed firmware"):
                self.export()
            self.git(self.repo, "reset", "--hard", "-q")

    def test_missing_wrong_dirty_or_untracked_engine_is_rejected(self):
        path = self.repo / source.ENGINE
        marker = (path / ".git").read_bytes()
        (path / ".git").unlink()
        with self.assertRaisesRegex(ValueError, "uninitialized"):
            self.export()
        (path / ".git").write_bytes(marker)
        for name in ("src/dsp.c", "unexpected.txt"):
            original = (path / name).read_bytes() if (path / name).exists() else None
            self.write(path, name, "dirty engine")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "committed pin or has local changes"):
                self.export()
            if original is None:
                (path / name).unlink()
            else:
                (path / name).write_bytes(original)
        self.git(path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "different pin")
        with self.assertRaisesRegex(ValueError, "committed pin"):
            self.export()

    def test_committed_symlinks_and_reserved_paths_are_rejected(self):
        for name in ("SOURCE-PINS.json", "build/secret", "link"):
            if name == "link":
                (self.repo / name).symlink_to("/etc/passwd")
            else:
                self.write(self.repo, name, "reserved source")
            self.git(self.repo, "add", "-f", name)
            self.git(self.repo, "commit", "-qm", "unsupported entry")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe source path|unsupported source entry"):
                self.export()
            self.git(self.repo, "reset", "--hard", "-q", "HEAD~")

    def test_corrupt_missing_or_extra_archive_files_are_rejected(self):
        def corrupt(items):
            return [(info, b"corrupt" if info.name.endswith("src/dsp.c") else data) for info, data in items]
        for change in (corrupt, lambda items: [(info, data) for info, data in items if not info.name.endswith("src/dsp.c")],
                       lambda items: [*items, items[-1]]):
            self.export()
            self.rewrite(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "checksum mismatch|file manifest|unique and ordered"):
                source.verify_archive(self.bundle)
        self.export()
        info = source.export(self.repo, self.base / "other.tar.gz", "1.6")
        with self.assertRaisesRegex(ValueError, "provenance"):
            source.verify_archive(self.bundle, info)
        self.bundle.write_bytes(b"corrupt gzip")
        with self.assertRaisesRegex(ValueError, "invalid source archive"):
            source.verify_archive(self.bundle)

    def test_archive_path_traversal_and_links_are_rejected_without_extraction(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                           ("felucca-1.6-source/.git/config", tarfile.REGTYPE),
                           ("felucca-1.6-source/evil", tarfile.SYMTYPE),
                           ("felucca-1.6-source/evil", tarfile.LNKTYPE)):
            self.export()
            def add(items):
                info = tarfile.TarInfo(name)
                info.type, info.linkname = kind, "../../escape"
                return sorted([*items, (info, b"danger" if kind == tarfile.REGTYPE else None)], key=lambda row: row[0].name)
            self.rewrite(add)
            with self.subTest(name=name, kind=kind), self.assertRaises(ValueError):
                source.verify_archive(self.bundle)
        self.assertFalse((self.base / "escape").exists())

    def test_unpacked_sources_build_without_git_and_reject_changed_missing_or_unsafe_files(self):
        root = self.unpack()
        metadata = source.verify_tree(root)
        self.assertFalse((root / ".git").exists())
        self.assertFalse((root / source.ENGINE / ".git").exists())
        blocker = self.base / "blocked"
        blocker.mkdir()
        (blocker / "git").write_text("#!/bin/sh\necho Git must not be needed >&2\nexit 91\n")
        (blocker / "git").chmod(0o755)
        env = dict(os.environ, PATH=str(blocker) + os.pathsep + os.environ["PATH"])
        subprocess.run([str(root / "build.sh")], cwd=root, env=env, check=True, capture_output=True)
        self.assertEqual(len((root / "build/app.bin").read_bytes()), 32)
        source.verify_tree(root)  # Generated files do not invalidate the source marker.
        path = root / source.ENGINE / "src/dsp.c"
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            source.verify_tree(root)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            source.verify_tree(root)
        path.symlink_to(self.engine / "src/dsp.c")
        with self.assertRaisesRegex(ValueError, "symlink"):
            source.verify_tree(root)
        path.unlink()
        path.write_bytes(original)
        build_script = root / "build.sh"
        build_script.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "executable mode"):
            source.verify_tree(root)
        metadata["files"]["../escape"] = {"mode": 0o644, "sha256": "0" * 64}
        (root / source.MANIFEST).write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "unsafe source path"):
            source.verify_tree(root)


if __name__ == "__main__":
    unittest.main()
