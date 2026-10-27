#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile actual LCD adapters and reject incompatible fill/blit definitions."""
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
BLIT_NOOPS = tuple(ROOT / f'tests/{name}_test.c' for name in (
    'backup', 'editor', 'engid', 'fm6_eff', 'fm6bank', 'icon_stream',
    'persistence', 'settings', 'text_ref', 'theme', 'track_badge'))
BLIT_ADAPTERS = (DRIVER, UI, BROWSER, *BLIT_NOOPS)
SIGNATURE = 'static void lcd_fill(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t c)'


class FirmwareLcdContract(unittest.TestCase):
    def setUp(self):
        self.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not self.cc or shutil.which(self.cc[0]) is None:
            self.fail('configured host C compiler unavailable')

    def compile(self, path, source=None, defines=()):
        return subprocess.run([*self.cc, '-w', '-fsyntax-only', '-x', 'c', *defines,
                               '-I', str(ROOT / 'firmware/src'), '-I', str(ROOT / 'build/gen'),
                               '-I', str(ROOT / 'build/host'),
                               '-iquote', str(path.parent),
                               str(path) if source is None else '-'],
                              input=source, cwd=ROOT, text=True, capture_output=True)

    def test_actual_adapters(self):
        for path in (REAL, ROOT / 'tests/screen_capture_test.c', ROOT / 'tests/ui_test.c',
                     ROOT / 'web/emu/native_check.c', RESCUE, RESCUE_INPUT):
            with self.subTest(adapter=path.name):
                result = self.compile(path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_blit_noop_adapters(self):
        for path in BLIT_NOOPS:
            with self.subTest(adapter=path.name):
                result = self.compile(path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_cpu2_off_blit_adapters(self):
        entries = {DRIVER: REAL, UI: ROOT / 'tests/ui_test.c',
                   BROWSER: ROOT / 'web/emu/native_check.c'}
        for path in BLIT_ADAPTERS:
            with self.subTest(adapter=path.name):
                result = self.compile(entries.get(path, path), defines=('-DFELUCCA_CPU2=0',))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_mutable_blit_sources_are_rejected(self):
        for path in BLIT_ADAPTERS:
            with self.subTest(adapter=path.name):
                entry = REAL if path == DRIVER else path
                result = self.compile(entry)
                self.assertEqual(result.returncode, 0, result.stderr)
                source = path.read_text()
                pixels = 'px' if path == DRIVER else 'p'
                signature = ('static void lcd_blit(uint32_t x, uint32_t y, '
                             'uint32_t w, uint32_t h, const uint16_t *' + pixels + ')')
                declaration = 'static lcd_blit_fn lcd_blit;'
                self.assertEqual(source.count(signature), 1, 'expected one actual blit definition')
                self.assertEqual(source.count(declaration), 1, 'expected one typed declaration')
                source = source.replace(signature, signature.replace('const uint16_t *', 'uint16_t *'), 1)
                control = source.replace(declaration, '', 1)
                if path == DRIVER:
                    # Both probes retain the real delayed-DMA HAL and original
                    # driver include directory. Only the typed declaration differs.
                    wrapper = REAL.read_text()
                    self.assertEqual(wrapper.count('#include LCD_DRIVER_SOURCE'), 1)
                    source = wrapper.replace('#include LCD_DRIVER_SOURCE', source, 1)
                    control = wrapper.replace('#include LCD_DRIVER_SOURCE', control, 1)
                    entry = DRIVER
                result = self.compile(entry, source)
                self.assertNotEqual(result.returncode, 0, 'mutable blit source signature was accepted')
                self.assertIn('lcd_blit', result.stderr)
                self.assertIn('conflicting types', result.stderr)
                result = self.compile(entry, control)
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
