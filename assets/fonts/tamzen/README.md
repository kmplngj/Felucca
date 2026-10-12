# Tamzen UI experiment

Unmodified `Tamzen6x12r.bdf` and `Tamzen8x16r.bdf` from
[Tamzen-1.11.6](https://github.com/sunaku/tamzen-font/tree/Tamzen-1.11.6/bdf).
The authors' licence is preserved in `LICENSE` and `LICENSES/Tamzen.txt`.

`tools/gen_bitmap_font.py` subsets them to the existing UI character set, adds
the missing middle dot and ellipsis, and packs two 1-bit faces. The large face
shares the medium face's bitmap data at integer 2× scaling. Per-glyph BDF boxes
are respected, including the 8×17 lowercase cells in the nominal 8×16 face.
Existing keycap atlases retain their Inter Tight legends and attribution.
