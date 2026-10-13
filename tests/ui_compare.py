#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exact comparisons of manifests from the real Felucca host UI renderer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, __version__ as pillow_version

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_provenance(renderer):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    patterns = ("firmware/src/*.[ch]", "firmware/hal/*.[ch]", "tests/*.[ch]",
                "tests/ui_render.py", "tests/ui_compare.py", "tools/gen_aa*.py", "tools/gen_bitmap_font.py",
                "assets/fonts/**/*.ttf", "assets/fonts/**/*.woff2", "assets/fonts/**/*.bdf",
                "assets/fonts/**/*.bmp", "web/fukiai.ttf", "build/gen/*.h")
    inputs = {str(p.relative_to(ROOT)): sha256(p)
              for pattern in patterns for p in sorted(ROOT.glob(pattern))}
    return {"revision": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
            "capture": "before-render" if renderer else "conversion-only",
            "renderer_sha256": sha256(renderer) if renderer else None,
            "renderer": "tests/ui_render.c", "generator": "tests/ui_render.py",
            "pillow": pillow_version, "inputs": inputs}


def key(scene):
    return (scene["palette"], scene["style"], scene["name"])


def label(scene_key):
    return "/".join(scene_key)


def replay_manifest(manifest):
    """Expose timestamped replay frames to the existing exact pixel comparator.

    Keep replay provenance separate from the static scene renderer. A changed
    workload/timeline is incompatible even when two frame filenames happen to match.
    """
    provenance = manifest["provenance"]
    if (not isinstance(provenance, dict) or not isinstance(provenance.get("inputs"), dict)
            or not provenance.get("inputs") or not provenance.get("revision")
            or provenance.get("adapter") != "tools/replay_native.c"
            or not provenance.get("binary_sha256")):
        raise ValueError("replay requires native adapter/source/binary provenance")
    if (manifest.get("scenario_schema") != 1 or not manifest.get("scenario_sha256")
            or not isinstance(manifest.get("initial"), dict)
            or not isinstance(manifest.get("timing"), dict)):
        raise ValueError("replay requires scenario and timeline identity")
    screen = manifest["screen"]
    if (not isinstance(screen, dict) or screen.get("width") != 240 or screen.get("height") != 240
            or screen.get("source") != "real firmware lcd_fill/lcd_blit"
            or screen.get("format") != "RGB888 PPM from panel-order RGB565"):
        raise ValueError("replay requires the real 240 x 240 RGB565 LCD capture")
    features = provenance["features"]
    if not isinstance(features, dict) or any(type(features.get(k)) is not int or features[k] not in (0, 1)
                                            for k in ("fm4", "icons", "slice")):
        raise ValueError("replay requires explicit compiled FM4/icons/SLICE settings")
    scenes = []
    frames = screen["frames"]
    if not isinstance(frames, list) or len(frames) > 256:
        raise ValueError("replay frames must be a bounded list")
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("replay frame must be an object")
        sample, order = frame["requested_sample"], frame["order"]
        if type(sample) is not int or sample < 0 or type(order) is not int or order < 0:
            raise ValueError("replay frame requires nonnegative sample/order")
        scenes.append({"palette": "REPLAY", "style": "NATIVE",
                       "name": f"sample-{sample:08d}-order-{order:04d}",
                       "required": True, "file": frame["file"], "sha256": frame["sha256"],
                       "dimensions": [240, 240]})
    return {"schema": 1,
            "settings": {"mode": "RGB", "width": 240, "height": 240,
                         "pixel_format": screen["format"], "fm4": features["fm4"],
                         "icons": features["icons"], "slice": features["slice"],
                         "capture_kind": "interaction-replay", "scenario_sha256": manifest["scenario_sha256"],
                         "initial": manifest["initial"], "timing": manifest["timing"]},
            "provenance": provenance, "scenes": scenes}


