# M8Stealth sources

Unmodified font files by Trash80 from Dirtywave/M8WebDisplay, commit
`eabcc3da605b38f8fbe113c610c84122a17eb5ed`:

- https://github.com/Dirtywave/M8WebDisplay/blob/eabcc3da605b38f8fbe113c610c84122a17eb5ed/m8stealth57.woff2
- https://github.com/Dirtywave/M8WebDisplay/blob/eabcc3da605b38f8fbe113c610c84122a17eb5ed/m8stealth89.woff2

Both fonts declare CC BY-SA 3.0 in their name tables. The full licence is
[CC-BY-SA-3.0-M8Stealth.txt](../../../LICENSES/CC-BY-SA-3.0-M8Stealth.txt).
Author pages: https://fontstruct.com/fontstructions/show/2043303 and
https://fontstruct.com/fontstructions/show/2296206.

The two unmodified ASCII bitmap reference atlases are from octoocto/m8gd, commit
`19585d52c4ea38f8ad68c62201cf95c310653976`, under `rust/src/constants/`.
m8gd credits Trash80 for converting these fonts to bitmaps.
They are reference data for `tests/m8_font_test.py`, not packed firmware inputs.

## Local bitmap adaptations

`tools/gen_bitmap_font.py --preset m8stealth` rasterises at native grids (8/12 ppem),
packs one bit per pixel, and uses whole-pixel advances of 6/9 px.
L/N share M ink at exact 2×, with 18 px capitals. L's advance is reduced from 18 to 17 px to
keep a 1 px gap and fit three-digit card readouts; N retains 18 px. These roles
add metadata only. A doubled S is possible without a new raster, but is not
emitted without a reading task that needs it. ASCII ink matches the reference atlases exactly.
`tests/m8_font_test.py` also compares direct 16/24 ppem rasterisation of the
original WOFF2 files with exact doubling of their 8/12 ppem native output:
all 95 ASCII glyphs per file match in ink, bearings and advance, with monochrome
Pillow/FreeType rendering. This does not assert another application's smoothing
or the M8 device firmware's internal renderer.
The output adds copyright, degree, middle dot, umlauts and ellipsis because
these ten Felucca characters are absent from the font cmap. These bitmap
adaptations are identified as changes and retain CC BY-SA 3.0.
The WOFF2 files remain unmodified.

## Preserved embedded attribution

m8stealth57.woff2

```text
Copyright trash80 2021
“stealth57_alt, which is based on “stealth57
```

m8stealth89.woff2

```text
Copyright trash80 2023
“m8stealth79Bold, which is based on “m8stealth79, which is based on “m8stealth78, which is based on “m8stealth88, which is based on “m8stealth89, which is based on “m8 8x9 rounded, which is based on “m8 8x9 rounded” by “Matthias Tellen” (https://fontstruct.com/fontstructors/show/733334/mad_malik), which is based on “m8 8x9 square” by “Matthias Tellen” (https://fontstruct.com/fontstructors/show/733334/mad_malik)
```

## SHA-256

```text
b14bef6752f91197166ffe5ee7283f168d022d8c30b3c9ba57233451704edce6  m8stealth57.woff2
b811d17dc96b9c617e76fc12eaeb4c8e79614d79885935567429e1cea907d02e  m8stealth89.woff2
20ce076b5938ce6ea2d23004575abaffc7dfb84a4d938266e1414b8b6b5d86f4  5_7.bmp
e4d175dcab30c2a30254f337c7666a22c5324d417193fd803b160c7f55a72b37  8_9.bmp
```
