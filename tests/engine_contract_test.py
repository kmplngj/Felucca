#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile the real firmware core against compatible and incompatible portable headers."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FirmwareEngineContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'firmware/src').mkdir(parents=True)
        (self.root / 'firmware/engines/src').mkdir(parents=True)
        for name in ('core.h', 'boot_policy.h'):
            shutil.copyfile(ROOT / 'firmware/src' / name, self.root / 'firmware/src' / name)
        self.header = self.root / 'firmware/engines/src/felucca_engine.h'
        self.header.write_bytes((ROOT / 'firmware/engines/src/felucca_engine.h').read_bytes())
        self.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not self.cc or shutil.which(self.cc[0]) is None:
            self.fail('configured host C compiler unavailable')

    def compile(self, *flags, fs=44100):
        return subprocess.run([*self.cc, '-std=c99', '-fsyntax-only', '-x', 'c',
                               '-I', str(self.root / 'firmware/src'), '-I', str(ROOT / 'build/gen'), *flags, '-'],
                              input=(f'#define FS {fs}\n#define CTL 32\n'
                                     '#define __attribute__(x) /* target section placement, as in hostsim.c */\n'
                                     '#include "core.h"\nint main(void) { return 0; }\n'),
                              text=True, capture_output=True)

    def test_supported_real_firmware_host(self):
        result = self.compile()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_library_rates_do_not_enable_unsupported_firmware_rates(self):
        for fs in (32000, 48000, 96000, 192000):
            with self.subTest(fs=fs):
                result = self.compile(fs=fs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Felucca firmware requires FS 44100', result.stderr)

    def test_incompatible_host_requirement_is_rejected(self):
        result = self.compile('-DFELUCCA_ENGINE_API_REQUIRED=2')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Felucca-Engines', result.stderr)

    def test_future_library_version_is_rejected(self):
        text, count = re.subn(r'^(#define FELUCCA_ENGINE_API_VERSION)\s+[^\n]+', r'\1 2u',
                             self.header.read_text(), flags=re.M)
        self.assertEqual(count, 1, 'contract version must be declared explicitly')
        self.header.write_text(text)
        result = self.compile()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Felucca', result.stderr)

    def test_unversioned_library_is_rejected_by_firmware(self):
        text, count = re.subn(r'^#define FELUCCA_ENGINE_API_VERSION[^\n]*\n', '',
                             self.header.read_text(), flags=re.M)
        self.assertEqual(count, 1)
        self.header.write_text(text)
        result = self.compile()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('matching, versioned Felucca-Engines API', result.stderr)


if __name__ == '__main__':
    unittest.main()
