#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Native CLI setup/preflight/handoff tests. No native adapter or network is used."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import m_flasher as F
import fm1_pr as P

CAPABILITIES = {'schema': 1, 'midi_ota': True, 'protocol': F.PROTOCOL}


class Setup(unittest.TestCase):
    REAL_HOST_PLATFORM = staticmethod(F.host_platform)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.destination = self.base / 'managed' / 'install'
        host = patch.object(F, 'host_platform', return_value='linux-x86_64')
        host.start()
        self.addCleanup(host.stop)

    def artifact(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        binary = directory / F.binary_name()
        binary.write_bytes(b'inert fake executable; never execute')
        source = {'repository': F.REPOSITORY, 'revision': F.REVISION,
                  'platform': F.host_platform(), 'binary': F.binary_name(),
                  'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
        (directory / 'source.json').write_text(json.dumps(source))
        return binary

    def test_platforms_are_explicit_and_macos_is_universal(self):
        for system, arch, expected in [('Darwin','arm64','macos'), ('Darwin','x86_64','macos'),
                                      ('Linux','x86_64','linux-x86_64'), ('Windows','AMD64','windows-x86_64')]:
            with patch.object(F.platform, 'system', return_value=system), patch.object(F.platform, 'machine', return_value=arch):
                self.assertEqual(self.REAL_HOST_PLATFORM(), expected)
        with patch.object(F.platform, 'system', return_value='Other'), self.assertRaises(ValueError):
            self.REAL_HOST_PLATFORM()

    def test_manifest_source_platform_hash_and_symlinks_checked_before_execution(self):
        binary = self.artifact(self.destination)
        self.assertEqual(F.verify_directory(self.destination), binary)
        original = binary.read_bytes()
        binary.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            F.verify_directory(self.destination)
        binary.write_bytes(original)
        manifest = self.destination / 'source.json'
        valid = json.loads(manifest.read_text())
        for key in ('revision', 'repository', 'platform', 'binary'):
            manifest.write_text(json.dumps(valid | {key: 'wrong'}))
            with self.assertRaisesRegex(ValueError, 'pinned'):
                F.verify_directory(self.destination)
        manifest.write_text(json.dumps(valid))
        binary.unlink()
        if sys.platform != 'win32':
            binary.symlink_to(self.destination / 'source.json')
            with self.assertRaisesRegex(ValueError, 'regular'):
                F.verify_directory(self.destination)

    def test_capability_query_is_the_only_executable_invocation(self):
        binary = self.base / 'm-flasher'
        with patch.object(F, 'run', return_value=json.dumps(CAPABILITIES)) as call:
            self.assertEqual(F.check_capabilities(binary), binary)
        call.assert_called_once_with([binary, '--capabilities'], timeout=15)
        for result in ('old CLI output', '[]', json.dumps(CAPABILITIES | {'midi_ota': False}),
                       json.dumps(CAPABILITIES | {'protocol': 'other'})):
            with patch.object(F, 'run', return_value=result), self.assertRaises(ValueError):
                F.check_capabilities(binary)

    def test_setup_is_atomic_reused_and_source_explicit(self):
        with patch.object(F, 'cache_directory', return_value=self.destination), \
                patch.object(F, 'download', side_effect=self.artifact) as download, \
                patch.object(F, 'build_source') as build, \
                patch.object(F, 'check_capabilities', side_effect=lambda p:p) as capabilities:
            self.assertEqual(F.ensure(), self.destination / F.binary_name())
            self.assertEqual(F.ensure(), self.destination / F.binary_name())
            download.assert_called_once()
            build.assert_not_called()
            self.assertEqual(capabilities.call_count, 2)
        self.assertTrue((self.destination / 'source.json').is_file())

    def test_failure_never_publishes_partial_install(self):
        def fail(directory):
            self.artifact(directory)
            raise ValueError('interrupted download')
        with patch.object(F, 'cache_directory', return_value=self.destination), \
                patch.object(F, 'download', side_effect=fail), self.assertRaises(ValueError):
            F.ensure()
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_source_build_is_pinned_locked_and_keeps_the_same_manifest_contract(self):
        def cargo(arguments, timeout):
            self.assertEqual(arguments[:3], ['cargo', 'install', '--git'])
            self.assertIn(F.REVISION, arguments)
            self.assertIn('--locked', arguments)
            destination = Path(arguments[arguments.index('--root') + 1]) / 'bin'
            destination.mkdir(parents=True)
            (destination / F.binary_name()).write_bytes(b'inert compiled binary')
            return ''
        self.destination.mkdir(parents=True)
        with patch.object(F, 'run', side_effect=cargo):
            F.build_source(self.destination)
        self.assertEqual(F.verify_directory(self.destination), self.destination / F.binary_name())

    def test_corrupt_cached_binary_is_never_executed_or_silently_replaced(self):
        binary = self.artifact(self.destination)
        binary.write_bytes(b'corrupt')
        with patch.object(F, 'cache_directory', return_value=self.destination), \
                patch.object(F, 'check_capabilities') as execute, patch.object(F, 'download') as download, \
                self.assertRaisesRegex(ValueError, 'SHA-256') as error:
            F.ensure()
        self.assertIn(str(self.destination), str(error.exception))
        self.assertIn('tools/m_flasher.py', str(error.exception))
        execute.assert_not_called()
        download.assert_not_called()

    def test_explicit_binary_has_no_automatic_download(self):
        with patch.object(F, 'check_capabilities', side_effect=lambda p:p), patch.object(F, 'download') as download:
            self.assertEqual(F.ensure(self.base / 'chosen'), self.base / 'chosen')
        download.assert_not_called()

    def test_exact_successful_push_artifact_selected(self):
        run = {'id': 10, 'head_sha': F.REVISION, 'event': 'push', 'status': 'completed', 'conclusion': 'success'}
        wrong = run | {'id': 11, 'head_sha': 'a'*40}
        artifact = {'name': f'm-flasher-midi-{F.host_platform()}', 'expired': False}
        with patch.object(F, 'run', side_effect=[json.dumps({'workflow_runs': [wrong,run]}),
                                               json.dumps({'artifacts': [artifact]}), '']) as call:
            F.download(self.base)
        args = call.call_args_list[-1].args[0]
        self.assertEqual(args[:4], ['gh','run','download','10'])
        self.assertIn(str(self.base), args)
        self.assertNotIn('11', args)

    def test_no_artifact_never_fetches_arbitrary_source(self):
        for artifacts in ([], [{'name': f'm-flasher-midi-{F.host_platform()}', 'expired': True}]):
            run = {'id':10, 'head_sha':F.REVISION, 'event':'push', 'status':'completed', 'conclusion':'success'}
            with patch.object(F, 'run', side_effect=[json.dumps({'workflow_runs':[run]}),json.dumps({'artifacts':artifacts})]) as call, \
                    self.assertRaisesRegex(ValueError, 'from-source'):
                F.download(self.base)
            self.assertEqual(call.call_count,2)

    def test_subprocess_errors_redact_signed_urls(self):
        with patch.object(F.subprocess, 'run', return_value=subprocess.CompletedProcess([],1,'','GET https://example.invalid/file?signature=SECRET forbidden')), self.assertRaises(ValueError) as error:
            F.run(['gh','run','download'])
        self.assertNotIn('SECRET',str(error.exception))
        with patch.object(F.subprocess, 'run', side_effect=FileNotFoundError('missing')), self.assertRaises(ValueError):
            F.run(['absent'])


class Handoff(unittest.TestCase):
    def test_native_and_python_are_explicit(self):
        with patch.object(F, 'ensure', return_value=Path('/native/m-flasher')):
            self.assertEqual(P.prepare_installer('native'), ['/native/m-flasher','midi','firmware'])
        with patch.object(P.subprocess, 'run', return_value=subprocess.CompletedProcess([],0)) as run:
            self.assertEqual(P.prepare_installer('python')[0], sys.executable)
        self.assertEqual(run.call_args.args[0], [sys.executable,'-c','import mido, rtmidi'])
        with self.assertRaisesRegex(ValueError, 'requires'):
            P.prepare_installer('python', Path('other'))
        with patch.object(P.subprocess, 'run', return_value=subprocess.CompletedProcess([],1)), self.assertRaisesRegex(ValueError, 'before starting CI'):
            P.prepare_installer('python')

    def test_missing_native_blocks_all_ci_work(self):
        with patch.object(F, 'ensure', side_effect=ValueError('installer missing')), \
                patch.object(P, 'resolve_revision') as resolve, patch.object(P, 'ensure_run') as build, \
                patch.object(P, 'install') as install, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(P.main(['392','--validation','target']),2)
        for call in (resolve,build,install):
            call.assert_not_called()

    def test_noninstall_modes_skip_setup(self):
        with patch.object(F, 'ensure') as ensure, patch.object(P,'resolve_revision',return_value='a'*40), \
                patch.object(P,'prepare_worktree'), patch.object(P,'remove_worktree'), \
                patch.object(P,'api',return_value={'default_branch':'main'}), \
                patch.object(P,'ensure_run',return_value={}), patch.object(P,'download',return_value=Path('file.fwsc')):
            for flags in (['--download-only'],['--prepare-only'],['--resolve-only'],['--remove-worktree','unused']):
                self.assertEqual(P.main(['392',*flags]),0)
        ensure.assert_not_called()

    def test_native_handoff_preserves_port_confirmation_failure_and_package_path(self):
        with patch.object(P.subprocess,'run',return_value=subprocess.CompletedProcess([],5)) as call:
            self.assertEqual(P.install(Path('/a path/firmware.fwsc'),'FM-1',False,
                                       command=['/native/m-flasher','midi','firmware']),5)
            self.assertEqual(call.call_args.args[0], ['/native/m-flasher','midi','firmware','/a path/firmware.fwsc','--port','FM-1'])
            P.install(Path('file.fwsc'),yes=True,command=['/native/m-flasher','midi','firmware'])
            self.assertEqual(call.call_args.args[0][-1],'--yes')


if __name__ == '__main__':
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
