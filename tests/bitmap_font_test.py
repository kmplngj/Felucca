#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Reject font metrics that would narrow in the target's aag_t record."""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gen_bitmap_font import emit


class GlyphStorageTest(unittest.TestCase):
    def generate(self, advance=1, bx=0, by=0, width=1, height=1, scale=1,
                 baseline=1, offset=None, compact=False):
        glyphs = {ord('H'): (1, 0, 0, [[1]]),
                  ord('A'): (advance, bx, by, [[1] * width for _ in range(height)])}
        shared = {} if offset is None else {'data': bytearray(b'\x80'),
                                            'offsets': {ord('H'): 0, ord('A'): offset}}
        with contextlib.redirect_stdout(io.StringIO()):
            return emit('S', 1, glyphs, [ord('H'), ord('A')], 15, baseline, scale, compact=compact, **shared)

    def test_metric_overflow_is_rejected(self):
        cases = (('bx', {'bx': -129}), ('bx', {'bx': 128}),
                 ('bx', {'bx': 64, 'scale': 2, 'baseline': 2}),
                 ('by', {'by': -1}), ('by', {'by': 256}),
                 ('bw', {'width': 128, 'scale': 2, 'baseline': 2}),
                 ('bh', {'height': 128, 'scale': 2, 'baseline': 256}),
                 ('adv', {'advance': -1}), ('adv', {'advance': 4096}),
                 ('off', {'offset': -1}), ('off', {'offset': 65536}))
        for field, kwargs in cases:
            with self.subTest(field=field, kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, field + r'=.* outside'):
                    self.generate(**kwargs)

    def test_representable_edges_are_kept(self):
        for kwargs in ({'bx': -128}, {'bx': 127}, {'by': 255},
                       {'width': 255}, {'height': 255, 'baseline': 255},
                       {'advance': 4095}, {'offset': 65535}):
            with self.subTest(kwargs=kwargs):
                self.generate(**kwargs)

    def test_compact_requires_positive_constant_bitmap_advance(self):
        for kwargs in ({'advance': 2}, {'advance': 0}, {'scale': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'compact metadata requires'):
                self.generate(compact=True, **kwargs)
        self.generate(compact=True)
        glyphs = {ord('H'): (0, 0, 0, [[1]])}
        with self.assertRaisesRegex(ValueError, 'compact metadata requires'):
            emit('S', 1, glyphs, [ord('H')], 15, 1, 1, compact=True)

    def test_compact_keeps_full_offset_and_signed_bearing_ranges(self):
        for kwargs in ({'bx': -128}, {'bx': 127}, {'offset': 65535}):
            with self.subTest(kwargs=kwargs):
                self.generate(compact=True, **kwargs)


if __name__ == '__main__':
    unittest.main()