def load_manifest(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    if manifest.get("schema") != 1:
        raise ValueError("unsupported manifest schema")
    is_replay = manifest.get("kind") == "interaction-replay"
    if is_replay:
        manifest = replay_manifest(manifest)
    settings = manifest["settings"]
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    if settings["mode"] != "RGB" or settings["width"] != 240 or settings["height"] != 240:
        raise ValueError("expected exact 240 x 240 RGB screen settings")
    for field in ("pixel_format", "fm4", "icons", "slice"):
        if field not in settings:
            raise ValueError(f"missing render setting: {field}")
    provenance = manifest["provenance"]
    if not isinstance(provenance, dict) or not isinstance(provenance.get("inputs"), dict):
        raise ValueError("provenance and inputs must be objects")
    if not is_replay and (provenance.get("capture") != "before-render" or not provenance.get("renderer_sha256")):
        raise ValueError("provenance must be captured with ui_render.py --renderer before drawing")
    if not provenance.get("revision") or not provenance.get("inputs"):
        raise ValueError("missing revision or font/generator/source provenance")
    if not is_replay and (provenance.get("renderer") != "tests/ui_render.c" or provenance.get("generator") != "tests/ui_render.py"):
        raise ValueError("comparison requires the real Felucca renderer and PNG generator")
    indexed = {}
    if not isinstance(manifest["scenes"], list):
        raise ValueError("scenes must be a list")
    for scene in manifest["scenes"]:
        if not isinstance(scene, dict):
            raise ValueError("each scene must be an object")
        k = key(scene)
        if not all(isinstance(v, str) and v for v in k) or k in indexed:
            raise ValueError(f"invalid or duplicate scene: {k}")
        if type(scene.get("required")) is not bool or not scene.get("sha256"):
            raise ValueError(f"missing required flag or image hash: {label(k)}")
        if scene.get("kind") == "filmstrip":
            dimensions = scene.get("dimensions")
            if (not isinstance(dimensions, list) or len(dimensions) != 2 or
                    any(type(n) is not int or n <= 0 for n in dimensions)):
                raise ValueError(f"invalid filmstrip dimensions: {label(k)}")
        elif "dimensions" in scene and scene["dimensions"] != [240, 240]:
            raise ValueError(f"normal scene dimensions must be 240 x 240: {label(k)}")
        path = Path(scene["file"])
        if path.is_absolute() or ".." in path.parts or not (directory / path).resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"image path escapes render directory: {path}")
        indexed[k] = scene
    if not indexed:
        raise ValueError("manifest contains no scenes")
    return manifest, indexed


def read_scene(directory, scene, settings):
    path = directory / scene["file"]
    if not path.is_file():
        return None
    if sha256(path) != scene["sha256"]:
        raise ValueError(f"image hash differs from manifest: {path}")
    with Image.open(path) as image:
        expected = (tuple(scene["dimensions"]) if scene.get("kind") == "filmstrip"
                    else (settings["width"], settings["height"]))
        if image.mode != "RGB" or image.size != expected:
            raise ValueError(f"wrong dimensions/mode for {path}: {image.size} {image.mode}, expected {expected} RGB")
        return image.copy()


def pixel_difference(before, after):
    if before.size != after.size:
        raise ValueError(f"paired dimensions differ: {before.size} versus {after.size}")
    difference = ImageChops.difference(before, after)
    r, g, b = difference.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda n: 255 if n else 0)
    count = mask.histogram()[255]
    visual = Image.new("RGB", before.size, (0, 0, 0))
    visual.paste((255, 0, 255), mask=mask)
    return count, mask.getbbox(), visual


def write_sheets(out, rows, page_start=1):
    """Bound each page to twelve scene rows, at native pixels, with no resampling."""
    files = []
    for page, start in enumerate(range(0, len(rows), 12), page_start):
        items = rows[start:start + 12]
        width = max(240, max(max(im.width for im in images) for _, images in items))
        height = sum(max(im.height for im in images) + 34 for _, images in items) + 26
        sheet = Image.new("RGB", (3 * (width + 8) + 8, height), (45, 45, 45))
        draw = ImageDraw.Draw(sheet)
        for column, title in enumerate(("BEFORE", "AFTER", "EXACT PIXEL DIFF (magenta)")):
            draw.text((8 + column * (width + 8), 5), title, fill="white")
        y = 26
        for title, images in items:
            draw.text((8, y), title, fill="white")
            y += 20
            for column, im in enumerate(images):
                sheet.paste(im, (8 + column * (width + 8), y))
            y += max(im.height for im in images) + 14
        name = f"comparison_{page:03d}.png"
        sheet.save(out / name)
        files.append(name)
    return files


