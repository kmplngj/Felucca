#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exact resource extraction, authoritative boundary failures and stale-evidence refusal."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build as B
import build_report as R


def symbols(values):
    return ''.join(f'{value:08x} g .bss 00000000 {name}\n' for name, value in values.items())


class ResourceReport(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {'FELUCCA_CRASH_CTX': '0'})
        environment.start()
        self.addCleanup(environment.stop)
        fonts = patch('font_resources.linked', return_value={})
        fonts.start()
        self.addCleanup(fonts.stop)
        cpu = patch.object(B, 'CPU2', False)
        cpu.start()
        self.addCleanup(cpu.stop)
        regions = B.ld_regions()
        self.values = {'_start': B.APP_XIP, '_bss_end': regions['RAM'][0] + 256,
                       '_pool_start': regions['POOL'][0], '_pool_end': regions['POOL'][0] + 256,
                       '_rt_start': regions['RAMTEXT'][0], '_rt_end': regions['RAMTEXT'][0] + 100,
                       '_c1_start': regions['RAMTEXT'][0] + 100, '_c1_end': regions['RAMTEXT'][0] + 100,
                       '_guard0': 0x01C74000, '_ustack_lo': 0x01C74100, '_ustack_top': 0x01C7A000,
                       '_guard1': 0x01C7A000, '_sstack_lo': 0x01C7A100, '_sstack_top': 0x01C7C000}
        self.noinit = regions['NOINIT'][1] - 100
        self.image = bytes.fromhex('04818000') + bytes(12)

    def evidence(self, *, tail=0, worker=False):
        used = self.noinit + tail
        hdr = f' 5 .noinit {used:08x} 01c7c000 01c7c000 00040000 2**2\n'
        syms = symbols(self.values) + f'01c7c000 g .noinit {self.noinit:08x} retained\n'
        rt = 'Disassembly of section .ram_text:\n 1c00000: 00 00 \tret\n'
        if worker:
            rt += 'Disassembly of section .c1_text:\n 1c00064: 00 00 \tcall r0\n'
        return self.image, hdr, syms, ' 2000120: 00 00 \tr0 = 0\n', rt

    def test_exact_spans_margins_and_reserved_stacks(self):
        measured, stacks = R.resources(B, self.evidence())
        self.assertEqual(set(measured), {'app', 'RAM', 'POOL', 'RAMTEXT', 'NOINIT'})
        self.assertEqual(measured['RAM']['used_bytes'], 256)
        self.assertEqual(measured['RAM']['margin_bytes'], 73728 - 256 - B.RAM_SPARE_MIN)
        self.assertEqual(measured['NOINIT']['spare_bytes'], 100)
        self.assertEqual(measured['NOINIT']['margin_bytes'], 0)
        self.assertEqual(measured['RAMTEXT']['used_bytes'], 100)
        self.assertEqual(stacks['main_user']['reserved_bytes'], 24320)
        self.assertEqual(stacks['main_supervisor']['reserved_bytes'], 7936)
        self.assertEqual(stacks['main_user_guard']['reserved_bytes'], 256)
        self.assertNotIn('worker_supervisor', stacks)

    def test_authoritative_one_byte_floors_and_anonymous_tail(self):
        for region, symbol_name, floor in (('RAM', '_bss_end', B.RAM_SPARE_MIN),
                                            ('POOL', '_pool_end', B.POOL_SPARE_MIN)):
            origin, size = B.ld_regions()[region]
            self.values[symbol_name] = origin + size - floor
            self.assertEqual(R.resources(B, self.evidence())[0][region]['margin_bytes'], 0)
            self.values[symbol_name] += 1
            with self.assertRaisesRegex(ValueError, 'headroom'):
                R.resources(B, self.evidence())
            self.values[symbol_name] = origin + 256
        with self.assertRaisesRegex(ValueError, 'NOINIT headroom 99 B'):
            R.resources(B, self.evidence(tail=1))
        with patch.dict(os.environ, FELUCCA_CRASH_CTX='1'):
            self.noinit += B.CRASH_CTX_NOINIT
            self.assertEqual(R.resources(B, self.evidence())[0]['NOINIT']['enforced_spare_min_bytes'], 24)
            with self.assertRaisesRegex(ValueError, 'NOINIT headroom 23 B'):
                R.resources(B, self.evidence(tail=1))

    def test_missing_reversed_overlap_or_overflow_evidence_refused(self):
        for name in ('_bss_end', '_rt_start', '_c1_end', '_ustack_lo'):
            value = self.values.pop(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                R.resources(B, self.evidence())
            self.values[name] = value
        for name, value in (('_rt_end', 0), ('_c1_start', self.values['_rt_start']),
                            ('_c1_end', self.values['_rt_start'] + 0x6001), ('_ustack_top', 0)):
            original = self.values[name]
            self.values[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                R.resources(B, self.evidence())
            self.values[name] = original
        evidence = list(self.evidence())
        evidence[1] = ''
        with self.assertRaisesRegex(ValueError, 'missing .noinit'):
            R.resources(B, evidence)
        evidence = list(self.evidence())
        evidence[-1] = ' 1c00000: 00 00 \tcall r0\n'
        with self.assertRaisesRegex(ValueError, 'contains calls'):
            R.resources(B, evidence)

    def test_worker_stacks_are_already_in_ram_allocation(self):
        self.values.update(_c1_ustack=0x01C09000, _c1_ustack_top=0x01C0A000,
                           _c1_sstack=0x01C0A000, _c1_sstack_top=0x01C0A100)
        self.values['_c1_end'] += 20
        with patch.object(B, 'CPU2', True):
            _, stacks = R.resources(B, self.evidence(worker=True))
        self.assertEqual(stacks['worker_user_including_guard']['reserved_bytes'], 4096)
        self.assertEqual(stacks['worker_supervisor']['reserved_bytes'], 256)
        self.assertEqual(stacks['worker_supervisor']['accounted_in'], 'RAM')

    def test_stale_artifact_inventory_configuration_and_measurements_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = 'felucca.fwsc'
            for name in R.artifact_paths(package):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}\n' if 'build-identity' in name else name)
            source = root / 'source.c'
            source.write_text('source')
            inputs = {'source.c': R.digest(source)}
            config = {'actual': 'flags'}
            measured = R.resources(B, self.evidence())
            with patch.object(B, 'SRC', root), patch.object(B, 'OUT', root / 'build'), \
                    patch.object(B, 'BUILD_IDENTITY', {}), patch.object(R, 'input_hashes', return_value=inputs), \
                    patch.object(R, 'configuration', return_value=config):
                before = R.write(B, self.evidence(), package, inputs, config)
                first = (root / 'build/resource-report.json').read_bytes()
                R.write(B, self.evidence(), package, inputs, config)
                self.assertEqual(first, (root / 'build/resource-report.json').read_bytes())
                R.verify(root, before, config=config, measured=measured, fonts={})
                legacy = copy.deepcopy(before)
                legacy['schema_version'] = 1
                legacy.pop('native_font_resources')
                R.verify(root, legacy, config=config, measured=measured)
                for mutate in (
                        lambda r: r['artifact_sha256'].pop('build/felucca.elf'),
                        lambda r: r['resources']['RAM'].update(used_bytes=-1),
                        lambda r: r.pop('native_font_resources'),
                        lambda r: r.pop('resources'), lambda r: r.pop('stack_reservations'),
                        lambda r: r.update(build_identity={'revision': 'false'}),
                        lambda r: r['configuration'].update(actual='other')):
                    changed = copy.deepcopy(before)
                    mutate(changed)
                    with self.assertRaises(ValueError):
                        R.verify(root, changed, config=config, measured=measured, fonts={})
                with self.assertRaisesRegex(ValueError, 'configuration'):
                    R.verify(root, before, config={'actual': 'different'}, measured=measured, fonts={})
                elf = root / 'build/felucca.elf'
                elf.write_text('stale')
                with self.assertRaisesRegex(ValueError, 'felucca.elf'):
                    R.verify(root, before, config=config, measured=measured, fonts={})
                elf.write_text('build/felucca.elf')
                source.write_text('changed dirty input')
                with self.assertRaisesRegex(ValueError, 'source.c'):
                    R.verify(root, before, config=config, measured=measured, fonts={})

    def test_initial_source_inventory_excludes_stale_generated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.c'
            source.write_text('source')
            generated = root / 'build/gen/generated.h'
            generated.parent.mkdir(parents=True)
            generated.write_text('old generated')
            def inventory(command):
                return b'source.c\0' if '--recurse-submodules' in command else b''
            with patch.object(R.subprocess, 'check_output', side_effect=inventory):
                initial = R.input_hashes(root, include_generated=False)
                generated.write_text('freshly generated')
                self.assertEqual(initial, R.input_hashes(root, include_generated=False))
                self.assertEqual(set(initial), {'source.c'})
                self.assertEqual(set(R.input_hashes(root)), {'source.c', 'build/gen/generated.h'})
                source.write_text('changed during generation')
                self.assertNotEqual(initial, R.input_hashes(root, include_generated=False))

    def test_effective_flags_preprocess_only_and_normalize_compiler_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            tc = Path(folder)
            for name in ('pi32v2/bin/clang', 'pi32v2/bin/ld', 'common/bin/objdump', 'common/bin/objcopy'):
                path = tc / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            for name in R.HEADER_ROOTS:
                path = tc / name / 'stdint.h'; path.parent.mkdir(parents=True); path.write_text('fixture header')
            def command(tool, *args):
                if tool == 'cc':
                    self.assertIn('-E', args)
                    self.assertIn('-dM', args)
                    self.assertNotIn('-c', args)
                    self.assertIn('-Os', args)
                    return ('#define FELUCCA_ENGINE_H\n#define FELUCCA_CPU2 1\n'
                            '#define FELUCCA_ID "FM-1_900"\n#define FELUCCA_SLICE 1\n#define FELUCCA_FM4 0\n'
                            '#define NPART 4\n#define NTRK NPART\n#define NSTEP 64\n')
                return 'clang version 4.0.1\nInstalledDir: /different/workspace\n'
            with patch.object(B, 'tc', side_effect=command), patch.object(B, 'toolchain', return_value=tc), \
                    patch.object(B.fm1pkg_make, 'sdk_file', return_value=b'sdk'):
                result = R.configuration(B)
            self.assertEqual(result['effective_defines']['FELUCCA_CPU2'], '1')
            self.assertEqual(result['effective_defines']['FELUCCA_ENGINE_H'], '')
            self.assertNotIn('InstalledDir', result['compiler']['version'])
            self.assertEqual(result['logical_constants'], {'NPART': '4', 'NTRK': 'NPART', 'NSTEP': '64'})
            self.assertEqual(result['generator_runtime'], R.generator_runtime(B.SRC))

    def test_generator_environment_is_bound_before_asset_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'uv.lock').write_text('locked generator inputs\n')
            before = R.generator_runtime(root)
            self.assertEqual(before['lock_sha256'], R.digest(root / 'uv.lock'))
            self.assertNotIn(str(root), json.dumps(before))
            tools = {'generator_runtime': before}
            (root / 'uv.lock').write_text('different lock\n')
            with patch.object(R, 'input_hashes', return_value={}), \
                    patch.object(R, 'tool_fingerprints', return_value={'generator_runtime': R.generator_runtime(root)}):
                with self.assertRaisesRegex(ValueError, 'source/tool/SDK inputs changed'):
                    R.check_initial_inputs(B, {}, tools)

    def test_ci_python_loader_environment_is_bound_and_changes_refused(self):
        self.enterContext(patch.object(B, 'use_docker', return_value=False))
        ci_value = '/opt/hostedtoolcache/Python/3.12.15/x64/lib'
        expected = {'LD_LIBRARY_PATH': hashlib.sha256(ci_value.encode('utf-8')).hexdigest()}
        with tempfile.TemporaryDirectory() as folder:
            tc = Path(folder)
            for name in ('pi32v2/bin/clang', 'pi32v2/bin/ld', 'common/bin/objdump', 'common/bin/objcopy'):
                path = tc / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture tool')
            for name in R.HEADER_ROOTS:
                path = tc / name / 'stdint.h'; path.parent.mkdir(parents=True); path.write_text('fixture header')
            macros = ('#define FELUCCA_CPU2 0\n#define FELUCCA_ID "FM-1_900"\n'
                      '#define FELUCCA_SLICE 1\n#define FELUCCA_FM4 0\n')
            with patch.object(B, 'toolchain', return_value=tc), \
                    patch.object(B.fm1pkg_make, 'sdk_file', return_value=b'sdk'), \
                    patch.object(B, 'tc', side_effect=lambda tool, *args: macros if tool == 'cc' else 'clang fixture'), \
                    patch.object(R, 'input_hashes', return_value={}), \
                    patch.dict(os.environ, {'LD_LIBRARY_PATH': ci_value}):
                before = R.tool_fingerprints(B)
                self.assertEqual(R.ALLOWED_LOADER_ENV, ('LD_LIBRARY_PATH',))
                self.assertEqual(R.loader_environment_fingerprints({}), {})
                self.assertEqual(R.loader_environment_fingerprints({'LD_LIBRARY_PATH': ''}), {})
                self.assertEqual(R.loader_environment_fingerprints({'LD_LIBRARY_PATH': ci_value}), expected)
                self.assertNotIn(ci_value, json.dumps(expected))
                self.assertEqual(before['loader_environment_sha256'], expected)
                self.assertEqual(R.configuration(B)['loader_environment_sha256'], expected)
                R.check_initial_inputs(B, {}, before)
                for changed in (ci_value + '/changed', ''):
                    with self.subTest(changed=changed), patch.dict(os.environ, {'LD_LIBRARY_PATH': changed}):
                        self.assertNotEqual(before['loader_environment_sha256'],
                                            R.tool_fingerprints(B)['loader_environment_sha256'])
                        with self.assertRaisesRegex(ValueError, 'source/tool/SDK inputs changed'):
                            R.check_initial_inputs(B, {}, before)
                for forbidden in ('CPATH', 'LD_PRELOAD', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES'):
                    with self.subTest(forbidden=forbidden), patch.dict(os.environ, {forbidden: 'injected'}):
                        with self.assertRaisesRegex(ValueError, 'unsupported compiler environment: ' + forbidden):
                            R.tool_fingerprints(B)

    def test_installed_headers_missing_changed_and_injected_search_paths(self):
        self.enterContext(patch.object(B, 'use_docker', return_value=False))
        for name in R.COMPILER_ENV:
            with self.subTest(name=name), patch.dict(os.environ, {name: 'injected'}):
                with self.assertRaisesRegex(ValueError, 'unsupported compiler environment: ' + name):
                    R.tool_fingerprints(B)
        with tempfile.TemporaryDirectory() as folder:
            tc = Path(folder)
            for name in ('pi32v2/bin/clang', 'pi32v2/bin/ld', 'common/bin/objdump', 'common/bin/objcopy'):
                path = tc / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture tool')
            with patch.object(B, 'toolchain', return_value=tc), patch.object(B.fm1pkg_make, 'sdk_file', return_value=b'sdk'):
                with self.assertRaisesRegex(ValueError, 'missing compiler include root'):
                    R.tool_fingerprints(B)
                for name in R.HEADER_ROOTS:
                    path = tc / name / 'stdint.h'; path.parent.mkdir(parents=True); path.write_text('fixture header')
                before = R.tool_fingerprints(B)
                header = tc / R.HEADER_ROOTS[0] / 'stdint.h'; header.write_text('changed header')
                self.assertNotEqual(before['compiler_headers_sha256'], R.tool_fingerprints(B)['compiler_headers_sha256'])
                with patch.object(R, 'input_hashes', return_value={}):
                    with self.assertRaisesRegex(ValueError, 'source/tool/SDK inputs changed'):
                        R.check_initial_inputs(B, {}, before)

    def test_docker_ignores_unforwarded_compiler_search_but_refuses_host_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            tc = Path(folder)
            for name in ('pi32v2/bin/clang', 'pi32v2/bin/ld', 'common/bin/objdump', 'common/bin/objcopy'):
                path = tc / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture tool')
            for name in R.HEADER_ROOTS:
                path = tc / name / 'stdint.h'; path.parent.mkdir(parents=True); path.write_text('fixture header')
            with patch.object(B, 'use_docker', return_value=True), \
                    patch.object(B, 'toolchain', return_value=tc), \
                    patch.object(B.fm1pkg_make, 'sdk_file', return_value=b'sdk'), \
                    patch.object(B, 'tc', side_effect=AssertionError('capture must not compile')), \
                    patch.object(R, 'input_hashes', return_value={}), \
                    patch.dict(os.environ, {name: '' for name in R.COMPILER_ENV}):
                before = R.tool_fingerprints(B)
                self.assertEqual(before['execution_environment']['backend'], 'docker')
                for name in ('CPATH', 'LIBRARY_PATH', 'SDKROOT', 'CCC_OVERRIDE_OPTIONS'):
                    with self.subTest(name=name), patch.dict(os.environ, {name: 'host-only-search'}):
                        self.assertEqual(R.tool_fingerprints(B), before)
                        R.check_initial_inputs(B, {}, before)
                for name in ('LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH'):
                    with self.subTest(name=name), patch.dict(os.environ, {name: 'host-injection'}):
                        with self.assertRaisesRegex(ValueError, 'unsupported compiler environment: ' + name):
                            R.tool_fingerprints(B)

    def test_cli_default_empty_and_explicit_tool_sdk_paths(self):
        # Run the actual CLI and build helpers in an isolated source tree. Only
        # profile/identity freshness and external target tools are fixture inputs;
        # configuration, fingerprints, inventories and resource guards stay real.
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / 'source'
            tools = root / 'tools'
            tools.mkdir(parents=True)
            for name in ('build_report.py', 'build.py', 'fm1pkg_make.py', 'lz4blk.py'):
                shutil.copyfile(ROOT / 'tools' / name, tools / name)
            (tools / 'profile.py').write_text(
                "def generated(root, name):\n"
                "    if name != 'standard': raise ValueError('fixture profile mismatch')\n"
                "    return {}\n"
                "def check_outputs(outputs, path): pass\n"
                "def contract_json(root): return 'contract\\n'\n")
            (tools / 'font_resources.py').write_text('def linked(root, gen, syms): return {}\n')
            (tools / 'build_identity.py').write_text('def check(root, gen): pass\n')
            (root / 'firmware/engines').mkdir(parents=True)
            shutil.copyfile(ROOT / 'firmware/app.ld', root / 'firmware/app.ld')
            (root / '.gitignore').write_text('build/\n__pycache__/\n')
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            for name in R.artifact_paths('felucca.fwsc'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}\n' if 'build-identity' in name else name)
            evidence = self.evidence()
            (root / 'build/felucca.bin').write_bytes(evidence[0])
            (root / 'build/felucca.dis').write_text(evidence[3])
            (root / 'build/profile-contract.json').write_text('contract\n')
            home = base / 'home with spaces'
            toolchain = home / '.jieli/toolchain'
            sdk = home / 'fw-AC79_AIoT_SDK'
            compiler = (f'#!{sys.executable}\nimport sys\n'
                        "if '--version' in sys.argv: print('clang version fixture')\n"
                        "else:\n"
                        "    assert '-dM' in sys.argv and '-E' in sys.argv and '-c' not in sys.argv\n"
                        "    print('#define FELUCCA_CPU2 0\\n#define FELUCCA_ID \"FM-1_900\""
                        "\\n#define FELUCCA_SLICE 1\\n#define FELUCCA_FM4 0')\n")
            objdump = (f'#!{sys.executable}\nimport sys\n'
                       f'outputs = {dict(zip(("-h", "-t", "-d", "-j"), evidence[1:]))!r}\n'
                       "sys.stdout.write(outputs['-j' if '-j' in sys.argv else sys.argv[1]])\n")
            for name, content in (('pi32v2/bin/clang', compiler), ('common/bin/objdump', objdump),
                                  ('pi32v2/bin/ld', 'linker fixture'), ('common/bin/objcopy', 'objcopy fixture')):
                path = toolchain / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                path.chmod(0o755)
            for name in R.HEADER_ROOTS:
                path = toolchain / name / 'stdint.h'; path.parent.mkdir(parents=True); path.write_text('fixture header')
            for name in B.SDK_SHA256:
                path = sdk / 'cpu/wl82/tools' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('sdk fixture: ' + name).encode())
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(('FELUCCA_', 'JIELI_'))
                   and key not in ('AC79_SDK', 'PYTHONPATH')}
            env.update(HOME=str(home), JIELI_DOCKER='0', FELUCCA_CPU2='0', FELUCCA_CRASH_CTX='0')
            # A successful build records effective tool/SDK bytes, never host paths.
            with patch.dict(os.environ, dict(env, JIELI_TOOLCHAIN=str(toolchain), AC79_SDK=str(sdk)), clear=True), \
                    patch.object(B, 'SRC', root), patch.object(B, 'FW', root / 'firmware'), \
                    patch.object(B, 'OUT', root / 'build'), patch.object(B, 'BUILD_IDENTITY', {}), \
                    patch.object(B.fm1pkg_make, 'SDK', None):
                R.write(B, evidence, 'felucca.fwsc', R.input_hashes(root), R.configuration(B))
            custom_tc, custom_sdk = base / 'custom tools', base / 'custom sdk'
            shutil.copytree(toolchain, custom_tc)
            shutil.copytree(sdk, custom_sdk)
            command = [sys.executable, str(tools / 'build_report.py'), '--verify',
                       'build/resource-report.json']
            for overrides in ({}, {'JIELI_TOOLCHAIN': '', 'AC79_SDK': ''},
                              {'JIELI_TOOLCHAIN': str(custom_tc), 'AC79_SDK': str(custom_sdk)},
                              {'JIELI_TOOLCHAIN': '../custom tools', 'AC79_SDK': '../custom sdk'},
                              {'JIELI_TOOLCHAIN': '', 'AC79_SDK': str(custom_sdk)},
                              {'JIELI_TOOLCHAIN': str(custom_tc), 'AC79_SDK': ''}):
                with self.subTest(overrides=overrides):
                    result = subprocess.run(command, cwd=root, env=dict(env, **overrides),
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('artifacts, inputs and configuration match', result.stdout)
            # Existing overrides with different bytes must still invalidate evidence.
            (custom_tc / 'pi32v2/bin/clang').write_text(compiler + '# different toolchain\n')
            (custom_sdk / 'cpu/wl82/tools/cfg_tool.bin').write_bytes(b'different SDK')
            for overrides in ({'JIELI_TOOLCHAIN': str(custom_tc)}, {'AC79_SDK': str(custom_sdk)}):
                result = subprocess.run(command, cwd=root, env=dict(env, **overrides),
                                        text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('stale resource report configuration', result.stderr)

    def test_import_does_not_apply_cli_path_defaults(self):
        command = [sys.executable, '-c',
                   "import os; before = dict(os.environ); import build_report; "
                   "assert dict(os.environ) == before"]
        for value in (None, '', '/explicit path'):
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'tools'))
            for name in ('JIELI_TOOLCHAIN', 'AC79_SDK'):
                if value is None:
                    env.pop(name, None)
                else:
                    env[name] = value
            with self.subTest(value=value):
                subprocess.run(command, env=env, check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
