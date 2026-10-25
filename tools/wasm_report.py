#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build the real browser runtime; publish a receipt only after all inputs stay fresh."""
# Verified archives must not execute cached helpers before checking their source tree.
# os/sys are loaded by Python startup; defer all repository and other stdlib imports.
import os as _source_os
import sys as _source_sys

_source_root = _source_os.path.dirname(_source_os.path.dirname(_source_os.path.realpath(__file__)))
# A malformed invocation or failed archive bootstrap must not leave a prior receipt.
if __name__ == '__main__':
    try:
        _source_os.unlink(_source_os.path.join(_source_root, 'build/emu/runtime-report.json'))
    except FileNotFoundError:
        pass
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
import ast
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import build_report as R

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = 'build/emu/runtime-report.json'
FILES = ('build/emu/felucca.wasm', 'build/emu/index.html', 'build/emu/worklet.js',
         'build/emu/fonts/DotGothic16-subset.woff', 'build/emu/fonts/OFL.txt')
PROFILES = ('build/gen/resolved-profile.json', 'build/profile-contract.json',
            'build/gen/build-identity.json')
RECIPES = ('tools/wasm_report.py', 'web/emu/build.sh', 'web/emu/felucca_web.c')
CONSTANTS = ('FS', 'CTL', 'NPART', 'NVOICE', 'NTRK', 'NSTEP', 'HALF_FRAMES',
             'C1_NP', 'NENGINES', 'ENG_ID_MAX')
ADAPTER = {'FELUCCA_WEB': '1', 'FELUCCA_FLASH': '1', 'FELUCCA_OTA': '0',
           'FELUCCA_UAC': '0', 'FELUCCA_UART': '0',
           # usb.c derives these from the adapter's UAC=0, not native USB flags.
           'FELUCCA_UAC_48K': '0', 'FELUCCA_UAC_AS_FIRST': '0'}
TARGET_ONLY = {
    'FELUCCA_ID': 'native package identity; browser has no package',
    'FELUCCA_OTA_DRYRUN': 'native update transport absent',
    'FELUCCA_OTA_RAMONLY': 'native RAM-only updater absent',
    'FELUCCA_UAC_TONE': 'native USB audio diagnostic absent',
    'FELUCCA_UAC_48K': 'native USB audio rate absent',
    'FELUCCA_UAC_AS_FIRST': 'native USB enumeration absent',
    'FELUCCA_USB_LAYOUT': 'native USB enumeration absent',
    'FELUCCA_USB_PID': 'native USB enumeration absent',
    'FELUCCA_CDC_DEFAULT': 'native USB enumeration absent',
    'FELUCCA_CRASH_CTX': 'native crash capture absent',
    'FELUCCA_SCREEN_CAPTURE': 'native CDC screen capture absent',
    'FELUCCA_MUL64_REPRO': 'native main-loop diagnostic absent',
}
SHARED = set(('ARENA_CHECK BUILD_COMMIT BUILD_DIRTY BUILD_ID BUILD_PR BOOT_POLICY_H '
              'ENGINE_API_REQUIRED ENGINE_API_VERSION ENGINE_H ENG_OMIT ENG_TEST14 '
              'FM4 ICONS CPU2 CDC SLICE SOURCE_REPOSITORY SPLASH_ID VERSION '
              'BUILD_IDENTITY_H UNION_CONTROL_MASK CATEGORY FAVORITES').split())
SHARED = {'FELUCCA_' + name for name in SHARED}


def sha(value):
    return hashlib.sha256(R.canonical(value)).hexdigest()


