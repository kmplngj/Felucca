#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build isolated standard/reduced hosts and carry actual records between them."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/profile-tests'

def run(*args, env=None):
    subprocess.run([str(a) for a in args],check=True,cwd=ROOT,env=env)

def compiler_command(value):
    """Keep wrappers/flags but remove inherited default selection include directories."""
    parts=shlex.split(value)
    out=[]
    i=0
    while i < len(parts):
        arg=parts[i]
        separated=arg=='-I' and i+1 < len(parts)
        directory=parts[i+1] if separated else arg[2:] if arg.startswith('-I') else None
        if directory is not None and (ROOT/directory).resolve()==(ROOT/'build/gen').resolve():
            i+=2 if separated else 1
            continue
        out.append(arg)
        i+=1
    return out


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cc=compiler_command(os.environ.get('CC','cc'))
    for name in ('standard','reduced-lofi'):
        # Include paths come before common generated assets; each host gets its own selection.
        gen=ROOT/'build'/f'profile-{name}-gen'
        run(sys.executable,'tools/profile.py','--profile',name,'--out',gen)
        run(sys.executable,'tools/profile.py','--profile',name,'--out',gen,'--check')
        flags=['-O2','-w','-I'+str(gen),'-Ibuild/gen','-Ifirmware/src']
        macros=subprocess.check_output([*cc,*flags,'-dM','-E','tests/profile_roundtrip.c'],text=True,cwd=ROOT)
        assert f'#define FELUCCA_PROFILE_NAME \"{name}\"' in macros, 'wrong compiled profile identity'
        assert f'#define FELUCCA_PROFILE_ENGINE_3 {int(name=="standard")}' in macros, 'wrong compiled engine selection'
        for src in ('profile_roundtrip','engine_metadata_test','engid_test'):
            exe=OUT/f'{name}-{src}'
            run(*cc,*flags,f'tests/{src}.c','-lm','-o',exe)
            if src != 'profile_roundtrip': run(exe)
        # The emulator bridge uses this very same selection, even for native validation.
        run(*cc,*flags,'web/emu/native_check.c','-lm','-o',OUT/f'{name}-emu-native')
        symbols=subprocess.check_output(['nm',str(OUT/f'{name}-profile_roundtrip')],text=True)
        if name=='standard':
            assert 'lofi_render' in symbols, 'standard implementation is missing'
        if name=='reduced-lofi':
            for symbol in ('lofi_render','LOFI_PRESETS','WRAM'):
                assert symbol not in symbols, f'omitted symbol remains: {symbol}'
    run(OUT/'standard-profile_roundtrip','create',OUT/'standard.records')
    run(OUT/'reduced-lofi-profile_roundtrip',OUT/'standard.records',OUT/'reduced.records')
    run(OUT/'standard-profile_roundtrip',OUT/'reduced.records',OUT/'returned.records')
    contents=[(OUT/f'{name}.records').read_bytes() for name in ('standard','reduced','returned')]
    assert contents[0]==contents[1]==contents[2], 'standard/reduced/standard records changed'
    print('standard -> reduced -> standard: project, user preset and backup favourites byte-identical; '
          +hashlib.sha256(contents[0]).hexdigest())

if __name__=='__main__':main()
