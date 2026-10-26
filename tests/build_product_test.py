#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline checks of tools/build.py --product: precedence, validation, output names, no job on bad input.
No toolchain or SDK is needed: every generator, compiler and package step is mocked."""
from pathlib import Path
import io
import os
import json
import signal
import subprocess
import threading
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as B
import fm1pkg_make


class Stop(Exception):
    pass


class Resolve(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"FELUCCA_PROFILE": "standard"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_release_refuses_diagnostic_builds(self):
        """FELUCCA_CRASH_CTX / FELUCCA_MUL64_REPRO (#425, #428) are development builds only"""
        self.assertEqual(B.DIAG_FLAGS, ("FELUCCA_CRASH_CTX", "FELUCCA_MUL64_REPRO", "FELUCCA_SCREEN_CAPTURE"))
        for flag in B.DIAG_FLAGS:
            with patch.dict(os.environ, {flag: "1"}):
                with self.assertRaises(SystemExit) as raised:
                    B.resolve(["--release", "1.0"])
                self.assertIn(flag, str(raised.exception))
                self.assertEqual(B.resolve([])["name"], "felucca.fwsc")      # a development build is fine
            with patch.dict(os.environ, {flag: "0"}):
                self.assertEqual(B.resolve(["--release", "1.0"])["product"], "FM-1_910")

    def test_default_unchanged(self):
        c = B.resolve([])
        self.assertEqual((c["product"], c["version"], c["name"], c["explicit"]), ("FM-1_900", None, "felucca.fwsc", False))

    def test_release_default_unchanged(self):
        c = B.resolve(["--release", "1.0"])
        self.assertEqual((c["product"], c["version"], c["name"], c["rel"], c["app"]),
                         ("FM-1_910", "v1.0", "felucca-1.0.fwsc", "release-1.0", "felucca-1.0-app.bin"))

    def test_precedence(self):
        self.assertEqual(B.resolve(["--release", "1.2", "--product", "FM-1_ACME"])["product"], "FM-1_ACME")
        self.assertEqual(B.resolve(["--product", "FM-1_ACME"])["product"], "FM-1_ACME")
        self.assertEqual(B.resolve(["--release", "1.2"])["product"], "FM-1_912")

    def test_version_stays_independent(self):
        c = B.resolve(["--release", "1.2-rc1", "--product", "FM-1_ACME"])
        self.assertEqual(c["version"], "v1.2-rc1")

    def test_products_do_not_share_names(self):
        a = B.resolve(["--release", "1.0", "--product", "FM-1_AAA"])
        b = B.resolve(["--release", "1.0", "--product", "FM-1_BBB"])
        d = B.resolve(["--release", "1.0"])
        for key in ("name", "rel", "app"):
            self.assertEqual(len({a[key], b[key], d[key]}), 3, key)
        self.assertNotEqual(B.resolve(["--product", "FM-1_AAA"])["name"], "felucca.fwsc")

    def test_explicit_equal_to_derived_keeps_names(self):
        c = B.resolve(["--release", "1.0", "--product", "FM-1_910"])
        self.assertEqual((c["name"], c["rel"], c["app"]), ("felucca-1.0.fwsc", "release-1.0", "felucca-1.0-app.bin"))
        self.assertEqual(B.resolve(["--product", "FM-1_900"])["name"], "felucca.fwsc")

    def test_release_digits_ascii(self):
        for r in ("\u0661.\u0662", "1.\u0662", "1.0.\u0663"):    # Arabic-Indic digits
            with self.subTest(r=r), self.assertRaises(SystemExit):
                B.resolve(["--release", r])

    def test_default_not_left_from_an_earlier_build(self):
        B.PRODUCT = "FM-1_ACME"             # as main() leaves it after a --product build
        try:
            self.assertEqual(B.resolve([])["product"], "FM-1_900")
        finally:
            B.PRODUCT = B.DEV_PRODUCT

    def test_valid(self):
        for p in ("FM-1_900", "FM-1_ACME", "FM-1_A.B-C_9", "FM-1_" + "X" * 15, "FM-1_0150", "FM-1_800001"):
            with self.subTest(p=p):
                B.check_product(p)

    def test_invalid(self):
        bad = ["", "FM-1_", "FM-1_" + "x" * 16, "fm-1_abc", "FM-1_acme", "FM-1_Acme", "FM-2_abc", "ACME", "FM-1_a b", "FM-1_a\"b", "FM-1_a'b",
               "FM-1_a\\b", "FM-1_a\nb", "FM-1_a\tb", "FM-1_a\x00b", "FM-1_ä", "FM-1_a\u200b", " FM-1_abc",
               "FM-1_abc\n", "FM-1_a/b", "FM-1_a;b", "ota-FM-1_900", "ota-FM-1_015",
               "FM-1_015", "FM-1_016", "FM-1_099", "FM-1_000",   # M-VAVE's identities (#619)
               "FM-1_8000012"]                                     # its FM1 Open firmware
        for p in bad:
            with self.subTest(p=p), self.assertRaises(SystemExit):
                B.check_product(p)

    def test_marker_limit_matches_package(self):
        for c in map(chr, range(0x21, 0x7F)):       # same rule as fm1pkg_make.ufw
            p = "FM-1_" + c
            try:
                B.check_product(p)
                ok = True
            except SystemExit:
                ok = False
            if ok:
                fm1pkg_make.ufw(b"\0" * 64, b"\0" * 64, p)


class ToolchainCalls(unittest.TestCase):
    """Real tc/session logic with a fake Docker boundary; no backend is launched."""
    def setUp(self):
        self.real_run = subprocess.run
        self.calls = []
        self.calls_lock = threading.Lock()
        self.containers = {}
        self.image = {"Id": "sha256:" + "a" * 64, "Architecture": "amd64", "Os": "linux",
                      "Config": {"Env": ["PATH=/bin"], "Entrypoint": None}}
        self.platform_error = self.inspect_error = self.start_error = self.tool_error = self.remove_error = 0
        self.partial = self.bad_cid = False
        self.start_hook = self.remove_hook = None
        self.unrunnable_image_ids = set()
        self.stderr = io.StringIO()
        for target, name, value in ((B, "_TOOL_SESSION", None), (B, "SRC", Path('/source tree')),
                                    (B, "use_docker", lambda: True),
                                    (B, "toolchain", lambda: Path('/tool chain')),
                                    (B.subprocess, "run", self.backend), (sys, "stderr", self.stderr)):
            patched = patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def backend(self, argv, **kwargs):
        expected = {"cwd": B.SRC, "capture_output": True, "text": True}
        if argv[0] == 'docker' and (argv[1] in ('image', 'inspect', 'rm')
                                    or (argv[1] == 'run' and '-d' in argv)):
            expected['start_new_session'] = True
        self.assertEqual(kwargs, expected)
        with self.calls_lock:
            self.calls.append(list(argv))
        output, error, code = '', '', 0
        if argv[:3] == ['docker', 'image', 'inspect']:
            code = self.inspect_error or (self.platform_error if '--platform' in argv else 0)
            output = json.dumps([self.image]) if not code else ''
            error = 'unsupported inspection' if code else ''
        elif argv[:2] == ['docker', 'run'] and '-d' in argv:
            if argv[-3] in self.unrunnable_image_ids:
                return subprocess.CompletedProcess(argv, 125, '', 'No such image: ' + argv[-3])
            session = B._TOOL_SESSION
            if self.start_hook:
                self.start_hook()
            cid = (str(len(self.containers) + 1) * 64)[:64]
            if not self.start_error or self.partial:
                self.containers[cid] = {'Id': cid, 'Name': '/' + session.name,
                                        'Config': {'Labels': {'io.felucca.build-session': session.token}}}
            output, code = ('malformed' if self.bad_cid else cid + '\n'), self.start_error
            error = 'startup failed\n' if code else ''
        elif argv[:2] == ['docker', 'inspect']:
            found = [record for record in self.containers.values() if record['Name'].lstrip('/') == argv[-1]]
            output, code, error = (json.dumps(found), 0, '') if found else ('', 1, 'No such container\n')
        elif argv[:2] == ['docker', 'rm']:
            if self.remove_hook:
                self.remove_hook()
            if self.remove_error:
                code, error = self.remove_error, 'engine unavailable\n'
            else:
                self.assertIn(argv[-1], self.containers)
                self.containers.pop(argv[-1])
        else:
            output, error, code = 'tool stdout\n', 'tool stderr\n', self.tool_error
        return subprocess.CompletedProcess(argv, code, output, error)

    def commands(self, operation):
        return [argv for argv in self.calls if argv[:2] == ['docker', operation]]

    def test_non_main_thread_session_keeps_legacy_lifetime(self):
        errors = []
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        def worker():
            try:
                with B.toolchain_session():
                    B.tc('cc', 'file')
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.commands('run')), 1)
        self.assertIn('--rm', self.commands('run')[0])
        self.assertNotIn('-d', self.commands('run')[0])
        self.assertFalse(self.commands('exec'))
        self.assertFalse(self.commands('image'))
        self.assertFalse(self.commands('rm'))
        self.assertIn('outside the Python main thread', self.stderr.getvalue())
        self.assertIsNone(B._TOOL_SESSION)
        self.assertEqual({sig: signal.getsignal(sig) for sig in before}, before)

    def test_native_and_standalone_paths_keep_exact_argv_and_streams(self):
        with patch.object(B, 'use_docker', return_value=False):
            with B.toolchain_session():
                self.assertEqual(B.tc('cc', Path('/source tree/file with spaces.c'), '-DVALUE=$x;"q"'), 'tool stdout\n')
        self.assertEqual(self.calls, [['/tool chain/pi32v2/bin/clang', '-target', 'pi32v2',
                                      'file with spaces.c', '-DVALUE=$x;"q"']])
        self.assertEqual(self.stderr.getvalue(), 'tool stderr\n')
        self.calls.clear()
        B.tc('common/bin/objdump', '-t', 'input file')
        self.assertEqual(self.calls, [['docker', 'run', '--rm', '--platform', 'linux/amd64',
                                      '-v', '/source tree:/work', '-v', '/tool chain:/opt/jieli:ro',
                                      '-w', '/work', B.DOCKER_IMAGE, '/opt/jieli/common/bin/objdump', '-t', 'input file']])

    def test_lazy_shared_session_exact_args_and_cleanup(self):
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with B.toolchain_session():
            self.assertEqual(self.calls, [])
            session = B._TOOL_SESSION
            B.tc('cc', Path('/source tree/a b.c'), 'ü', '$HOME', '"literal"')
            B.tc('common/bin/objdump', '-t', 'a b.elf')
            self.assertEqual(len(self.commands('run')), 1)
            self.assertEqual(len(self.commands('image')), 1)
            startup = self.commands('run')[0]
            self.assertEqual(startup, ['docker', 'run', '-d', '--name', session.name, '--label',
                'io.felucca.build-session=' + session.token, '--platform', 'linux/amd64',
                '-v', '/source tree:/work', '-v', '/tool chain:/opt/jieli:ro', '-w', '/work',
                self.image['Id'], 'sleep', 'infinity'])
            self.assertEqual(self.commands('exec')[0], ['docker', 'exec', '-w', '/work', session.cid,
                '/opt/jieli/pi32v2/bin/clang', '-target', 'pi32v2', 'a b.c', 'ü', '$HOME', '"literal"'])
            cid = session.cid
        self.assertEqual(self.commands('rm'), [['docker', 'rm', '--force', cid]])
        self.assertFalse(self.containers)
        self.assertIsNone(B._TOOL_SESSION)
        self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)
        with self.assertRaisesRegex(SystemExit, 'session is closed'):
            session.command('cc', [])

    def test_parallel_first_use_starts_once(self):
        entered, release = threading.Event(), threading.Event()
        errors, results = [], []
        def block():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release startup')
        self.start_hook = block
        def worker():
            try:
                results.extend(B.tc_all(*[("cc", str(i)) for i in range(8)]))
            except BaseException as error:
                errors.append(error)
        with B.toolchain_session():
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(len(self.commands('run')), 1)
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, ['tool stdout\n'] * 8)
        self.assertEqual(len(self.commands('exec')), 8)
        self.assertEqual(len({argv[4] for argv in self.commands('exec')}), 1)
        self.assertEqual(len(self.commands('rm')), 1)

    def test_overlapping_sessions_remove_only_their_own_container(self):
        first, second = B.ToolchainSession(), B.ToolchainSession()
        with patch.object(B, '_TOOL_SESSION', first):
            first.command('cc', ['first'])
        with patch.object(B, '_TOOL_SESSION', second):
            second.command('cc', ['second'])
        self.assertNotEqual(first.name, second.name)
        self.assertNotEqual(first.cid, second.cid)
        first.close()
        self.assertNotIn(first.cid, self.containers)
        self.assertIn(second.cid, self.containers)
        self.assertEqual(second.command('cc', ['still-active'])[4], second.cid)
        second.close()
        self.assertFalse(self.containers)
        self.assertEqual([argv[-1] for argv in self.commands('rm')], [first.cid, second.cid])

    def test_fresh_invocations_have_unique_owned_identity(self):
        sessions = []
        for _ in range(2):
            with B.toolchain_session():
                sessions.append(B._TOOL_SESSION)
                B.tc('cc', 'file')
        self.assertNotEqual(sessions[0].name, sessions[1].name)
        self.assertNotEqual(sessions[0].token, sessions[1].token)
        self.assertEqual(len(self.commands('run')), 2)
        self.assertEqual(len(self.commands('rm')), 2)
        self.assertFalse(self.containers)

    def test_custom_entrypoint_or_bad_inspection_uses_visible_legacy_path(self):
        for value, code in ((['setup'], 0), (None, 1)):
            with self.subTest(entrypoint=value, inspect_code=code):
                self.image['Config']['Entrypoint'] = value
                self.inspect_error = code
                self.calls.clear()
                with B.toolchain_session():
                    B.tc('cc', 'first')
                    B.tc('cc', 'second')
                self.assertEqual(len(self.commands('run')), 2)
                self.assertTrue(all('--rm' in argv and '-d' not in argv for argv in self.commands('run')))
                self.assertFalse(self.commands('exec'))
                self.assertFalse(self.commands('rm'))
        self.assertIn('one-shot tool containers', self.stderr.getvalue())

    def test_platform_unsupported_fallback_requires_actual_amd64_config(self):
        self.platform_error = 125
        with B.toolchain_session():
            B.tc('cc', 'file')
        self.assertEqual(len(self.commands('image')), 2)
        self.assertEqual(len(self.commands('exec')), 1)
        for arch, config in (('', None), ('arm64', self.image['Config']), ('amd64', {})):
            with self.subTest(arch=arch, config=config):
                self.calls.clear()
                self.image['Architecture'], self.image['Config'] = arch, config
                with B.toolchain_session():
                    B.tc('cc', 'file')
                self.assertFalse(self.commands('exec'))
                self.assertIn('--rm', self.commands('run')[0])

    def test_multiarch_index_config_none_never_qualifies(self):
        self.image.update(Architecture='', Os='', Config=None)
        with B.toolchain_session():
            B.tc('cc', 'file')
        self.assertFalse(self.commands('exec'))
        self.assertIn('--rm', self.commands('run')[0])

    def test_selected_manifest_uses_runnable_repository_digest(self):
        # Docker containerd store: --platform inspect returns the child manifest Id,
        # but only its named index digest can be used to start the selected image.
        selected = 'sha256:a4672c0cb26fbdde88e38fa2dfb6c681942306680e41e4378b28770b6e79ee91'
        runnable = 'debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587'
        self.image.update(Id=selected, RepoDigests=['not-an-immutable-ref', runnable],
                          Descriptor={'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                      'digest': selected,
                                      'platform': {'architecture': 'amd64', 'os': 'linux'}})
        self.unrunnable_image_ids.add(selected)
        with B.toolchain_session():
            B.tc('cc', 'file')
        self.assertEqual(self.commands('run')[0][-3], runnable)
        self.assertEqual(len(self.commands('run')), 1)
        self.assertEqual(len(self.commands('exec')), 1)
        self.assertEqual(len(self.commands('rm')), 1)
        self.assertFalse(self.containers)

    def test_manifest_without_usable_repository_digest_keeps_legacy_path(self):
        self.image['Descriptor'] = {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                    'digest': self.image['Id']}
        for refs in ([], ['debian:bookworm-slim'], ['debian@sha256:short'],
                     ['--unsafe@sha256:' + 'b' * 64], [None]):
            with self.subTest(refs=refs):
                self.image['RepoDigests'] = refs
                self.calls.clear()
                with B.toolchain_session():
                    B.tc('cc', 'file')
                self.assertEqual(len(self.commands('run')), 1)
                self.assertIn('--rm', self.commands('run')[0])
                self.assertFalse(self.commands('exec'))
                self.assertFalse(self.commands('rm'))
        self.assertIn('no runnable immutable reference', self.stderr.getvalue())

    def test_podman_bare_image_id_is_supported(self):
        self.image['Id'] = 'a' * 64
        with B.toolchain_session():
            B.tc('cc', 'file')
        self.assertEqual(self.commands('run')[0][-3], 'a' * 64)
        self.assertEqual(len(self.commands('exec')), 1)

    def test_start_failure_and_partial_start_cleanup_never_retry(self):
        for partial in (False, True):
            with self.subTest(partial=partial):
                self.calls.clear()
                self.partial, self.start_error = partial, 125
                with self.assertRaisesRegex(SystemExit, 'cannot start owned'):
                    with B.toolchain_session():
                        session = B._TOOL_SESSION
                        B.tc('cc', 'file')
                with self.assertRaisesRegex(SystemExit, 'session is closed'):
                    session.command('cc', [])
                self.assertEqual(len(self.commands('run')), 1)
                self.assertEqual(len(self.commands('rm')), int(partial))
                self.assertFalse(self.containers)

    def test_invalid_start_cid_cleans_only_labeled_partial_container(self):
        self.bad_cid = True
        with self.assertRaisesRegex(SystemExit, 'cannot start owned'):
            with B.toolchain_session():
                B.tc('cc', 'file')
        self.assertEqual(len(self.commands('rm')), 1)
        self.assertFalse(self.containers)

    def test_foreign_name_collision_is_not_removed(self):
        self.start_error = 125
        def collide():
            self.containers['f' * 64] = {'Id': 'f' * 64, 'Name': '/' + B._TOOL_SESSION.name,
                                       'Config': {'Labels': {'io.felucca.build-session': 'foreign'}}}
        self.start_hook = collide
        with self.assertRaisesRegex(SystemExit, 'cannot start owned'):
            with B.toolchain_session():
                B.tc('cc', 'file')
        self.assertFalse(self.commands('rm'))
        self.assertIn('f' * 64, self.containers)
        self.assertIn('refusing cleanup without exact container ownership', self.stderr.getvalue())

    def test_tool_failure_preserves_streams_and_primary_error_during_cleanup_failure(self):
        self.tool_error, self.remove_error = 17, 125
        with self.assertRaisesRegex(SystemExit, 'pi32v2/bin/clang failed'):
            with B.toolchain_session():
                B.tc('cc', 'file')
        self.assertEqual(self.stderr.getvalue().count('tool stdout\ntool stderr\n'), 1)
        self.assertIn('cleanup failed for owned container', self.stderr.getvalue())
        self.assertEqual(len(self.commands('rm')), 1)

    def test_cleanup_failure_after_success_is_not_a_successful_lifecycle(self):
        self.remove_error = 125
        with self.assertRaisesRegex(SystemExit, 'owned toolchain cleanup failed'):
            with B.toolchain_session():
                B.tc('cc', 'file')
        self.assertIsNone(B._TOOL_SESSION)

    def test_exception_without_tool_failure_still_cleans(self):
        with self.assertRaisesRegex(ValueError, 'generation failure'):
            with B.toolchain_session():
                B.tc('cc', 'file')
                raise ValueError('generation failure')
        self.assertFalse(self.containers)

    def test_active_interrupt_and_deferred_same_thread_startup(self):
        for signum, expected in ((signal.SIGINT, KeyboardInterrupt), (signal.SIGTERM, SystemExit)):
            for startup in (False, True):
                with self.subTest(signal=signum, startup=startup):
                    self.calls.clear()
                    self.start_hook = (lambda: B._TOOL_SESSION.interrupted(signum, None)) if startup else None
                    before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
                    with self.assertRaises(expected) as raised:
                        with B.toolchain_session():
                            B.tc('cc', 'file')
                            B._TOOL_SESSION.interrupted(signum, None)
                    if signum == signal.SIGTERM:
                        self.assertEqual(raised.exception.code, 143)
                    self.assertFalse(self.containers)
                    self.assertEqual(len(self.commands('rm')), 1)
                    self.assertEqual({sig: signal.getsignal(sig) for sig in before}, before)

    def test_signal_during_worker_startup_waits_for_owned_creation(self):
        entered, release, closing = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def block():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release startup')
        self.start_hook = block
        def worker():
            try:
                B.tc('cc', 'file')
            except BaseException as error:
                errors.append(error)
        thread = releaser = None
        try:
            with self.assertRaises(SystemExit) as raised:
                with B.toolchain_session():
                    session = B._TOOL_SESSION
                    original_close = session.close
                    def close():
                        closing.set()
                        return original_close()
                    thread = threading.Thread(target=worker)
                    thread.start()
                    self.assertTrue(entered.wait(5))
                    def unblock():
                        if closing.wait(5):
                            release.set()
                    releaser = threading.Thread(target=unblock)
                    releaser.start()
                    with patch.object(session, 'close', side_effect=close):
                        session.interrupted(signal.SIGTERM, None)
            self.assertEqual(raised.exception.code, 143)
        finally:
            release.set()
            if thread:
                thread.join(5)
            if releaser:
                releaser.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], SystemExit)
        self.assertEqual(errors[0].code, 143)
        self.assertFalse(self.containers)
        self.assertEqual(len(self.commands('run')), 1)
        self.assertEqual(len(self.commands('rm')), 1)

    def test_secondary_signal_during_cleanup_is_deferred(self):
        self.remove_hook = lambda: B._TOOL_SESSION.interrupted(signal.SIGINT, None)
        with self.assertRaises(KeyboardInterrupt):
            with B.toolchain_session():
                B.tc('cc', 'file')
        self.assertFalse(self.containers)
        self.assertEqual(len(self.commands('rm')), 1)

    def test_real_child_process_signal_handlers_cleanup_and_exit(self):
        # The child exercises actual OS delivery/handler restoration with a fake
        # command boundary. It never creates a Docker container.
        script = r"""
import json, os, signal, subprocess, sys
from pathlib import Path
import build as B
calls=[]
def fake(argv, **kwargs):
    calls.append(argv)
    if argv[1:3] == ['image','inspect']:
        output=json.dumps([{'Id':'sha256:'+'a'*64,'Architecture':'amd64','Os':'linux',
                            'Config':{'Env':['PATH=/bin'],'Entrypoint':None}}])
    elif argv[1:2] == ['run']:
        output='c'*64+'\n'
    else:
        output=''
    return subprocess.CompletedProcess(argv,0,output,'')
B.subprocess.run=fake
B.use_docker=lambda: True
B.toolchain=lambda: Path('/fake toolchain')
try:
    with B.toolchain_session():
        B.tc('cc','file')
        os.kill(os.getpid(),int(sys.argv[1]))
finally:
    print(json.dumps({'removed':sum(x[1:2]==['rm'] for x in calls),'session_cleared':B._TOOL_SESSION is None}))
"""
        for signum in (signal.SIGINT, signal.SIGTERM):
            result = self.real_run([sys.executable, '-c', script, str(signum)], cwd=ROOT,
                                   env=dict(os.environ, PYTHONPATH=str(ROOT / 'tools')),
                                   capture_output=True, text=True, timeout=10)
            with self.subTest(signal=signum):
                self.assertIn(result.returncode, (-signum, 128 + signum), result.stderr)
                self.assertEqual(json.loads(result.stdout), {'removed': 1, 'session_cleared': True})


