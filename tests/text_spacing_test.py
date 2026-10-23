#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""Check native bitmap bounds and fixed whole-pixel advances; optionally render specimens.
The parser/decoder also supports historical capture headers for comparison tools.
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import ui_font_data as gf  # noqa: E402

LOWER = ["oeo", "coco", "eco", "nono", "minimum", "hello", "level", "decay", "release", "sound", "Pitch", "Cutoff",
         "doob", "bdpq", "occasion", "accessed", "Resonance", "Envelope", "Attack", "Sustain", "Volume", "Tempo",
         "Swing", "Pattern", "Chance", "Multi-engine synthesizer", "H\xfcgelton Instruments", "Hello world",
         "Mixed case text", "Glide", "Drive", "Feedback", "Motion", "Phrases", "Song", "Mixer", "Calibration"]
UPPER = ["CUTOFF", "RESO", "LEVEL", "DECAY", "RELEASE", "SOUND", "OCOE", "COCO", "NONO", "MINIMUM", "SUPER SAW",
         "FELUCCA", "PRESETS", "ANALOG", "DIGITAL", "PITCH", "SWING", "AV AW LT TA YO"]
RULE = ["gfx"]   # "gfx": src/gfx.c cv_text; "rounded": the earlier rule (each glyph at the rounded pen, 1 phase)


def parse(path):
    """the faces of a generated ui_fonts.h -> {name: dict(h, asc, first, last, ex, psh, g, data, kern)}"""
    t = Path(path).read_text()
    faces = {}
    for m in re.finditer(r"static const aafont_t AF_(\w+) = \{([^}]*)\};", t):
        name, f = m.group(1), [x.strip() for x in m.group(2).split(",")]
        arr = lambda n: [int(v, 0) for v in re.search(r"AF_%s_%s\[\d+\] = \{([^}]*)\}" % (name, n), t)
                         .group(1).replace("\n", " ").split(",") if v.strip()]
        g = [tuple(int(v) for v in e.split(",")) for e in
             re.findall(r"\{(-?\d+, -?\d+, -?\d+, -?\d+, -?\d+, -?\d+)\}",
                        re.search(r"AF_%s_G\[\d+\] = \{(.*?)\n\};" % name, t, re.S).group(1))]
        kern = {}
        if f[8] != "0":
            kern = dict(zip(arr("KERN"), arr("KD")))
        data_name = f[7]
        raw = re.search(r'\b' + data_name + r'\[\d+\] = \{([^}]*)\}', t)[1]
        data = bytes(int(v.strip(), 0) for v in raw.split(',') if v.strip())
        scale = int(f[12]) if len(f) > 13 else 0
        hc = f[13] if len(f) > 13 else f[12] if len(f) > 12 else "0"
        faces[name] = {"h": int(f[0]), "asc": int(f[1]), "first": int(f[2]), "last": int(f[3]), "nex": int(f[4]),
                       "g": g, "data": data, "kern": kern, "ex": arr("EX")[:int(f[4])], "scale": scale,
                       "psh": int(f[11]) if len(f) > 11 else 0,
                       "hc": arr("HC") if hc != "0" else None}
    return faces


def glyph_at(f, c):
    """the glyph number of code c in the face, None = not in it"""
    if f["first"] <= c <= f["last"]:
        return c - f["first"]
    if c in f["ex"]:
        return f["last"] - f["first"] + 1 + f["ex"].index(c)
    return None


def glyph(f, c):
    """src/gfx.c glyph(): the index of the glyph (its phase 0 entry is g[index << psh])"""
    if ord("a") <= c <= ord("z") and f["last"] < ord("a"):
        c -= 32
    k = glyph_at(f, c)
    if k is None and c == 0x85:
        k = glyph_at(f, ord("."))
    if k is None:
        k = glyph_at(f, ord("?"))
    return k or 0


