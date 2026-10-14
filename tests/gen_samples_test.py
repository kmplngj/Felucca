#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generated drum inputs must ignore stale build files and contaminated header caches."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gen_samples as samples


class GeneratedInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.waves = self.root / "build/genwav"
        self.cache = self.root / "build/gen_samples.cache"
        self.header = self.root / "build/samples.h"
        for name, value in (("SRC", self.root), ("GENDIR", self.waves), ("CACHE", self.cache),
                            ("CC0", self.root / "assets/samples-cc0")):
            context = patch.object(samples, name, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.dict(os.environ, FELUCCA_SLICE="1")
        context.start()
        self.addCleanup(context.stop)

    def generate(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            samples.main(self.header)
        return output.getvalue()

    def poison(self):
        # This extra name sorts before D KICK.wav and claims its role. A previous
        # build's modified canonical WAV and other stale outputs must also disappear.
        extra = self.waves / "D 00 KICK.wav"
        shutil.copyfile(self.waves / "D SNARE.wav", extra)
        shutil.copyfile(self.waves / "D SNARE.wav", self.waves / "D KICK.wav")
        (self.waves / "old-generator.txt").write_text("stale")
        (self.waves / "old-subdirectory").mkdir()
        self.assertEqual(samples.gm_kit_sources()["kick"], extra)
        return extra

    def test_extra_and_modified_wavs_cannot_change_header_or_canonical_cache(self):
        self.generate()
        baseline = self.header.read_bytes()
        cache = self.cache.read_bytes()
        names = {path.name for path in self.waves.iterdir()}
        key = samples.input_key(False)
        extra = self.poison()
        self.assertNotEqual(samples.input_key(False), key)
        output = self.generate()
        self.assertEqual(self.header.read_bytes(), baseline)
        self.assertEqual(self.cache.read_bytes(), cache)
        self.assertEqual({path.name for path in self.waves.iterdir()}, names)
        self.assertEqual(samples.gm_kit_sources()["kick"], self.waves / "D KICK.wav")
        self.assertFalse(extra.exists())
        self.assertIn("(cached)", output)

    def test_parallel_processes_publish_complete_identical_headers_and_cache(self):
        self.generate()
        baseline = self.header.read_bytes()
        cache = self.cache.read_text()
        tooling = self.root / "tools"
        tooling.mkdir()
        for name in ("gen_samples.py", "gen_waves.py", "sampleio.py"):
            shutil.copyfile(Path(samples.__file__).with_name(name), tooling / name)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for warm in (False, True):
            self.poison()
            if not warm:
                self.cache.unlink()
            self.header.unlink()
            outputs = [self.header if i < 6 else self.root / f"build/parallel-{warm}-{i}.h" for i in range(12)]
            processes = [subprocess.Popen([sys.executable, str(tooling / "gen_samples.py"), str(path)],
                                          env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                         for path in outputs]
            try:
                deadline = time.monotonic() + 60
                while any(process.poll() is None for process in processes):
                    self.assertLess(time.monotonic(), deadline, "parallel sample generators timed out")
                    # Observe the shared header/cache during publication, not merely
                    # after writers finish; partial writes can otherwise go unnoticed.
                    for path in set(outputs):
                        if path.exists():
                            self.assertEqual(path.read_bytes(), baseline)
                    if self.cache.exists():
                        self.assertEqual(self.cache.read_text(), cache)
                    time.sleep(0.005)
                for process in processes:
                    stdout, stderr = process.communicate()
                    self.assertEqual(process.returncode, 0, stdout + stderr)
                    if warm:
                        self.assertIn("(cached)", stdout)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()
            for path in set(outputs):
                self.assertEqual(path.read_bytes(), baseline)
            self.assertEqual(self.cache.read_text(), cache)
            self.assertFalse(list((self.root / "build").glob(".genwav-*")))
            self.assertFalse(list((self.root / "build").glob(".samples-*")))
            self.assertFalse((self.waves / "D 00 KICK.wav").exists())

    def test_contaminated_cache_is_replaced_then_clean_header_is_cached(self):
        self.generate()
        baseline = self.header.read_bytes()
        key = samples.input_key(False)
        self.poison()
        builder = samples.Builder()
        builder.slice_break()
        builder.slice_piano()
        contaminated = builder.header()
        self.assertNotEqual(contaminated.encode(), baseline)
        self.cache.write_text(f"{samples.input_key(False)}\n{builder.summary()}\n{contaminated}")
        output = self.generate()
        self.assertEqual(self.header.read_bytes(), baseline)
        self.assertEqual(self.cache.read_text().splitlines()[0], key)
        self.assertNotIn("(cached)", output)
        self.assertIn("(cached)", self.generate())
        self.assertEqual(self.header.read_bytes(), baseline)


if __name__ == "__main__":
    unittest.main()
