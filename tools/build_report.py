#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exact, artifact-bound resource evidence from a successful production target build."""
# Verified archives must not execute cached helpers before checking their source tree.
# os/sys are loaded by Python startup; defer all repository and other stdlib imports.
import os as _source_os
import sys as _source_sys

_source_root = _source_os.path.dirname(_source_os.path.dirname(_source_os.path.realpath(__file__)))
_source_verifier = None
if _source_os.path.isfile(_source_os.path.join(_source_root, "SOURCE-PINS.json")):
    _source_sys.dont_write_bytecode = True
    _source_os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    _source_import_paths = _source_sys.path[:]
    try:
        # The verifier uses only stdlib. Exclude archive paths while loading it,
        # so an unmanifested module cannot shadow a stdlib dependency either.
        _source_sys.path = [p for p in _source_import_paths
                            if not (_source_os.path.realpath(p or _source_os.getcwd()) == _source_root
                                    or _source_os.path.realpath(p or _source_os.getcwd()).startswith(_source_root + _source_os.sep))]
        _source_verifier_path = _source_os.path.join(_source_root, "tools", "source_archive.py")
        _source_verifier = {"__name__": "felucca_source_verifier", "__file__": _source_verifier_path}
        with open(_source_verifier_path, "rb") as _source_verifier_file:
            exec(compile(_source_verifier_file.read(), _source_verifier_path, "exec"), _source_verifier)
        _source_verifier["verify_tree"](_source_root)
    except (OSError, ValueError) as _source_error:
        raise SystemExit(str(_source_error))
    finally:
        _source_sys.path = _source_import_paths


import argparse
import hashlib
import json
import importlib.metadata
from pathlib import Path
import re
import subprocess
import sys

COMPILER_ENV = ('CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH',
                'LIBRARY_PATH', 'COMPILER_PATH', 'GCC_EXEC_PREFIX', 'SDKROOT',
                'CLANG_CONFIG_FILE_SYSTEM_DIR', 'CLANG_CONFIG_FILE_USER_DIR',
                'CLANG_CONFIG_FILE', 'CLANG_CONFIG_FILE_PATH', 'CLANG_NO_DEFAULT_CONFIG',
                'CCC_OVERRIDE_OPTIONS', 'CCC_ADD_ARGS', 'LD_PRELOAD',
                'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH')
ALLOWED_LOADER_ENV = ('LD_LIBRARY_PATH',)
HOST_INJECTION_ENV = ('LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH')
HEADER_ROOTS = ('pi32v2/lib/clang/4.0.1/include', 'pi32v2/include')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def input_hashes(root, *, include_generated=True):
    """A complete source inventory (a superset of the compilation closure), plus generated inputs.

    Hash actual working bytes, including nonignored untracked files; HEAD alone is
    never claimed to identify dirty inputs. Verified source archives need no Git.
    """
    marker = root / 'SOURCE-PINS.json'
    if marker.exists():
        from profile import source_pins
        source_pins(root)  # production archive verification, including extra-input rejection
        names = set(json.loads(marker.read_text())['files']) | {'SOURCE-PINS.json'}
    else:
        def paths(repo, *args):
            output = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', *args])
            return {name.decode() for name in output.split(b'\0') if name}
        names = paths(root, '--recurse-submodules') | paths(root, '--others', '--exclude-standard')
        # Git's outer untracked inventory does not descend into a submodule.
        names |= {'firmware/engines/' + name for name in
                  paths(root / 'firmware/engines', '--others', '--exclude-standard')}
    if include_generated:
        names |= {str(path.relative_to(root)) for path in (root / 'build/gen').rglob('*')
                  if path.is_file() and path.suffix in {'.h', '.inc', '.json'}}
    return {name: digest(root / name) for name in sorted(names) if (root / name).is_file()}


def generator_runtime(root):
    """Record the environment that generates the bound headers, not the sealing process's environment."""
    def version(distribution):
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            return None
    try:
        from PIL import features
        raqm, freetype = features.version('raqm'), features.version('freetype2')
    except ImportError:
        raqm = freetype = None
    lock = root / 'uv.lock'
    return {'python': sys.version.split()[0], 'Pillow': version('Pillow'),
            'fontTools': version('fonttools'), 'Brotli': version('Brotli'),
            'raqm': raqm, 'freetype': freetype,
            'lock_sha256': digest(lock) if lock.is_file() else None}


