#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real Git fixtures for complete source export, integrity and Git-free rebuilding."""
import hashlib
import importlib.util
import io
import json
import os
import py_compile
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

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
        self.write(self.repo, "tools/profile.py", 'PROFILE = "standard"\n')
        self.write(self.repo, "tools/generate_fixture.py", '''from pathlib import Path
import fixture_helper
root = Path(__file__).resolve().parents[1]
(root / "build/child.txt").write_text(fixture_helper.VALUE)
''')
        self.write(self.repo, "tools/fixture_helper.py", 'VALUE = "verified child import"\n')
        self.write(self.repo, "tools/build.py", '''import os
import sys
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
from pathlib import Path
import hashlib
import subprocess
root = Path(__file__).resolve().parents[1]
verifier_path = root / "tools/source_archive.py"
namespace = {"__name__": "felucca_source_verifier", "__file__": str(verifier_path)}
exec(compile(verifier_path.read_bytes(), str(verifier_path), "exec"), namespace)
namespace["verify_tree"](root)
import profile
assert profile.PROFILE == "standard"
(root / "build").mkdir(exist_ok=True)
subprocess.run([sys.executable, str(root / "tools/generate_fixture.py")], check=True)
inputs = [root / "firmware/src/felucca.c", root / "firmware/engines/src/dsp.c"]
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
        for name in ("SOURCE-PINS.json", "build/secret", "tools/committed.pyc", "link"):
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

    def test_unmanifested_real_sample_changes_generator_inputs_and_is_rejected(self):
        import gen_samples
        original = Path(source.__file__).resolve().parents[1] / "assets/samples-cc0/PIANO/03_GPiano_sus_C4_v2_rr1_Player.wav"
        self.write(self.repo, "assets/samples-cc0/PIANO/03_Piano_C4.wav", original.read_bytes())
        self.commit(self.repo)
        root = self.unpack()
        metadata = source.verify_tree(root)
        with patch.object(gen_samples, "SRC", root), patch.object(gen_samples, "CC0", root / "assets/samples-cc0"), \
                patch.object(gen_samples, "GENDIR", root / "build/genwav"):
            key = gen_samples.input_key(True)
            shutil.copyfile(root / "assets/samples-cc0/PIANO/03_Piano_C4.wav",
                            root / "assets/samples-cc0/PIANO/05_extra_C4.wav")
            self.assertNotEqual(gen_samples.input_key(True), key)
        self.assertEqual(json.loads((root / source.MANIFEST).read_text()), metadata)
        with self.assertRaisesRegex(ValueError, "unmanifested source file: assets/samples-cc0/PIANO/05_extra_C4.wav"):
            source.verify_tree(root)

    def test_unmanifested_sources_and_symlinks_fail_but_generated_outputs_pass(self):
        root = self.unpack()
        for name in ("build/gen/generated.h", "firmware/engines/build/standalone-test"):
            self.write(root, name, "generated output")
        source.verify_tree(root)
        for name in ("firmware/src/extra.h", "firmware/engines/src/extra.h", "tools/extra.py",
                     "tools/__pycache__/extra.py"):
            self.write(root, name, "extra build input")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unmanifested source file"):
                source.verify_tree(root)
            (root / name).unlink()
        for name in ("extra", "build/unsafe", "firmware/engines/build/unsafe", "tools/__pycache__/unsafe.pyc"):
            (root / name).symlink_to(self.engine, target_is_directory=True)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "symlink"):
                source.verify_tree(root)
            (root / name).unlink()
        source.verify_tree(root)

    def unchecked_cache(self, root, module, marker):
        path = root / "tools" / (module + ".py")
        payload = self.base / "poison.py"
        payload.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nraise RuntimeError('poisoned bytecode executed')\n")
        cache = Path(importlib.util.cache_from_source(str(path)))
        cache.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(str(payload), cfile=str(cache), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        return cache

    def test_bytecode_caches_are_rejected_even_inside_generated_outputs(self):
        root = self.unpack()
        for name in ("tools/__pycache__/profile.cpython-312.pyc", "tools/profile.pyc",
                     "tools/profile.pyo", "build/__pycache__/profile.cpython-312.pyc",
                     "firmware/engines/build/importable.pyc", "build/importable.PYC", "build/importable.PYO"):
            self.write(root, name, b"malformed bytecode")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "bytecode|unmanifested"):
                source.verify_tree(root)
            (root / name).unlink()
        source.verify_tree(root)

    def test_unchecked_profile_and_verifier_bytecode_rejects_before_side_effects(self):
        root = self.unpack()
        for module in ("profile", "source_archive"):
            marker = self.base / (module + "-executed")
            cache = self.unchecked_cache(root, module, marker)
            result = subprocess.run([str(root / "build.sh")], cwd=root, text=True, capture_output=True)
            with self.subTest(module=module):
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "bytecode|unmanifested")
                self.assertFalse(marker.exists(), "cached module ran before source verification")
                self.assertFalse((root / "build/app.bin").exists())
            cache.unlink()
        result = subprocess.run([str(root / "build.sh")], cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(list(root.rglob("*.pyc")))

    def test_actual_tool_entrypoints_reject_cached_repository_helpers_before_import(self):
        # Exercise the real tools: checking the tree after a helper import is too late.
        tooling = Path(__file__).resolve().parents[1] / "tools"
        for name in ("build.py", "profile.py", "ci.py", "fm1pkg_make.py", "lz4blk.py", "fm1_install.py"):
            self.write(self.repo, "tools/" + name, (tooling / name).read_bytes())
        self.commit(self.repo)
        root = self.unpack()
        commands = (("build.py", ["--help"], "fm1pkg_make"),
                    ("profile.py", ["--help"], "source_archive"),
                    ("ci.py", ["version", "1.6"], "build"))
        for script, arguments, module in commands:
            marker = self.base / (script + "-executed")
            cache = self.unchecked_cache(root, module, marker)
            result = subprocess.run([sys.executable, str(root / "tools" / script), *arguments],
                                    cwd=root, text=True, capture_output=True)
            with self.subTest(script=script):
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "bytecode|unmanifested")
                self.assertFalse(marker.exists(), "entry point imported poisoned cached helper")
            cache.unlink()
            result = subprocess.run([sys.executable, str(root / "tools" / script), *arguments],
                                    cwd=root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(list(root.rglob("*.pyc")))

    def test_actual_entrypoints_do_not_import_unlisted_stdlib_shadow_modules(self):
        tooling = Path(__file__).resolve().parents[1] / "tools"
        for name in ("build.py", "profile.py", "ci.py", "fm1pkg_make.py", "lz4blk.py", "fm1_install.py"):
            self.write(self.repo, "tools/" + name, (tooling / name).read_bytes())
        self.commit(self.repo)
        root = self.unpack()
        marker = self.base / "stdlib-shadow-executed"
        self.write(root, "tools/json.py", f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
        for script, args in (("build.py", ["--help"]), ("profile.py", ["--help"]), ("ci.py", ["version", "1.6"]),
                             ("source_archive.py", ["verify", "."])):
            result = subprocess.run([sys.executable, str(root / "tools" / script), *args],
                                    cwd=root, text=True, capture_output=True)
            with self.subTest(script=script):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unmanifested source file: tools/json.py", result.stderr)
                self.assertFalse(marker.exists(), "bootstrap imported an unlisted stdlib shadow")

    def test_symlink_above_source_root_is_allowed_and_internal_symlinks_are_rejected(self):
        root = self.unpack()
        alias = self.base / "unpacked-alias"
        alias.symlink_to(root.parent, target_is_directory=True)
        through_alias = alias / root.name
        self.assertEqual(source.verify_tree(through_alias), source.verify_tree(root))
        extra = root / "tools/unlisted-link"
        extra.symlink_to(self.engine, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            source.verify_tree(through_alias)

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
        self.assertEqual((root / "build/child.txt").read_text(), "verified child import")
        self.assertFalse(list(root.rglob("*.pyc")))
        subprocess.run([str(root / "build.sh")], cwd=root, env=env, check=True, capture_output=True)
        self.assertFalse(list(root.rglob("*.pyc")))
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
