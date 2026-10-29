#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generate native M8Stealth UI bitmaps; large roles share the existing ink.
WOFF2 inputs are rasterised on their native grids. The extra Felucca characters
are explicit local bitmap adaptations under CC BY-SA 3.0.
"""
import argparse
import io
from pathlib import Path

from ui_font_data import CODE, EXTRAS, L_CHARS
from aa_raster import c_array


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


def emit(name, ascent, glyphs, chars, height, baseline, scale, data=None, offsets=None, label=None, tracking=0,
         compact=False):
    # The UI's baseline is the capitals' bottom, rather than the font's line
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
        pen = advance * scale + tracking
        if name in ('L', 'X') and code == ord('.'):
            # Large numerals: the point takes its ink and one source pixel each side, not a digit's cell
            # ("1.18", not "1. 18"). Digits stay tabular.
            pen = (bx + w + 1) * scale
        entry = (offsets[code], pen * 16, bx * scale,
                 (by * scale + baseline - cap_bottom * scale) if w else 0, w * scale, h * scale)
        # aag_t stores off/adv as uint16_t, bx as int8_t and by/bw/bh as uint8_t.
        # Reject narrowing even when Python runs with assertions disabled.
        for field, value, low, high in zip(('off', 'adv', 'bx', 'by', 'bw', 'bh'), entry,
                                          (0, 0, -128, 0, 0, 0), (65535, 65535, 127, 255, 255, 255)):
            if not low <= value <= high:
                raise ValueError(f'face {name}, glyph U+{code:04X}: {field}={value} outside {low}..{high}')
        if len(data) > 65535:
            raise ValueError(f'face {name}: bitmap data exceeds 65535 bytes')
        table.append(entry)
    fixed_adv = table[0][1] if compact else 0
    if compact and (not scale or not fixed_adv or any(e[1] != fixed_adv for e in table)):
        raise ValueError(f'face {name}: compact metadata requires a positive constant advance and bitmap scale')
    lines = []
    if not shared:
        lines.append(c_array(f'AF_{name}_DATA', 'uint8_t', list(data), 24, '0x{:02x}'))
    record_type = 'aag_fixed_t' if compact else 'aag_t'
    lines.append(f'static const {record_type} AF_{name}_G[{len(table)}] = {{')
    entries = [(e[0], *e[2:]) for e in table] if compact else table
    lines += ['    {' + ', '.join(map(str, entry)) + '},' for entry in entries]
    lines.append('};')
    sparse = name in ('L', 'X')                      # numeral roles: L_CHARS only
    extras = chars[1:] if sparse else EXTRAS
    lines.append(c_array(f'AF_{name}_EX', 'uint8_t', [CODE.get(c, c) for c in extras]))
    last = 32 if sparse else 126
    source = 'M' if shared else name
    lines.append(f'static const aafont_t AF_{name} = {{{height}, {baseline}, 32, {last}, {len(extras)}, 0, '
                 f'AF_{name}_G, AF_{source}_DATA, 0, 0, AF_{name}_EX, 0, {scale}, {fixed_adv}, 0}};')
    cap = table[chars.index(ord('H'))]
    lines += [f'#define AF_{name}_CAP_Y {cap[3]}', f'#define AF_{name}_CAP_H {cap[5]}']
    cost = (0 if shared else len(data)) + len(table) * (6 if compact else 8) + len(extras)
    label = label or f"M8Stealth {name}"
    print(f'face {name}: {label}; '
          f'{len(chars)} glyphs, {cost} B tables')
    return '\n'.join(lines), data, offsets, cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out')
    parser.add_argument('--preset', choices=('m8stealth',), default='m8stealth')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'assets/fonts' / args.preset
    small = read_m8(root / 'm8stealth57.woff2', 8, 7)
    medium = read_m8(root / 'm8stealth89.woff2', 12, 9)
    notice = 'M8Stealth by Trash80, CC BY-SA 3.0; local extra marks; see assets/fonts/m8stealth/README.md.'
    chars = list(range(32, 127)) + EXTRAS
    parts = [f'/* Generated by tools/gen_bitmap_font.py. {notice} */',
             '#pragma once', '#include <stdint.h>', '#define UI_FONT_BITMAP 1', '#define UI_FONT_M8STEALTH 1',
             '#define UI_FONT_HUFFMAN_BOOKS 0']
    s, _, _, sc = emit('S', *small, chars, 15, 12, 1, label='M8Stealth57 5x7', compact=True)
    m, data, offsets, mc = emit('M', *medium, chars, 19, 15, 1, label='M8Stealth89 8x9', compact=True)
    # Keep a 1px gap after the doubled 8px ink, so three-digit readouts stay
    # within the 51px card. Shapes remain exact 2x; only the pen stride changes.
    l, _, _, lc = emit('L', *medium, [ord(c) for c in L_CHARS], 35, 28, 2, data, offsets,
                       label='M8Stealth89 x2, 17px advance (shared M)',
                       tracking=-1)
    # Full mixed-case reading role, exact 2x M shapes and advance. Only glyph
    # metadata is added; every bitmap byte is shared with the existing M face.
    n, _, _, nc = emit('N', *medium, chars, 35, 28, 2, data, offsets,
                       label='M8Stealth89 full x2 (shared M)', compact=True)
    # The dominant focused readout: exact 3x M ink, a 2 px gap after the 24 px
    # ink (26 px pen), numerals and capitals only. Metadata only, like L and N.
    x, _, _, xc = emit('X', *medium, [ord(c) for c in L_CHARS], 50, 40, 3, data, offsets,
                       label='M8Stealth89 x3, 26px advance (shared M)', tracking=-1)
    parts += [s, m, l, n, x]
    from font_resources import MANIFEST, checked, serialize
    header = '\n\n'.join(parts) + '\n'
    manifest = checked(Path(__file__).resolve().parents[1], header)
    Path(args.out).write_text(header)
    Path(args.out).with_name(MANIFEST).write_text(serialize(manifest))
    print(f'fonts total {sc + mc + lc + nc + xc} B tables + 180 B descriptors -> {args.out}')


if __name__ == '__main__':
    main()