def loader_environment_fingerprints(env):
    """Bind allowed loader search values without publishing host paths.

    This identifies the value, not the resolved libraries or system runtime.
    """
    return {name: hashlib.sha256(env[name].encode('utf-8')).hexdigest()
            for name in ALLOWED_LOADER_ENV if env.get(name)}


def tool_fingerprints(build):
    """Hash tool/SDK inputs before any jobs; do not launch the compiler here."""
    docker = build.use_docker()
    for name in COMPILER_ENV:
        # Docker does not forward host compiler search/configuration variables.
        # Host Python generators still run locally, so loader injection remains
        # unsupported with either compiler backend.
        if build.os.environ.get(name) and (not docker or name in HOST_INJECTION_ENV):
            raise ValueError('unsupported compiler environment: ' + name)
    toolchain = build.toolchain()
    headers = {}
    for directory in HEADER_ROOTS:
        include = toolchain / directory
        if not include.is_dir() or not (include / 'stdint.h').is_file():
            raise ValueError('missing compiler include root/stdint.h: ' + directory)
        if include.is_symlink():
            raise ValueError('compiler include root is a symlink: ' + directory)
        for path in sorted(include.rglob('*')):
            if path.is_symlink():
                raise ValueError('compiler header path is a symlink: ' + str(path.relative_to(toolchain)))
            if path.is_file():
                if not path.resolve().is_relative_to(toolchain.resolve()):
                    raise ValueError('compiler header escapes toolchain')
                headers[path.relative_to(toolchain).as_posix()] = digest(path)
    return {'generator_runtime': generator_runtime(build.SRC),
            'loader_environment_sha256': loader_environment_fingerprints(build.os.environ),
            'compiler_headers_sha256': headers,
            'execution_environment': {'backend': 'docker' if docker else 'native',
                                      'image_reference': build.DOCKER_IMAGE if docker else None,
                                      'system_runtime_fingerprint': None},
            'compiler_sha256': digest(build.toolchain() / 'pi32v2/bin/clang'),
            'toolchain_sha256': {name: digest(build.toolchain() / name) for name in
                                 ('pi32v2/bin/ld', 'common/bin/objdump', 'common/bin/objcopy')},
            'sdk_sha256': {name: hashlib.sha256(build.fm1pkg_make.sdk_file(name)).hexdigest()
                           for name in build.SDK_SHA256}}


def check_initial_inputs(build, sources, tools):
    if (input_hashes(build.SRC, include_generated=False) != sources
            or tool_fingerprints(build) != tools):
        raise ValueError('source/tool/SDK inputs changed during asset or loader generation')


def configuration(build):
    flags = build.app_flags()
    # Preprocess only, with exactly the C compilation flags. This captures actual
    # source/generated defaults and conditional macros without a second compile.
    macros = build.tc('cc', *flags, '-dM', '-E', build.FW / 'src/felucca.c')
    defines = dict(re.findall(r'^#define (FELUCCA_\w+)(?:[ \t]+(.*))?$', macros, re.M))
    constants = dict(re.findall(r'^#define (FS|CTL|NPART|NVOICE|NTRK|NSTEP|HALF_FRAMES|C1_NP|NENGINES|ENG_ID_MAX)[ \t]+(.*)$',
                                macros, re.M))
    if not {'FELUCCA_CPU2', 'FELUCCA_ID', 'FELUCCA_SLICE', 'FELUCCA_FM4'} <= defines.keys():
        raise ValueError('compiler did not expose required effective build defines')
    fingerprints = tool_fingerprints(build)
    return {'compile_flags': ['-target', 'pi32v2', *flags], 'effective_defines': defines,
            'logical_constants': constants, 'generator_runtime': fingerprints['generator_runtime'],
            'loader_environment_sha256': fingerprints['loader_environment_sha256'],
            'compiler_headers_sha256': fingerprints['compiler_headers_sha256'],
            'execution_environment': fingerprints['execution_environment'],
            'selective_minsize': build.os.environ.get('FELUCCA_SIZE') != '0',
            'cpu2': build.CPU2, 'product': build.PRODUCT, 'version_override': build.VERSION,
            'compiler': {'version': '\n'.join(line for line in build.tc('pi32v2/bin/clang', '--version').strip().splitlines()
                                              if not line.startswith('InstalledDir:')),
                         'sha256': fingerprints['compiler_sha256']},
            'toolchain_sha256': fingerprints['toolchain_sha256'],
            'sdk_reference': 'AC79NN_SDK_V1.2.1_2023-12-13',
            'sdk_sha256': fingerprints['sdk_sha256']}


