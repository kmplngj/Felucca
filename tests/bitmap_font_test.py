#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Reject font metrics that would narrow in the target's aag_t record."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gen_bitmap_font import emit
import font_resources as F


class FontResourceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.gen = self.root / 'build/gen'
        self.gen.mkdir(parents=True)
        for name in F.INPUTS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.header = '#define UI_FONT_M8STEALTH 1\n'
        for face in 'SMLNX':
            if face in 'SM':
                self.header += f'static const uint8_t AF_{face}_DATA[1] = {{128}};\n'
            source = face if face in 'SM' else 'M'
            self.header += (f'static const aag_t AF_{face}_G[1] = {{{{0, 16, 0, 0, 1, 1}}}};\n'
                            f'static const uint8_t AF_{face}_EX[0] = {{}};\n'
                            f'static const aafont_t AF_{face} = {{15, 12, 32, 32, 0, 0, '
                            f'AF_{face}_G, AF_{source}_DATA, 0, 0, AF_{face}_EX, 0, 1, 0}};\n'
                            f'#define AF_{face}_CAP_Y 5\n#define AF_{face}_CAP_H 7\n')
        environment = patch.dict(os.environ, FELUCCA_FONT='m8stealth')
        environment.start()
        self.addCleanup(environment.stop)
        self.manifest = F.inventory(self.root, self.header)
        self.policy = dict(schema_version=1, expected=self.manifest,
                           max_array_descriptor_bytes=self.manifest['array_descriptor_bytes'])
        self.save()

    def save(self):
        (self.root / F.POLICY).write_text(F.serialize(self.policy))
        (self.gen / 'ui_fonts.h').write_text(self.header)
        (self.gen / F.MANIFEST).write_text(F.serialize(self.manifest))

    def symbols(self):
        return ''.join(f'02000000 l O .text {size:08x} {name}\n'
                       for name, size in self.manifest['symbol_bytes'].items())

    def test_exact_contract_and_target_allocation(self):
        self.assertEqual(F.check_generated(self.root, self.gen), self.manifest)
        linked = F.linked(self.root, self.gen, self.symbols())
        self.assertEqual(linked['groups']['text_arrays_descriptors']['bytes'], 222)
        self.assertIsNone(linked['groups']['icons']['bytes'])
        self.assertEqual(self.manifest['target_abi']['descriptor_bytes'], 36)
        (self.gen / F.MANIFEST).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'stale native font manifest'):
            F.check_generated(self.root, self.gen)

    def test_extra_face_and_duplicated_scaled_payload_refused(self):
        extra = self.header + ('static const aag_t AF_Z_G[1] = {{0, 16, 0, 0, 1, 1}};\n'
                 'static const uint8_t AF_Z_EX[0] = {};\n'
                 'static const aafont_t AF_Z = {15, 12, 32, 32, 0, 0, AF_Z_G, AF_S_DATA, 0, 0, AF_Z_EX, 0, 1, 0};\n'
                 '#define AF_Z_CAP_Y 5\n#define AF_Z_CAP_H 7\n')
        with self.assertRaisesRegex(ValueError, 'face set'):
            F.checked(self.root, extra)
        duplicate = self.header + 'static const uint8_t AF_L_DATA[1] = {128};'
        with self.assertRaisesRegex(ValueError, 'share M payload'):
            F.checked(self.root, duplicate)
        redirected = self.header.replace('AF_L_G, AF_M_DATA', 'AF_L_G, AF_S_DATA')
        with self.assertRaisesRegex(ValueError, 'share M payload'):
            F.checked(self.root, redirected)

    def test_asset_growth_glyph_growth_metrics_and_stale_input_refused(self):
        changes = (self.header.replace('AF_S_DATA[1]', 'AF_S_DATA[2]'),
                   self.header.replace('AF_S_G[1]', 'AF_S_G[2]'),
                   self.header.replace('{15, 12,', '{16, 12,'))
        for header in changes:
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, 'contract changed'):
                F.checked(self.root, header)
        for name in F.INPUTS:
            path = self.root / name
            before = path.read_bytes()
            path.write_bytes(before + b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'contract changed'):
                F.checked(self.root, self.header)
            path.write_bytes(before)
        for variant in ('tamzen', 'inter-tight', ''):
            with patch.dict(os.environ, FELUCCA_FONT=variant):
                with self.assertRaisesRegex(ValueError, 'FELUCCA_FONT'):
                    F.check_generated(self.root, self.gen)

    def test_bound_still_applies_after_identity_review(self):
        self.policy['max_array_descriptor_bytes'] -= 1
        self.save()
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            F.checked(self.root, self.header)

    def test_actual_target_sizes_missing_extra_and_malformed_symbols(self):
        syms = self.symbols()
        for changed in (syms.replace('00000024 AF_S', '00000028 AF_S'),
                        syms + '02000000 l O .text 00000001 AF_Z_DATA\n',
                        syms + 'malformed AF_Z_DATA\n',
                        '\n'.join(syms.splitlines()[1:]),
                        syms + syms.splitlines()[0] + '\n',
                        syms.replace('.text', '.bss'),
                        syms.replace('00000024 AF_S', 'bad-size AF_S')):
            with self.subTest(syms=changed), self.assertRaises(ValueError):
                F.linked(self.root, self.gen, changed)


class GlyphStorageTest(unittest.TestCase):
    def generate(self, advance=1, bx=0, by=0, width=1, height=1, scale=1,
                 baseline=1, offset=None):
        glyphs = {ord('H'): (1, 0, 0, [[1]]),
                  ord('A'): (advance, bx, by, [[1] * width for _ in range(height)])}
        shared = {} if offset is None else {'data': bytearray(b'\x80'),
                                            'offsets': {ord('H'): 0, ord('A'): offset}}
        with contextlib.redirect_stdout(io.StringIO()):
            return emit('S', 1, glyphs, [ord('H'), ord('A')], 15, baseline, scale, **shared)

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


if __name__ == '__main__':
    unittest.main()
