#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Pin generated M8Stealth ASCII ink to the independent upstream bitmap atlases."""
import sys
from pathlib import Path

from PIL import Image
from text_spacing_test import bitmap, glyph_at, parse


def main():
    header = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/gen/ui_fonts.h')
    if '#define UI_FONT_M8STEALTH 1' not in header.read_text():
        print('M8Stealth source bitmap check: not this font variant')
        return
    root = Path(__file__).resolve().parents[1] / 'assets/fonts/m8stealth'
    faces = parse(header)
    checked = 0
    for name, source, width, height in (('S', '5_7.bmp', 5, 7), ('M', '8_9.bmp', 8, 9),
                                        ('L', '8_9.bmp', 8, 9)):
        f = faces[name]
        scale = f['scale']
        cap_y = f['g'][glyph_at(f, ord('H'))][3]
        atlas = Image.open(root / source).convert('L')
        for code in range(32, 127):
            index = glyph_at(f, code)
            if index is None:
                continue
            g = f['g'][index]
            pixels = bitmap(f, g)
            actual = Image.new('1', (width * scale, height * scale))
            for y in range(g[5]):
                for x in range(g[4]):
                    if pixels[y * g[4] + x]:
                        actual.putpixel((g[2] + x, g[3] - cap_y + y), 1)
            box = ((code % 16) * width, (code // 16) * height,
                   (code % 16 + 1) * width, (code // 16 + 1) * height)
            expected = atlas.crop(box).point(lambda p: int(p >= 128), mode='1')
            expected = expected.resize(actual.size, Image.Resampling.NEAREST)
            assert actual.tobytes() == expected.tobytes(), (name, chr(code))
            checked += 1
        if name != 'L':
            for code in (0xA9, 0xB0, 0xB7, 0xC4, 0xD6, 0xDC, 0xE4, 0xF6, 0xFC, 0x85):
                index = glyph_at(f, code)
                assert index is not None, (name, hex(code))
                g = f['g'][index]
                assert any(bitmap(f, g)) and 0 <= g[3] <= g[3] + g[5] <= f['h']
    assert faces['L']['data'] == faces['M']['data']
    print(f'M8Stealth: {checked} glyphs match upstream ASCII bitmaps at 1x/2x; all extra marks fit; L shares M')


if __name__ == '__main__':
    main()
