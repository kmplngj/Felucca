#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""SMK release trust boundaries: actual archives, package layout and hashes."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_manifest_test as fixtures
import build_identity
import build_manifest as M
import build_report as R
import ci
import fm1pkg_make as P
import smk_release as S
import source_archive

class SmkRelease(unittest.TestCase):
    def setUp(self):
        f = self.f = fixtures.Bundles()
        f.setUp(); self.addCleanup(f.doCleanups)
        f.fixture.write(f.root, 'docs/smk37.md', 'SMK instructions\n'); f.fixture.commit(f.root)
        source_archive.export(f.root, f.archive, '1.6')
        f.metadata, f.marker_hash = M.archive_metadata(f.archive)
        f.revision = f.fixture.git(f.root, 'rev-parse', 'HEAD').decode().strip()
        shutil.rmtree(f.reproduction.parent)
        with tarfile.open(f.archive, 'r:gz') as archive: archive.extractall(f.reproduction.parent, filter='data')
        self.bundles = f.fixture.base / 'smk'; self.dest = f.fixture.base / 'assets'; self.dest.mkdir()

    def make(self, model):
        f = self.f; stem, package, product = S.names('1.6', model)
        with patch.object(P, 'SDK', f.fixture.base / 'sdk'):
            raw = P.ufw(P.flash_image(f.app, P.KEY, board='smk37'), f.ota, product)
        for root, source in ((f.root, 'git'), (f.reproduction, 'verified archive')):
            report = f._outputs(root, dict(build_identity.resolve(f.root, 'v1.6'), source=source))
            c = report['configuration']; c.update(board='smk37', model=model, product=product, version_override='v1.6')
            c['effective_defines'].update(BOARD_SMK37='1', SMK_MODEL='"'+P.MODELS[model]+'"', FELUCCA_ID='"'+product+'"', FELUCCA_UART='0')
            report['configuration_sha256'] = hashlib.sha256(R.canonical(c)).hexdigest()
            report['package'] = package; (root / 'build' / package).write_bytes(raw)
            report['artifact_sha256'] = {name: S.digest(root/name) for name in R.artifact_paths(package)}
            (root/S.REPORT).write_text(json.dumps(report))
        S.prepare(f.root, '1.6', model, f.reproduction, self.bundles/model)
        return self.bundles/model

    def reseal(self, root):
        m = S.read(root/S.MANIFEST)
        m['files'] = {p.relative_to(root).as_posix(): S.digest(p) for p in root.rglob('*') if p.is_file() and p.name not in (S.MANIFEST,'SHA256SUMS')}
        (root/S.MANIFEST).write_text(json.dumps(m)); ci.write_checksums(root)

    def all_models(self):
        for model in P.MODELS: self.make(model)
        source = S.read(self.bundles/'pro'/S.MANIFEST)['source_distribution']
        (self.dest/'BUILD-PROVENANCE.json').write_text(json.dumps(dict(version='1.6', revision=self.f.revision, source_distribution=source)))
        (self.dest/'felucca-1.6.fwsc').write_bytes(b'approved FM1'); ci.write_checksums(self.dest)

    def test_all_models_preserve_fm1_and_checksums(self):
        self.all_models(); S.stage(self.bundles,self.dest,'1.6',self.f.revision)
        self.assertEqual((self.dest/'felucca-1.6.fwsc').read_bytes(), b'approved FM1')
        for model in P.MODELS:
            stem, package, _ = S.names('1.6',model)
            for name in (package,stem+'-manifest.json',stem+'-resource-report.json',stem+'-resolved-profile.json'):
                self.assertTrue((self.dest/name).is_file())
        ci.verify_checksums(self.dest)
        with self.assertRaisesRegex(ValueError,'collide'): S.stage(self.bundles,self.dest,'1.6',self.f.revision)

    def test_wrong_identity_or_missing_artifact_fails(self):
        root = self.make('elite')
        for v,m,r in (('1.5','elite',self.f.revision),('1.6','pro',self.f.revision),('1.6','elite','a'*40)):
            with self.subTest(v=v,m=m), self.assertRaises(ValueError): S.verify(root,v,m,r)
        (root/'build/gen/resolved-profile.json').unlink()
        with self.assertRaises(ValueError): S.verify(root,'1.6','elite',self.f.revision)

    def test_resealed_package_still_fails_native_artifact_binding(self):
        root=self.make('pro'); p=root/'build'/S.names('1.6','pro')[1]
        raw=p.read_bytes(); p.write_bytes(raw[:-1]+bytes([raw[-1]^1])); self.reseal(root)
        with self.assertRaisesRegex(ValueError,'artifact mismatch'): S.verify(root,'1.6','pro',self.f.revision)

    def test_resealed_wrong_board_layout_cannot_borrow_valid_resource_report(self):
        root = self.make('pro'); package = S.names('1.6', 'pro')[1]
        with patch.object(P, 'SDK', self.f.fixture.base / 'sdk'):
            raw = P.ufw(P.flash_image(self.f.app, P.KEY), self.f.ota, 'SMK-37 Pro_916')
        (root/'build'/package).write_bytes(raw)
        report = S.read(root/S.REPORT)
        report['artifact_sha256']['build/'+package] = S.digest(root/'build'/package)
        (root/S.REPORT).write_text(json.dumps(report)); self.reseal(root)
        with self.assertRaisesRegex(S.fm1_install.InstallError, 'flash.bin layout'):
            S.verify(root, '1.6', 'pro', self.f.revision)

    def test_reproduction_manifest_and_archive_hashes_fail_closed(self):
        root=self.make('mke'); p=root/'reproduction-resource-report.json'; r=S.read(p)
        r['input_sha256']['SOURCE-PINS.json']='a'*64
        r['inputs_sha256']=hashlib.sha256(R.canonical(r['input_sha256'])).hexdigest()
        p.write_text(json.dumps(r)); self.reseal(root)
        with self.assertRaisesRegex(ValueError,'source manifest mismatch'): S.verify(root,'1.6','mke',self.f.revision)
        m=S.read(root/S.MANIFEST); m['source_distribution']['manifest_sha256']='b'*64
        (root/S.MANIFEST).write_text(json.dumps(m)); ci.write_checksums(root)
        with self.assertRaisesRegex(ValueError,'source archive does not match'): S.verify(root,'1.6','mke',self.f.revision)

    def test_last_model_failure_stages_nothing(self):
        self.all_models(); before={p.name:p.read_bytes() for p in self.dest.iterdir()}
        (self.bundles/'mke'/'SMK37.md').write_text('tampered')
        with self.assertRaises(ValueError): S.stage(self.bundles,self.dest,'1.6',self.f.revision)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.dest.iterdir()})
        (self.bundles/'mke'/'SMK37.md').write_bytes((self.f.root/'docs/smk37.md').read_bytes())
        self.reseal(self.bundles/'mke')
        fm1 = S.read(self.dest/'BUILD-PROVENANCE.json'); fm1['source_distribution']['sha256'] = 'f'*64
        (self.dest/'BUILD-PROVENANCE.json').write_text(json.dumps(fm1)); ci.write_checksums(self.dest)
        with self.assertRaisesRegex(ValueError, 'source distribution mismatch'):
            S.stage(self.bundles,self.dest,'1.6',self.f.revision)

if __name__=='__main__': unittest.main()
