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
UI = ROOT / 'tests/ui_harness.h'
UI_ENTRY = ROOT / 'tests/ui_test.c'
SETTINGS = ROOT / 'tests/settings_test.c'
BROWSER = ROOT / 'web/emu/felucca_web.c'


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
        result = self.compile(UI_ENTRY)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_settings_adapter(self):
        result = self.compile(SETTINGS)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_browser_adapter(self):
        result = self.compile(ROOT / 'web/emu/native_check.c')
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_signature_rejected(self, path, signature, wrong_signature, name):
        # Compile the actual adapter first: a missing generated input is not
        # evidence that the deliberately incompatible declaration was rejected.
        result = self.compile(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = path.read_text()
        self.assertEqual(source.count(signature), 1, 'expected one actual accessor definition')
        source = source.replace(signature, wrong_signature, 1)
        result = self.compile(path, source)
        self.assertNotEqual(result.returncode, 0, 'incompatible accessor signature was accepted')
        self.assertIn(name, result.stderr)
        self.assertIn('conflicting types', result.stderr)

    def test_wrong_ui_signature_is_rejected(self):
        self.assert_signature_rejected(
            UI, 'static uint32_t fm1_input_edges(uint32_t *x)',
            'static uint32_t fm1_input_edges(int x)', 'fm1_input_edges')

    def test_wrong_encoder_signatures_are_rejected(self):
        cases = [
            (UI, 'static int32_t fm1_enc_take(uint32_t e)',
             'static uint32_t fm1_enc_take(uint32_t e)'),
            (SETTINGS, 'static int32_t fm1_enc_take(uint32_t k)',
             'static int32_t fm1_enc_take(int32_t k)'),
            (BROWSER, 'static int32_t fm1_enc_take(uint32_t e)',
             'static uint32_t fm1_enc_take(uint32_t e)'),
        ]
        for path, signature, wrong_signature in cases:
            with self.subTest(adapter=path.name):
                self.assert_signature_rejected(path, signature, wrong_signature, 'fm1_enc_take')

    def test_wrong_note_edge_signatures_are_rejected(self):
        for path in (UI, BROWSER):
            with self.subTest(adapter=path.name):
                self.assert_signature_rejected(
                    path, 'static uint32_t fm1_input_note_edges(void)',
                    'static uint32_t fm1_input_note_edges(int unused)', 'fm1_input_note_edges')


if __name__ == '__main__':
    unittest.main()
