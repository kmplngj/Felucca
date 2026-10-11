#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generate an experimental pixel UI: two 1-bit faces, L shares M at 2x.

The input BDFs are unmodified Tamzen-1.11.6. Names carry Unicode while some
ENCODING values use legacy slots. Preserve each glyph's BBX, including the
8x17 lowercase cells within the nominal 8x16 face. Only the two UI marks
missing upstream (middle dot and ellipsis) are drawn here.
M8Stealth57/89 WOFF2 inputs are rasterised on their native grids; missing
Felucca characters are explicit local bitmap adaptations under CC BY-SA 3.0.
"""
import argparse
import io
import re
from pathlib import Path

from gen_aa_font import CODE, EXTRAS, L_CHARS
from aa_raster import c_array


def read_bdf(path):
    text = path.read_text()
    width, height, _, _ = map(int, re.search(r'^FONTBOUNDINGBOX (.*)$', text, re.M)[1].split())
    ascent = int(re.search(r'^FONT_ASCENT (\d+)', text, re.M)[1])
    glyphs = {}
    for block in re.findall(r'^STARTCHAR (.*?)^ENDCHAR', text, re.M | re.S):
        name = block.splitlines()[0]
        match = re.fullmatch(r'U\+([0-9a-fA-F]+)', name)
        code = int(match[1], 16) if match else int(re.search(r'^ENCODING (-?\d+)', block, re.M)[1])
        w, h, bx, bottom = map(int, re.search(r'^BBX (.*)$', block, re.M)[1].split())
        advance = int(re.search(r'^DWIDTH (\d+)', block, re.M)[1])
        rows = re.search(r'^BITMAP\n(.*)', block, re.M | re.S)[1].splitlines()
        assert len(rows) == h and advance == width, (path, name)
        pixels = [[(int(row, 16) >> (len(row) * 4 - 1 - x)) & 1 for x in range(w)] for row in rows]
        glyphs[code] = (advance, bx, ascent - bottom - h, pixels)
    # Match the period's baseline; three separated dots keep the cell advance.
    dot = glyphs[ord('.')]
    dot_y = max(y for y, row in enumerate(dot[3]) if any(row)) + dot[2]
    ellipsis = [[0] * width for _ in range(height)]
    for x in (0, width // 3, 2 * width // 3):
        ellipsis[dot_y][x] = 1
    middle = [[0] * width for _ in range(height)]
    middle[(ascent - 1) // 2][width // 2] = 1
    glyphs[0x2026] = (width, 0, 0, ellipsis)
    glyphs[0xB7] = (width, 0, 0, middle)
    return ascent, glyphs


def trimmed(glyph):
    advance, bx, by, pixels = glyph
    ink = [(x, y) for y, row in enumerate(pixels) for x, v in enumerate(row) if v]
    if not ink:
        return advance, 0, 0, 0, 0, []
    x0, y0 = min(x for x, _ in ink), min(y for _, y in ink)
    x1, y1 = max(x for x, _ in ink) + 1, max(y for _, y in ink) + 1
    bits = [v for row in pixels[y0:y1] for v in row[x0:x1]]
    return advance, bx + x0, by + y0, x1 - x0, y1 - y0, bits


def pack(bits):
    return bytes(sum(v << (7 - j) for j, v in enumerate(bits[i:i + 8])) for i in range(0, len(bits), 8))


def read_m8(path, px, cap_height):
    """Rasterise the unmodified WOFF2 at its native grid, without antialiasing.

    At 8/12 ppem the ASCII outlines reproduce m8gd's 5x7/8x9 bitmaps exactly.
    Keep the native integer advances (6/9), rather than M8's wider screen grid.
    The ten extra Felucca characters are explicit local bitmap adaptations.
    """
    from fontTools.ttLib import TTFont
    from PIL import Image, ImageDraw, ImageFont

    with TTFont(path, recalcTimestamp=False) as tt:
        tt.flavor = None
        tt.flavorData = None
        ttf = io.BytesIO()
        tt.save(ttf)
    ttf.seek(0)
    font = ImageFont.truetype(ttf, px, layout_engine=ImageFont.Layout.BASIC)
    glyphs = {}
    for code in range(32, 127):
        ch = chr(code)
        bx, by, right, bottom = font.getbbox(ch, anchor='ls')
        image = Image.new('1', (right - bx, bottom - by))
        draw = ImageDraw.Draw(image)
        draw.fontmode = '1'
        draw.text((-bx, -by), ch, font=font, anchor='ls', fill=1)
        pixels = [[int(image.getpixel((x, y)) != 0) for x in range(image.width)] for y in range(image.height)]
        advance = int(font.getlength(ch))
        assert font.getlength(ch) == advance
        glyphs[code] = (advance, bx, by + cap_height, pixels)

    advance = glyphs[ord('H')][0]
    def mark(code, rows, by, bx=0):
        glyphs[code] = (advance, bx, by, [[int(v) for v in row] for row in rows])

    # Copyright and degree are drawn at this face's grid; dots follow its period.
    if cap_height == 7:
        mark(0xA9, ('01110', '10001', '10111', '10101', '10111', '10001', '01110'), 0)
        mark(0xB0, ('010', '101', '010'), 0)
    else:
        mark(0xA9, ('00111100', '01000010', '10000001', '10011101', '10010001',
                    '10011101', '10000001', '01000010', '00111100'), 0)
        mark(0xB0, ('0110', '1001', '1001', '0110'), 0)
    _, _, dot_y, dot_w, dot_h, dot_bits = trimmed(glyphs[ord('.')])
    dot_rows = [dot_bits[y * dot_w:(y + 1) * dot_w] for y in range(dot_h)]
    middle = [[0] * advance for _ in range(dot_h)]
    for y in range(dot_h):
        middle[y][(advance - dot_w) // 2:(advance - dot_w) // 2 + dot_w] = dot_rows[y]
    glyphs[0xB7] = (advance, 0, (cap_height - dot_h) // 2, middle)
    ellipsis = [[0] * advance for _ in range(dot_h)]
    for x in (0, advance // 3, 2 * advance // 3):
        for y in range(dot_h):
            ellipsis[y][x:x + dot_w] = dot_rows[y]
    glyphs[0x2026] = (advance, 0, dot_y, ellipsis)
    for code, base in ((0xC4, 'A'), (0xD6, 'O'), (0xDC, 'U'), (0xE4, 'a'), (0xF6, 'o'), (0xFC, 'u')):
        adv, bx, by, pixels = glyphs[ord(base)]
        width = len(pixels[0])
        dots = [0] * width
        dots[1] = dots[width - 3] = 1
        glyphs[code] = (adv, bx, by - 3, [dots, [0] * width, [0] * width] + pixels)
    return cap_height, glyphs


def emit(name, ascent, glyphs, chars, height, baseline, scale, data=None, offsets=None, label=None, tracking=0):
    # The UI's baseline is the capitals' bottom, rather than the BDF's line
    # ascent. Keep native glyphs' relative placement while meeting that contract.
    cap = trimmed(glyphs[ord('H')])
    cap_bottom = cap[2] + cap[4]
    shared = data is not None
    if not shared:
        data, offsets = bytearray(), {}
    table = []
    for code in chars:
        advance, bx, by, w, h, bits = trimmed(glyphs[code])
        if not shared:
            offsets[code] = len(data)
            data += pack(bits)
        assert len(data) < 65536
        table.append((offsets[code], (advance * scale + tracking) * 16, bx * scale,
                      (by * scale + baseline - cap_bottom * scale) if w else 0, w * scale, h * scale))
    lines = []
    if not shared:
        lines.append(c_array(f'AF_{name}_DATA', 'uint8_t', list(data), 24, '0x{:02x}'))
    lines.append(f'static const aag_t AF_{name}_G[{len(table)}] = {{')
    lines += ['    {' + ', '.join(map(str, entry)) + '},' for entry in table]
    lines.append('};')
    extras = chars[1:] if name == 'L' else EXTRAS
    lines.append(c_array(f'AF_{name}_EX', 'uint8_t', [CODE.get(c, c) for c in extras]))
    last = 32 if name == 'L' else 126
    source = 'M' if shared else name
    lines.append(f'static const aafont_t AF_{name} = {{{height}, {baseline}, 32, {last}, {len(extras)}, 0, '
                 f'AF_{name}_G, AF_{source}_DATA, 0, 0, AF_{name}_EX, 0, {scale}, 0}};')
    cap = table[chars.index(ord('H'))]
    lines += [f'#define AF_{name}_CAP_Y {cap[3]}', f'#define AF_{name}_CAP_H {cap[5]}']
    cost = (0 if shared else len(data)) + len(table) * 8 + len(extras)
    label = label or f'Tamzen {"8x16 x2 (shared M)" if shared else "6x12" if name == "S" else "8x16"}'
    print(f'face {name}: {label}; '
          f'{len(chars)} glyphs, {cost} B tables')
    return '\n'.join(lines), data, offsets, cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out')
    parser.add_argument('--preset', choices=('tamzen', 'm8stealth'), default='tamzen')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'assets/fonts' / args.preset
    m8 = args.preset == 'm8stealth'
    if m8:
        small = read_m8(root / 'm8stealth57.woff2', 8, 7)
        medium = read_m8(root / 'm8stealth89.woff2', 12, 9)
        notice = 'M8Stealth by Trash80, CC BY-SA 3.0; local extra marks; see assets/fonts/m8stealth/README.md.'
    else:
        small, medium = (read_bdf(root / name) for name in ('Tamzen6x12r.bdf', 'Tamzen8x16r.bdf'))
        notice = 'Tamzen/Tamsyn; see assets/fonts/tamzen/LICENSE.'
    chars = list(range(32, 127)) + EXTRAS
    parts = [f'/* Generated by tools/gen_bitmap_font.py. {notice} */',
             '#pragma once', '#include <stdint.h>', '#define UI_FONT_BITMAP 1', f'#define UI_FONT_M8STEALTH {int(m8)}']
    s, _, _, sc = emit('S', *small, chars, 15, 12, 1, label='M8Stealth57 5x7' if m8 else None)
    m, data, offsets, mc = emit('M', *medium, chars, 19, 15, 1, label='M8Stealth89 8x9' if m8 else None)
    # Keep a 1px gap after the doubled 8px ink, so three-digit readouts stay
    # within the 51px card. Shapes remain exact 2x; only the pen stride changes.
    l, _, _, lc = emit('L', *medium, [ord(c) for c in L_CHARS], 35, 28, 2, data, offsets,
                       label='M8Stealth89 x2, 17px advance (shared M)' if m8 else None,
                       tracking=-1 if m8 else 0)
    parts += [s, m, l]
    Path(args.out).write_text('\n\n'.join(parts) + '\n')
    print(f'fonts total {sc + mc + lc} B tables + 108 B descriptors -> {args.out}')


if __name__ == '__main__':
    main()
