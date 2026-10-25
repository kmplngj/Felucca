#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the real driver against external fake compiler/SDK processes, never a compiler."""
import copy
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
import build_identity
import build_report
import wasm_report as W


class RuntimeReport(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='felucca-wasm-report-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'source'
        self.sdk = self.base / 'sdk'
        self.root.mkdir()
        self.sdk.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('FELUCCA_', 'GITHUB_', 'EM_', 'EMCC_', 'EMSDK', '_EMCC_'))
                    and k not in ('CFLAGS', 'CXXFLAGS', 'LDFLAGS')}
        self.env['PATH'] = str(self.sdk) + os.pathsep + self.env['PATH']
        self.env['EMSDK_PYTHON'] = sys.executable
        self.env['EM_CONFIG'] = str(self.sdk / '.emscripten')
        self.env['FIXTURE_SDK'] = str(self.sdk)
        self.env['FIXTURE_ACTION'] = ''
        self.env['FIXTURE_ARGV'] = str(self.base / 'argv.json')
        self.env['FIXTURE_EXECUTABLE'] = str(self.base / 'executable.json')
        for name, value in {
            '.gitignore': 'build/\n',
            '.gitmodules': '[submodule "firmware/engines"]\n\tpath = firmware/engines\n'
                           '\turl = https://github.com/kmplngj/Felucca-Engines.git\n',
            'firmware/src/felucca.c': '#define FELUCCA_VERSION "v1.6.1"\n',
            'tools/profile.py': 'import sys\nsys.exit(0)\n',
            # Native verification remains an external process boundary. Its full
            # production verifier has dedicated resource-report tests.
            'tools/build_report.py': 'import os,sys\nif __name__ == "__main__":\n    sys.exit(int(os.getenv("FIXTURE_TARGET_EXIT","0")))\n',
            'tools/wasm_report.py': (ROOT / 'tools/wasm_report.py').read_text(),
            'web/emu/build.sh': (ROOT / 'web/emu/build.sh').read_text(),
            'web/emu/felucca_web.c': '/* fixture compilation input */\n',
            'web/emu/index.html': '<title>@VERSION@@PREVIEW@</title>\n',
            'web/emu/worklet.js': '/* actual fixture worklet bytes */\n',
            'web/emu/fonts/OFL.txt': 'fixture font license\n',
            'web/emu/fonts/DotGothic16-subset.woff': 'fixture font bytes\n',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        engine = self.root / 'firmware/engines'
        (engine / 'src').mkdir(parents=True)
        (engine / 'src/felucca_engine.h').write_text('/* fixture MIT engine */\n')
        self.git(engine, 'init', '-q')
        self.commit(engine)
        self.git(self.root, 'init', '-q')
        self.git(self.root, 'config', 'remote.origin.url', 'https://github.com/kmplngj/Felucca.git')
        self.commit(self.root)
        self.pin = self.git(engine, 'rev-parse', 'HEAD').strip()
        self.native = {
            'FELUCCA_FLASH': '1', 'FELUCCA_OTA': '1', 'FELUCCA_UAC': '1', 'FELUCCA_UART': '1',
            'FELUCCA_CPU2': '1', 'FELUCCA_CDC': '1', 'FELUCCA_ICONS': '1',
            'FELUCCA_ISR_ASSERT': '0',
            'FELUCCA_UAC_48K': '1', 'FELUCCA_UAC_AS_FIRST': '1',
            'FELUCCA_ENG_TEST14': '0', 'FELUCCA_ENG_OMIT': '(-1)', 'FELUCCA_FM4': '0',
            'FELUCCA_VERSION': '\"v1.6.1\"',
        }
        self.constants = {'NPART': '4', 'NVOICE': '8', 'NSTEP': '64', 'HALF_FRAMES': '128'}
        for name in ('emcc.py', '.emscripten', 'emscripten-version.txt', 'cache/sysroot/include/stdint.h',
                     'cache/sysroot/lib/libc.a', 'llvm/bin/clang', 'llvm/bin/wasm-ld',
                     'binaryen/bin/wasm-opt'):
            path = self.sdk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture SDK 1\n')
        tool = '''#!PYTHON
import json,os,pathlib,sys
sdk=pathlib.Path(os.environ["FIXTURE_SDK"])
if pathlib.Path(sys.argv[0]).name=="em-config":
    values={"EMSCRIPTEN_ROOT":str(sdk),"LLVM_ROOT":str(sdk/"llvm/bin"),
            "BINARYEN_ROOT":str(sdk/"binaryen"),"CACHE":str(sdk/"cache"),"NODE_JS":sys.executable}
    print(values[sys.argv[1]])
elif "--version" in sys.argv:
    print("fixture emcc 1.0")
elif "-dM" in sys.argv:
    values=json.loads((sdk/"macros.json").read_text())
    for arg in sys.argv[1:]:
        if arg.startswith("-DFELUCCA_"):
            key,_,value=arg[2:].partition("=")
            values[key]=value
    for key,value in values.items():
        print("#define "+key+" "+value)
else:
    pathlib.Path(os.environ["FIXTURE_ARGV"]).write_text(json.dumps(sys.argv[1:]))
    pathlib.Path(os.environ["FIXTURE_EXECUTABLE"]).write_text(json.dumps(sys.argv[0]))
    action=os.getenv("FIXTURE_ACTION","")
    if action=="fail":
        sys.exit(7)
    if action=="missing":
        sys.exit(0)
    pathlib.Path(sys.argv[sys.argv.index("-o")+1]).write_bytes(b"\\x00asmREAL-FIXTURE")
    changes={"source":"web/emu/worklet.js","generated":"build/gen/felucca_tables.h",
             "profile":"build/gen/resolved-profile.json","report":"build/resource-report.json"}
    if action in changes:
        p=pathlib.Path(changes[action]); p.write_bytes(p.read_bytes()+b" ")
    if action=="tool":
        p=sdk/"llvm/bin/clang";p.write_bytes(p.read_bytes()+b" ")
    if action=="library":
        p=sdk/"cache/sysroot/lib/libc.a";p.write_bytes(p.read_bytes()+b" ")
    if action=="configuration":
        p=sdk/".emscripten";p.write_bytes(p.read_bytes()+b" ")
    if action=="retarget":
        p=pathlib.Path(os.environ["FIXTURE_LINK"])
        p.unlink()
        p.symlink_to(os.environ["FIXTURE_DESTINATION"],target_is_directory=True)
'''.replace('PYTHON', sys.executable)
        for name in ('emcc', 'em-config'):
            (self.sdk / name).write_text(tool)
            (self.sdk / name).chmod(0o755)
        self.prepare()

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args],
                                       text=True, stderr=subprocess.DEVNULL)

    def commit(self, root):
        self.git(root, 'add', '.')
        self.git(root, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'fixture source')

    def prepare(self):
        gen = self.root / 'build/gen'
        gen.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, self.env, clear=True):
            identity = build_identity.write(self.root, gen)
        (gen / 'felucca_tables.h').write_text('/* generated fixture tables */\n')
        (gen / 'resolved-profile.json').write_text(json.dumps({'source_pins': {'engines_gitlink': self.pin}}))
        (self.root / 'build/profile-contract.json').write_text('{"schema_version":1}\n')
        runtime = dict(self.native, **W.ADAPTER, FELUCCA_ISR_ASSERT='1', **self.constants)
        (self.sdk / 'macros.json').write_text(json.dumps(runtime))
        self.report = {
            'configuration': {'effective_defines': self.native, 'logical_constants': self.constants,
                              'loader_environment_sha256': build_report.loader_environment_fingerprints(self.env)},
            'configuration_sha256': 'f' * 64, 'build_identity': identity,
            'input_sha256': build_report.input_hashes(self.root),
        }
        self.target = self.root / 'build/resource-report.json'
        self.target.write_text(json.dumps(self.report))

    def build(self, paired=True):
        with patch.dict(os.environ, self.env, clear=True):
            return W.build_runtime(self.root, self.target if paired else None, self.env)

    def test_default_argv_matches_old_literal_recipe(self):
        actual, preprocess = W.arguments('v1.6.1', {}, self.root)
        self.assertEqual(actual, ['emcc', '-O2', '-ffp-contract=off', '-std=gnu99', '-w',
                                  '-DFELUCCA_VERSION="v1.6.1"', '-Ibuild/gen', '-Ifirmware/src',
                                  '--no-entry', '-sSTANDALONE_WASM', '-sSTACK_SIZE=1048576',
                                  '-sINITIAL_MEMORY=33554432', '-sFILESYSTEM=0',
                                  '-o', 'build/emu/felucca.wasm', 'web/emu/felucca_web.c'])
        self.assertEqual(preprocess, actual[:8] + ['-dM', '-E', 'web/emu/felucca_web.c'])

    def test_old_shell_expansion_does_not_interpret_quotes_or_code(self):
        (self.root / 'flag-one').write_text('')
        self.assertEqual(W.shell_words(' flag-* "-O3" $(touch nope) ', self.root),
                         ['flag-one', '"-O3"', '$(touch', 'nope)'])
        self.assertFalse((self.root / 'nope').exists())

    def test_paired_real_driver_receipt_and_offline_verify(self):
        receipt = self.build()
        self.assertEqual(receipt['target']['report_sha256'], W.R.digest(self.target))
        self.assertEqual(receipt['freshness']['before_sha256'], receipt['freshness']['after_sha256'])
        self.assertEqual(receipt['files'], W.output_files(self.root))
        self.assertEqual(W.verify_receipt(self.root, receipt, self.report,
                         target_report_sha256=W.R.digest(self.target)), receipt['configuration'])
        argv = json.loads((self.base / 'argv.json').read_text())
        self.assertEqual(argv, receipt['configuration']['compile_argv'][1:])
        self.assertIn('-DFELUCCA_CPU2=1', argv)
        self.assertEqual(len(receipt['files']), 5)

    def test_cpu2_cdc_icons_off_are_explicit_not_browser_defaults(self):
        for name in ('FELUCCA_CPU2', 'FELUCCA_CDC', 'FELUCCA_ICONS'):
            self.native[name] = '0'
        self.prepare()
        receipt = self.build()
        for name in ('FELUCCA_CPU2', 'FELUCCA_CDC', 'FELUCCA_ICONS'):
            self.assertIn('-D' + name + '=0', receipt['configuration']['compile_argv'])
            self.assertEqual(receipt['logical_mapping']['defines'][name]['runtime'], '0')

    def test_unpaired_never_invokes_native_verifier(self):
        self.env['FIXTURE_TARGET_EXIT'] = '99'
        receipt = self.build(False)
        self.assertIsNone(receipt['target'])
        self.assertNotIn('-DFELUCCA_CPU2=1', receipt['configuration']['compile_argv'])

    def test_unpaired_nonstandard_sdk_keeps_build_available_without_receipt(self):
        (self.sdk / 'em-config').unlink()
        self.assertIsNone(self.build(False))
        self.assertTrue((self.root / W.FILES[0]).is_file())
        self.assertFalse((self.root / W.RECEIPT).exists())

    def test_failed_native_verifier_never_compiles(self):
        self.env['FIXTURE_TARGET_EXIT'] = '9'
        with self.assertRaisesRegex(ValueError, 'command failed'):
            self.build()
        self.assertFalse((self.base / 'argv.json').exists())
        self.assertFalse((self.root / W.RECEIPT).exists())

    def test_ambiguous_target_json_rejected_before_verifier_and_attempt_logs_retained(self):
        for document in ('{"configuration":{},"configuration":{}}', '{"number":NaN}'):
            with self.subTest(document=document):
                self.target.write_text(document)
                with self.assertRaises(ValueError):
                    self.build()
                self.assertFalse((self.base / 'argv.json').exists())
                self.assertFalse((self.root / W.RECEIPT).exists())
        logs = list((self.root / 'build/wasm-report').glob('attempt-*.log'))
        self.assertEqual(len(logs), 2)
        self.assertNotEqual(logs[0], logs[1])

    def test_compile_failure_and_missing_output_cannot_restamp_old_wasm(self):
        for action in ('fail', 'missing'):
            with self.subTest(action=action):
                for name in (W.RECEIPT, W.FILES[0]):
                    path = self.root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('stale')
                self.env['FIXTURE_ACTION'] = action
                reason = r'command failed \(7\)' if action == 'fail' else 'unexpected runtime output set'
                with self.assertRaisesRegex(ValueError, reason):
                    self.build()
                self.assertTrue((self.base / 'argv.json').exists())
                self.assertFalse((self.root / W.RECEIPT).exists())

    def test_source_generated_profile_report_tool_library_mutations_fail_closed(self):
        for action in ('source', 'generated', 'profile', 'report', 'tool', 'library', 'configuration'):
            with self.subTest(action=action):
                # Each mutation needs independent committed and generated inputs.
                self.env['FIXTURE_ACTION'] = action
                before = {p: p.read_bytes() for p in
                          (self.root / 'web/emu/worklet.js',
                           self.root / 'build/gen/felucca_tables.h',
                           self.root / 'build/gen/resolved-profile.json', self.target,
                           self.sdk / 'llvm/bin/clang', self.sdk / 'cache/sysroot/lib/libc.a',
                           self.sdk / '.emscripten')}
                with self.assertRaisesRegex(ValueError, 'changed during runtime build'):
                    self.build()
                self.assertFalse((self.root / W.RECEIPT).exists())
                for path, data in before.items():
                    path.write_bytes(data)

    def test_sdk_manifest_covers_header_and_library_not_just_executables(self):
        log = self.root / 'build/sdk.log'
        resolved = W.sdk_tools(self.sdk / 'emcc', self.root, self.env, log)
        before = W.tool_fingerprint(resolved)
        irrelevant = self.sdk / 'cache/ports/unrelated.zip'
        irrelevant.parent.mkdir()
        irrelevant.write_bytes(b'unrelated cached download')
        self.assertEqual(W.tool_fingerprint(resolved), before)
        bundled = self.sdk / 'node_modules/acorn/index.js'
        bundled.parent.mkdir(parents=True)
        bundled.write_text('bundled compiler dependency\n')
        self.assertNotEqual(W.tool_fingerprint(resolved)['sdk_content_manifest_sha256'],
                            before['sdk_content_manifest_sha256'])
        before = W.tool_fingerprint(resolved)
        path = self.sdk / 'cache/sysroot/include/stdint.h'
        path.write_text('changed typedef\n')
        after = W.tool_fingerprint(resolved)
        self.assertEqual(before['clang_sha256'], after['clang_sha256'])
        self.assertNotEqual(before['sdk_content_manifest_sha256'], after['sdk_content_manifest_sha256'])

    def test_retargeted_external_cache_is_rejected_before_receipt(self):
        first, second = self.base / 'cache-first', self.base / 'cache-second'
        shutil.move(self.sdk / 'cache', first)
        shutil.copytree(first, second)
        (second / 'sysroot/include/stdint.h').write_text('changed external cache header\n')
        link = self.sdk / 'cache'
        link.symlink_to(first, target_is_directory=True)
        self.env.update(FIXTURE_ACTION='retarget', FIXTURE_LINK=str(link),
                        FIXTURE_DESTINATION=str(second))
        with self.assertRaisesRegex(ValueError, 'tool/SDK inputs changed'):
            self.build()
        self.assertFalse((self.root / W.RECEIPT).exists())

    def assert_retargeted_identity_rejected(self, kind):
        # Equal bytes intentionally distinguish destination identity from the
        # content-only checks that missed the reviewer's external-cache case.
        locations = {'cache': self.sdk / 'cache', 'sysroot': self.sdk / 'cache/sysroot',
                     'llvm': self.sdk / 'llvm', 'binaryen': self.sdk / 'binaryen',
                     'sdk': self.sdk, 'configuration': self.sdk / '.emscripten',
                     'clang': self.sdk / 'llvm/bin/clang', 'em-config': self.sdk / 'em-config'}
        link = locations[kind]
        first, second = self.base / (kind + '-first'), self.base / (kind + '-second')
        directory = link.is_dir()
        shutil.move(link, first)
        if directory:
            shutil.copytree(first, second)
        else:
            shutil.copy2(first, second)
        link.symlink_to(first, target_is_directory=directory)
        frozen_emcc = (self.sdk / 'emcc').resolve()
        self.env.update(FIXTURE_ACTION='retarget', FIXTURE_LINK=str(link),
                        FIXTURE_DESTINATION=str(second))
        with self.assertRaisesRegex(ValueError, 'tool/SDK inputs changed'):
            self.build()
        self.assertEqual(json.loads((self.base / 'executable.json').read_text()), str(frozen_emcc))
        self.assertFalse((self.root / W.RECEIPT).exists())
        self.assertEqual(len(list((self.root / 'build/wasm-report').glob('attempt-*.log'))), 1)

    def test_cache_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('cache')

    def test_sysroot_symlink_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('sysroot')

    def test_llvm_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('llvm')

    def test_binaryen_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('binaryen')

    def test_sdk_identity_change_keeps_frozen_emcc_and_is_rejected(self):
        self.assert_retargeted_identity_rejected('sdk')

    def test_configuration_symlink_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('configuration')

    def test_compiler_symlink_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('clang')

    def test_em_config_symlink_identity_change_with_equal_bytes_is_rejected(self):
        self.assert_retargeted_identity_rejected('em-config')

    def test_allowed_loader_environment_is_hashed_and_bound_to_native(self):
        self.env['LD_LIBRARY_PATH'] = '/fixture/setup-python/lib'
        self.prepare()
        receipt = self.build()
        expected = build_report.loader_environment_fingerprints(self.env)
        self.assertEqual(receipt['configuration']['loader_environment_sha256'], expected)
        self.assertEqual(expected, self.report['configuration']['loader_environment_sha256'])
        self.assertNotIn(self.env['LD_LIBRARY_PATH'], json.dumps(receipt['configuration']))
        bad = copy.deepcopy(receipt)
        bad['configuration']['loader_environment_sha256'] = {'LD_LIBRARY_PATH': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'loader environment mismatch'):
            W.verify_receipt(self.root, bad, self.report, target_report_sha256=W.R.digest(self.target))
        bad['configuration']['loader_environment_sha256'] = {'LD_PRELOAD': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'loader environment mismatch'):
            W.verify_receipt(self.root, bad, self.report, target_report_sha256=W.R.digest(self.target))

    def test_loader_environment_mismatch_stops_before_native_verifier_or_compile(self):
        self.env['LD_LIBRARY_PATH'] = '/different/setup-python/lib'
        with self.assertRaisesRegex(ValueError, 'loader environment mismatch'):
            self.build()
        self.assertFalse((self.base / 'argv.json').exists())
        self.assertFalse((self.root / W.RECEIPT).exists())

    def test_unsupported_native_flash_and_unknown_flags_rejected(self):
        for flags in ('-DFELUCCA_CPU2=0', '-include other.h', '-sFILESYSTEM=1', '-mystery'):
            with self.subTest(flags=flags):
                with self.assertRaisesRegex(ValueError, 'unsupported paired'):
                    W.arguments('v1.6.1', {'EMU_CFLAGS': flags}, self.root, self.report)
        self.native['FELUCCA_FLASH'] = '0'
        with self.assertRaisesRegex(ValueError, 'FLASH=1'):
            W.arguments('v1.6.1', {}, self.root, self.report)

    def test_unknown_macro_test_engine_and_constant_mismatch_rejected(self):
        for key, value in (('FELUCCA_NEW_DSP', '1'), ('FELUCCA_ENG_TEST14', '1'),
                           ('FELUCCA_ENG_OMIT', '3'), ('NPART', '5')):
            with self.subTest(key=key):
                runtime = dict(self.native, **W.ADAPTER, FELUCCA_ISR_ASSERT='1', **self.constants)
                runtime[key] = value
                (self.sdk / 'macros.json').write_text(json.dumps(runtime))
                expected = {'FELUCCA_NEW_DSP': 'unmapped FELUCCA macro',
                            'FELUCCA_ENG_TEST14': 'paired test engine',
                            'FELUCCA_ENG_OMIT': 'paired engine omission',
                            'NPART': 'logical constant mismatch'}[key]
                with self.assertRaisesRegex(ValueError, expected):
                    self.build()
                self.assertFalse((self.root / W.RECEIPT).exists())

    def test_retained_actual_preprocessor_maps_and_strict_assertion_adapter(self):
        # Captured clean87e C/generated inputs with candidate Python helpers:
        # build/issue466-actual-mapping/actual-maps.json (actual JieLi/emcc -dM).
        # Inline data keeps the regression independent of ignored local evidence.
        native = {'FELUCCA_ARENA_CHECK': '0',
         'FELUCCA_BOOT_POLICY_H': '',
         'FELUCCA_BUILD_COMMIT': '"87e17594c2bc1a540db1700f521ac2ef5a3d6ec6"',
         'FELUCCA_BUILD_DIRTY': '0',
         'FELUCCA_BUILD_ID': '"87e17594"',
         'FELUCCA_BUILD_IDENTITY_H': '',
         'FELUCCA_BUILD_PR': '""',
         'FELUCCA_CATEGORY': '1',
         'FELUCCA_CDC': '1',
         'FELUCCA_CDC_DEFAULT': '1',
         'FELUCCA_CPU2': '1',
         'FELUCCA_CRASH_CTX': '0',
         'FELUCCA_ENGINE_API_REQUIRED': '1u',
         'FELUCCA_ENGINE_API_VERSION': '1u',
         'FELUCCA_ENGINE_H': '',
         'FELUCCA_ENG_OMIT': '(-1)',
         'FELUCCA_ENG_TEST14': '0',
         'FELUCCA_FAVORITES': '1',
         'FELUCCA_FLASH': '1',
         'FELUCCA_FM4': '0',
         'FELUCCA_ICONS': '1',
         'FELUCCA_ID': '"FM-1_900"',
         'FELUCCA_ISR_ASSERT': '0',
         'FELUCCA_MUL64_REPRO': '0',
         'FELUCCA_OTA': '1',
         'FELUCCA_OTA_DRYRUN': '0',
         'FELUCCA_OTA_RAMONLY': '0',
         'FELUCCA_PROFILE_ENGINE_0': '1',
         'FELUCCA_PROFILE_ENGINE_1': 'FELUCCA_FM4',
         'FELUCCA_PROFILE_ENGINE_10': '1',
         'FELUCCA_PROFILE_ENGINE_11': '1',
         'FELUCCA_PROFILE_ENGINE_12': '1',
         'FELUCCA_PROFILE_ENGINE_13': 'FELUCCA_SLICE',
         'FELUCCA_PROFILE_ENGINE_14': '0',
         'FELUCCA_PROFILE_ENGINE_2': '1',
         'FELUCCA_PROFILE_ENGINE_3': '1',
         'FELUCCA_PROFILE_ENGINE_4': '1',
         'FELUCCA_PROFILE_ENGINE_5': '1',
         'FELUCCA_PROFILE_ENGINE_6': '1',
         'FELUCCA_PROFILE_ENGINE_7': '1',
         'FELUCCA_PROFILE_ENGINE_8': '1',
         'FELUCCA_PROFILE_ENGINE_9': '1',
         'FELUCCA_PROFILE_NAME': '"standard"',
         'FELUCCA_PROFILE_NSHOWN': '((FELUCCA_PROFILE_ENGINE_0 && FELUCCA_ENG_OMIT != 0) + '
                                   '(FELUCCA_PROFILE_ENGINE_1 && FELUCCA_FM4 && FELUCCA_ENG_OMIT != '
                                   '1) + (FELUCCA_PROFILE_ENGINE_2 && FELUCCA_ENG_OMIT != 2) + '
                                   '(FELUCCA_PROFILE_ENGINE_3 && FELUCCA_ENG_OMIT != 3) + '
                                   '(FELUCCA_PROFILE_ENGINE_4 && FELUCCA_ENG_OMIT != 4) + '
                                   '(FELUCCA_PROFILE_ENGINE_5 && FELUCCA_ENG_OMIT != 5) + '
                                   '(FELUCCA_PROFILE_ENGINE_6 && FELUCCA_ENG_OMIT != 6) + '
                                   '(FELUCCA_PROFILE_ENGINE_7 && FELUCCA_ENG_OMIT != 7) + '
                                   '(FELUCCA_PROFILE_ENGINE_8 && FELUCCA_ENG_OMIT != 8) + '
                                   '(FELUCCA_PROFILE_ENGINE_9 && FELUCCA_ENG_OMIT != 9) + '
                                   '(FELUCCA_PROFILE_ENGINE_10 && FELUCCA_ENG_OMIT != 10) + '
                                   '(FELUCCA_PROFILE_ENGINE_11 && FELUCCA_ENG_OMIT != 11) + '
                                   '(FELUCCA_PROFILE_ENGINE_12 && FELUCCA_ENG_OMIT != 12) + '
                                   '(FELUCCA_PROFILE_ENGINE_13 && FELUCCA_SLICE && FELUCCA_ENG_OMIT '
                                   '!= 13) + (FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14) + '
                                   '(FELUCCA_ENG_TEST14 && FELUCCA_ENG_OMIT != '
                                   'FELUCCA_PROFILE_NSLOTS))',
         'FELUCCA_PROFILE_NSLOTS': '15',
         'FELUCCA_PROFILE_SHA256': '"ba9ad596646f7eeca859ea5b1e0b354563da8c069acbeab7e212c4d31f80c822"',
         'FELUCCA_SCREEN_CAPTURE': '0',
         'FELUCCA_SLICE': '1',
         'FELUCCA_SOURCE_REPOSITORY': '"github.com/kmplngj/Felucca"',
         'FELUCCA_SPLASH_ID': '"87e17594"',
         'FELUCCA_UAC': '1',
         'FELUCCA_UAC_48K': '1',
         'FELUCCA_UAC_AS_FIRST': '1',
         'FELUCCA_UAC_TONE': '0',
         'FELUCCA_UART': '1',
         'FELUCCA_UNION_CONTROL_MASK': '0x91ull',
         'FELUCCA_USB_LAYOUT': '0',
         'FELUCCA_USB_PID': '0x0001',
         'FELUCCA_VERSION': '"v1.6.1"'}
        runtime = {'FELUCCA_ARENA_CHECK': '0',
         'FELUCCA_BOOT_POLICY_H': '',
         'FELUCCA_BUILD_COMMIT': '"87e17594c2bc1a540db1700f521ac2ef5a3d6ec6"',
         'FELUCCA_BUILD_DIRTY': '0',
         'FELUCCA_BUILD_ID': '"87e17594"',
         'FELUCCA_BUILD_IDENTITY_H': '',
         'FELUCCA_BUILD_PR': '""',
         'FELUCCA_CATEGORY': '1',
         'FELUCCA_CDC': '1',
         'FELUCCA_CDC_DEFAULT': '1',
         'FELUCCA_CPU2': '1',
         'FELUCCA_ENGINE_API_REQUIRED': '1u',
         'FELUCCA_ENGINE_API_VERSION': '1u',
         'FELUCCA_ENGINE_H': '',
         'FELUCCA_ENG_OMIT': '(-1)',
         'FELUCCA_ENG_TEST14': '0',
         'FELUCCA_FAVORITES': '1',
         'FELUCCA_FLASH': '1',
         'FELUCCA_FM4': '0',
         'FELUCCA_ICONS': '1',
         'FELUCCA_ISR_ASSERT': '1',
         'FELUCCA_OTA': '0',
         'FELUCCA_PROFILE_ENGINE_0': '1',
         'FELUCCA_PROFILE_ENGINE_1': 'FELUCCA_FM4',
         'FELUCCA_PROFILE_ENGINE_10': '1',
         'FELUCCA_PROFILE_ENGINE_11': '1',
         'FELUCCA_PROFILE_ENGINE_12': '1',
         'FELUCCA_PROFILE_ENGINE_13': 'FELUCCA_SLICE',
         'FELUCCA_PROFILE_ENGINE_14': '0',
         'FELUCCA_PROFILE_ENGINE_2': '1',
         'FELUCCA_PROFILE_ENGINE_3': '1',
         'FELUCCA_PROFILE_ENGINE_4': '1',
         'FELUCCA_PROFILE_ENGINE_5': '1',
         'FELUCCA_PROFILE_ENGINE_6': '1',
         'FELUCCA_PROFILE_ENGINE_7': '1',
         'FELUCCA_PROFILE_ENGINE_8': '1',
         'FELUCCA_PROFILE_ENGINE_9': '1',
         'FELUCCA_PROFILE_NAME': '"standard"',
         'FELUCCA_PROFILE_NSHOWN': '((FELUCCA_PROFILE_ENGINE_0 && FELUCCA_ENG_OMIT != 0) + '
                                   '(FELUCCA_PROFILE_ENGINE_1 && FELUCCA_FM4 && FELUCCA_ENG_OMIT != '
                                   '1) + (FELUCCA_PROFILE_ENGINE_2 && FELUCCA_ENG_OMIT != 2) + '
                                   '(FELUCCA_PROFILE_ENGINE_3 && FELUCCA_ENG_OMIT != 3) + '
                                   '(FELUCCA_PROFILE_ENGINE_4 && FELUCCA_ENG_OMIT != 4) + '
                                   '(FELUCCA_PROFILE_ENGINE_5 && FELUCCA_ENG_OMIT != 5) + '
                                   '(FELUCCA_PROFILE_ENGINE_6 && FELUCCA_ENG_OMIT != 6) + '
                                   '(FELUCCA_PROFILE_ENGINE_7 && FELUCCA_ENG_OMIT != 7) + '
                                   '(FELUCCA_PROFILE_ENGINE_8 && FELUCCA_ENG_OMIT != 8) + '
                                   '(FELUCCA_PROFILE_ENGINE_9 && FELUCCA_ENG_OMIT != 9) + '
                                   '(FELUCCA_PROFILE_ENGINE_10 && FELUCCA_ENG_OMIT != 10) + '
                                   '(FELUCCA_PROFILE_ENGINE_11 && FELUCCA_ENG_OMIT != 11) + '
                                   '(FELUCCA_PROFILE_ENGINE_12 && FELUCCA_ENG_OMIT != 12) + '
                                   '(FELUCCA_PROFILE_ENGINE_13 && FELUCCA_SLICE && FELUCCA_ENG_OMIT '
                                   '!= 13) + (FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14) + '
                                   '(FELUCCA_ENG_TEST14 && FELUCCA_ENG_OMIT != '
                                   'FELUCCA_PROFILE_NSLOTS))',
         'FELUCCA_PROFILE_NSLOTS': '15',
         'FELUCCA_PROFILE_SHA256': '"ba9ad596646f7eeca859ea5b1e0b354563da8c069acbeab7e212c4d31f80c822"',
         'FELUCCA_SLICE': '1',
         'FELUCCA_SOURCE_REPOSITORY': '"github.com/kmplngj/Felucca"',
         'FELUCCA_SPLASH_ID': '"87e17594"',
         'FELUCCA_UAC': '0',
         'FELUCCA_UAC_48K': '0',
         'FELUCCA_UAC_AS_FIRST': '0',
         'FELUCCA_UART': '0',
         'FELUCCA_UNION_CONTROL_MASK': '0x91ull',
         'FELUCCA_USB_LAYOUT': '0',
         'FELUCCA_USB_PID': '0x0001',
         'FELUCCA_VERSION': '"v1.6.1"',
         'FELUCCA_WEB': '1'}
        native_constants = {'C1_NP': '(FELUCCA_CPU2 ? NPART : 1)',
         'CTL': '32',
         'ENG_ID_MAX': '64u',
         'FS': '44100',
         'HALF_FRAMES': '128',
         'NENGINES': '(FELUCCA_PROFILE_NSLOTS + FELUCCA_ENG_TEST14)',
         'NPART': '4',
         'NSTEP': '64',
         'NTRK': 'NPART',
         'NVOICE': '8'}
        runtime_constants = {'C1_NP': '(FELUCCA_CPU2 ? NPART : 1)',
         'CTL': '32',
         'ENG_ID_MAX': '64u',
         'FS': '44100',
         'HALF_FRAMES': '128',
         'NENGINES': '(FELUCCA_PROFILE_NSLOTS + FELUCCA_ENG_TEST14)',
         'NPART': '4',
         'NSTEP': '64',
         'NTRK': 'NPART',
         'NVOICE': '8'}
        for native_assert in ('0', '1'):
            native['FELUCCA_ISR_ASSERT'] = native_assert
            mapping = W.logical_mapping(native, runtime, native_constants, runtime_constants)
            for name in ('FELUCCA_CATEGORY', 'FELUCCA_FAVORITES'):
                self.assertEqual(mapping['defines'][name],
                                 {'native': '1', 'runtime': '1', 'rule': 'equal'})
            row = mapping['defines']['FELUCCA_ISR_ASSERT']
            self.assertEqual((row['native'], row['runtime']), (native_assert, '1'))
            self.assertIn('simulated interrupt-depth assertions enabled', row['rule'])
        disabled = dict(runtime, FELUCCA_ISR_ASSERT='0')
        with self.assertRaisesRegex(ValueError, 'unsupported ISR assertion adapter'):
            W.logical_mapping(native, disabled, native_constants, runtime_constants)
        for name in ('FELUCCA_CATEGORY', 'FELUCCA_FAVORITES'):
            with self.subTest(name=name):
                wrong = dict(runtime, **{name: '0'})
                with self.assertRaisesRegex(ValueError, 'logical macro mismatch: ' + name):
                    W.logical_mapping(native, wrong, native_constants, runtime_constants)
        unknown = dict(runtime, FELUCCA_NEW_DSP='1')
        with self.assertRaisesRegex(ValueError, 'unmapped FELUCCA macro: FELUCCA_NEW_DSP'):
            W.logical_mapping(native, unknown, native_constants, runtime_constants)

    def test_paired_unknown_compiler_environment_fails_before_compile(self):
        for name in ('EMCC_CFLAGS', 'CPATH', 'C_INCLUDE_PATH', 'LIBRARY_PATH', 'COMPILER_PATH',
                     'SDKROOT', 'CCC_OVERRIDE_OPTIONS', 'CLANG_CONFIG_FILE_USER_DIR', 'LD_PRELOAD'):
            with self.subTest(name=name):
                self.env[name] = '/unbound/compiler/input'
                with self.assertRaisesRegex(ValueError, 'unsupported paired compiler environment'):
                    self.build()
                self.assertFalse((self.base / 'argv.json').exists())
                del self.env[name]

    def test_adapter_differences_are_explicit_and_exact_pin_is_required(self):
        receipt = self.build()
        for name, value in W.ADAPTER.items():
            row = receipt['logical_mapping']['defines'][name]
            self.assertEqual(row['runtime'], value)
            self.assertEqual(row['rule'], 'browser adapter override')
        receipt['source']['engines_revision'] = ''
        with self.assertRaisesRegex(ValueError, 'Engines pin mismatch'):
            W.verify_receipt(self.root, receipt, self.report, target_report_sha256=W.R.digest(self.target))

    def test_offline_tamper_and_fake_equal_freshness_are_rejected(self):
        receipt = self.build()
        unknown = copy.deepcopy(receipt)
        unknown['configuration']['unreviewed_option'] = True
        with self.assertRaisesRegex(ValueError, 'configuration fields'):
            W.verify_receipt(self.root, unknown, self.report, target_report_sha256=W.R.digest(self.target))
        bad = copy.deepcopy(receipt)
        bad['freshness'] = {'before_sha256': '0' * 64, 'after_sha256': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'freshness'):
            W.verify_receipt(self.root, bad, self.report, target_report_sha256=W.R.digest(self.target))
        (self.root / W.FILES[2]).write_text('tampered\n')
        with self.assertRaisesRegex(ValueError, 'artifacts'):
            W.verify_receipt(self.root, receipt, self.report, target_report_sha256=W.R.digest(self.target))

    def test_unexpected_outputs_cannot_be_silently_bound(self):
        path = self.root / 'build/emu/leftover.js'
        path.parent.mkdir(parents=True)
        path.write_text('stale side output')
        with self.assertRaisesRegex(ValueError, 'output set'):
            self.build()
        self.assertFalse((self.root / W.RECEIPT).exists())

    def test_unpaired_extra_developer_outputs_remain_and_do_not_block_build(self):
        path = self.root / 'build/emu/developer-notes.txt'
        path.parent.mkdir(parents=True)
        path.write_text('keep personal ignored file')
        self.assertIsNone(self.build(False))
        self.assertEqual(path.read_text(), 'keep personal ignored file')
        self.assertTrue((self.root / W.FILES[0]).is_file())
        self.assertFalse((self.root / W.RECEIPT).exists())

    def test_import_of_offline_verifier_does_not_invalidate_receipt(self):
        path = self.root / W.RECEIPT
        path.parent.mkdir(parents=True)
        path.write_text('keep exact receipt bytes')
        completed = subprocess.run([sys.executable, '-c',
                                   'import sys; sys.path.insert(0, "tools"); import wasm_report'],
                                  cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(path.read_text(), 'keep exact receipt bytes')

    def test_preview_and_copied_bytes_are_actual_inventory(self):
        self.env['EMU_PREVIEW'] = '0'
        receipt = self.build()
        self.assertEqual((self.root / W.FILES[1]).read_text(), '<title>v1.6.1</title>\n')
        for name in W.FILES[2:]:
            self.assertEqual((self.root / name).read_bytes(),
                             (self.root / name.replace('build/emu/', 'web/emu/')).read_bytes())
        self.assertFalse(receipt['configuration']['preview'])

    def test_malformed_cli_retires_receipt_before_argument_parsing(self):
        path = self.root / W.RECEIPT
        path.parent.mkdir(parents=True)
        path.write_text('stale')
        completed = subprocess.run([sys.executable, self.root / 'tools/wasm_report.py', '--unknown'],
                                   env=self.env, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
