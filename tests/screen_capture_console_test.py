#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real console grammar and nonblocking CDC-ring contract; no device access."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]

class ScreenCaptureConsoleTest(unittest.TestCase):
    def test_real_enabled_and_disabled_console(self):
        outroot = ROOT / "build" / "host"
        outroot.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="screen-console-", dir=outroot) as directory:
            for enabled in (0, 1):
                binary = Path(directory) / f"console-{enabled}"
                subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c99", "-O1",
                                "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-unused-variable",
                                f"-DFELUCCA_SCREEN_CAPTURE={enabled}",
                                str(ROOT / "tests/screen_capture_console_test.c"), "-o", str(binary)],
                               check=True, cwd=ROOT)
                result = subprocess.run([str(binary)], capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertIn(b"screen capture console checks passed", result.stdout)
                if enabled:
                    data = re.search(rb"SCAP DATA token=1 offset=0 length=96 crc=([0-9A-F]{8}) data=([0-9A-F]{192})\r\n", result.stdout)
                    self.assertIsNotNone(data, result.stdout)
                    pixels = bytes.fromhex(data[2].decode())
                    self.assertEqual(pixels, bytes.fromhex("F800") * 48)
                    self.assertEqual(int(data[1], 16), zlib.crc32(pixels))

if __name__ == "__main__":
    unittest.main()
