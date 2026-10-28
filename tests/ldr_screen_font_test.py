#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Loader glyphs must equal the native M8 source, with no missing UI copy."""
import re
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gen_bitmap_font import read_m8


class LoaderFont(unittest.TestCase):
    def test_native_source_and_complete_copy(self):
        header = (ROOT / 'firmware/loader/ldr_font.h').read_text()
        chars = re.search(r'LDR_CH\[\] = "([^"]+)"', header)[1]
        for face, px, cap, source in (('S', 8, 7, 'm8stealth57.woff2'), ('M', 12, 9, 'm8stealth89.woff2')):
            _, glyphs = read_m8(ROOT / 'assets/fonts/m8stealth' / source, px, cap)
            block = header.split(f'LDR_FONT_{face}')[1].split('};')[0]
            rows = re.findall(r'\{([^{}]+)\}, /\* (.) \*/', block)
            self.assertEqual(len(rows), len(chars))
            for (values, ch), expected_ch in zip(rows, chars):
                self.assertEqual(ch, expected_ch)
                actual = [int(v, 16) for v in values.split(',')]
                _, bx, by, pixels = glyphs[ord(ch)]
                expected = [0] * cap
                for y, row in enumerate(pixels):
                    for x, value in enumerate(row):
                        if value:
                            self.assertTrue(0 <= by + y < cap and 0 <= bx + x < 8)
                            expected[by + y] |= 1 << (7 - bx - x)
                self.assertEqual(actual, expected, (face, ch))
        screen = (ROOT / 'firmware/loader/ldr_screen.c').read_text()
        for copy in re.findall(r'"([A-Z][A-Z %\-]+)"', screen):
            self.assertFalse(set(copy) - set(chars + ' '), copy)
            self.assertLessEqual(len(copy) * 9, 240, copy)


if __name__ == '__main__':
    unittest.main()
