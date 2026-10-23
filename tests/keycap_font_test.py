#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Check packed keycap ink against m8gd's independent native bitmap atlas."""
import hashlib
import math
import re
import sys
from pathlib import Path

from PIL import Image


# Wire-independent UI IDs nevertheless keep their established order and labels.
LABELS = [('PRESETS', 'PRESETS'), ('SELECT', 'SELECT'), ('ALGO', 'ALGO'),
          ('OCTDN', 'OCT-'), ('OCTUP', 'OCT+'), ('PLAY', 'PLAY'), ('REC', 'REC'),
          ('SAVE', 'SAVE'), ('EDIT', 'EDIT'), ('SEQ', 'SEQ'), ('GLO', 'GLO'),
          ('HOME', 'HOME'), ('ARP', 'ARP'), ('KEYS', 'KEYS'), ('K1', 'K1'),
          ('K2', 'K2'), ('K3', 'K3'), ('K4', 'K4'), ('MUTE', 'MUTE'),
          ('ARM', 'ARM'), ('HOLD', 'HOLD'), ('ON', 'ON'), ('OFF', 'OFF'),
          ('FX', 'FX'), ('K14', 'K1-4'), ('SCL', 'SCL'), ('OCTPM', 'OCT-/+'),
          ('LFO', 'LFO'), ('ENV', 'ENV')]

# Before #248: exact packed masks and angle bytes, unrelated to label changes.
KNOB_SHA256 = {
    'BIG_COV': '1d239508bbb77607a96e4b0a374348ff5fc13bf48c4b02053ab8795bc49c0aea',
    'BIG_ANG': 'fea9d784e5388c3824047394402c670d43e71980a86c29d6edd7f74bb945ca8a',
    'SMALL_COV': 'bcb2c13d47ff54f5d0a1d873436c42798e4e011d0983e153706cf637acd3d5a7',
    'SMALL_ANG': '091c24c9c9814959c9a2615e9f26419c5730872a7d8820813bc18068f19b2539',
}


def array(source, name):
    body = re.search(r'\b' + name + r'\[[^]]*\]\s*=\s*\{(.*?)\};', source, re.S)[1]
    return bytes(int(v, 0) for v in re.findall(r'0x[0-9a-f]+|\d+', body))


def main():
    header = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/gen/ui_keycaps.h')
    source = header.read_text()
    assert re.search(r'#define KC_H 13\b', source)
    ids = re.findall(r'^\s+KC_(\w+),\s*/\* (.*?) \*/', source, re.M)
    assert ids == LABELS, 'keycap IDs, order or labels changed'
    entries = [(int(o), int(w), label) for o, w, label in
               re.findall(r'\{(\d+), (\d+), "([^"]+)"\}', source)]
    assert [label for _, _, label in entries] == [label for _, label in LABELS]
    data = array(source, 'KC_DATA')
    root = Path(__file__).resolve().parents[1]
    atlas = Image.open(root / 'assets/fonts/m8stealth/5_7.bmp').convert('L')
    end = 0
    for offset, width, label in entries:
        assert offset == end, (label, 'noncontiguous packed data')
        size = math.ceil(width * 13 / 2)
        packed = data[offset:offset + size]
        assert len(packed) == size
        pixels = [v for byte in packed for v in (byte >> 4, byte & 15)]
        if width * 13 % 2:
            assert pixels[-1] == 0, (label, 'nonzero packing pad')
        pixels = pixels[:width * 13]
        assert not set(pixels) & set(range(6, 15)), (label, 'antialiased label ink')
        expected = set()
        for i, ch in enumerate(label):
            code = ord(ch)
            for y in range(7):
                for x in range(5):
                    if atlas.getpixel(((code % 16) * 5 + x, (code // 16) * 7 + y)) >= 128:
                        expected.add((i * 6 + x, y + 3))
        left, right = min(x for x, _ in expected), max(x for x, _ in expected)
        expected = {(x - left + 3, y) for x, y in expected}
        actual = {(i % width, i // width) for i, value in enumerate(pixels) if value == 15}
        assert actual == expected, (label, 'native M8 ink differs')
        assert width == right - left + 7, (label, 'three-pixel side padding')
        assert min(y for _, y in actual) == 3 and max(y for _, y in actual) == 9
        # Independently recover the 4x4 subpixel rounded-rectangle coverage.
        for y in range(13):
            for x in range(width):
                coverage = 0
                for sy in (0.125, 0.375, 0.625, 0.875):
                    for sx in (0.125, 0.375, 0.625, 0.875):
                        px, py = x + sx, y + sy
                        dx = max(4 - px, 0, px - (width - 4))
                        dy = max(4 - py, 0, py - 9)
                        coverage += dx * dx + dy * dy <= 16
                expected_nibble = min(4, round(coverage * 5 / 16)) if coverage < 16 else 5
                value = pixels[y * width + x]
                assert value == (15 if (x, y) in expected else expected_nibble), (label, x, y, value)
                if (x, y) in expected:
                    assert coverage == 16, (label, 'ink intersects pill edge')
        end += size
    assert end == len(data), 'unused or missing keycap data'
    for name, digest in KNOB_SHA256.items():
        assert hashlib.sha256(array(source, 'KNOB_' + name)).hexdigest() == digest, name
    print(f'Keycaps: {len(entries)} fixed labels match native M8 atlas; 3px padding, '
          '13px pills/radius 4, nibble packing and all knob bytes preserved')


if __name__ == '__main__':
    main()