def compare(before_dir, after_dir, out, palettes=(), styles=(), names=(), filmstrips=False):
    out = out.resolve()
    for source in (before_dir.resolve(), after_dir.resolve()):
        if out == source or source.is_relative_to(out) or out.is_relative_to(source):
            raise ValueError("report directory must be separate from both render directories")
    out.mkdir(parents=True, exist_ok=True)
    # Report directories may be reused for narrower selections or invalid captures.
    # Keep unrelated files, but remove pages owned by the previous comparison.
    for page in out.glob("comparison_*.png"):
        number = page.stem[len("comparison_"):]
        if len(number) >= 3 and number.isascii() and number.isdecimal() and page.is_file():
            page.unlink()
    summary = {"schema": 1, "method": "exact RGB pixels; bbox right/bottom exclusive",
               "selection": {"palettes": list(palettes), "styles": list(styles), "scenes": list(names), "filmstrips": filmstrips},
               "errors": [], "added": [], "removed": [], "missing": [], "scenes": [], "sheets": []}
    rows = []
    try:
        before, left = load_manifest(before_dir)
        after, right = load_manifest(after_dir)
        summary["before"] = {"directory": str(before_dir), "settings": before["settings"], "provenance": before["provenance"]}
        summary["after"] = {"directory": str(after_dir), "settings": after["settings"], "provenance": after["provenance"]}
        # Firmware release strings are provenance, not a drawing format setting.
        for field in sorted(set(before["settings"]) | set(after["settings"])):
            if field != "version" and before["settings"].get(field) != after["settings"].get(field):
                raise ValueError(f"incompatible render setting: {field}")
        if filmstrips and not any(s.get("kind") == "filmstrip" for s in list(left.values()) + list(right.values())):
            raise ValueError("filmstrips requested but neither capture contains them")
        selected = [k for k in sorted(left.keys() | right.keys())
                    if (not palettes or k[0] in palettes) and (not styles or k[1] in styles)
                    and (not names or k[2] in names)
                    and (filmstrips or (left.get(k) or right[k]).get("kind") != "filmstrip")]
        if not selected:
            raise ValueError("selection contains no scenes")
        for requested, present, title in ((palettes, {k[0] for k in selected}, "palette"),
                                           (styles, {k[1] for k in selected}, "style"),
                                           (names, {k[2] for k in selected}, "scene")):
            if set(requested) - present:
                raise ValueError(f"unknown selected {title}: {sorted(set(requested) - present)}")
        for k in selected:
            scene_id = label(k)
            if k not in left:
                summary["added"].append(scene_id)
            if k not in right:
                summary["removed"].append(scene_id)
            images = []
            for side, directory, manifest, scenes in (("before", before_dir, before, left), ("after", after_dir, after, right)):
                if k not in scenes:
                    images.append(None)
                    if (left.get(k) or right[k])["required"]:
                        summary["missing"].append({"side": side, "scene": scene_id, "reason": "required scene absent from manifest"})
                    continue
                image = read_scene(directory, scenes[k], manifest["settings"])
                images.append(image)
                if image is None:
                    summary["missing"].append({"side": side, "scene": scene_id, "reason": "image file absent", "required": scenes[k]["required"]})
            a, b = images
            if a is None or b is None:
                continue
            count, bbox, diff = pixel_difference(a, b)
            summary["scenes"].append({"palette": k[0], "style": k[1], "name": k[2], "changed_pixels": count, "bbox": bbox})
            rows.append((f"{scene_id}: {count} pixels; bbox {bbox}", (a, b, diff)))
            if len(rows) == 12:
                summary["sheets"].extend(write_sheets(out, rows, len(summary["sheets"]) + 1))
                rows.clear()
    except (ValueError, KeyError, TypeError, OSError) as error:
        summary["errors"].append(str(error))
    summary["changed_pixels"] = sum(scene["changed_pixels"] for scene in summary["scenes"])
    summary["changed_scenes"] = sum(scene["changed_pixels"] > 0 for scene in summary["scenes"])
    summary["status"] = ("invalid" if summary["errors"] else "different" if summary["changed_scenes"] or
                         summary["added"] or summary["removed"] or summary["missing"] else "identical")
    summary["sheets"].extend(write_sheets(out, rows, len(summary["sheets"]) + 1))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", type=Path, default=Path("build/ui_compare"))
    parser.add_argument("--strict", action="store_true", help="exit 1 for any differences/missing scenes; 2 for invalid comparisons")
    parser.add_argument("--palette", action="append", default=[])
    parser.add_argument("--style", action="append", default=[])
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--filmstrips", action="store_true", help="include explicitly captured rolling-digit filmstrips")
    args = parser.parse_args()
    try:
        summary = compare(args.before, args.after, args.out, args.palette, args.style, args.scene, args.filmstrips)
    except ValueError as error:
        parser.error(str(error))
    print("ui_compare: {}; {} changed pixels; {}/summary.json".format(summary["status"], summary["changed_pixels"], args.out))
    return (2 if summary["errors"] else 1 if summary["status"] != "identical" else 0) if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
