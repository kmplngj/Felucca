#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile actual LCD adapters and reject incompatible fill coordinates/colours."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / 'firmware/src/lcd.c'
REAL = ROOT / 'tests/lcd_power_test.c'
UI = ROOT / 'tests/ui_harness.h'
BROWSER = ROOT / 'web/emu/felucca_web.c'
RESCUE = ROOT / 'tests/rescue_test.c'
RESCUE_INPUT = ROOT / 'tests/rescue_input_test.c'
SIGNATURE = 'static void lcd_fill(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t c)'


class FirmwareLcdContract(unittest.TestCase):
    def setUp(self):
        self.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not self.cc or shutil.which(self.cc[0]) is None:
            self.fail('configured host C compiler unavailable')

    def compile(self, path, source=None):
        return subprocess.run([*self.cc, '-w', '-fsyntax-only', '-x', 'c',
                               '-I', str(ROOT / 'firmware/src'), '-I', str(ROOT / 'build/gen'),
                               '-iquote', str(path.parent),
                               str(path) if source is None else '-'],
                              input=source, cwd=ROOT, text=True, capture_output=True)

    def test_actual_adapters(self):
        for path in (REAL, ROOT / 'tests/screen_capture_test.c', ROOT / 'tests/ui_test.c',
                     ROOT / 'web/emu/native_check.c', RESCUE, RESCUE_INPUT):
            with self.subTest(adapter=path.name):
                result = self.compile(path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def assert_signature_rejected(self, path, wrong_signature):
        # Prove the actual source compiles with its prerequisites before mutation.
        entry = REAL if path == DRIVER else path
        result = self.compile(entry)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = path.read_text()
        self.assertEqual(source.count(SIGNATURE), 1, 'expected one actual fill definition')
        source = source.replace(SIGNATURE, wrong_signature, 1)
        if path == DRIVER:
            # Keep the real driver's delayed-DMA HAL fixture; only replace the
            # included driver text, with its original relative include directory.
            entry_source = REAL.read_text()
            self.assertEqual(entry_source.count('#include LCD_DRIVER_SOURCE'), 1)
            source = entry_source.replace('#include LCD_DRIVER_SOURCE', source, 1)
            entry = DRIVER
        result = self.compile(entry, source)
        self.assertNotEqual(result.returncode, 0, 'incompatible fill signature was accepted')
        self.assertIn('lcd_fill', result.stderr)
        self.assertIn('conflicting types', result.stderr)

    def test_wide_colour_is_rejected(self):
        wrong = SIGNATURE.replace('uint16_t c', 'uint32_t c')
        for path in (DRIVER, UI, BROWSER, RESCUE):
            with self.subTest(adapter=path.name):
                self.assert_signature_rejected(path, wrong)

    def test_signed_coordinates_are_rejected(self):
        self.assert_signature_rejected(
            RESCUE_INPUT, 'static void lcd_fill(int x, int y, int w, int h, int c)')


if __name__ == '__main__':
    unittest.main()
