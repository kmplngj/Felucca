#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Malformed selections, dependency graph conflicts, provenance and freshness."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import shutil

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('felucca_profile', ROOT/'tools/profile.py')
profile=importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)

class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.catalog=profile.read_json(ROOT/'profiles/catalog.json')
        self.standard=profile.read_json(ROOT/'profiles/standard.json')
        self.reference=profile.read_json(ROOT/profile.IDENTITY_REFERENCE)
    def fails(self, text, c=None, p=None):
        with self.assertRaisesRegex(ValueError,text):
            profile.resolve(c or self.catalog,p or self.standard,self.reference)
    def test_standard_and_reduced_stable_ids(self):
        a,_=profile.resolve(self.catalog,self.standard,self.reference)
        b,_=profile.resolve(self.catalog,profile.read_json(ROOT/'profiles/reduced-lofi.json'),self.reference)
        self.assertEqual(set(e['id'] for e in a)-set(e['id'] for e in b),{3})
        self.assertEqual(self.catalog['defaults'],[0,12,4,10])
        self.assertNotIn('FELUCCA_CPU2',json.dumps(self.catalog))
    def test_macro_is_opt_in_and_fixture_follows_catalog(self):
        standard=profile.generated(ROOT,'standard')
        macro=profile.generated(ROOT,'macro')
        a=json.loads(standard['resolved-profile.json'])
        b=json.loads(macro['resolved-profile.json'])
        self.assertEqual(set(b['engine_ids'])-set(a['engine_ids']),{14})
        self.assertNotIn('braids',a['providers'])
        self.assertIn('braids',b['providers'])
        self.assertFalse(any('braids/' in p for p in a['input_sha256']))
        self.assertIn('assets/braids/upstream/digital_oscillator.cc',b['input_sha256'])
        self.assertIn('firmware/src/macro_dsp.c',b['input_sha256'])
        self.assertIn('#define FELUCCA_PROFILE_NSLOTS 15',macro['felucca_profile.h'])
        self.assertIn('ENG_AT(FELUCCA_PROFILE_NSLOTS, &ENG_TEST14)',macro['engine_registry.inc'])
        self.assertNotIn('requires the original',macro['felucca_profile.h'])

    def test_macro_transitive_asset_change_invalidates_only_selected_profile(self):
        outputs=profile.generated(ROOT,'macro')
        pins=json.loads(outputs['resolved-profile.json'])['source_pins']
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=set(json.loads(outputs['resolved-profile.json'])['input_sha256'])
            paths.add('profiles/standard.json')
            for rel in paths:
                dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy(ROOT/rel,dest)
            with patch.object(profile,'source_pins',return_value=pins):
                before={n:profile.generated(root,n) for n in ('standard','macro')}
                helper=root/'assets/braids/upstream/digital_oscillator.cc'
                helper.write_text(helper.read_text()+'\n// mutation fixture\n')
                self.assertEqual(before['standard'],profile.generated(root,'standard'))
                self.assertNotEqual(before['macro'],profile.generated(root,'macro'))

    def test_unknown_and_duplicate_ids(self):
        self.standard['engines'].append(63);self.fails('unknown')
        self.standard['engines'].pop();self.standard['engines'].append(3);self.fails('duplicate')
        self.standard['engines'].pop();self.catalog['engines'][2]['id']=0;self.fails('duplicate')

    def test_keys_cannot_be_reassigned_removed_or_duplicated(self):
        for mutate, error in (
                (lambda c: c['engines'][0].update(key=c['engines'][2]['key']), 'duplicate engine keys'),
                (lambda c: c['engines'][0].update(key='felucca.engine.renamed'), 'mapping changed'),
                (lambda c: c['engines'][0].pop('key'), 'missing or invalid'),
                (lambda c: c['engines'][0].update(key='donor.engine.analog'), 'missing or invalid'),
                (lambda c: c['engines'][0].update(key='felucca.engine.Bad_slug'), 'missing or invalid'),
                (lambda c: c['engines'].pop(), 'retain every allocated'),
                (lambda c: (c['engines'][0].update(id=2), c['engines'][2].update(id=0)), 'mapping changed')):
            catalog=copy.deepcopy(self.catalog);mutate(catalog)
            with self.subTest(error=error): self.fails(error,c=catalog)

    def test_reference_rejects_ambiguous_or_missing_allocations(self):
        for mutate, error in (
                (lambda r: r['slots'].pop(), 'all 64'),
                (lambda r: r['slots'][63].update(id=62), 'duplicate engine IDs'),
                (lambda r: r['slots'][0].update(id=True), 'invalid engine identity reference slots'),
                (lambda r: r['slots'][0].update(status='unknown'), 'status'),
                (lambda r: r['slots'][0].update(key='analog'), 'namespaced'),
                (lambda r: r['slots'][2].update(key=r['slots'][0]['key']), 'duplicate engine keys'),
                (lambda r: r['slots'][63].update(key='felucca.engine.future'), 'reserved'),
                (lambda r: r['slots'][14].update(key=None,status='reserved'), 'retain every allocated'),
                (lambda r: r['slots'][15].update(key='felucca.engine.future',status='active'), 'retain every allocated')):
            reference=copy.deepcopy(self.reference);mutate(reference)
            with self.subTest(error=error), self.assertRaisesRegex(ValueError,error):
                profile.resolve(self.catalog,self.standard,reference)

    def test_display_and_source_metadata_are_not_engine_identity(self):
        self.catalog['engines'][3].update(name='DISPLAY',symbol='ENG_RELOCATED',source='firmware/engines/src/relocated-lofi.c')
        engines,_=profile.resolve(self.catalog,self.standard,self.reference)
        self.assertEqual(next(e for e in engines if e['id']==3)['key'],'felucca.engine.lofi')

    def test_requested_root_supplies_reference_and_reference_is_a_freshness_input(self):
        original=profile.generated(ROOT,'standard')
        pins=json.loads(original['resolved-profile.json'])['source_pins']
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for rel in json.loads(original['resolved-profile.json'])['input_sha256']:
                dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy(ROOT/rel,dest)
            # Editing both authorities deliberately is permitted, not a signature bypass.
            catalog=profile.read_json(root/'profiles/catalog.json')
            reference=profile.read_json(root/profile.IDENTITY_REFERENCE)
            catalog['engines'][3]['key']='felucca.engine.fixture-lofi'
            reference['slots'][3]['key']='felucca.engine.fixture-lofi'
            (root/'profiles/catalog.json').write_text(json.dumps(catalog))
            path=root/profile.IDENTITY_REFERENCE;path.write_text(json.dumps(reference))
            with patch.object(profile,'source_pins',return_value=pins):
                before=profile.generated(root,'standard')
                info=json.loads(before['resolved-profile.json'])
                self.assertEqual(next(e for e in info['engine_identities'] if e['id']==3)['key'],'felucca.engine.fixture-lofi')
                out=root/'generated';out.mkdir()
                for name,content in before.items(): (out/name).write_text(content)
                path.write_text(path.read_text()+'\n')
                changed=profile.generated(root,'standard')
                self.assertNotEqual(before,changed)
                with self.assertRaisesRegex(ValueError,'stale generated profile'):profile.check_outputs(changed,out)
                path.unlink()
                with self.assertRaises(FileNotFoundError):profile.generated(root,'standard')
    def test_defaults_and_exclusions(self):
        self.standard['engines'].remove(0);self.fails('default')
        self.standard['engines'].append(0);self.standard['exclude']=[3];self.fails('conflict')
    def test_native_owner_dependency_and_missing_provider(self):
        self.standard['engines'].remove(7);self.fails('requires firmware-native')
        self.standard['engines'].append(7);self.catalog['engines'][3]['requires']=['absent'];self.fails('missing dependency')
    def test_cycles_and_explicit_provider_exclusion(self):
        self.catalog['providers'][0]['requires']=['portable-dsp'];self.fails('cycle')
        self.catalog['providers'][0]['requires']=[];self.standard['exclude_providers']=['portable-dsp'];self.fails('conflict')
    def test_metadata_is_required(self):
        for key in ['tag','icon','cc','category','preset_categories','order','union_control']:
            c=copy.deepcopy(self.catalog);del c['engines'][3][key];self.fails('metadata',c=c)

    def test_profiles_reject_retired_and_noninteger_ids(self):
        self.standard['engines'].append(1);self.fails('retired')
        self.standard['engines'].pop()
        for value in (False, 0.0, '0'):
            p=copy.deepcopy(self.standard);p['engines'][0]=value
            self.fails('must be integers',p=p)
            p=copy.deepcopy(self.standard);p['exclude']=[value]
            self.fails('must be integers',p=p)
        c=copy.deepcopy(self.catalog);c['engines'][0]['id']=False
        self.fails('stable range',c=c)

    def test_source_paths_cannot_escape_collection_ownership(self):
        for source in ('', '.', '/firmware/engines/src/eng_analog.c',
                       'firmware/engines/../src/eng_fm6.c', 'firmware/engines/./src/eng_analog.c',
                       'firmware//engines/src/eng_analog.c', 'firmware/engines/src/eng_analog.c/',
                       'firmware\\engines\\src\\eng_analog.c'):
            c=copy.deepcopy(self.catalog);c['engines'][0]['source']=source
            self.fails('invalid source path',c=c)
        for i,source in ((0,'firmware/src/eng_fm6.c'),(2,'firmware/engines/src/eng_analog.c')):
            c=copy.deepcopy(self.catalog);c['engines'][i]['source']=source
            self.fails('source differs',c=c)
        c=copy.deepcopy(self.catalog);c['engines'][0]['owner']='unknown'
        self.fails('unknown collection',c=c)

    def test_collection_boundaries_and_dependencies(self):
        c=copy.deepcopy(self.catalog);c['collections']['other']=copy.deepcopy(c['collections']['portable-mit'])
        self.fails('unsupported collection',c=c)
        c=copy.deepcopy(self.catalog);c['collections']['portable-mit']['path']='firmware/elsewhere'
        self.fails('unsupported collection',c=c)
        c=copy.deepcopy(self.catalog);c['collections']['portable-mit']['requires']=['absent']
        self.fails('unknown dependency',c=c)
        c=copy.deepcopy(self.catalog);c['collections']['firmware']['requires']=['portable-mit']
        c['collections']['portable-mit']['requires']=['firmware']
        self.fails('collection dependency cycle',c=c)

    def test_synthetic_gpl_owner_reuses_mit_and_cannot_enable_checkout(self):
        c=copy.deepcopy(self.catalog);p=copy.deepcopy(self.standard);r=copy.deepcopy(self.reference)
        c['collections']['portable-gpl']=dict(path='firmware/engines-gpl',repository='https://example.invalid/fixture',
            license='GPL-3.0-only',licenses=['firmware/engines-gpl/LICENSE'],requires=['portable-mit'])
        e=copy.deepcopy(c['engines'][-1]);e.update(id=15,key='felucca.engine.gpl-fixture',name='FIXTURE',order=15,
            owner='portable-gpl',source='firmware/engines-gpl/src/fixture.c',requires=['portable-dsp'])
        c['engines'].append(e);p['engines'].append(15);r['slots'][15].update(key=e['key'],status='active')
        engines,providers=profile.resolve(c,p,r)
        self.assertEqual(engines[-1]['owner'],'portable-gpl')
        self.assertIn('portable-dsp',[p['id'] for p in providers])
        with patch.object(profile,'validate_selection',return_value=(c,p,engines,providers)):
            with self.assertRaisesRegex(ValueError,'not integrated.*#360'):profile.generated(ROOT,'standard')
        c['collections']['firmware']['requires']=['portable-gpl']
        with self.assertRaisesRegex(ValueError,'requires another collection'):
            profile.resolve(c,self.standard,r)

    def test_collection_provenance_and_head_independent_selection(self):
        output=profile.generated(ROOT,'standard');resolved=json.loads(output['resolved-profile.json'])
        self.assertEqual(set(resolved['collections']),{'firmware','portable-mit'})
        mit=resolved['collections']['portable-mit'];native=resolved['collections']['firmware']
        self.assertEqual(mit['revision'],resolved['source_pins']['engines_gitlink'])
        self.assertEqual(native['revision'],resolved['source_pins']['firmware_revision'])
        self.assertEqual(mit['api']['required'],mit['api']['actual'])
        self.assertIn('native-core',mit['dependencies'])
        self.assertIn(profile.IDENTITY_REFERENCE,native['input_sha256'])
        self.assertIn('firmware/engines/LICENSE',mit['input_sha256'])
        self.assertIn('firmware/src/core.h',native['input_sha256'])
        inputs=[set(c['input_sha256']) for c in resolved['collections'].values()]
        self.assertFalse(inputs[0]&inputs[1]);self.assertEqual(set.union(*inputs),set(resolved['input_sha256']))
        pins=dict(resolved['source_pins'],firmware_revision='f'*40)
        with patch.object(profile,'source_pins',return_value=pins):changed=profile.generated(ROOT,'standard')
        self.assertEqual(resolved['selection_sha256'],json.loads(changed['resolved-profile.json'])['selection_sha256'])
        for name in profile.OUTPUTS:
            if name!='resolved-profile.json':self.assertEqual(output[name],changed[name])

    def test_api_and_license_inputs_affect_freshness(self):
        outputs=profile.generated(ROOT,'standard');resolved=json.loads(outputs['resolved-profile.json'])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for rel in resolved['input_sha256']:
                dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy(ROOT/rel,dest)
            with patch.object(profile,'source_pins',return_value=resolved['source_pins']):
                for rel in ('LICENSE','firmware/engines/LICENSE','firmware/engines/src/felucca_engine.h','firmware/src/core.h'):
                    original=(root/rel).read_text();(root/rel).write_text(original+'\n')
                    changed=profile.generated(root,'standard')
                    self.assertNotEqual(outputs,changed)
                    (root/rel).write_text(original)
                for rel,old,new in (('firmware/engines/src/felucca_engine.h','FELUCCA_ENGINE_API_VERSION 1u','FELUCCA_ENGINE_API_VERSION 2u'),
                                    ('firmware/src/core.h','FELUCCA_ENGINE_API_REQUIRED 1u','FELUCCA_ENGINE_API_REQUIRED 2u')):
                    original=(root/rel).read_text();self.assertIn(old,original)
                    (root/rel).write_text(original.replace(old,new))
                    with self.assertRaisesRegex(ValueError,'incompatible portable API'):profile.generated(root,'standard')
                    (root/rel).write_text(original)

    def test_legacy_flags_distinguish_recipe_constraints_from_effective_engines(self):
        resolved=json.loads(profile.generated(ROOT,'standard',feature_flags={'FELUCCA_FM4':'1','FELUCCA_SLICE':'0'})['resolved-profile.json'])
        self.assertIn(1,resolved['engine_ids']);self.assertNotIn(1,resolved['profile_engine_ids'])
        self.assertIn(13,resolved['profile_engine_ids']);self.assertNotIn(13,resolved['engine_ids'])
        self.assertEqual({e['id'] for e in resolved['engine_identities']},set(resolved['engine_ids']))
        self.assertIn('firmware/src/eng_digital.c',resolved['input_sha256'])
        self.assertNotIn('firmware/src/eng_slice.c',resolved['input_sha256'])
    def test_target_budget_render_coverage_is_complete(self):
        import ast
        module=ast.parse((ROOT/'tests/target_budget.py').read_text())
        names=next(ast.literal_eval(node.value) for node in module.body
                   if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='FUNCS')
        for engine in self.catalog['engines']:
            self.assertIn(engine['render'],names, f"engine {engine['id']} missing target render budget coverage")
    def test_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'x.json';path.write_text('{"id":3,"id":7}')
            with self.assertRaisesRegex(ValueError,'duplicate JSON key'): profile.read_json(path)
    def test_transitive_generator_mutations_invalidate_selection(self):
        outputs=profile.generated(ROOT,'standard')
        pins=json.loads(outputs['resolved-profile.json'])['source_pins']
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            # Copy the resolver's declared input inventory, never mutate the real source tree.
            for rel in json.loads(outputs['resolved-profile.json'])['input_sha256']:
                dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy(ROOT/rel,dest)
            out=root/'build/gen';out.mkdir(parents=True)
            with patch.object(profile,'source_pins',return_value=pins):
                before=profile.generated(root,'standard')
                for name,content in before.items(): (out/name).write_text(content)
                profile.check_outputs(before,out)
                for helper in ('tools/sampleio.py','tools/gen_waves.py','tools/aa_raster.py'):
                    original=(root/helper).read_text()
                    (root/helper).write_text(original+'\n# mutation fixture\n')
                    changed=profile.generated(root,'standard')
                    with self.assertRaisesRegex(ValueError,'stale generated profile'):
                        profile.check_outputs(changed,out)
                    self.assertNotEqual(json.loads(before['resolved-profile.json'])['selection_sha256'],
                                        json.loads(changed['resolved-profile.json'])['selection_sha256'])
                    self.assertNotEqual(json.loads(before['resolved-profile.json'])['input_sha256'][helper],
                                        json.loads(changed['resolved-profile.json'])['input_sha256'][helper])
                    for name,content in changed.items(): (out/name).write_text(content)
                    profile.check_outputs(changed,out)
                    (root/helper).write_text(original)
                    for name,content in before.items(): (out/name).write_text(content)

    def test_profile_compiler_keeps_wrappers_but_drops_default_selection_include(self):
        spec=importlib.util.spec_from_file_location('profile_integration',ROOT/'tests/profile_integration_test.py')
        integration=importlib.util.module_from_spec(spec);spec.loader.exec_module(integration)
        for include in ('-Ibuild/gen','-I build/gen',f'-I{ROOT}/build/gen',f'-I {ROOT}/build/gen'):
            self.assertEqual(integration.compiler_command('ccache clang -O1 '+include+' -Wall -Iother'),
                             ['ccache','clang','-O1','-Wall','-Iother'])
    def test_check_uses_recorded_font_without_hiding_explicit_override(self):
        env=dict(os.environ,FELUCCA_FONT='m8stealth',FELUCCA_FM4='0',FELUCCA_SLICE='1')
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable, str(ROOT/'tools/gen_bitmap_font.py'), str(Path(td)/'ui_fonts.h')],
                           check=True, env=env, capture_output=True)
            cmd=[sys.executable,str(ROOT/'tools/profile.py'),'--out',td,'--profile','standard']
            subprocess.run(cmd,env=env,check=True,capture_output=True)
            default_env=env.copy();default_env.pop('FELUCCA_FONT')
            self.assertEqual(subprocess.run(cmd+['--check'],env=default_env,capture_output=True).returncode,0)
            for retired in ('tamzen', 'inter-tight'):
                rejected=subprocess.run(cmd+['--check'],env=dict(env,FELUCCA_FONT=retired),capture_output=True)
                self.assertNotEqual(rejected.returncode,0)
                self.assertIn(b'm8stealth only',rejected.stderr)
            self.assertEqual(subprocess.run(cmd+['--check'],env=env,capture_output=True).returncode,0)
            manifest = Path(td)/'ui-font-manifest.json'
            original = manifest.read_bytes()
            manifest.write_text('{}')
            rejected = subprocess.run(cmd+['--check'], env=env, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b'stale native font manifest', rejected.stderr)
            manifest.write_bytes(original)

    def test_determinism_and_stale_generated_selection(self):
        env=dict(os.environ,FELUCCA_FM4='0',FELUCCA_SLICE='1')
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable, str(ROOT/'tools/gen_bitmap_font.py'), str(Path(td)/'ui_fonts.h')],
                           check=True, env=env, capture_output=True)
            cmd=[sys.executable,str(ROOT/'tools/profile.py'),'--out',td,'--profile','standard']
            subprocess.run(cmd,check=True,env=env,capture_output=True)
            stamp=(Path(td)/'resolved-profile.json').read_bytes()
            subprocess.run(cmd,check=True,env=env,capture_output=True)
            self.assertEqual(stamp,(Path(td)/'resolved-profile.json').read_bytes())
            self.assertEqual(subprocess.run(cmd+['--check'],env=env,capture_output=True).returncode,0)
            (Path(td)/'engine_registry.inc').write_text('stale')
            self.assertNotEqual(subprocess.run(cmd+['--check'],env=env,capture_output=True).returncode,0)
            subprocess.run(cmd,check=True,env=env,capture_output=True)
            self.assertNotEqual(subprocess.run(cmd[:-1]+['reduced-lofi','--check'],env=env,capture_output=True).returncode,0)
            self.assertNotEqual(subprocess.run(cmd+['--check'],env=dict(env,FELUCCA_SLICE='0'),capture_output=True).returncode,0)
            info=json.loads(stamp)
            self.assertIn('assets/fonts/m8stealth/resource-policy.json', info['input_sha256'])
            self.assertEqual(len(info['source_pins']['engines_gitlink']),40)
            self.assertIn('firmware/engines/src/eng_lofi.c',info['input_sha256'])

if __name__=='__main__':unittest.main()
