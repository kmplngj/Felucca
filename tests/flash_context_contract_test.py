#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile actual flash contexts and reject incompatible definitions/call types."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / 'firmware/hal/fm1_flash.h'
HOST = ROOT / 'tests/host_flash_context.h'
RESCUE = ROOT / 'tests/rescue_test.c'
SIGNATURES = (
    ('irq_save', 'uint32_t irq_save(void)', 'uint64_t irq_save(void)'),
    ('irq_restore', 'void irq_restore(uint32_t f)', 'void irq_restore(int32_t f)'),
    ('fl_jedec_ram', 'uint32_t fl_jedec_ram(void)', 'uint64_t fl_jedec_ram(void)'),
    ('fl_plain_window_init', 'void fl_plain_window_init(void)',
     'void fl_plain_window_init(uint32_t unused)'),
)


def far_probe(names):
    # &* normalizes the host's function designator and HAL's function pointer.
    # Keep this in the compiler fixture: no code or data is added to firmware.
    return ''.join(
        '\ntypedef char flash_far_signature_' + name + '[\n'
        '    __builtin_types_compatible_p(__typeof__(&*FL_FAR(' + name + ')),\n'
        '                                 ' + name + '_fn *) ? 1 : -1];\n'
        for name in names)


class FirmwareFlashContextContract(unittest.TestCase):
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
        for path in (HAL, ROOT / 'tests/backup_test.c', ROOT / 'tests/fm6bank_test.c',
                     ROOT / 'tests/persistence_test.c', ROOT / 'web/emu/native_check.c', RESCUE):
            with self.subTest(adapter=path.relative_to(ROOT)):
                result = self.compile(path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_host_context_variants(self):
        for jedec in ('0u', '0x856014u'):
            with self.subTest(jedec=jedec):
                result = self.compile(HOST, '#define HOST_FLASH_JEDEC ' + jedec + '\n' +
                                      HOST.read_text())
                self.assertEqual(result.returncode, 0, result.stderr)

    def assert_signature_rejected(self, path, name, signature, wrong_signature):
        # A successful actual-source control rules out missing build prerequisites.
        result = self.compile(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = path.read_text()
        self.assertEqual(source.count(signature), 1, 'expected one actual context definition')
        source = source.replace(signature, wrong_signature, 1)
        result = self.compile(path, source)
        self.assertNotEqual(result.returncode, 0, 'incompatible context signature was accepted')
        self.assertIn(name, result.stderr)
        self.assertIn('conflicting types', result.stderr)

    def test_wrong_hal_and_shared_signatures_are_rejected(self):
        for path in (HAL, HOST):
            for name, signature, wrong in SIGNATURES:
                with self.subTest(adapter=path.relative_to(ROOT), function=name):
                    self.assert_signature_rejected(path, name, signature, wrong)

    def test_wrong_dynamic_rescue_jedec_signature_is_rejected(self):
        self.assert_signature_rejected(RESCUE, *SIGNATURES[2])

    def test_far_macro_preserves_function_types(self):
        for path in (HAL, HOST, RESCUE):
            with self.subTest(adapter=path.relative_to(ROOT)):
                names = ('fl_jedec_ram',) if path == RESCUE else ('fl_jedec_ram', 'irq_restore')
                source = path.read_text()
                probe = far_probe(names)
                result = self.compile(path, source + probe)
                self.assertEqual(result.returncode, 0, result.stderr)
                macros = [line for line in source.splitlines() if line.startswith('#define FL_FAR(')]
                self.assertEqual(len(macros), 1, 'expected one actual far-call macro')
                # This callable cast accepts the existing call sites, so their
                # argument errors cannot masquerade as a failed type assertion.
                source = source.replace(macros[0], '#define FL_FAR(fn) ((uint64_t (*)())(fn))', 1)
                result = self.compile(path, source)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.compile(path, source + probe)
                self.assertNotEqual(result.returncode, 0, 'incompatible far-call type was accepted')
                self.assertIn('flash_far_signature_fl_jedec_ram', result.stderr)


if __name__ == '__main__':
    unittest.main()
