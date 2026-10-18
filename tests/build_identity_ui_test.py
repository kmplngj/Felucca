#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Render boundary build metadata in every supported font and palette."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_identity


def run():
    out = ROOT / 'build/identity-ui'
    for font in ('m8stealth', 'tamzen', 'inter-tight'):
        directory = out / font
        (directory / 'ppm').mkdir(parents=True, exist_ok=True)
        # The longest strings conservatively combine the dirty and PR bounds;
        # real verified PR inputs are required to be clean.
        data = {'version': 'v1.6.1', 'build': 'ffffffff-dirty', 'pr_label': 'PR #9999999 merge',
                'repository': 'o' * 39 + '/' + 'r' * 100}
        (directory / 'build_identity.h').write_text(build_identity.outputs(data)['build_identity.h'])
        generator = 'gen_aa_font.py' if font == 'inter-tight' else 'gen_bitmap_font.py'
        subprocess.run([sys.executable, str(ROOT / 'tools' / generator),
                        str(directory / 'ui_fonts.h'), '--preset', font], check=True)
        exe = directory / 'render'
        subprocess.run(shlex.split(os.environ.get('CC', 'clang')) +
                       ['-O1', '-w', '-I' + str(directory), '-Ibuild/gen', '-Ifirmware/src', '-Itests',
                        'tests/build_identity_ui.c', '-lm', '-o', str(exe)], cwd=ROOT, check=True)
        subprocess.run([str(exe), str(directory)], cwd=ROOT, check=True)
        images = sorted((directory / 'ppm').glob('*.ppm'))
        sheet = Image.new('RGB', (480, 264 * (len(images) // 2)), (80, 80, 80))
        draw = ImageDraw.Draw(sheet)
        # Put each palette's ABOUT and splash next to each other.
        for i, path in enumerate(images):
            x, y = (i % 2) * 240, (i // 2) * 264
            im = Image.open(path)
            im.save(path.with_suffix('.png'))
            sheet.paste(im, (x, y))
            draw.text((x + 4, y + 242), path.stem, fill='white')
        sheet.save(directory / 'sheet.png')
    print('identity UI: inspect build/identity-ui/<font>/sheet.png')


if __name__ == '__main__':
    run()
