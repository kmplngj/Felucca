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
    def fails(self, text, c=None, p=None):
        with self.assertRaisesRegex(ValueError,text):
            profile.resolve(c or self.catalog,p or self.standard)
    def test_standard_and_reduced_stable_ids(self):
        a,_=profile.resolve(self.catalog,self.standard)
        b,_=profile.resolve(self.catalog,profile.read_json(ROOT/'profiles/reduced-lofi.json'))
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
            cmd=[sys.executable,str(ROOT/'tools/profile.py'),'--out',td,'--profile','standard']
            subprocess.run(cmd,env=env,check=True,capture_output=True)
            default_env=env.copy();default_env.pop('FELUCCA_FONT')
            self.assertEqual(subprocess.run(cmd+['--check'],env=default_env,capture_output=True).returncode,0)
            for retired in ('tamzen', 'inter-tight'):
                rejected=subprocess.run(cmd+['--check'],env=dict(env,FELUCCA_FONT=retired),capture_output=True)
                self.assertNotEqual(rejected.returncode,0)
                self.assertIn(b'm8stealth only',rejected.stderr)
            self.assertEqual(subprocess.run(cmd+['--check'],env=env,capture_output=True).returncode,0)

    def test_determinism_and_stale_generated_selection(self):
        env=dict(os.environ,FELUCCA_FM4='0',FELUCCA_SLICE='1')
        with tempfile.TemporaryDirectory() as td:
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
            self.assertEqual(len(info['source_pins']['engines_gitlink']),40)
            self.assertIn('firmware/engines/src/eng_lofi.c',info['input_sha256'])

if __name__=='__main__':unittest.main()
