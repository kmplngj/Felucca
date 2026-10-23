#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""THROWAWAY #572: one-command native captures and a local comparison gallery.

uv run --locked --group build python tests/prototypes/large_readability.py
No target toolchain, SDK, device, Emscripten or firmware mutation is required.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/large-prototype"


def main():
    os.chdir(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ppm").mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT / "tools"))
    # Existing asset generation, including source/engine/font provenance.
    with (OUT / "generate.log").open("w") as log:
        subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'tools'); import build; build.generate()"],
                       check=True, stdout=log, stderr=subprocess.STDOUT)
    cc = os.environ.get("CC", "cc")
    command = [cc, "-O1", "-w", "-Ibuild/gen", "-Ifirmware/src", "-Itests",
               "tests/prototypes/large_readability.c", "-lm", "-o", str(OUT / "capture")]
    with (OUT / "capture.log").open("w") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run([str(OUT / "capture"), str(OUT)], check=True, stdout=log, stderr=subprocess.STDOUT)
    from PIL import Image, ImageChops, ImageDraw
    images = OUT / "images"
    images.mkdir(exist_ok=True)
    for source in (OUT / "ppm").glob("*.ppm"):
        with Image.open(source) as im:
            im.save(images / (source.stem + ".png"))
    # D's design constraint is exact preservation outside the 44 px bank, not
    # a newly sketched version of an algorithm/history/meter workspace.
    unchanged = 0
    for source in images.glob("D-*.png"):
        scene = source.stem.split("_", 1)[1].rsplit("-k", 1)[0]
        if scene in ("sound", "name", "settings"):
            continue  # shared adjuncts/control, not parameter-bank proposals
        with Image.open(source) as candidate, Image.open(images / source.name.replace("D-", "normal-", 1)) as normal:
            for box in ((0, 0, 240, 28), (0, 72, 240, 240)):
                if ImageChops.difference(candidate.crop(box), normal.crop(box)).getbbox():
                    raise RuntimeError(f"D changed the native workspace: {source.name}")
        unchanged += 1
    files = ["tests/prototypes/large_readability.c", "tests/prototypes/large_readability.py",
             "tests/prototypes/large_readability.html", "tests/ui_render.c", "tests/ui_test.c"]
    files += [str(p.relative_to(ROOT)) for p in (ROOT / "firmware/src").glob("ui*.c")]
    files += [str(p.relative_to(ROOT)) for p in (ROOT / "build/gen").glob("*.h")]
    provenance = {
        "kind": "host-only throwaway design prototype; no target/resource/device acceptance",
        "base": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "engines": subprocess.check_output(["git", "-C", "firmware/engines", "rev-parse", "HEAD"], text=True).strip(),
        "compiler": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
        "command": command, "profile": "standard", "font": "M8Stealth",
        "canvas": [240, 240], "palettes": 10, "styles": ["FLAT", "LINE"],
        "modes": ["NORMAL", "current LARGE", "A", "B", "C", "D"], "focus_states": 4,
        "captures": len(list(images.glob("*.png"))),
        "D_workspace": {"compared": unchanged, "outside_bank_changed_pixels": 0,
                        "bank_xywh": [0, 28, 240, 44], "reference": "NORMAL"},
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
    }
    (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    shutil.copyfile(ROOT / "tests/prototypes/large_readability.html", OUT / "index.html")
    scenes = ["home", "fraction", "mod", "fm6", "operator", "detail", "mixer", "sound", "name", "settings"]
    for palette in ["GREY", "PAPER", "MONO", "HI-CON", "GREEN"]:
        variants = ["normal", "current", "A", "B", "C", "D"]
        sheet = Image.new("RGB", (8 + len(variants) * 248, len(scenes) * 265 + 8), "#eeeae3")
        pen = ImageDraw.Draw(sheet)
        for row, scene in enumerate(scenes):
            for col, variant in enumerate(variants):
                with Image.open(images / f"{variant}-{palette}-FLAT_{scene}-k4.png") as im:
                    sheet.paste(im, (8 + col * 248, 8 + row * 265))
                pen.text((8 + col * 248, 250 + row * 265), f"{variant} / {scene}", fill="#222")
        sheet.save(OUT / f"comparison-{palette}.png")
    # Compact native-pixel boards for the issue, without resampling LCD pixels.
    for filename, variants, tasks, palette in [
        ("comparison.png", ["current", "A", "B", "C", "D"], ["home", "fraction", "mod"], "GREY"),
        ("elektron-D.png", ["normal", "B", "D"], ["fm6", "mod", "detail", "mixer"], "AMBER"),
        ("preview-D.png", ["normal", "D"], ["fm6"], "AMBER"),
    ]:
        sheet = Image.new("RGB", (8 + len(variants) * 248, len(tasks) * 265 + 8), "#eeeae3")
        pen = ImageDraw.Draw(sheet)
        for row, scene in enumerate(tasks):
            for col, variant in enumerate(variants):
                with Image.open(images / f"{variant}-{palette}-FLAT_{scene}-k4.png") as im:
                    sheet.paste(im, (8 + col * 248, 8 + row * 265))
                pen.text((8 + col * 248, 250 + row * 265), f"{variant} / {scene}", fill="#222")
        sheet.save(OUT / filename)
    print(f"LARGE prototype: {provenance['captures']} native captures; open {OUT / 'index.html'}; "
          f"{(OUT / 'report.txt').read_text(errors='replace').splitlines()[-1]}; "
          f"D workspace unchanged in {unchanged} comparisons")


if __name__ == "__main__":
    main()