def symbol(syms, name):
    values = re.findall(r'^([0-9a-f]+) .*\s' + re.escape(name) + r'$', syms, re.M | re.I)
    if len(values) != 1:
        raise ValueError(f'missing or duplicate resource symbol {name}')
    return int(values[0], 16)


def span(syms, low, high):
    start, end = symbol(syms, low), symbol(syms, high)
    if end < start:
        raise ValueError(f'reversed resource symbols {low}/{high}')
    return {'origin': start, 'end': end, 'reserved_bytes': end-start}


def resources(build, evidence):
    measured = {}
    errors, _ = build.check(*evidence, resources=measured)
    if errors:
        raise ValueError('resource report requires passing build guards: ' + '; '.join(errors))
    _, _, syms, _, _ = evidence
    regions = build.ld_regions()
    origin, capacity = regions['RAMTEXT']
    flash = span(syms, '_rt_start', '_rt_end')
    worker = span(syms, '_c1_start', '_c1_end')
    if flash['origin'] != origin or worker['origin'] < flash['end']:
        raise ValueError('RAMTEXT sections are outside their region or overlap')
    used = max(flash['end'], worker['end']) - origin
    if used > capacity:
        raise ValueError('RAMTEXT exceeds linker region')
    measured['RAMTEXT'] = dict(origin=origin, capacity_bytes=capacity, used_bytes=used,
                              spare_bytes=capacity-used, enforced_spare_min_bytes=0,
                              margin_bytes=capacity-used, authority='firmware/app.ld linker region',
                              sections={'.ram_text': flash['reserved_bytes'],
                                        '.c1_text': worker['reserved_bytes']})
    stacks = {'main_user': span(syms, '_ustack_lo', '_ustack_top'),
              'main_supervisor': span(syms, '_sstack_lo', '_sstack_top'),
              'main_user_guard': span(syms, '_guard0', '_ustack_lo'),
              'main_supervisor_guard': span(syms, '_guard1', '_sstack_lo')}
    if build.CPU2:
        stacks['worker_user_including_guard'] = span(syms, '_c1_ustack', '_c1_ustack_top')
        stacks['worker_supervisor'] = span(syms, '_c1_sstack', '_c1_sstack_top')
        stacks['worker_user_including_guard']['accounted_in'] = 'RAM'
        stacks['worker_supervisor']['accounted_in'] = 'RAM'
    return measured, stacks


def artifact_paths(package):
    if Path(package).name != package or not package.endswith('.fwsc'):
        raise ValueError('invalid resource report package name')
    return ['build/felucca.bin', 'build/felucca.elf', 'build/felucca.dis',
            'build/felucca.dis.profile.json', 'build/gen/resolved-profile.json',
            'build/gen/build-identity.json', 'build/profile-contract.json',
            'build/loader/ota.bin', 'build/' + package]