def command(argv, root, env, log):
    """Only external process seam; retain exact resolved argv and both output streams."""
    with log.open('a') as output:
        output.write(json.dumps([str(a) for a in argv]) + '\n')
        output.flush()
        result = subprocess.run([str(a) for a in argv], cwd=root, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.write(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError(f'command failed ({result.returncode}): {argv[0]}; see {log}')
    return result.stdout.strip()


def shell_words(value, root):
    """Match the old unquoted parameter expansion: IFS splitting, then globbing.

    Quotes inside an environment variable were literal shell characters, not
    shell syntax. Do not replace this with shlex.split or evaluate shell code.
    """
    words = []
    for word in re.split(r'[ \t\n]+', value.strip(' \t\n')):
        if word:
            matches = sorted(glob.glob(word, root_dir=root))
            words.extend(matches or [word])
    return words


def arguments(version, env, root, target=None):
    common = [*shell_words(env.get('EMU_OPT') or '-O2', root),
              '-ffp-contract=off', '-std=gnu99', '-w',
              *shell_words(env.get('EMU_CFLAGS', ''), root)]
    if target is not None:
        # Paired v1 is intentionally bounded. Unknown flags can change source
        # selection, forced includes, ABI, link inputs or postprocessing.
        safe = re.compile(r'-(?:O[0-3sz]|g[0-4]?|msimd128|fno-vectorize|fno-slp-vectorize)')
        if any(not safe.fullmatch(flag) for flag in common
               if flag not in ('-ffp-contract=off', '-std=gnu99', '-w')):
            raise ValueError('unsupported paired EMU_OPT/EMU_CFLAGS option')
        native = target['configuration']['effective_defines']
        if native.get('FELUCCA_FLASH') != '1':
            raise ValueError('paired runtime requires native FELUCCA_FLASH=1')
        for name in ('FELUCCA_CPU2', 'FELUCCA_CDC', 'FELUCCA_ICONS'):
            if native.get(name) not in ('0', '1'):
                raise ValueError(f'unsupported paired {name}')
            common.append(f'-D{name}={native[name]}')
    common += [f'-DFELUCCA_VERSION="{version}"', '-Ibuild/gen', '-Ifirmware/src']
    compile_argv = ['emcc', *common, '--no-entry', '-sSTANDALONE_WASM',
                    '-sSTACK_SIZE=1048576', '-sINITIAL_MEMORY=33554432', '-sFILESYSTEM=0',
                    '-o', FILES[0], 'web/emu/felucca_web.c']
    preprocess_argv = ['emcc', *common, '-dM', '-E', 'web/emu/felucca_web.c']
    return compile_argv, preprocess_argv


def macros(output):
    return dict(re.findall(r'^#define ([A-Za-z_]\w*)(?:[ \t]+(.*))?$', output, re.M))


def logical_mapping(native, runtime, native_constants, runtime_constants):
    rows = {}
    # isr_assert.h deliberately defaults to simulated interrupt-depth checks
    # off-target. Keep the browser trap/checks, independent of whether the
    # target enables its different diagnostic counter; this is not ISR proof.
    if (native.get('FELUCCA_ISR_ASSERT') not in ('0', '1') or
            runtime.get('FELUCCA_ISR_ASSERT') != '1'):
        raise ValueError('unsupported ISR assertion adapter: runtime must enable simulated checks')
    if native.get('FELUCCA_ENG_TEST14', '0') != '0' or runtime.get('FELUCCA_ENG_TEST14') != '0':
        raise ValueError('paired test engine is unsupported')
    for values in (native, runtime):
        if values.get('FELUCCA_ENG_OMIT', '(-1)') not in ('(-1)', '-1'):
            raise ValueError('paired engine omission is unsupported')
    for name in sorted(native.keys() | runtime.keys()):
        a, b = native.get(name), runtime.get(name)
        if name == 'FELUCCA_ISR_ASSERT':
            rule = 'browser simulated interrupt-depth assertions enabled; native diagnostic recorded'
        elif name in ADAPTER:
            if b != ADAPTER[name]:
                raise ValueError(f'wrong browser adapter macro: {name}')
            rule = 'browser adapter override'
        elif name in TARGET_ONLY:
            if b is not None and b != a:
                raise ValueError(f'target-only runtime macro mismatch: {name}')
            rule = TARGET_ONLY[name]
        elif name in SHARED or name.startswith('FELUCCA_PROFILE_'):
            if a != b:
                raise ValueError(f'logical macro mismatch: {name}')
            rule = 'equal'
        else:
            raise ValueError(f'unmapped FELUCCA macro: {name}')
        rows[name] = {'native': a, 'runtime': b, 'rule': rule}
    constants = {}
    for name in ('NPART', 'NVOICE', 'NSTEP', 'HALF_FRAMES'):
        if name not in native_constants or name not in runtime_constants:
            raise ValueError(f'missing logical constant: {name}')
    for name in sorted(native_constants.keys() | runtime_constants.keys()):
        if name not in CONSTANTS or native_constants.get(name) != runtime_constants.get(name):
            raise ValueError(f'logical constant mismatch: {name}')
        constants[name] = {'native': native_constants[name], 'runtime': runtime_constants[name],
                           'rule': 'equal'}
    return {'defines': rows, 'constants': constants}


def source_identity(root):
    from source_archive import source_files, verify_tree
    from build_identity import repository, git
    if (root / 'SOURCE-PINS.json').exists():
        pins = verify_tree(root)
        return {'repository': pins.get('repository'), 'revision': pins['firmware_revision'],
                'committed_files_sha256': sha(pins['files']),
                'engines_revision': pins['engines']['revision']}
    engine, files = source_files(root)  # clean committed source, exact initialized pin
    inventory = {name: {'mode': mode, 'sha256': hashlib.sha256(data).hexdigest()}
                 for name, (mode, data) in files.items()}
    return {'repository': repository(root), 'revision': git(root, 'rev-parse', 'HEAD'),
            'committed_files_sha256': sha(inventory), 'engines_revision': engine['revision']}


def sdk_tools(emcc, root, env, log):
    # em-config is the installed producer's authority, including Homebrew wrappers.
    config = emcc.parent / 'em-config'
    if not config.is_file():
        raise ValueError('SDK provenance missing: no em-config beside resolved emcc')
    get = lambda key: command([config, key], root, env, log)
    sdk = Path(get('EMSCRIPTEN_ROOT')).resolve()
    if not (sdk / 'emcc.py').is_file():
        raise ValueError('SDK provenance missing: invalid Emscripten root')
    llvm, binaryen, cache = (Path(get(key)).resolve() for key in ('LLVM_ROOT', 'BINARYEN_ROOT', 'CACHE'))
    node = get('NODE_JS')
    if node.startswith('['):
        node = ast.literal_eval(node)[0]
    node = Path(shutil.which(node, path=env.get('PATH')) or node).resolve()
    # Homebrew's wrapper selects its own Python independently of the caller.
    wrapper = emcc.read_text(errors='ignore')[:8192]
    selected_python = re.search(r'EMSDK_PYTHON="([^"$]+)"', wrapper)
    python_name = selected_python[1] if selected_python else env.get('EMSDK_PYTHON', 'python3')
    python = Path(shutil.which(python_name, path=env.get('PATH')) or python_name).resolve()
    tools = {'emcc': emcc, 'clang': llvm / 'clang', 'wasm_ld': llvm / 'wasm-ld',
             'wasm_opt': binaryen / 'bin/wasm-opt', 'node': node, 'python': python,
             'em_config': config.resolve()}
    if any(not path.is_file() for path in tools.values()):
        raise ValueError('SDK provenance missing: a configured tool is absent')
    configs = [Path(env['EM_CONFIG'])] if env.get('EM_CONFIG') else [
        sdk / '.emscripten', sdk.parent.parent / '.emscripten', Path.home() / '.emscripten']
    configuration = next((p.resolve() for p in configs if p.is_file()), None)
    if configuration is None:
        raise ValueError('SDK provenance missing: no actual configuration file')
    tools['configuration'] = configuration
    # Include compiler drivers, sysroot, prebuilt libraries and all configured
    # LLVM/Binaryen inputs. Mutable Python bytecode, Git metadata and lock files
    # are not compiler inputs. Cache sanity receipts are machine-specific only.
    # The installed sysroot (headers plus all installed library variants) is a
    # bounded installation closure. Ports downloads/build scratch, test caches
    # and unrelated cache roots are not inputs to this no-ports recipe.
    roots = {'emscripten': sdk, 'llvm': llvm.parent, 'binaryen': binaryen,
             'sysroot': cache / 'sysroot'}
    version = command([emcc, '--version'], root, env, log)
    revision = None
    emsdk = Path(env['EMSDK']) if env.get('EMSDK') else None
    if emsdk and (emsdk / '.git').exists():
        revision = command(['git', '-C', emsdk, 'rev-parse', 'HEAD'], root, env, log)
    release = (sdk / 'emscripten-version.txt').read_text().strip()
    return tools, roots, version, release, revision


def tool_fingerprint(resolved):
    tools, roots, version, release, revision = resolved
    inventory = {}
    for label, base in roots.items():
        if not base.is_dir():
            raise ValueError(f'SDK provenance missing: {label}')
        for path in sorted(base.rglob('*')):
            relative = path.relative_to(base)
            if (any(part in ('.git', '__pycache__') for part in relative.parts)
                    or (label == 'emscripten' and relative.parts[0] in
                        ('cache', 'test', 'tests'))
                    or path.suffix in ('.pyc', '.pyo', '.lock')
                    or path.name in ('sanity.txt', 'cache.lock')):
                continue
            if path.is_file():
                inventory[label + '/' + relative.as_posix()] = R.digest(path)
    inventory.update({'tool/' + name: R.digest(path) for name, path in tools.items()})
    return {'emcc_version': version, 'emcc_sha256': R.digest(tools['emcc']),
            'clang_sha256': R.digest(tools['clang']), 'wasm_ld_sha256': R.digest(tools['wasm_ld']),
            'wasm_opt_sha256': R.digest(tools['wasm_opt']), 'sdk_release': release,
            'sdk_content_manifest_sha256': sha(inventory), 'emsdk_revision': revision}


def snapshot(inputs, profiles, configuration, target):
    return sha({'input_sha256': inputs, 'profile_sha256': profiles,
                'toolchain': configuration['toolchain'],
                'recipe_sha256': configuration['recipe_sha256'], 'target': target})


def output_names(root):
    return {p.relative_to(root).as_posix() for p in (root / 'build/emu').rglob('*')
            if (p.is_file() or p.is_symlink()) and p.relative_to(root).as_posix() != RECEIPT}


def output_files(root, *, exact=True):
    if exact and output_names(root) != set(FILES):
        raise ValueError('unexpected runtime output set')
    result = []
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError(f'missing/unsafe runtime output: {name}')
        result.append({'path': name, 'sha256': R.digest(path), 'bytes': path.stat().st_size})
    return result


def verify_receipt(root, receipt, target_report, *, target_report_sha256):
    """Offline pairing check, without invoking any compiler or re-inventorying source."""
    root = Path(root)
    fields = {'schema_version', 'kind', 'source', 'target', 'profile_sha256', 'input_sha256',
              'configuration', 'logical_mapping', 'freshness', 'files'}
    if (not isinstance(receipt, dict) or set(receipt) != fields or
            type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 1 or
            receipt.get('kind') != 'felucca-wasm-build-receipt'):
        raise ValueError('unsupported runtime receipt')
    target = {'report_sha256': target_report_sha256,
              'configuration_sha256': target_report['configuration_sha256']}
    if receipt.get('target') != target or receipt.get('input_sha256') != target_report['input_sha256']:
        raise ValueError('runtime/native report mismatch')
    if receipt.get('profile_sha256') != {p: R.digest(root / p) for p in PROFILES}:
        raise ValueError('stale runtime profile/identity')
    config = receipt['configuration']
    config_fields = {'producer_path', 'recipe_sha256', 'compile_argv', 'preprocess_argv',
                     'effective_defines', 'logical_mapping_version',
                     'logical_configuration_sha256', 'preview', 'toolchain'}
    if not isinstance(config, dict) or set(config) != config_fields:
        raise ValueError('unsupported runtime configuration fields')
    toolchain = config['toolchain']
    expected_tools = {'emcc_version', 'emcc_sha256', 'clang_sha256', 'wasm_ld_sha256',
                      'wasm_opt_sha256', 'sdk_release', 'sdk_content_manifest_sha256',
                      'emsdk_revision'}
    if (set(toolchain) != expected_tools or
            any(not isinstance(toolchain[k], str) or
                not re.fullmatch('[0-9a-f]{64}', toolchain[k])
                for k in expected_tools if k.endswith('_sha256')) or
            not isinstance(toolchain['emcc_version'], str) or not toolchain['emcc_version'] or
            not isinstance(toolchain['sdk_release'], str) or not toolchain['sdk_release'] or
            (toolchain['emsdk_revision'] is not None and
             not re.fullmatch('[0-9a-f]{40}', toolchain['emsdk_revision']))):
        raise ValueError('invalid runtime toolchain fingerprints')
    if type(config['preview']) is not bool:
        raise ValueError('invalid runtime preview flag')
    if config['recipe_sha256'] != {p: target_report['input_sha256'].get(p) for p in RECIPES}:
        raise ValueError('runtime recipe differs from native sources')
    runtime = config['effective_defines']
    constants = {name: row['runtime'] for name, row in receipt['logical_mapping']['constants'].items()}
    mapping = logical_mapping(target_report['configuration']['effective_defines'], runtime,
                              target_report['configuration']['logical_constants'], constants)
    if receipt['logical_mapping'] != mapping or config['logical_configuration_sha256'] != sha(mapping):
        raise ValueError('invalid logical runtime mapping')
    version = target_report['build_identity']['version']
    # Recompute the bounded flags from the retained invocation, rather than
    # trusting an independent string that claims to describe those bytes.
    argv = config['compile_argv']
    prefix = argv[1:argv.index('-ffp-contract=off')]
    extras = argv[argv.index('-w')+1:argv.index(f'-DFELUCCA_CPU2={runtime["FELUCCA_CPU2"]}')]
    expected = arguments(version, {'EMU_OPT': ' '.join(prefix), 'EMU_CFLAGS': ' '.join(extras)},
                         root, target_report)
    if (argv, config['preprocess_argv']) != expected:
        raise ValueError('runtime compile/preprocess argv mismatch')
    if (config['producer_path'] != 'web/emu' or type(config['logical_mapping_version']) is not int or
            config['logical_mapping_version'] != 1):
        raise ValueError('unsupported runtime mapping version')
    if receipt.get('files') != output_files(root):
        raise ValueError('stale runtime artifacts')
    expected_snapshot = snapshot(receipt['input_sha256'], receipt['profile_sha256'], config, target)
    if receipt.get('freshness') != {'before_sha256': expected_snapshot, 'after_sha256': expected_snapshot}:
        raise ValueError('runtime freshness evidence mismatch')
    source = receipt['source']
    if not isinstance(source, dict) or set(source) != {
            'repository', 'revision', 'committed_files_sha256', 'engines_revision'}:
        raise ValueError('invalid runtime source fields')
    identity = target_report['build_identity']
    if source['repository'] != identity['repository'] or source['revision'] != identity['revision']:
        raise ValueError('runtime source identity mismatch')
    resolved = json.loads((root / PROFILES[0]).read_text())
    # Exact source/archive closure is also checked by the enclosing bundle.
    if not re.fullmatch('[0-9a-f]{64}', source['committed_files_sha256']):
        raise ValueError('invalid runtime committed-source digest')
    if (not re.fullmatch('[0-9a-f]{40}', source['engines_revision']) or
            source['engines_revision'] != resolved['source_pins']['engines_gitlink']):
        raise ValueError('runtime Engines pin mismatch')
    return config


def build_runtime(root, target_path=None, env=None):
    root = Path(root).resolve()
    receipt_path = root / RECEIPT
    receipt_path.unlink(missing_ok=True)
    receipt_path.with_suffix('.json.tmp').unlink(missing_ok=True)
    env = dict(os.environ if env is None else env)
    logs = root / 'build/wasm-report'
    logs.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='attempt-', suffix='.log', dir=logs)
    os.close(descriptor)
    log = Path(name)  # Each failed/successful attempt survives subsequent retries.
    target = None
    if target_path is not None:
        target_path = Path(target_path).resolve()
        from profile import read_json
        target = read_json(target_path)  # Reject duplicate keys before any compiler/tool work.
        json.dumps(target, allow_nan=False)  # JSON's nonfinite extensions are not evidence.
        command([sys.executable, 'tools/build_report.py', '--verify', target_path], root, env, log)
        # Frozen cache makes implicit sysroot/library regeneration a hard failure.
        env['EM_FROZEN_CACHE'] = '1'
        permitted_em = {'EM_CONFIG', 'EM_CACHE', 'EM_PORTS', 'EM_LLVM_ROOT',
                        'EM_BINARYEN_ROOT', 'EM_NODE_JS', 'EM_FROZEN_CACHE'}
        inherited_options = {
            'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH',
            'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'COMPILER_PATH', 'GCC_EXEC_PREFIX', 'SDKROOT',
            'MACOSX_DEPLOYMENT_TARGET', 'CCC_OVERRIDE_OPTIONS', 'CLANG_CONFIG_FILE_SYSTEM_DIR',
            'CLANG_CONFIG_FILE_USER_DIR', 'CLANG_NO_DEFAULT_CONFIG', 'LD_PRELOAD',
            'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH',
        }
        forbidden = [k for k in env if env[k] and
                     (k.startswith(('EMCC_', '_EMCC_', 'EMMAKEN_')) or
                      (k.startswith('EM_') and k not in permitted_em) or k in inherited_options)]
        if forbidden:
            raise ValueError('unsupported paired compiler environment: ' + ', '.join(sorted(forbidden)))
    command([sys.executable, 'tools/profile.py', '--check'], root, env, log)
    from build_identity import check
    check(root, root / 'build/gen')
    if not (root / 'build/gen/felucca_tables.h').is_file():
        raise ValueError('run ./build.sh once first (build/gen)')
    identity = json.loads((root / PROFILES[2]).read_text())
    emcc_name = shutil.which('emcc', path=env.get('PATH'))
    if not emcc_name:
        raise ValueError('no emcc (Emscripten)')
    emcc = Path(emcc_name).resolve()
    for directory in (root / 'build/emu', root / 'build/emu/fonts'):
        if directory.is_symlink():
            raise ValueError('unsafe runtime output directory')
    compile_argv, preprocess_argv = arguments(identity['version'], env, root, target)
    inputs = R.input_hashes(root)
    profiles = {p: R.digest(root / p) for p in PROFILES if (root / p).is_file()}
    target_link = ({'report_sha256': R.digest(target_path),
                    'configuration_sha256': target['configuration_sha256']} if target else None)
    provenance_error = None
    try:
        source = source_identity(root)
        resolved_tools = sdk_tools(emcc, root, env, log)
        toolchain = tool_fingerprint(resolved_tools)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if target:
            raise
        provenance_error = str(error)
    # Unpaired developer invocations retain their old availability/flags even
    # when a nonstandard SDK or dirty source cannot supply a sealed receipt.
    definitions = None
    if provenance_error is None:
        definitions = macros(command([emcc, *preprocess_argv[1:]], root, env, log))
    mapping = logical_mapping(target['configuration']['effective_defines'],
                              {k: v for k, v in definitions.items() if k.startswith('FELUCCA_')},
                              target['configuration']['logical_constants'],
                              {k: definitions[k] for k in CONSTANTS if k in definitions}) if target else None
    config = None
    if provenance_error is None:
        config = {'producer_path': 'web/emu', 'recipe_sha256': {p: R.digest(root / p) for p in RECIPES},
                  'compile_argv': compile_argv, 'preprocess_argv': preprocess_argv,
                  'effective_defines': {k: v for k, v in definitions.items() if k.startswith('FELUCCA_')},
                  'logical_mapping_version': 1, 'logical_configuration_sha256': sha(mapping),
                  'preview': env.get('EMU_PREVIEW', '1') != '0', 'toolchain': toolchain}
        before = snapshot(inputs, profiles, config, target_link)
    # Remove only this producer's known outputs; unknown leftovers fail closed.
    for name in FILES:
        path = root / name
        path.unlink(missing_ok=True)
    (root / 'build/emu/fonts').mkdir(parents=True, exist_ok=True)
    command([emcc, *compile_argv[1:]], root, env, log)
    page = (root / 'web/emu/index.html').read_bytes().replace(b'@VERSION@', identity['version'].encode())
    page = page.replace(b'@PREVIEW@', b'' if env.get('EMU_PREVIEW', '1') == '0' else b' (preview)')
    (root / FILES[1]).write_bytes(page)
    for name in FILES[2:]:
        shutil.copyfile(root / name.replace('build/emu/', 'web/emu/', 1), root / name)
    files = output_files(root, exact=target is not None)
    if target is None and output_names(root) != set(FILES):
        provenance_error = 'extra developer runtime files; exact output inventory cannot be sealed'
    if provenance_error:
        print('emu: receipt unavailable: ' + provenance_error)
        print(f'emu: build/emu ({files[0]["bytes"]} B wasm, {identity["version"]})')
        return None
    if (R.input_hashes(root) != inputs or {p: R.digest(root / p) for p in profiles} != profiles
            or source_identity(root) != source or tool_fingerprint(resolved_tools) != toolchain
            or output_files(root) != files
            or (target_path is not None and R.digest(target_path) != target_link['report_sha256'])):
        raise ValueError('source/generated/profile/report/tool/SDK inputs changed during runtime build')
    after = snapshot(R.input_hashes(root), {p: R.digest(root / p) for p in profiles}, config, target_link)
    if after != before:
        raise ValueError('source/generated/profile inputs changed before runtime receipt publication')
    receipt = {'schema_version': 1, 'kind': 'felucca-wasm-build-receipt', 'source': source,
               'target': target_link, 'profile_sha256': profiles, 'input_sha256': inputs,
               'configuration': config, 'logical_mapping': mapping,
               'freshness': {'before_sha256': before, 'after_sha256': after}, 'files': files}
    if target:
        verify_receipt(root, receipt, target, target_report_sha256=target_link['report_sha256'])
    temporary = receipt_path.with_suffix('.json.tmp')
    try:
        temporary.write_bytes(R.canonical(receipt) + b'\n')
        temporary.replace(receipt_path)  # last written, never bless stale Wasm on failure
    finally:
        temporary.unlink(missing_ok=True)
    print(f'emu: build/emu ({files[0]["bytes"]} B wasm, {identity["version"]})')
    return receipt


def main():
    # Before parsing, including malformed invocations, retire the old receipt.
    (ROOT / RECEIPT).unlink(missing_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-report', type=Path)
    args = parser.parse_args()
    try:
        build_runtime(ROOT, args.target_report)
    except (KeyError, TypeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