def place(f, s):
    """src/gfx.c cv_text_flags: [(ch, gx, entry)] for a string drawn at x = 0"""
    out, pen, prev, psh, err = [], 0, 0, f["psh"], 0
    for ch in s:
        c = ord(ch)
        if ord("a") <= c <= ord("z") and f["last"] < ord("a"):
            c -= 32
        if prev:
            pen += f["kern"].get((prev << 8) | c, 0)
        gi = glyph(f, c)
        g0 = f["g"][gi << psh]
        if RULE[0] == "rounded":                     # the tables before the phases: the rounded pen
            pos = (pen + 8) & ~15
            e = g0
        elif psh and f["g"][(gi << psh) + 1][0] != g0[0]:   # the phase position nearer the previous glyph's offset
            step = 16 >> psh
            lo = pen - (pen & (step - 1))
            pos = lo if abs(lo - pen - err) <= abs(lo + step - pen - err) else lo + step
            e = f["g"][(gi << psh) + ((pos >> (4 - psh)) & ((1 << psh) - 1))]
        else:                                        # one phase: the rounded pen
            pos = (pen + 8) & ~15
            e = g0
        err = pos - pen
        out.append((ch, (pos >> 4) + e[2], e))
        pen += e[1]
        prev = c
    return out


def bitmap(f, e):
    off, adv, bx, by, bw, bh = e
    if f["scale"]:
        scale = f["scale"]
        sw = bw // scale
        return [15 * ((f["data"][off + ((y // scale * sw + x // scale) // 8)] >>
                       (7 - (y // scale * sw + x // scale) % 8)) & 1)
                for y in range(bh) for x in range(bw)]
    if f["hc"]:                                      # Huffman-coded (ui_font_data.py huff_pack)
        return gf.huff_unpack(f["hc"], f["data"][off:], bw * bh)
    v = []
    for b in f["data"][off:off + (bw * bh + 1) // 2]:
        v += [b >> 4, b & 15]
    return v[:bw * bh]


def specimen(f, words, scale=4):
    """the strings drawn by the table rule, gray on black, x scale"""
    lh = f["h"] + 4
    ws = [place(f, s) for s in words]
    w = max(gx + e[4] for p in ws for _, gx, e in p) + 8
    img = Image.new("L", (w, lh * len(words) + 4), 0)
    px = img.load()
    for k, p in enumerate(ws):
        for _, gx, e in p:
            bm = bitmap(f, e)
            for y in range(e[5]):
                for x in range(e[4]):
                    v = bm[y * e[4] + x] * 17
                    if v:
                        X, Y = 4 + gx + x, 2 + k * lh + e[3] + y
                        px[X, Y] = max(px[X, Y], v)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("header", nargs="?", default="build/gen/ui_fonts.h")
    ap.add_argument("--png", help="directory for the specimen PNGs")
    ap.add_argument("--tag", default="after")
    ap.add_argument("--no-limit", action="store_true", help="report only")
    ap.add_argument("--rule", choices=["gfx", "rounded"], default="gfx",
                    help="placement: cv_text's (default) or the earlier rounded pen (to measure old tables)")
    a = ap.parse_args()
    RULE[0] = a.rule
    faces = parse(a.header)
    if not faces["S"]["scale"]:
        raise SystemExit("Only native M8Stealth bitmap headers are supported")
    for name, width in (("S", 6), ("M", 9), ("L", 17), ("N", 18)):
        f = faces[name]
        assert f["scale"] == (2 if name in ("L", "N") else 1)
        assert not f["kern"] and not f["psh"]
        assert all(e[1] == width * 16 for e in f["g"])
        assert all(e[4] % f["scale"] == e[5] % f["scale"] == 0 for e in f["g"])
        for e in f["g"]:
            bitmap(f, e)
        print(f"text spacing {name}: whole-pixel {width}px fixed cells; bitmap bounds ok")
        if a.png:
            Path(a.png).mkdir(parents=True, exist_ok=True)
            words = LOWER if name != "L" else [w for w in UPPER if all(glyph_at(f, ord(ch)) is not None for ch in w)]
            specimen(f, words).save(Path(a.png) / f"{a.tag}_{name}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
