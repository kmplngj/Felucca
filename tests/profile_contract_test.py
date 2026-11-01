#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Canonical registry export, production dependency refusal and pin provenance."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import profile


class Contract(unittest.TestCase):
    def test_canonical_recipes_ignore_developer_environment(self):
        before = profile.contract_json(ROOT)
        with patch.dict(os.environ, FELUCCA_PROFILE='unknown', FELUCCA_FONT='tamzen',
                        FELUCCA_FM4='1', FELUCCA_SLICE='0'):
            self.assertEqual(before, profile.contract_json(ROOT))
        value = json.loads(before)
        self.assertEqual(set(value['supported_profiles']), {'standard', 'reduced-lofi', 'macro', 'adpcm'})
        recipes = value['supported_profiles']
        standard = recipes['standard']['resolved']['engine_ids']
        self.assertNotIn(1, standard)
        self.assertNotIn(14, standard)
        self.assertNotIn(15, standard)
        self.assertEqual(recipes['adpcm']['resolved']['engine_ids'], standard + [15])
        self.assertNotIn(14, recipes['adpcm']['resolved']['engine_ids'])
        self.assertEqual(recipes['macro']['resolved']['engine_ids'], standard + [14])
        self.assertEqual(recipes['reduced-lofi']['resolved']['engine_ids'], [i for i in standard if i != 3])
        self.assertEqual(value['registry']['defaults'], [0, 12, 4, 10])
        self.assertEqual(value['source_pins'], profile.source_pins(ROOT))
        self.assertIn('firmware/engines/LICENSE', value['license_sha256'])
        self.assertIn('LICENSES/CC0-1.0.txt', value['license_sha256'])
        self.assertIn({'kind': 'engine', 'id': 14}, recipes['macro']['provider_reasons']['braids'])
        self.assertIn({'kind': 'provider', 'id': 'portable-dsp'},
                      recipes['standard']['provider_reasons']['native-core'])
        self.assertNotIn('engines-gpl', before)
        identities=value['engine_identity_reference']['slots']
        self.assertEqual(len(identities),64)
        self.assertEqual(identities[1],{'id':1,'key':'felucca.engine.digital','status':'retired'})
        self.assertEqual(identities[14],{'id':14,'key':'felucca.engine.macro','status':'active'})
        self.assertEqual(identities[15],{'id':15,'key':'felucca.engine.adpcm','status':'active'})
        self.assertTrue(all(s['status']=='reserved' and s['key'] is None for s in identities[16:]))
        for recipe in recipes.values():
            resolved=recipe['resolved']
            self.assertEqual(resolved['profile_engine_ids'],recipe['recipe']['engines'])
            self.assertEqual(set(resolved['collections']),{'firmware','portable-mit'})
            self.assertEqual(resolved['provider_dependencies'],
                             sorted([p for p in value['registry']['providers'] if p['id'] in resolved['providers']],key=lambda p:p['id']))
            self.assertEqual(resolved['collections']['portable-mit']['revision'],value['source_pins']['engines_gitlink'])
            self.assertEqual(resolved['collections']['portable-mit']['api']['actual'],
                             resolved['collections']['portable-mit']['api']['required'])
            self.assertEqual([e['id'] for e in resolved['engine_identities']],resolved['engine_ids'])
            for engine in resolved['engine_identities']:
                self.assertEqual(engine['key'],identities[engine['id']]['key'])
            self.assertEqual(resolved['engine_identity_reference']['sha256'],resolved['input_sha256'][profile.IDENTITY_REFERENCE])
        self.assertFalse(value['validation']['profiles_may_select_retired_engines'])
        self.assertTrue(value['validation']['source_paths_must_match_collection_owner'])
        self.assertTrue(value['validation']['portable_api_must_match_firmware_requirement'])
        for fm4 in ('0','1'):
            resolved=json.loads(profile.generated(ROOT,'standard',feature_flags={'FELUCCA_FM4':fm4,'FELUCCA_SLICE':'1'})['resolved-profile.json'])
            self.assertEqual(any(e['id']==1 and e['status']=='retired' for e in resolved['engine_identities']),fm4=='1')

    def test_contract_rejects_mapping_drift_through_the_production_resolver(self):
        read=profile.read_json
        def changed(path):
            data=read(path)
            if path.name=='catalog.json':data['engines'][14]['key']='felucca.engine.other'
            return data
        with patch.object(profile,'read_json',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'mapping changed'):profile.contract(ROOT)

    def test_export_reuses_production_dependency_validation(self):
        original = profile.read_json(ROOT / 'profiles/catalog.json')
        read = profile.read_json
        for mutate, error in (
                (lambda c: c['engines'][0].update(requires=['absent']), 'missing dependency'),
                (lambda c: c['providers'][0].update(requires=['portable-dsp']), 'cycle'),
                (lambda c: c.update(defaults=[63]), 'boot default'),
                (lambda c: c['engines'].append(copy.deepcopy(c['engines'][0])), 'duplicate engine')):
            catalog = copy.deepcopy(original)
            mutate(catalog)
            def fixture(path):
                return catalog if path.name == 'catalog.json' else read(path)
            with self.subTest(error=error), patch.object(profile, 'read_json', side_effect=fixture):
                with self.assertRaisesRegex(ValueError, error):
                    profile.contract(ROOT)

    def test_mismatched_engine_pin_refuses_export(self):
        git = profile.git
        def mismatch(root, *args):
            if root == ROOT / 'firmware/engines' and args == ('rev-parse', 'HEAD'):
                return '0' * 40
            return git(root, *args)
        with patch.object(profile, 'git', side_effect=mismatch):
            with self.assertRaisesRegex(ValueError, 'pinned gitlink'):
                profile.contract(ROOT)

    def test_cli_determinism_and_stale_contract_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'contract.json'
            command = [sys.executable, str(ROOT / 'tools/profile.py'), '--export-contract', str(output)]
            subprocess.run(command, check=True, capture_output=True)
            first = output.read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(first, output.read_bytes())
            self.assertEqual(subprocess.run(command + ['--check'], capture_output=True).returncode, 0)
            output.write_text('{}\n')
            self.assertNotEqual(subprocess.run(command + ['--check'], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
