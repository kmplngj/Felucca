#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile actual flash data adapters and reject incompatible definitions/calls."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / 'firmware/hal/fm1_flash.h'
RESCUE = ROOT / 'tests/rescue_test.c'
PARTIAL = tuple(ROOT / 'tests' / name for name in
                ('editor_test.c', 'fm6_eff_test.c', 'engid_test.c'))
RAM_NAMES = ('fl_erase4k_ram', 'fl_prog_ram', 'fl_read_ram')
WRAPPER_NAMES = ('fl_erase4k', 'fl_write')


def far_probe():
    # &* normalizes the rescue function designator and HAL function pointer.
    # These assertions stay in the compile fixture; firmware gains no code/data.
    return ''.join(
        '\ntypedef char flash_data_far_signature_' + name + '[\n'
        '    __builtin_types_compatible_p(__typeof__(&*FL_FAR(' + name + ')),\n'
        '                                 ' + name + '_fn *) ? 1 : -1];\n'
        for name in RAM_NAMES)


class FirmwareFlashDataContract(unittest.TestCase):
    def setUp(self):
        self.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not self.cc or shutil.which(self.cc[0]) is None:
            self.fail('configured host C compiler unavailable')

    def compile(self, path, source=None):
        return subprocess.run([*self.cc, '-w', '-fsyntax-only', '-x', 'c',
                               '-I', str(ROOT / 'firmware/src'), '-I', str(ROOT / 'build/gen'),
                               '-iquote', str(path.parent), str(path) if source is None else '-'],
                              input=source, cwd=ROOT, text=True, capture_output=True)

    def test_actual_adapters(self):
        for path in (HAL, RESCUE, *PARTIAL):
            with self.subTest(adapter=path.relative_to(ROOT)):
                result = self.compile(path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def assert_signature_rejected(self, path, name, signature, wrong_signature):
        # The actual-source control rules out missing generated prerequisites.
        result = self.compile(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = path.read_text()
        self.assertEqual(source.count(signature), 1, 'expected one actual data definition')
        source = source.replace(signature, wrong_signature, 1)
        result = self.compile(path, source)
        self.assertNotEqual(result.returncode, 0, 'incompatible data signature was accepted')
        self.assertIn(name, result.stderr)
        self.assertIn('conflicting types', result.stderr)

        # Remove only the typed declaration: the same mutated implementation
        # must compile, so unrelated body/call errors cannot establish rejection.
        declaration = 'static ' + name + '_fn ' + name + ';\n'
        self.assertEqual(source.count(declaration), 1, 'expected one typed declaration')
        result = self.compile(path, source.replace(declaration, '', 1))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_return_types_are_rejected(self):
        for path in (HAL, RESCUE, *PARTIAL):
            names = (*RAM_NAMES, *WRAPPER_NAMES) if path in (HAL, RESCUE) else WRAPPER_NAMES
            for name in names:
                with self.subTest(adapter=path.relative_to(ROOT), function=name):
                    self.assert_signature_rejected(path, name, 'int ' + name + '(',
                                                   'int64_t ' + name + '(')

    def test_original_void_buffer_signatures_are_rejected(self):
        cases = [
            (RESCUE, 'fl_prog_ram', 'const uint8_t *p', 'const void *p'),
            (RESCUE, 'fl_read_ram', 'uint8_t *p', 'void *p'),
            (RESCUE, 'fl_write', 'const uint8_t *p', 'const void *p'),
            *((path, 'fl_write', 'const uint8_t *p', 'const void *p') for path in PARTIAL),
        ]
        for path, name, buffer, wrong_buffer in cases:
            with self.subTest(adapter=path.relative_to(ROOT), function=name):
                signature = 'int ' + name + '(uint32_t off, ' + buffer + ', uint32_t n'
                wrong = signature.replace(buffer, wrong_buffer, 1)
                self.assert_signature_rejected(path, name, signature, wrong)

    def test_far_macro_preserves_ram_function_types(self):
        for path in (HAL, RESCUE):
            with self.subTest(adapter=path.relative_to(ROOT)):
                source = path.read_text()
                probe = far_probe()
                result = self.compile(path, source + probe)
                self.assertEqual(result.returncode, 0, result.stderr)
                macros = [line for line in source.splitlines() if line.startswith('#define FL_FAR(')]
                self.assertEqual(len(macros), 1, 'expected one actual far-call macro')
                # The callable cast still accepts actual call sites. Only the
                # added function-type assertions should reject its wrong result.
                source = source.replace(macros[0], '#define FL_FAR(fn) ((int64_t (*)())(fn))', 1)
                result = self.compile(path, source)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.compile(path, source + probe)
                self.assertNotEqual(result.returncode, 0, 'incompatible far-call type was accepted')
                for name in RAM_NAMES:
                    self.assertIn('flash_data_far_signature_' + name, result.stderr)


if __name__ == '__main__':
    unittest.main()