class TerminalSignals(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'terminal process groups require POSIX')
    def test_terminal_interrupt_waits_for_delayed_daemon_creation_and_cleanup(self):
        # Actual clients and process-group signals, with an independent fake daemon.
        # The daemon can commit creation after an interrupted client has exited.
        import time
        docker_script = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
state = Path(os.environ['FELUCCA_FAKE_DOCKER_STATE'])
def wait_for(name):
    deadline = time.monotonic() + 10
    while not (state / name).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('fake daemon gate timed out: ' + name)
        time.sleep(0.005)
args = sys.argv[1:]
if args[0] == 'daemon':
    wait_for('create-request.json')
    wait_for('publish')
    (state / 'owned.json').write_text((state / 'create-request.json').read_text())
    (state / 'daemon-published').touch()
elif args[:2] == ['image', 'inspect']:
    print(json.dumps([{'Id': 'sha256:' + 'a'*64, 'Architecture': 'amd64', 'Os': 'linux',
                       'Config': {'Env': ['PATH=/bin'], 'Entrypoint': None}}]))
elif args[0] == 'run':
    def interrupted(signum, frame):
        (state / 'client-interrupted').touch()
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    label = args[args.index('--label') + 1].split('=', 1)
    record = {'Id': 'c'*64, 'Name': '/' + args[args.index('--name') + 1],
              'Config': {'Labels': {label[0]: label[1]}}}
    (state / 'create-request.tmp').write_text(json.dumps(record))
    (state / 'create-request.tmp').replace(state / 'create-request.json')
    (state / 'run-ready.tmp').write_text(json.dumps({'pgid': os.getpgrp()}))
    (state / 'run-ready.tmp').replace(state / 'run-ready.json')
    wait_for('daemon-published')
    print(record['Id'])
