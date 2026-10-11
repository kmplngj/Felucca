#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""PPM -> PNG for the UI renders of tests/ui_render.c (Pillow). Under OUTDIR (default build/ui_new):
  (the STEP page's piano roll scenes, roll_* step chance drum: also in build/ui_roll/<PALETTE>_<screen>.png)
  <PALETTE>/<screen>.png   240 x 240, true size
  sheet_<PALETTE>.png      every screen of one palette, 1x, with its name
  (MENU > STYLE: LINE_<PALETTE>/ and sheet_LINE_<PALETTE>.png for GREY MONO NIGHT PAPER;
   MENU > LARGE: sheet_LARGE_GREY.png, sheet_LARGE_MONO.png, sheet_LARGE-LINE_GREY.png)
With SLOTDIR (ui_render.py OUTDIR SLOTDIR): its filmstrips of the rolling digits, SLOTDIR/*.ppm -> *.png.
--renderer PATH compiles/runs the real renderer before conversion and captures source, asset,
compiler and binary provenance in manifest.json. Filmstrips are separate optional manifest scenes.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys

import ui_compare
from pathlib import Path

from PIL import Image, ImageDraw

def convert(args):
    out = args.out
    shots = {}
    stems = (out / "scenes.txt").read_text().splitlines()
    for stem in sorted(stems):
        f = out / "ppm" / f"{stem}.ppm"
        pal, name = f.stem.split("_", 1)
        styled = pal in ("LINE", "LARGE", "LARGE-LINE")   # STYLE / MENU > LARGE renders: <STYLE>_<PALETTE>_<screen>
        if styled:
            p2, name = name.split("_", 1)
            pal = f"{pal}_{p2}"
        (out / pal).mkdir(parents=True, exist_ok=True)
        img = Image.open(f).convert("RGB")
        img.save(out / pal / f"{name}.png")
        shots.setdefault(pal, []).append((name, img))
        if styled:
            continue
        if pal in ("GREY", "MONO", "GREEN") and (name.startswith("perform_") or name == "menu_hold"):   # the FX layer's screens
            (out.parent / "ui_fx").mkdir(parents=True, exist_ok=True)
            img.save(out.parent / "ui_fx" / f"{pal}_{name}.png")
        if pal in ("GREY", "MONO", "GREEN") and (name.startswith("layer_") or name.startswith("perform_")):   # the quick layers
            (out.parent / "ui_layers").mkdir(parents=True, exist_ok=True)
            img.save(out.parent / "ui_layers" / f"{pal}_{name}.png")
        if name.startswith("roll_") or name in ("step", "chance", "drum"):   # the STEP page's piano roll (and the grid)
            (out.parent / "ui_roll").mkdir(parents=True, exist_ok=True)
            img.save(out.parent / "ui_roll" / f"{pal}_{name}.png")
        if pal in ("GREY", "MONO", "GREEN") and (name.startswith("name_") or name in ("project_named", "song_named", "user_foot")):
            (out.parent / "ui_name").mkdir(parents=True, exist_ok=True)   # NAME (src/ui_name.c) and the names it shows
            img.save(out.parent / "ui_name" / f"{pal}_{name}.png")
    for pal in ("GREY", "MONO", "GREEN"):   # DIGITAL's 8 algorithm charts (+ OP LEVEL): x3, the panel, in build/ui_alg/
        algs = [(n, im) for n, im in shots.get(pal, []) if n.startswith("alg_") or n == "op_level"]
        if not algs:
            continue
        (out.parent / "ui_alg").mkdir(parents=True, exist_ok=True)
        pw, ph, lh = 240 * 3, 122 * 3, 18
        sheet = Image.new("RGB", (2 * pw + 24, ((len(algs) + 1) // 2) * (ph + lh + 8) + 8), (90, 90, 90))
        d = ImageDraw.Draw(sheet)
        for i, (name, img) in enumerate(algs):
            big = img.resize((720, 720), Image.NEAREST)
            big.save(out.parent / "ui_alg" / f"{pal}_{name}.png")
            x, y = 8 + (i % 2) * (pw + 8), 8 + (i // 2) * (ph + lh + 8)
            sheet.paste(big.crop((0, 76 * 3, pw, 198 * 3)), (x, y))
            d.text((x, y + ph + 3), name.replace("alg_", "ALG "), fill=(235, 235, 235))
        sheet.save(out.parent / "ui_alg" / f"sheet_{pal}.png")
    for pal, items in shots.items():
        cols, cw, ch = 8, 248, 262
        rows = (len(items) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw + 8, rows * ch + 8), (90, 90, 90))
        d = ImageDraw.Draw(sheet)
        for i, (name, img) in enumerate(items):
            x, y = 8 + (i % cols) * cw, 8 + (i // cols) * ch
            sheet.paste(img, (x, y))
            d.text((x, y + 242), name, fill=(235, 235, 235))
        sheet.save(out / f"sheet_{pal}.png")
    print(f"ui_render: PNGs in {out}/<palette>/ and {out}/sheet_<palette>.png")
    if args.slot:
        for f in sorted(args.slot.glob("*.ppm")):
            Image.open(f).convert("RGB").save(f.with_suffix(".png"))
        print(f"ui_render: rolling-digit filmstrips in {args.slot}/*.png")

    scenes = []
    for group, items in sorted(shots.items()):
        if group.startswith(("LINE_", "LARGE_", "LARGE-LINE_")):
            style, palette = group.split("_", 1)
        else:
            style, palette = "FLAT", group
        for name, img in items:
            file = f"{group}/{name}.png"
            scenes.append({"palette": palette, "style": style, "name": name,
                           "file": file, "sha256": ui_compare.sha256(out / file), "required": True})
    if args.slot:
        for f in sorted(args.slot.glob("*.ppm")):
            palette, name = f.stem.split("_", 1)
            target = out / "filmstrips" / f.with_suffix(".png").name
            target.parent.mkdir(exist_ok=True)
            with Image.open(f) as image:
                image.convert("RGB").save(target)
                dimensions = list(image.size)
            scenes.append({"palette": palette, "style": "FILMSTRIP", "name": name,
                           "kind": "filmstrip", "dimensions": dimensions,
                           "file": str(target.relative_to(out)), "sha256": ui_compare.sha256(target), "required": True})
    manifest = {"schema": 1, "settings": json.loads((out / "render_settings.json").read_text()),
                "provenance": args.provenance, "scenes": scenes}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, nargs="?", default=Path("build/ui_new"))
    parser.add_argument("slot", type=Path, nargs="?")
    parser.add_argument("--renderer", type=Path, help="compile the real renderer at this path, run it and capture provenance")
    parser.add_argument("--fm4", action="store_true", help="compile with FELUCCA_FM4=1")
    parser.add_argument("--cc", default=os.environ.get("CC", "clang"))
    args = parser.parse_args()
    if args.renderer:
        # A failed recapture must not leave a previous success manifest usable.
        (args.out / "manifest.json").unlink(missing_ok=True)
        args.renderer.parent.mkdir(parents=True, exist_ok=True)
        version = re.search(r'^#define FELUCCA_VERSION "([^"]+)"', (ui_compare.ROOT / "firmware/src/felucca.c").read_text(), re.M).group(1)
        compile_command = shlex.split(args.cc) + ["-O1", "-w", f'-DFELUCCA_VERSION="{version}"',
                                                 "-Ibuild/gen", "-Ifirmware/src", "-Itests"]
        if args.fm4:
            compile_command.append("-DFELUCCA_FM4=1")
        compile_command += ["-o", str(args.renderer), "tests/ui_render.c", "-lm"]
        inputs_before = ui_compare.capture_provenance(None)["inputs"]
        result = subprocess.run(compile_command, cwd=ui_compare.ROOT)
        if result.returncode:
            return result.returncode
        args.provenance = ui_compare.capture_provenance(args.renderer)
        if inputs_before != args.provenance["inputs"]:
            raise RuntimeError("render inputs changed while compiling")
        args.provenance["compile_command"] = compile_command
        args.provenance["compiler"] = subprocess.check_output(shlex.split(args.cc) + ["--version"], text=True).splitlines()[0]
    else:
        args.provenance = ui_compare.capture_provenance(None)
    if args.renderer:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "ppm").mkdir(exist_ok=True)
        command = [str(args.renderer), str(args.out)]
        if args.slot:
            args.slot.mkdir(parents=True, exist_ok=True)
            command.append(str(args.slot))
        result = subprocess.run(command)
        if result.returncode:
            return result.returncode
        if args.provenance["inputs"] != ui_compare.capture_provenance(None)["inputs"]:
            raise RuntimeError("render inputs changed while drawing")
    convert(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