def write(build, evidence, package, inputs, config):
    measured, stacks = resources(build, evidence)
    from font_resources import linked
    fonts = linked(build.SRC, build.GEN, evidence[2])
    if input_hashes(build.SRC) != inputs or configuration(build) != config:
        raise ValueError('build inputs/configuration changed during target build')
    artifacts = artifact_paths(package)
    report = {'schema_version': 2, 'kind': 'felucca-post-link-resource-report',
              'validation': 'production build guards passed', 'package': package,
              'build_identity': build.BUILD_IDENTITY,
              'configuration': config, 'input_sha256': inputs,
              'configuration_sha256': hashlib.sha256(canonical(config)).hexdigest(),
              'inputs_sha256': hashlib.sha256(canonical(inputs)).hexdigest(),
              'artifact_sha256': {name: digest(build.SRC / name) for name in artifacts},
              'resources': measured, 'stack_reservations': stacks,
              'native_font_resources': fonts,
              'limitations': ['Exact linked allocation for these inputs and artifacts only',
                              'No live stack watermark, CPU/deadline measurement or cost prediction',
                              'Shared RAM/POOL split and worker stacks must not be double-counted']}
    (build.OUT / 'resource-report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    return report


def verify(root, report, *, config, measured, fonts=None):
    """Reject stale artifacts or source/config evidence; no capacity rules are reimplemented."""
    if (type(report.get('schema_version')) is not int or report.get('schema_version') not in (1, 2)
            or report.get('kind') != 'felucca-post-link-resource-report'
            or report.get('validation') != 'production build guards passed'):
        raise ValueError('unsupported resource report')
    if not isinstance(report.get('artifact_sha256'), dict):
        raise ValueError('missing resource report artifact hashes')
    if not isinstance(report.get('configuration'), dict):
        raise ValueError('missing resource report configuration')
    package = report.get('package')
    if not isinstance(package, str) or set(report.get('artifact_sha256', {})) != set(artifact_paths(package)):
        raise ValueError('incomplete resource report artifact set')
    for section in ('input_sha256', 'artifact_sha256'):
        entries = report.get(section)
        if not isinstance(entries, dict) or not entries:
            raise ValueError('missing resource report hashes')
        for name, expected in entries.items():
            path = Path(name)
            if (path.is_absolute() or '..' in path.parts or not isinstance(expected, str)
                    or not re.fullmatch('[0-9a-f]{64}', expected)
                    or not (root / path).is_file() or digest(root / path) != expected):
                raise ValueError(f'stale resource report {section}: {name}')
    if (hashlib.sha256(canonical(report['input_sha256'])).hexdigest() != report.get('inputs_sha256')
            or input_hashes(root) != report['input_sha256']):
        raise ValueError('stale resource report input inventory')
    if report['schema_version'] == 1 and ('build/gen/ui-font-manifest.json' in report['input_sha256']
                                       or 'native_font_resources' in report):
        raise ValueError('schema 1 cannot include native font evidence')
    if (hashlib.sha256(canonical(report['configuration'])).hexdigest() != report.get('configuration_sha256')
            or config != report['configuration']):
        raise ValueError('stale resource report configuration')
    if (report.get('resources'), report.get('stack_reservations')) != measured:
        raise ValueError('stale resource report resource/stack measurements')
    if report['schema_version'] == 2 and (fonts is None or report.get('native_font_resources') != fonts):
        raise ValueError('stale resource report native font measurements')
    if report.get('build_identity') != json.loads((root / 'build/gen/build-identity.json').read_text()):
        raise ValueError('stale resource report build identity')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path, required=True, metavar='REPORT')
    args = parser.parse_args()
    # Standalone verification needs the same unset/empty defaults as build.sh.
    # Apply them only at the CLI entry point, never when the build imports us.
    for name, default in (('JIELI_TOOLCHAIN', '.jieli/toolchain'), ('AC79_SDK', 'fw-AC79_AIoT_SDK')):
        if not _source_os.environ.get(name):
            _source_os.environ[name] = str(Path.home() / default)
    try:
        import build
        report = json.loads(args.verify.read_text())
        if not isinstance(report, dict):
            raise ValueError('invalid resource report object')
        # Restore identity inputs from evidence, then recompute actual flags/macros
        # under the caller's current environment. Feature/profile/font changes fail.
        build.PRODUCT = report['configuration']['product']
        build.VERSION = report['configuration']['version_override']
        build.fm1pkg_make.SDK = build.resolve([])['sdk']
        from profile import generated, check_outputs, contract_json
        name = build.os.environ.get('FELUCCA_PROFILE', 'standard')
        check_outputs(generated(build.SRC, name), build.GEN)
        if (build.OUT / 'profile-contract.json').read_text() != contract_json(build.SRC):
            raise ValueError('stale supported-profile contract')
        from build_identity import check as check_identity
        check_identity(build.SRC, build.GEN)
        elf = build.OUT / 'felucca.elf'
        hdr, syms, dis, rt = build.tc_all(
            ('common/bin/objdump', '-h', elf), ('common/bin/objdump', '-t', elf),
            ('common/bin/objdump', '-d', elf),
            ('common/bin/objdump', '-d', '-j', '.ram_text',
             *(("-j", ".c1_text") if build.CPU2 else ()), elf))
        if dis != (build.OUT / 'felucca.dis').read_text():
            raise ValueError('resource report disassembly differs from ELF')
        evidence = ((build.OUT / 'felucca.bin').read_bytes(), hdr, syms, dis, rt)
        fonts = None
        if report.get('schema_version') == 2:
            from font_resources import linked
            fonts = linked(build.SRC, build.GEN, syms)
        verify(build.SRC, report, config=configuration(build), measured=resources(build, evidence), fonts=fonts)
        print('resource report: artifacts, inputs and configuration match')
    except (KeyError, TypeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
