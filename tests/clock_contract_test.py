#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Check actual TIMER4/passive adapters and their existing scheduling policies."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / 'firmware/hal/fm1_time.h'
CLOCK = ROOT / 'tests/host_clock.h'


class ClockContractTests(unittest.TestCase):
    def setUp(self):
        self.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not self.cc or shutil.which(self.cc[0]) is None:
            self.fail('configured host C compiler unavailable')
        self.includes = ['-I', str(ROOT / 'build/gen'), '-I', str(ROOT / 'firmware/src')]

    def syntax(self, path, source=None):
        return subprocess.run([*self.cc, '-w', '-fsyntax-only', '-x', 'c', *self.includes,
                               '-iquote', str(path.parent), str(path) if source is None else '-'],
                              input=source, cwd=ROOT, text=True, capture_output=True)

    def test_actual_adapters_compile(self):
        # Includes the real HAL without executing its MMIO, then each passive
        # consumer through its normal translation-unit entry point.
        for path in (ROOT / 'tests/input_test.c', ROOT / 'tests/ui_test.c',
                     ROOT / 'web/emu/native_check.c'):
            with self.subTest(adapter=path.relative_to(ROOT)):
                result = self.syntax(path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_incompatible_definitions_require_the_contract(self):
        declaration = 'static fm1_ticks_fn fm1_ticks;'
        for path, signature in ((HAL, 'static inline uint32_t fm1_ticks(void)'),
                                (CLOCK, 'static uint32_t fm1_ticks(void)')):
            source = path.read_text()
            if path == CLOCK:
                source = '#include <stdint.h>\nstatic uint32_t clock_ticks;\n#define HOST_CLOCK_TICKS clock_ticks\n' + source
            positive = self.syntax(path, source)
            self.assertEqual(positive.returncode, 0, positive.stderr)
            self.assertEqual(source.count(signature), 1)
            self.assertEqual(source.count(declaration), 1)
            for wrong in (signature.replace('uint32_t', 'int32_t', 1),
                          signature.replace('(void)', '(uint32_t ignored)')):
                with self.subTest(adapter=path.name, signature=wrong):
                    mutated = source.replace(signature, wrong, 1)
                    rejected = self.syntax(path, mutated)
                    self.assertNotEqual(rejected.returncode, 0, 'incompatible clock accepted')
                    self.assertIn('fm1_ticks', rejected.stderr)
                    self.assertIn('conflicting types', rejected.stderr)
                    # Same wrong body compiles after removing only the typed
                    # declaration: unrelated missing inputs cannot pass this test.
                    control = self.syntax(path, mutated.replace(declaration, '', 1))
                    self.assertEqual(control.returncode, 0, control.stderr)

    def run_adapter(self, relative, body):
        source = ('#include <stdint.h>\n#include <stdio.h>\n'
                  f'#include "{ROOT / relative}"\n'
                  '#define REQUIRE(ok) do { if (!(ok)) { fprintf(stderr, "clock line %u: %s\\n", '
                  '__LINE__, #ok); return 1; } } while (0)\n'
                  'int main(void) {\n' + body + '\nreturn 0;\n}\n')
        out = ROOT / 'build/host'
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='clock-contract-', dir=out) as temporary:
            binary = Path(temporary) / 'clock'
            result = subprocess.run([*self.cc, '-O2', '-ffp-contract=off', '-w', '-x', 'c',
                                     *self.includes, '-', '-lm', '-o', str(binary)],
                                    input=source, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], cwd=ROOT, text=True,
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ui_entrypoints_keep_caller_driven_time(self):
        self.run_adapter('tests/ui_harness.h', '''
    uint32_t first, second;
    REQUIRE(FM1_TICKS_PER_US == 1u && host_ticks == 0u && fm1_ms == 0u);
    first = fm1_ticks();
    second = fm1_ticks();
    REQUIRE(first == 0u && second == first && fm1_ms == 0u);
    host_ticks = UINT32_MAX - 8000u;
    fm1_ms = UINT32_MAX - 8u;
    ui_power_on();
    REQUIRE(host_ticks == UINT32_MAX - 8000u && fm1_ms == UINT32_MAX - 8u);
    first = fm1_ticks();
    frame();
    second = fm1_ticks();
    REQUIRE(second < first && (uint32_t)(second - first) == 16000u && fm1_ms == 7u);
    first = fm1_ticks();
    turn(EN_K1, 1);
    second = fm1_ticks();
    REQUIRE((uint32_t)(second - first) == 216000u && fm1_ms == 23u);
    first = fm1_ticks();
    second = fm1_ticks();
    REQUIRE(first == second && fm1_ms == 23u);
    ui_power_on();
    REQUIRE(host_ticks == second && fm1_ms == 23u);
''')

    def test_browser_entrypoints_keep_audio_driven_time(self):
        self.run_adapter('web/emu/felucca_web.c', '''
    uint32_t first, second;
    REQUIRE(FM1_TICKS_PER_US == 24u && web_ticks == 0u && fm1_ms == 0u);
    first = fm1_ticks();
    second = fm1_ticks();
    REQUIRE(first == 0u && second == first && fm1_ms == 0u);
    web_nor_erase();
    web_boot();
    REQUIRE(web_ticks == 0u && fm1_ms == 0u);
    web_render(0);
    REQUIRE(web_ticks == 0u && fm1_ms == 0u && ring_w == 0u && ring_r == 0u);
    web_render(128);
    REQUIRE(web_ticks == 72000u && fm1_ms == 3u && ring_w == 128u && ring_r == 128u);
    first = fm1_ticks();
    second = fm1_ticks();
    REQUIRE(first == 72000u && second == first && fm1_ms == 3u);
    web_ticks = UINT32_MAX - 12000u;
    fm1_ms = UINT32_MAX;
    web_boot_ticks = web_ticks;
    first = fm1_ticks();
    web_ms();
    second = fm1_ticks();
    REQUIRE(second == 11999u && (uint32_t)(second - first) == 24000u && fm1_ms == 0u);
    web_boot();
    REQUIRE(web_ticks == second && fm1_ms == 0u);
''')


if __name__ == '__main__':
    unittest.main()
