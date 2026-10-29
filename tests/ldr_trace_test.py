#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real loader renderer/OTA trace contracts; no MIDI, USB or target execution."""
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build' / 'ldr-trace'
OUT.mkdir(parents=True, exist_ok=True)
CC = shlex.split(os.environ.get('CC', 'cc'))


def run(argv):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{argv!r}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main():
    variants = [('O2', ['-O2']), ('Os', ['-Os'])]
    if os.environ.get('SANITIZE') == '1':
        variants.append(('asan-ubsan', ['-O2', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']))
    wire_fixture = None
    with tempfile.TemporaryDirectory(prefix='run-', dir=OUT) as work:
        work = Path(work)
        for name, flags in variants:
            for source in ('ldr_trace_probe_test.c', 'ldr_trace_wire_test.c'):
                executable = work / (source.removesuffix('.c') + '-' + name)
                run([*CC, '-std=c11', '-Wall', '-Wextra', '-Werror', *flags,
                     'tests/' + source, '-o', str(executable)])
                output = run([str(executable)])
                print(output.strip())
                for line in output.splitlines():
                    if line.startswith('TRACE_WIRE_FIXTURE='):
                        wire_fixture = line.split('=', 1)[1]
        for opt in ('-O2', '-Os'):
            outputs = []
            for name, defines in (('unset', []), ('zero', ['-DFELUCCA_LDR_LCD_TRACE=0'])):
                path = work / (name + opt + '.o')
                run([*CC, '-std=c11', opt, *defines, '-c', 'tests/ldr_screen_test.c', '-o', str(path)])
                outputs.append(path.read_bytes())
            assert outputs[0] == outputs[1], 'Default flag is not byte-equivalent to explicit zero'
    assert wire_fixture is not None
    print(run([sys.executable, '-B', 'tests/ldr_trace_client_test.py', '--wire-hex', wire_fixture]).strip())
    spec = importlib.util.spec_from_file_location('ldr_trace_build', ROOT / 'tools/build.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    flag = 'FELUCCA_LDR_LCD_TRACE'
    neutral = {name: '0' for name in build.DIAG_FLAGS}
    neutral['FELUCCA_PROFILE'] = 'standard'
    with patch.dict(os.environ, neutral):
        os.environ.pop(flag, None)
        default = build.loader_flags()
        os.environ[flag] = '0'
        assert build.loader_flags() == default
        build.resolve(['--release', '1.2.3'])
        os.environ[flag] = '1'
        assert build.loader_flags() == default + ['-D' + flag + '=1']
        assert '-D' + flag + '=1' in build.app_flags(), 'Diagnostic flag missing from configuration binding'
        try:
            build.resolve(['--release', '1.2.3'])
        except SystemExit as error:
            assert 'diagnostic build' in str(error)
        else:
            raise AssertionError('Diagnostic release accepted')
        os.environ[flag] = 'invalid'
        try:
            build.loader_flags()
        except SystemExit:
            pass
        else:
            raise AssertionError('Invalid diagnostic value accepted')
    print('loader trace: real sources, passive wire readout, bounded window, default equivalence and build policy PASS')


if __name__ == '__main__':
    main()
