#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real source/archive and package fixtures; only external target commands are simulated.

These tests do not claim a real target, Git-free compiler reproduction or matching Wasm run.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build as B
import build_identity
import build_manifest as M
import build_report as R
import fm1_install
import fm1pkg_make
import source_archive
import source_archive_test as archive_fixtures


class Bundles(unittest.TestCase):
    def setUp(self):
        # Synthetic repositories have no relationship to the workflow's PR checkout.
        environment = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'})
        environment.start(); self.addCleanup(environment.stop)
        self.fixture = archive_fixtures.Archives(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.repo
        self.fixture.git(self.root, 'remote', 'add', 'origin', 'https://github.com/kmplngj/Felucca.git')
        self.fixture.write(self.root, 'uv.lock', 'fixture generator lock\n')
        self.fixture.write(self.root, 'LICENSING.md', 'Synthetic fixture notices; no vendor files.\n')
        self.fixture.write(self.root, 'assets/fonts/InterTight[wght].ttf', b'fixture variable font')
        self.fixture.write(self.root, 'assets/SAX/A#1.wav', b'fixture sample')
        self.fixture.write(self.root, 'tools/build_manifest.py', (ROOT / 'tools/build_manifest.py').read_bytes())
        self.fixture.commit(self.root)
        self.archive = self.fixture.base / 'felucca-1.6-source.tar.gz'
        source_archive.export(self.root, self.archive, '1.6')
        self.metadata, self.marker_hash = M.archive_metadata(self.archive)
        self.reproduction = self.fixture.base / 'extracted'
        with tarfile.open(self.archive, 'r:gz') as archive:
            archive.extractall(self.reproduction, filter='data')
        self.reproduction /= 'felucca-1.6-source'
        self.identity = build_identity.resolve(self.root, 'v1.6.1')
        self.revision = self.identity['revision']
        self.destination = self.fixture.base / 'bundle'
        self._package()
        self.report = self._outputs(self.root, self.identity)
        archived_identity = dict(self.identity, source='verified archive')
        self.reproduced = self._outputs(self.reproduction, archived_identity)
        self.calls = []
        self.commands = patch.object(M, 'run_check', side_effect=self._external_command)
        self.commands.start(); self.addCleanup(self.commands.stop)

    def _package(self):
        sdk = self.fixture.base / 'sdk'
        for name, data in [('uboot.boot', bytes(range(64))), ('cfg_tool.bin', b'cfg'), ('cfg/eq_cfg_hw.bin', b'eq')]:
            p = sdk / 'cpu/wl82/tools' / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        self.app = b'fixture app bytes'
        self.ota = B.ldr_wrap(fm1_install.LOADER_MARK + bytes((i * 101 + (i >> 7) * 29 + 101) & 255 for i in range(3000)))
        with patch.object(fm1pkg_make, 'SDK', sdk):
            self.package = fm1pkg_make.ufw(fm1pkg_make.flash_image(self.app, fm1pkg_make.KEY), self.ota, 'FM-1_900')

    def _outputs(self, root, identity):
        gen = root / 'build/gen'; gen.mkdir(parents=True, exist_ok=True)
        pins = {'firmware_revision': self.revision, 'engines_gitlink': self.metadata['engines']['revision'],
                'engines_upstream_revision': '1' * 40}
        source = 'firmware/src/felucca.c'
        resolved = {'profile': 'standard', 'asset_variant': 'm8stealth', 'source_pins': pins,
                    'build_flags': {'FELUCCA_FM4': '0', 'FELUCCA_SLICE': '1'}, 'selection_sha256': '2' * 64,
                    'input_sha256': {source: M.digest(root / source)}}
        contract = {'source_pins': {k: v for k, v in pins.items() if k != 'engines_upstream_revision'},
                    'supported_profiles': {'standard': {'resolved': resolved}}}
        for name, data in build_identity.outputs(identity).items(): (gen / name).write_text(data)
        (gen / 'resolved-profile.json').write_text(json.dumps(resolved))
        (gen / 'felucca_profile.h').write_text('/* compiled fixture selection */\n')
        outputs = {'build/felucca.bin': self.app, 'build/felucca.elf': b'fixture ELF',
                   'build/felucca.dis': b'fixture disassembly', 'build/loader/ota.bin': self.ota,
                   'build/felucca.fwsc': self.package,
                   'build/felucca.dis.profile.json': json.dumps({'resolved_profile': resolved}).encode(),
                   'build/profile-contract.json': json.dumps(contract).encode()}
        for name, data in outputs.items():
            p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        config = {'product': 'FM-1_900', 'version_override': 'v1.6.1', 'cpu2': True, 'selective_minsize': True,
                  'compile_flags': ['-target', 'pi32v2', '-Os'],
                  'effective_defines': {'FELUCCA_CPU2': '1', 'FELUCCA_FM4': '0', 'FELUCCA_SLICE': '1',
                                        'FELUCCA_ENG_TEST14': '0', 'FELUCCA_ENG_OMIT': '(-1)'},
                  'logical_constants': {'NPART': '4', 'NVOICE': '8', 'NSTEP': '64', 'HALF_FRAMES': '128'},
                  'generator_runtime': R.generator_runtime(root),
                  'execution_environment': {'backend': 'native', 'image_reference': None, 'system_runtime_fingerprint': None},
                  'compiler_headers_sha256': {'pi32v2/include/stdint.h': '3' * 64},
                  'compiler': {'version': 'fixture clang', 'sha256': '4' * 64},
                  'toolchain_sha256': {'ld': '5' * 64}, 'sdk_reference': 'fixture SDK', 'sdk_sha256': {'sdk': '6' * 64}}
        # External target execution is the fixture seam; source/archive/package verification remains real.
        source_hashes = {p: item['sha256'] for p, item in self.metadata['files'].items()}
        if identity['source'] == 'verified archive': source_hashes['SOURCE-PINS.json'] = self.marker_hash
        source_hashes.update({p.relative_to(root).as_posix(): M.digest(p) for p in gen.iterdir()})
        report = {'schema_version': 1, 'kind': 'felucca-post-link-resource-report',
                  'validation': 'production build guards passed', 'package': 'felucca.fwsc', 'build_identity': identity,
                  'configuration': config, 'configuration_sha256': hashlib.sha256(R.canonical(config)).hexdigest(),
                  'input_sha256': source_hashes, 'inputs_sha256': hashlib.sha256(R.canonical(source_hashes)).hexdigest(),
                  'artifact_sha256': {p: M.digest(root / p) for p in R.artifact_paths('felucca.fwsc')},
                  'resources': {'fixture': 'not a target measurement'}, 'stack_reservations': {}}
        (root / 'build/resource-report.json').write_text(json.dumps(report))
        return report

    def _external_command(self, command, cwd, output, env):
        self.calls.append((command, cwd))
        output.write_text('fixture external command exit 0\n')
        return command

    def create(self, **overrides):
        args = dict(allowed_revision=self.revision, profile_name='standard')
        args.update(overrides)
        return M.create(self.root, self.archive, self.reproduction, self.destination, **args)

    def reseal(self, mutate):
        manifest = M.read_json(self.destination / 'manifest.json')
        mutate(manifest)
        for name in manifest['files']: manifest['files'][name] = M.record(self.destination / name)
        (self.destination / 'manifest.json').write_bytes(M.canonical(manifest) + b'\n')
        (self.destination / 'SHA256SUMS').write_text(M.checksum_text(manifest['files'], M.digest(self.destination / 'manifest.json')))

    def test_real_archive_package_and_offline_move(self):
        manifest = self.create()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(manifest['runtime'], {'state': 'unavailable', 'reason': 'not_requested'})
        self.assertNotIn('manifest.json', manifest['files'])
        self.assertNotEqual(M.digest(self.root / 'build/resource-report.json'), M.digest(self.reproduction / 'build/resource-report.json'))
        moved = self.fixture.base / 'moved'; self.destination.rename(moved)
        self.assertEqual(M.verify(moved), manifest)

    def test_idempotent_creation_and_no_different_overwrite(self):
        first = self.create(); self.assertEqual(self.create(), first)
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            self.create(runtime_unavailable='build_failed')
        self.assertEqual(M.verify(self.destination), first)

    def test_revision_profile_and_dirty_source_refuse_before_external_checks(self):
        for args in [{'allowed_revision': self.revision[:8]}, {'allowed_revision': 'f' * 40}, {'profile_name': 'arbitrary'}]:
            with self.subTest(args=args), self.assertRaises(ValueError): self.create(**args)
        (self.root / 'firmware/src/felucca.c').write_text('changed after build')
        with self.assertRaisesRegex(ValueError, 'source changed after native build'): self.create()
        self.assertFalse(self.calls); self.assertFalse(self.destination.exists())

    def test_untracked_source_and_stale_generated_or_app_rejected(self):
        for name in ['extra.c', 'build/gen/felucca_profile.h', 'build/felucca.bin']:
            p = self.root / name; old = p.read_bytes() if p.exists() else None; p.write_bytes(b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError): self.create()
            if old is None: p.unlink()
            else: p.write_bytes(old)
        self.assertFalse(self.calls)

    def test_same_selection_different_cpu_configuration_has_different_key(self):
        manifest = self.create(); changed = copy.deepcopy(manifest['identity'])
        changed['target']['cpu2'] = False; changed['target']['effective_defines']['FELUCCA_CPU2'] = '0'
        self.assertEqual(changed['profile']['selection_sha256'], manifest['identity']['profile']['selection_sha256'])
        self.assertNotEqual(hashlib.sha256(b'felucca-build-key-v1\0' + M.canonical(changed)).hexdigest(), manifest['configuration_key'])

    def test_required_external_failure_never_emits_bundle(self):
        with patch.object(M, 'run_check', side_effect=ValueError('target budget failed')):
            with self.assertRaisesRegex(ValueError, 'target budget failed'): self.create()
        self.assertFalse(self.destination.exists())
        self.assertTrue(list(self.destination.parent.glob('.bundle.failed-*')))
        self.assertFalse((self.destination.parent / '.bundle.seal-lock').exists())

    def test_reproduction_mismatch_and_git_checkout_refused(self):
        (self.reproduction / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'Git-free'): self.create()
        (self.reproduction / '.git').rmdir()
        (self.reproduction / 'build/felucca.bin').write_bytes(b'wrong app')
        with self.assertRaisesRegex(ValueError, 'native artifact mismatch'): self.create()
        self.assertFalse(self.destination.exists())

    def test_file_hash_extra_file_symlink_and_path_refusals(self):
        self.create(); app = self.destination / 'build/felucca.bin'; old = app.read_bytes(); app.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'bundle file mismatch'): M.verify(self.destination)
        app.write_bytes(old)
        extra = self.destination / 'extra'; extra.write_text('unlisted')
        with self.assertRaisesRegex(ValueError, 'undeclared'): M.verify(self.destination)
        extra.unlink(); extra.symlink_to(app)
        with self.assertRaisesRegex(ValueError, 'symlink'): M.verify(self.destination)
        extra.unlink()
        for name in ('../escape', '/absolute', 'a/../b', 'a//b', '.', 'a\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError): M.safe_path(name)

    def test_borrowed_reproduction_receipt_refused_even_with_updated_outer_hashes(self):
        self.create(); receipt = self.destination / 'checks/source_reproduction.json'
        record = M.read_json(receipt); record['archive_sha256'] = '0' * 64; receipt.write_bytes(M.canonical(record))
        self.reseal(lambda manifest: None)
        with self.assertRaisesRegex(ValueError, 'reproduction receipt is for another build'): M.verify(self.destination)

    def test_changed_reproduced_configuration_refused_even_with_updated_outer_hashes(self):
        self.create(); path = self.destination / 'reproduction/build/resource-report.json'; report = M.read_json(path)
        report['configuration']['cpu2'] = False
        report['configuration_sha256'] = hashlib.sha256(R.canonical(report['configuration'])).hexdigest()
        path.write_bytes(M.canonical(report)); self.reseal(lambda manifest: None)
        with self.assertRaisesRegex(ValueError, 'reproduction configuration/resources differ'): M.verify(self.destination)

    def test_changed_check_binding_or_key_refused(self):
        self.create()
        self.reseal(lambda manifest: manifest.update(configuration_key='0' * 64))
        with self.assertRaisesRegex(ValueError, 'configuration key'): M.verify(self.destination)

    def test_unknown_fields_duplicate_keys_and_case_collisions_refused(self):
        self.create(); path = self.destination / 'manifest.json'; old = path.read_bytes()
        self.reseal(lambda manifest: manifest.update(unknown=True))
        with self.assertRaisesRegex(ValueError, 'invalid manifest'): M.verify(self.destination)
        path.write_bytes(old)
        path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'): M.verify(self.destination)

    def test_boolean_schema_nonfinite_and_case_collision_refused(self):
        self.create(); path = self.destination / 'manifest.json'; original = path.read_bytes()
        self.reseal(lambda manifest: manifest.update(schema_version=True))
        with self.assertRaisesRegex(ValueError, 'unsupported build manifest'): M.verify(self.destination)
        path.write_text('{"x":NaN}')
        with self.assertRaisesRegex(ValueError, 'Out of range float'): M.verify(self.destination)
        manifest = json.loads(original)
        manifest['files']['BUILD/FELUCCA.BIN'] = dict(manifest['files']['build/felucca.bin'])
        path.write_bytes(M.canonical(manifest) + b'\n')
        with self.assertRaisesRegex(ValueError, 'case-colliding'): M.verify(self.destination)

    def test_staging_creation_failure_and_existing_lock_preserve_owner(self):
        with patch.object(M.tempfile, 'mkdtemp', side_effect=OSError('staging refused')):
            with self.assertRaisesRegex(OSError, 'staging refused'): self.create()
        lock = self.destination.parent / '.bundle.seal-lock'
        self.assertFalse(lock.exists())
        lock.write_text('other owner')
        with self.assertRaises(FileExistsError): self.create()
        self.assertEqual(lock.read_text(), 'other owner')

    def test_broader_failure_evidence_is_copied_without_acceptance_inference(self):
        evidence = self.fixture.base / 'coverage.json'; evidence.write_text('{"status":"incomplete","failed":2}')
        manifest = self.create(evidence=[evidence])
        self.assertEqual(manifest['broader_acceptance']['host'], 'not_evaluated')
        self.assertEqual((self.destination / 'evidence/0-coverage.json').read_bytes(), evidence.read_bytes())
        self.assertEqual(M.verify(self.destination), manifest)

    def test_available_runtime_cannot_borrow_other_source(self):
        path = self.root / 'build/emu/runtime-report.json'; path.parent.mkdir(); path.write_text('{}')
        receipt = {'source': dict(M.source_identity(self.metadata), engines_revision='0' * 40), 'files': []}
        with patch.object(M, 'runtime_identity', return_value=({}, receipt)):
            with self.assertRaisesRegex(ValueError, 'runtime source differs'): self.create(runtime_receipt=path)

    def test_archive_entry_guard_runs_before_repository_imports(self):
        # The extracted entry verifies all sources before importing profile/build helpers.
        (self.reproduction / 'unmanifested.py').write_text('raise RuntimeError("must not execute")')
        result = subprocess.run([sys.executable, str(self.reproduction / 'tools/build_manifest.py'), 'verify', 'missing'],
                                cwd=self.reproduction, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unmanifested source file', result.stderr)
        self.assertNotIn('ImportError', result.stderr)


if __name__ == '__main__': unittest.main()
