#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Check INFO identity selection and real layout for each build context."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_identity


def run():
    out = ROOT / 'build/settings-identity'
    base = dict(version='v1.6.1', version_source='source', revision='f' * 40,
                dirty=False, build='ffffffff', pr_label='')
    cases = [
        ('commit', {}, 'ffffffff'),
        ('dirty', dict(dirty=True, build='ffffffff-dirty'), 'ffffffff-dirty'),
        ('release', dict(version_source='override'), 'v1.6.1'),
        ('dirty-release', dict(version_source='override', dirty=True, build='ffffffff-dirty'), 'ffffffff-dirty'),
        ('unknown', dict(version_source='override', revision=None, build='unknown'), 'unknown'),
        ('pr-merge', dict(pr_label='PR #9999999 merge'), 'PR #9999999 merge'),
        ('pr-head', dict(version_source='override', pr_label='PR #9999999 head'), 'PR #9999999 head'),
    ]
    for font in ('m8stealth', 'tamzen', 'inter-tight'):
        directory = out / font
        directory.mkdir(parents=True, exist_ok=True)
        generator = 'gen_aa_font.py' if font == 'inter-tight' else 'gen_bitmap_font.py'
        subprocess.run([sys.executable, str(ROOT / 'tools' / generator),
                        str(directory / 'ui_fonts.h'), '--preset', font], check=True)
        for name, overrides, expected in cases:
            header = build_identity.outputs(base | overrides)['build_identity.h']
            assert f'#define FELUCCA_SPLASH_ID "{expected}"' in header
            (directory / 'build_identity.h').write_text(header)
            case = directory / name
            (case / 'ppm').mkdir(parents=True, exist_ok=True)
            exe = directory / 'render'
            subprocess.run(shlex.split(os.environ.get('CC', 'clang')) +
                           ['-O0', '-w', '-I' + str(directory), '-Ibuild/gen', '-Ifirmware/src', '-Itests',
                            'tests/settings_identity_ui.c', '-lm', '-o', str(exe)], cwd=ROOT, check=True)
            subprocess.run([str(exe), str(case)], cwd=ROOT, check=True)
            for path in (case / 'ppm').glob('*.ppm'):
                Image.open(path).save(path.with_suffix('.png'))
    print('settings identity: 7 contexts x 3 fonts x 10 palettes x 2 styles x 2 sizes passed')


if __name__ == '__main__':
    run()
