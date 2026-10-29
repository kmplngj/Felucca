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
from release_notes import dev_identity


CASES = {
    'compiled': ('', '', 'source'),
    'dev-release': ('688cca29', '', 'override'),
    'release': ('1234abcd', '', 'override'),
    'long-release': ('1234abcd', '', 'override'),
    'commit': ('1234abcd', '', 'source'),
    'pr-head': ('1234abcd', 'PR #407 head', 'source'),
    'pr-merge': ('1234abcd', 'PR #407 merge', 'source'),
    'dirty': ('1234abcd-dirty', '', 'override'),
    'unknown': ('unknown', '', 'override'),
    # Conservative layout bound; verified PR builds themselves must be clean.
    'boundary': ('ffffffff-dirty', 'PR #9999999 merge', 'source'),
}


def run():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build/identity-ui'
    # Reproduce the first failing Dev identity through the production resolver.
    dev_sha = '688cca29ad194151b9167ee4f715b0b0900d30fb'
    dev = dev_identity([{'number': 765, 'merged_at': '2026-10-28',
                        'merge_commit_sha': dev_sha,
                        'base': {'ref': 'main', 'repo': {'full_name': 'fixture/Felucca'}}}],
                       'fixture/Felucca', dev_sha)
    for font in ('m8stealth',):
        directory = out / font
        directory.mkdir(parents=True, exist_ok=True)
        generator = 'gen_bitmap_font.py'
        subprocess.run([sys.executable, str(ROOT / 'tools' / generator),
                        str(directory / 'ui_fonts.h'), '--preset', font], check=True)
        for name, (revision, pr, origin) in CASES.items():
            case = directory / name
            (case / 'ppm').mkdir(parents=True, exist_ok=True)
            data = {'version': ('v' + dev['version'].lower() if name == 'dev-release' else
                               'v1.0-' + 'w' * 26 if name == 'long-release' else 'v1.6.1'),
                    'build': revision, 'pr_label': pr,
                    'version_source': origin, 'revision': None if revision == 'unknown' else 'f' * 40,
                    'dirty': revision.endswith('-dirty'),
                    'repository': (None if name == 'unknown' else
                                   'o' * 39 + '/' + 'r' * 100 if name == 'boundary' else
                                   'fixture/Felucca')}
            fixture_flags = []
            if name != 'compiled':
                header = case / 'build_identity.h'
                header.write_text(build_identity.outputs(data)['build_identity.h'])
                # The coverage compiler adds -Ibuild/gen before caller flags.
                # Force fixture identity before that header's include guard;
                # 'compiled' separately exercises the real generated identity.
                fixture_flags = ['-include', str(header)]
            exe = case / 'render'
            subprocess.run(shlex.split(os.environ.get('CC', 'clang')) +
                           ['-O1', '-w', *(['-DIDENTITY_SPLASH_ONLY'] if name == 'long-release' else []),
                            *fixture_flags, '-I' + str(directory),
                            '-Ibuild/gen', '-Ifirmware/src', '-Itests',
                            'tests/build_identity_ui.c', '-lm', '-o', str(exe)], cwd=ROOT, check=True)
            subprocess.run([str(exe.resolve()), str(case)], cwd=ROOT, check=True)
            for path in (case / 'ppm').glob('*.ppm'):
                Image.open(path).save(path.with_suffix('.png'))
        # Compact review sheet: identities in GREY, native-resolution.
        images = [directory / name / 'ppm/GREY_splash.png' for name in CASES]
        sheet = Image.new('RGB', (480, 264 * ((len(images) + 1) // 2)), (80, 80, 80))
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(images):
            x, y = (i % 2) * 240, (i // 2) * 264
            im = Image.open(path)
            im.save(path.with_suffix('.png'))
            sheet.paste(im, (x, y))
            draw.text((x + 4, y + 242), path.parents[1].name, fill='white')
        sheet.save(directory / 'sheet.png')
    print('identity UI: inspect build/identity-ui/<font>/sheet.png')


if __name__ == '__main__':
    run()