elif args[0] == 'inspect':
    if not (state / 'owned.json').exists():
        print('No such container', file=sys.stderr)
        raise SystemExit(1)
    print('[' + (state / 'owned.json').read_text() + ']')
elif args[0] == 'rm':
    record = json.loads((state / 'owned.json').read_text())
    if args[-1] != record['Id']:
        raise RuntimeError('wrong container removed')
    (state / 'owned.json').unlink()
    (state / 'removed').write_text(args[-1])
elif args[0] != 'exec':
    raise RuntimeError('unexpected fake Docker command: ' + repr(args))
'''
        builder_script = r'''
import importlib.util, os, signal, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('build', sys.argv[1])
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
state = Path(os.environ['FELUCCA_FAKE_DOCKER_STATE'])
original = B.ToolchainSession.interrupted
def interrupted(self, signum, frame):
    (state / 'signal-seen').touch()
    return original(self, signum, frame)
B.ToolchainSession.interrupted = interrupted
B.use_docker = lambda: True
B.toolchain = lambda: Path('/fake toolchain')
try:
    with B.toolchain_session():
        B.tc('cc', 'file')
finally:
    (state / 'builder-done').touch()
'''
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp)
                docker = state / 'docker'
                docker.write_text('#!' + sys.executable + '\n' + docker_script)
                docker.chmod(0o755)
                env = dict(os.environ, FELUCCA_FAKE_DOCKER_STATE=tmp,
                           PATH=tmp + os.pathsep + os.environ['PATH'],
                           PYTHONPATH=str(ROOT / 'tools'))
                daemon = subprocess.Popen([sys.executable, str(docker), 'daemon'], env=env,
                                          start_new_session=True, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE, text=True)
                child = subprocess.Popen([sys.executable, '-c', builder_script, str(Path(B.__file__).resolve())],
                                         cwd=ROOT, env=env, start_new_session=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                def wait_for(name):
                    deadline = time.monotonic() + 10
                    while not (state / name).exists():
                        if time.monotonic() >= deadline:
                            self.fail('process-group fixture timed out: ' + name)
                        time.sleep(0.005)
                try:
                    wait_for('run-ready.json')
                    client_group = json.loads((state / 'run-ready.json').read_text())['pgid']
                    os.killpg(child.pid, signum)
                    wait_for('signal-seen')
                    if client_group == child.pid:
                        # Reproduce the old race deterministically: the interrupted
                        # client exits and cleanup observes absence before the daemon commits.
                        wait_for('builder-done')
                        self.assertTrue((state / 'client-interrupted').exists())
                    (state / 'publish').touch()
                    wait_for('daemon-published')
                    stdout, stderr = child.communicate(timeout=10)
                    self.assertIn(child.returncode, (-signum, 128 + signum), stdout + stderr)
                    self.assertFalse((state / 'owned.json').exists(),
                                     'late daemon creation leaked an owned container after builder exit; '
                                     f'builder_pgid={child.pid}; client_pgid={client_group}; '
                                     + ((state / 'owned.json').read_text()
                                        if (state / 'owned.json').exists() else ''))
                    self.assertEqual((state / 'removed').read_text(), 'c' * 64)
                    self.assertFalse((state / 'client-interrupted').exists())
                finally:
                    (state / 'publish').touch()
                    if child.poll() is None:
                        try:
                            child.communicate(timeout=2)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.communicate(timeout=2)
                    try:
                        _, daemon_error = daemon.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        daemon.kill()
                        _, daemon_error = daemon.communicate(timeout=2)
                    self.assertEqual(daemon.returncode, 0, daemon_error)


class SessionCleanupContext(unittest.TestCase):
    """Only this context's propagating exception takes precedence over cleanup failure."""
    def setUp(self):
        self.session = MagicMock()
        self.cleanup_error = RuntimeError('daemon unavailable')
        self.session.close.side_effect = self.cleanup_error
        for name, value in (('use_docker', lambda: True),
                            ('ToolchainSession', lambda: self.session), ('_TOOL_SESSION', None)):
            patched = patch.object(B, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def finished(self):
        self.session.close.assert_called_once_with()
        self.session.install_handlers.assert_called_once_with()
        self.session.restore_handlers.assert_called_once_with()
        self.assertIsNone(B._TOOL_SESSION)

    def test_cleanup_failure_in_handled_caller_exception_is_fatal(self):
        caller = ValueError('already handled by caller')
        try:
            raise caller
        except ValueError:
            with self.assertRaisesRegex(SystemExit, 'owned toolchain cleanup failed') as raised:
                with B.toolchain_session():
                    self.assertIs(B._TOOL_SESSION, self.session)
            self.assertIs(sys.exc_info()[1], caller)
        self.assertIs(raised.exception.__cause__, self.cleanup_error)
        self.session.cleanup_error.assert_called_once_with(self.cleanup_error)
        self.finished()

    def test_cleanup_failure_preserves_the_actual_body_exception(self):
        for primary in (ValueError('body failed'), SystemExit(17), KeyboardInterrupt()):
            with self.subTest(primary=type(primary).__name__):
                self.session.reset_mock()
                try:
                    raise LookupError('already handled by caller')
                except LookupError:
                    with self.assertRaises(type(primary)) as raised:
                        with B.toolchain_session():
                            raise primary
                self.assertIs(raised.exception, primary)
                self.session.cleanup_error.assert_called_once_with(self.cleanup_error)
                self.finished()

    def test_successful_cleanup_in_handled_caller_exception_returns_normally(self):
        self.session.close.side_effect = None
        caller = ValueError('already handled by caller')
        try:
            raise caller
        except ValueError:
            with B.toolchain_session():
                self.assertIs(B._TOOL_SESSION, self.session)
            self.assertIs(sys.exc_info()[1], caller)
        self.session.cleanup_error.assert_not_called()
        self.finished()


class NoJobs(unittest.TestCase):
    """main() with mocked generators and compilers: bad input starts none of them, good input uses one identity."""

    def setUp(self):
        environment = patch.dict(os.environ, {"FELUCCA_PROFILE": "standard"})
        environment.start()
        self.addCleanup(environment.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        gen = Path(self.tmp.name) / "gen"
        gen.mkdir()
        (gen / "build-identity.json").write_text('{}\n')
        (gen / "resolved-profile.json").write_text('{"profile":"standard"}\n')
        self.m = {n: MagicMock(name=n) for n in ("generate", "build_loader", "build_app", "check", "mmio_check",
                                                 "tc_all", "run", "Pool")}
        self.m["build_loader"].return_value = b"ota"
        self.m["build_app"].return_value = (b"img", "", "", "", "")
        self.m["check"].return_value = ([], [])
        self.m["mmio_check"].return_value = []
        for n, new in (("generate", self.m["generate"]), ("build_loader", self.m["build_loader"]),
                       ("build_app", self.m["build_app"]), ("check", self.m["check"]),
                       ("mmio_check", self.m["mmio_check"]), ("ThreadPoolExecutor", self.m["Pool"])):
            p = patch.object(B, n, new)
            p.start()
            self.addCleanup(p.stop)
        import build_report
        self.report_mocks = {}
        for name in ('input_hashes', 'configuration', 'tool_fingerprints'):
            self.report_mocks[name] = MagicMock(return_value={})
            report_patch = patch.object(build_report, name, self.report_mocks[name])
            report_patch.start()
            self.addCleanup(report_patch.stop)
        report_patch = patch.object(build_report, 'write', side_effect=lambda *args:
                                   (out / 'resource-report.json').write_text('{}\n'))
        report_patch.start()
        self.addCleanup(report_patch.stop)
        for p in (patch('profile.contract_json', return_value='{}\n'), patch("build_identity.resolve", return_value={}), patch.object(B, "OUT", out), patch.object(B, "LDR", out / "loader"), patch.object(B, "GEN", gen),
                  patch.object(B.subprocess, "run", self.m["run"]),
                  patch.object(B.fm1pkg_make, "sdk_file", lambda rel: b""),
                  patch.object(B.fm1pkg_make, "flash_image", lambda img, key: img),
                  patch.object(B.fm1pkg_make, "ufw", self.ufw),
                  patch.object(B, "PRODUCT", B.PRODUCT), patch.object(B, "VERSION", None),
                  patch("sys.stdout", io.StringIO())):
            p.start()
            self.addCleanup(p.stop)
        self.out = out
        self.packed = []
        self.m["Pool"].return_value.__enter__.return_value.submit = lambda f: MagicMock(result=f)

    def ufw(self, flash, ota, product):
        self.packed.append(product)
        return b"pkg:" + product.encode()

    def started(self):
        return [n for n, m in self.m.items() if m.called]

    def test_imported_main_coalesces_loader_and_app_tools(self):
        calls = []
        def command(argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ['docker', 'image', 'inspect']:
                output = json.dumps([{'Id': 'sha256:' + 'a' * 64, 'Architecture': 'amd64', 'Os': 'linux',
                                      'Config': {'Env': ['PATH=/bin'], 'Entrypoint': None}}])
            else:
                output = 'c' * 64 + '\n' if argv[:2] == ['docker', 'run'] and '-d' in argv else ''
            return subprocess.CompletedProcess(argv, 0, output, '')
        self.m['run'].side_effect = command
        self.m['build_loader'].side_effect = lambda: (B.tc('cc', 'loader.c'), b'ota')[1]
        self.m['build_app'].side_effect = lambda: (B.tc('cc', 'app.c'), (b'img', '', '', '', ''))[1]
        with patch.object(B, 'use_docker', return_value=True), \
                patch.object(B, 'toolchain', return_value=Path('/fake toolchain')):
            B.main([])
        self.assertEqual(len([x for x in calls if x[:2] == ['docker', 'run']]), 1)
        self.assertEqual(len([x for x in calls if x[:2] == ['docker', 'exec']]), 2)
        self.assertEqual(len([x for x in calls if x[:2] == ['docker', 'rm']]), 1)

    def test_invalid_starts_nothing(self):
        for argv in (["--product", ""], ["--product", "FM-1_a b"], ["--product", "FM-1_" + "x" * 16],
                     ["--product", "FM-1_ä"], ["--product", "FM-1_015"], ["--product", "FM-1_a\"b"],
                     ["--release", "1.0", "--product", "bad"], ["--release", "bad", "--product", "FM-1_ok"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                B.main(argv)
            self.assertEqual(self.started(), [])
            self.assertEqual(list(self.out.iterdir()), [])
            self.assertEqual(self.packed, [])

    def test_unknown_profile_starts_no_jobs(self):
        with patch.dict("os.environ", {"FELUCCA_PROFILE": "unknown-profile"}):
            with self.assertRaises(SystemExit): B.main([])
        self.assertEqual(self.started(), [])
        self.assertEqual(self.packed, [])

    def test_reduced_release_requires_distinct_identity(self):
        with patch.dict("os.environ", {"FELUCCA_PROFILE": "reduced-lofi"}):
            for argv in (["--release", "1.0"], ["--release", "1.0", "--product", "FM-1_910"]):
                with self.assertRaises(SystemExit): B.main(argv)
            self.assertEqual(self.started(), [])
            c = B.resolve(["--release", "1.0", "--product", "FM-1_ACME"])
            self.assertEqual(c['name'], "felucca-1.0-FM-1_ACME-reduced-lofi.fwsc")

    def test_override_packages_one_identity(self):
        with patch.object(B, "build_app", side_effect=lambda: (self.assertEqual(B.PRODUCT, "FM-1_ACME"),
                                                                self.assertEqual(B.VERSION, "v1.0"),
                                                                (b"img", "", "", "", ""))[2]):
            B.main(["--release", "1.0", "--product", "FM-1_ACME"])
        self.assertEqual(self.packed, ["FM-1_ACME"])
        rel = self.out / "release-1.0-FM-1_ACME"
        self.assertEqual((rel / "felucca-1.0-FM-1_ACME.fwsc").read_bytes(), b"pkg:FM-1_ACME")
        self.assertIn("product FM-1_ACME", (rel / "BUILD-INPUTS.txt").read_text())
        self.assertFalse((self.out / "release-1.0").exists())

    def test_default_release_outputs(self):
        B.main(["--release", "1.0"])
        self.assertEqual(self.packed, ["FM-1_910"])
        rel = self.out / "release-1.0"
        self.assertTrue((rel / "felucca-1.0.fwsc").exists())
        self.assertTrue((rel / "felucca-1.0-app.bin").exists())
        self.assertFalse((rel / "BUILD-INPUTS.txt").exists())

    def test_repeated_builds_in_one_process(self):
        B.main(["--product", "FM-1_ACME"])
        B.main([])
        self.assertEqual(self.packed, ["FM-1_ACME", "FM-1_900"])
        self.assertEqual((self.out / "felucca.fwsc").read_bytes(), b"pkg:FM-1_900")

    def test_generation_source_or_tool_change_prevents_compile_and_report(self):
        for changed in ('input_hashes', 'tool_fingerprints'):
            for mock in self.report_mocks.values():
                mock.reset_mock(return_value=True, side_effect=True)
                mock.return_value = {}
            self.m['build_app'].reset_mock()
            current = {}
            self.report_mocks[changed].side_effect = lambda *args, **kwargs: dict(current)
            self.m['generate'].side_effect = lambda: current.update(changed='during generation')
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'asset or loader'):
                B.main([])
            self.m['build_app'].assert_not_called()
            self.assertFalse((self.out / 'resource-report.json').exists())
            self.assertEqual(self.packed, [])

    def test_help_preserves_existing_report_without_starting_jobs(self):
        report = self.out / 'resource-report.json'
        content = b'{"validation":"existing evidence"}\n'
        report.write_bytes(content)
        with self.assertRaises(SystemExit) as raised:
            B.main(['--help'])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(report.read_bytes(), content)
        self.assertEqual(self.started(), [])
        self.assertEqual(self.packed, [])

    def test_failed_attempt_removes_previous_success_report(self):
        report = self.out / 'resource-report.json'
        report.write_text('{"validation":"old success"}\n')
        self.m['check'].return_value = (['target guard failed'], [])
        with self.assertRaisesRegex(SystemExit, 'checks failed'):
            B.main([])
        self.assertFalse(report.exists())
        self.assertEqual(self.packed, [])
        report.write_text('old success')
        with self.assertRaises(SystemExit):
            B.main(['--product', 'bad'])
        self.assertFalse(report.exists())

    def test_default_dev_outputs(self):
        B.main([])
        self.assertEqual(self.packed, ["FM-1_900"])
        self.assertTrue((self.out / "felucca.fwsc").exists())


class TargetDefine(unittest.TestCase):
    def test_felucca_id_define(self):
        for product, want in ((None, "FM-1_900"), ("FM-1_ACME", "FM-1_ACME")):
            with tempfile.TemporaryDirectory() as folder, self.subTest(product=product):
                out = Path(folder) / "isolated"
                out.mkdir()
                shared = Path(folder) / "shared"
                shared.mkdir()
                sentinel = shared / "fm1_cpu1.o"
                sentinel.write_bytes(b"another build owns this object")
                isolated_object = out / "fm1_cpu1.o"
                isolated_object.write_bytes(b"stale isolated object")
                with patch.object(B, "OUT", out), patch.object(B, "PRODUCT", B.PRODUCT), \
                        patch.object(B, "VERSION", None), patch.object(B, "tc_all", side_effect=Stop) as tc:
                    c = B.resolve(["--product", product] if product else [])
                    B.PRODUCT = c["product"]
                    with self.assertRaises(Stop):
                        B.build_app()
                    cmds = tc.call_args.args
                    self.assertTrue(any(f'-DFELUCCA_ID="{want}"' in cmd for cmd in cmds))
                self.assertFalse(isolated_object.exists())
                self.assertEqual(sentinel.read_bytes(), b"another build owns this object")


if __name__ == "__main__":
    unittest.main()
