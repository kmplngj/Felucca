#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile actual input adapters and reject the UI fake's former signature drift."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'tests/ui_test.c'


class FirmwareInputContract(unittest.TestCase):
    def setUp(self):
        self.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not self.cc or shutil.which(self.cc[0]) is None:
            self.fail('configured host C compiler unavailable')

    def compile(self, path, source=None):
        return subprocess.run([*self.cc, '-w', '-fsyntax-only', '-x', 'c',
                               '-I', str(ROOT / 'firmware/src'), '-I', str(ROOT / 'build/gen'),
                               '-iquote', str(path.parent), str(path) if source is None else '-'],
                              input=source, cwd=ROOT, text=True, capture_output=True)

    def test_real_input_hal(self):
        result = self.compile(ROOT / 'tests/input_test.c')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ui_adapter(self):
        result = self.compile(UI)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_browser_adapter(self):
        result = self.compile(ROOT / 'web/emu/native_check.c')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_ui_signature_is_rejected(self):
        # Establish the actual harness's positive control before accepting a
        # negative compile result; missing generated headers must fail this test.
        result = self.compile(UI)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = UI.read_text()
        signature = 'static uint32_t fm1_input_edges(uint32_t *x)'
        self.assertEqual(source.count(signature), 1, 'expected one real UI accessor definition')
        source = source.replace(signature, 'static uint32_t fm1_input_edges(int x)', 1)
        result = self.compile(UI, source)
        self.assertNotEqual(result.returncode, 0, 'the former incompatible UI signature was accepted')
        self.assertIn('fm1_input_edges', result.stderr)
        self.assertIn('conflicting types', result.stderr)


if __name__ == '__main__':
    unittest.main()
