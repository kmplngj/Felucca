#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Resolve the firmware-owned engine registry once for target, host and emulator."""
# Verified archives must not execute cached helpers before checking their source tree.
# os/sys are loaded by Python startup; defer all repository and other stdlib imports.
import os as _source_os
import sys as _source_sys

_source_root = _source_os.path.dirname(_source_os.path.dirname(_source_os.path.realpath(__file__)))
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
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENGINE_ID_LIMIT = 64
IDENTITY_REFERENCE = 'profiles/engine-identities.json'

SUPPORTED_PROFILES = ('standard', 'reduced-lofi', 'macro')

OUTPUTS = ('felucca_profile.h', 'engine_includes.inc', 'engine_registry.inc',
           'engine_metadata.inc', 'engine_cc.inc', 'engine_categories.inc', 'engine_names.inc', 'engine_order.inc', 'resolved-profile.json')


def read_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f'duplicate JSON key: {key}')
            out[key] = value
        return out
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f'duplicate {label}')
    return set(values)


def validate_identities(catalog, reference):
    """Compare the catalog with the reviewed allocation authority supplied by its root.

    This catches accidental catalog drift, not deliberate edits to both inputs.
    Reserved slots have no key; allocated keys survive retirement and source moves.
    """
    if not isinstance(reference, dict) or type(reference.get('schema_version')) is not int or reference['schema_version'] != 1:
        raise ValueError('unsupported engine identity reference schema')
    slots = reference.get('slots')
    if not isinstance(slots, list) or any(not isinstance(s, dict) or type(s.get('id')) is not int or 'key' not in s for s in slots):
        raise ValueError('invalid engine identity reference slots')
    ids = unique([s['id'] for s in slots], 'engine IDs in identity reference')
    if ids != set(range(ENGINE_ID_LIMIT)):
        raise ValueError('identity reference must list all 64 stable slots')
    allocated = {}
    for slot in slots:
        status, key = slot.get('status'), slot.get('key')
        if status not in ('active', 'retired', 'reserved'):
            raise ValueError('invalid engine identity status')
        if status == 'reserved':
            if key is not None:
                raise ValueError('reserved engine identity slot must have no key')
        else:
            if not isinstance(key, str) or not re.fullmatch(r'felucca\.engine\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*', key):
                raise ValueError('invalid namespaced engine key in identity reference')
            allocated[slot['id']] = key
    unique(list(allocated.values()), 'engine keys in identity reference')
    keys = [e.get('key') for e in catalog['engines']]
    for key in keys:
        if not isinstance(key, str) or not re.fullmatch(r'felucca\.engine\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*', key):
            raise ValueError('missing or invalid namespaced engine key in catalog')
    unique(keys, 'engine keys in catalog')
    if {e['id'] for e in catalog['engines']} != allocated.keys():
        raise ValueError('catalog must retain every allocated engine identity, including retired slots')
    for e in catalog['engines']:
        if e['key'] != allocated[e['id']]:
            raise ValueError(f"engine identity mapping changed at ID {e['id']}")


def resolve(catalog, profile, reference):
    if catalog['schema_version'] != 1 or profile['schema_version'] != 1:
        raise ValueError('unsupported profile schema')
    raw_ids = [e['id'] for e in catalog['engines']]
    if any(type(i) is not int or not 0 <= i < ENGINE_ID_LIMIT for i in raw_ids):
        raise ValueError('engine IDs must be in stable range 0..63')
    ids = unique(raw_ids, 'engine IDs in registry')
    if not ids:
        raise ValueError('empty engine registry')
    if ids != set(range(max(ids) + 1)):
        raise ValueError('missing reserved stable slot in registry')
    validate_identities(catalog, reference)
    collections = catalog['collections']
    # source_pins/source_archive currently integrate only firmware and MIT. The
    # GPL owner is understood for metadata fixtures, never enabled by metadata.
    supported = {'firmware': '.', 'portable-mit': 'firmware/engines', 'portable-gpl': 'firmware/engines-gpl'}
    for owner, collection in collections.items():
        for facet in ('path', 'repository', 'license', 'licenses', 'requires'):
            if facet not in collection:
                raise ValueError(f'collection {owner} missing metadata: {facet}')
        if owner not in supported or collection['path'] != supported[owner]:
            raise ValueError(f'unsupported collection owner/path: {owner}')
        if any(dep not in collections for dep in collection['requires']):
            raise ValueError(f'collection {owner} unknown dependency')
    visiting_collections, checked_collections = set(), set()
    def check_collection(owner):
        if owner in visiting_collections:
            raise ValueError(f'collection dependency cycle at {owner}')
        if owner not in checked_collections:
            visiting_collections.add(owner)
            for dep in collections[owner]['requires']:
                check_collection(dep)
            visiting_collections.remove(owner)
            checked_collections.add(owner)
    for owner in collections:
        check_collection(owner)
    unique([e['name'] for e in catalog['engines']], 'engine names')
    for e in catalog['engines']:
        for facet in ('tag', 'icon', 'category', 'preset_categories', 'cc', 'order', 'union_control', 'source', 'symbol', 'render', 'budget_functions', 'tests', 'assets', 'requires'):
            if facet not in e or e[facet] is None:
                raise ValueError(f"engine {e['id']} missing metadata: {facet}")
        if e.get('owner') not in collections:
            raise ValueError(f"engine {e['id']} unknown collection owner")
        source = e['source']
        if not isinstance(source, str):
            raise ValueError(f"engine {e['id']} invalid source path")
        path = PurePosixPath(source)
        if (not path.parts or path.is_absolute() or path.as_posix() != source
                or '..' in path.parts or '\\' in source or any(ord(c) < 32 for c in source)):
            raise ValueError(f"engine {e['id']} invalid source path")
        if (e['owner'] != 'firmware' and not source.startswith(collections[e['owner']]['path'] + '/')
                or e['owner'] == 'firmware' and any(source.startswith(prefix + '/')
                    for owner, prefix in supported.items() if owner != 'firmware')):
            raise ValueError(f"engine {e['id']} source differs from collection owner")
        if not e['tag'] or len(e['tag']) > 4 or not 0 <= e['category'] < 9 or not 0 <= e['cc'] <= 255:
            raise ValueError(f"engine {e['id']} invalid identity metadata")
        if type(e['union_control']) is not bool:
            raise ValueError(f"engine {e['id']} union_control must be a boolean")
        if any(letter not in 'BLPUKDFO' for letter in e['preset_categories']):
            raise ValueError(f"engine {e['id']} invalid category letters")
    unique([e['order'] for e in catalog['engines']], 'display orders')
    raw_selected, raw_excluded = profile['engines'], profile.get('exclude', [])
    if any(type(i) is not int for i in raw_selected + raw_excluded):
        raise ValueError('selected and excluded engine IDs must be integers')
    selected = unique(raw_selected, 'selected engine IDs')
    excluded = unique(raw_excluded, 'excluded engine IDs')
    if (selected | excluded) - ids:
        raise ValueError(f'unknown engine IDs: {sorted((selected | excluded) - ids)}')
    if selected & excluded:
        raise ValueError('dependency conflict: selected engine explicitly excluded')
    statuses = {slot['id']: slot['status'] for slot in reference['slots']}
    if any(statuses[i] != 'active' for i in selected):
        raise ValueError('profile cannot select retired engine identity; use the existing FELUCCA_FM4 developer flag')
    if not set(catalog['defaults']) <= selected:
        raise ValueError('missing boot default engine')
    providers = {p['id']: p for p in catalog['providers']}
    if len(providers) != len(catalog['providers']):
        raise ValueError('duplicate provider IDs')
    roots = unique(profile['providers'], 'provider IDs')
    blocked = unique(profile.get('exclude_providers', []), 'excluded provider IDs')
    if (roots | blocked) - providers.keys():
        raise ValueError('unknown provider ID')
    visiting, done = set(), set()
    def visit(name):
        if name in blocked:
            raise ValueError(f'dependency conflict: excluded provider {name}')
        if name not in providers:
            raise ValueError(f'missing dependency provider {name}')
        if name in visiting:
            raise ValueError(f'dependency cycle at {name}')
        if name in done:
            return
        visiting.add(name)
        for dep in providers[name]['requires']:
            visit(dep)
        visiting.remove(name)
        done.add(name)
    engines = [e for e in catalog['engines'] if e['id'] in selected]
    owners = {e['owner'] for e in engines}
    for owner in owners:
        if not set(collections[owner]['requires']) <= owners:
            raise ValueError(f'dependency conflict: collection {owner} requires another collection')
    for root in sorted(roots):
        visit(root)
    for e in engines:
        for dep in e['requires']:
            visit(dep)
    for p in done:
        if not set(providers[p].get('requires_engines', [])) <= selected:
            raise ValueError(f'dependency conflict: provider {p} requires firmware-native engine/UI owner')
    return engines, [providers[p] for p in sorted(done)]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()


def source_pins(root):
    # Complete release archives carry verified provenance and need no .git directory.
    archive = root / 'SOURCE-PINS.json'
    if archive.exists():
        if _source_verifier is not None:
            pins = _source_verifier['verify_tree'](root)
        else:
            # Called from a normal Git checkout with an explicit archive root: load the
            # trusted checkout's verifier source, never the archive's import caches.
            verifier_path = ROOT / 'tools/source_archive.py'
            verifier = {'__name__':'felucca_source_verifier', '__file__':str(verifier_path)}
            exec(compile(verifier_path.read_bytes(), str(verifier_path), 'exec'), verifier)
            pins = verifier['verify_tree'](root)
        return {'firmware_revision': pins['firmware_revision'],
                'engines_gitlink': pins['engines']['revision']}
    pin = git(root, 'ls-files', '--stage', 'firmware/engines').split()[1]
    if git(root/'firmware/engines', 'rev-parse', 'HEAD') != pin:
        raise ValueError('checked-out Engines revision does not match the pinned gitlink')
    return {'firmware_revision': git(root, 'rev-parse', 'HEAD'), 'engines_gitlink': pin}


def condition(e, *, honor_omit=True):
    extra = ' && FELUCCA_FM4' if e['id'] == 1 else ' && FELUCCA_SLICE' if e['id'] == 13 else ''
    omit = f" && FELUCCA_ENG_OMIT != {e['id']}" if honor_omit else ""
    return f"FELUCCA_PROFILE_ENGINE_{e['id']}{extra}{omit}"


def portable_api(root):
    """Read the existing C contract, without maintaining another API version."""
    header, host_header = 'firmware/engines/src/felucca_engine.h', 'firmware/src/core.h'
    def revision(path, macro):
        match = re.search(r'^#define\s+' + re.escape(macro) + r'\s+(\d+)[uU]?\s*$',
                          (root / path).read_text(), re.MULTILINE)
        return int(match[1]) if match else None
    required = revision(host_header, 'FELUCCA_ENGINE_API_REQUIRED')
    actual = revision(header, 'FELUCCA_ENGINE_API_VERSION')
    if required is None or actual != required:
        raise ValueError(f'incompatible portable API revision: firmware requires {required}, collection provides {actual}')
    return dict(required=required, actual=actual, header=header, host_header=host_header)


def collection_provenance(catalog, engines, providers, pins, hashes, api, licenses):
    """Describe consumed collections using the existing source pin authority."""
    records = {}
    for owner in sorted({e['owner'] for e in engines}):
        collection = catalog['collections'][owner]
        dependencies = set()
        by_provider = {p['id']: p for p in providers}
        def visit(name):
            if name not in dependencies:
                dependencies.add(name)
                for dep in by_provider[name]['requires']:
                    visit(dep)
        owned = [e for e in engines if e['owner'] == owner]
        for engine in owned:
            for name in engine['requires']:
                visit(name)
        def owns(path):
            portable = path.startswith('firmware/engines/')
            return portable if owner == 'portable-mit' else not portable
        records[owner] = dict(path=collection['path'], repository=collection['repository'],
                             revision=pins['firmware_revision'] if owner == 'firmware' else pins['engines_gitlink'],
                             api=api if owner == 'portable-mit' else None,
                             license=collection['license'], licenses=[p for p in licenses if owns(p)],
                             requires=collection['requires'], engine_keys=[e['key'] for e in owned],
                             dependencies=sorted(dependencies),
                             input_sha256={p: digest for p, digest in hashes.items() if owns(p)})
    return records


def validate_selection(root, name):
    if not name or len(name) > 64 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in name):
        raise ValueError('invalid profile name')
    catalog_path, profile_path = root / 'profiles/catalog.json', root / f'profiles/{name}.json'
    catalog, profile = read_json(catalog_path), read_json(profile_path)
    if profile['name'] != name:
        raise ValueError('profile filename/name mismatch')
    engines, providers = resolve(catalog, profile, read_json(root / IDENTITY_REFERENCE))
    return catalog, profile, engines, providers


def generated(root, name, font_variant=None, *, feature_flags=None):
    catalog, profile, engines, providers = validate_selection(root, name)
    selected = {e['id'] for e in engines}
    # Existing developer options remain independent; DIGITAL's retired implementation can be requested.
    flags = (dict(feature_flags) if feature_flags is not None else
             {f: os.environ.get(f, d) for f, d in [('FELUCCA_FM4','0'), ('FELUCCA_SLICE','1')]})
    if any(v not in ('0','1') for v in flags.values()):
        raise ValueError('FELUCCA_FM4 and FELUCCA_SLICE must be 0 or 1')
    if flags['FELUCCA_FM4'] == '1':
        selected.add(1)
    if flags['FELUCCA_SLICE'] == '0':
        selected.discard(13)
    all_engines = sorted(catalog['engines'], key=lambda e: e['id'])
    engines = [e for e in all_engines if e['id'] in selected]
    if any(e['owner'] == 'portable-gpl' for e in engines):
        raise ValueError('portable-gpl collection is not integrated; checkout/build support belongs to issue #360')
    icons = read_json(root / 'assets/icons.json')['names']
    licenses = sorted(set([l for p in providers for l in p['licenses']] +
                          [l for owner in {e['owner'] for e in engines} for l in catalog['collections'][owner]['licenses']] +
                          ['LICENSING.md', 'assets/samples-cc0/ATTRIBUTION.txt'] +
                          [str(p.relative_to(root)) for p in (root/'LICENSES').glob('*.txt')]))
    api = portable_api(root)
    inputs = ['profiles/catalog.json', IDENTITY_REFERENCE, f'profiles/{name}.json', 'assets/icons.json', 'tools/profile.py',
              api['header'], api['host_header']] + licenses
    inputs += [e['source'] for e in engines]
    inputs += [i for p in providers for i in p['generator_inputs']]
    for asset in catalog['shared_assets']:
        path = root / asset
        if not path.exists():
            raise ValueError(f'missing generator asset: {asset}')
        inputs += [str(p.relative_to(root)) for p in sorted(path.rglob('*')) if p.is_file()] if path.is_dir() else [asset]
    hashes = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in sorted(set(inputs))}
    pins = source_pins(root)
    pins['engines_upstream_revision'] = catalog['engines_upstream_revision']
    collections = collection_provenance(catalog, engines, providers, pins, hashes, api, licenses)
    font_variant = font_variant if font_variant is not None else os.environ.get('FELUCCA_FONT', 'm8stealth')
    if font_variant != 'm8stealth':
        raise ValueError('FELUCCA_FONT supports m8stealth only; Tamzen and Inter Tight firmware fonts are retired')
    resolved = dict(schema_version=1, profile=name, asset_variant=font_variant, standard_base=catalog['standard_base'],
                    source_pins=pins, engine_ids=sorted(selected), portable_engine_ids=[e['id'] for e in engines if e['owner']=='portable-mit'],
                    profile_engine_ids=sorted(profile['engines']), collections=collections, provider_dependencies=providers,
                    firmware_native_engine_ids=[e['id'] for e in engines if e['owner']=='firmware'],
                    includes=[e['source'] for e in engines], providers=[p['id'] for p in providers],
                    defaults=catalog['defaults'], engine_budget_functions=sorted(set(f for e in engines for f in e['budget_functions'])),
                    excluded_engine_budget_functions=sorted(set(f for e in all_engines if e['id'] not in selected and e['id'] != 1 for f in e['budget_functions'])), build_flags=flags, fixed_owners=catalog['fixed_owners'],
                    assets=sorted(set(catalog['shared_assets'] + [a for e in engines for a in e['assets']])),
                    generator_inputs=sorted(set(i for p in providers for i in p['generator_inputs'])),
                    tests=sorted(set(catalog['shared_tests'] + [t for e in engines for t in e['tests']] + [t for p in providers for t in p.get('tests',[])])),
                    licenses=licenses, input_sha256=hashes)
    slots = {s['id']: s for s in read_json(root / IDENTITY_REFERENCE)['slots']}
    resolved['engine_identity_reference'] = {'path': IDENTITY_REFERENCE, 'sha256': hashes[IDENTITY_REFERENCE]}
    resolved['engine_identities'] = [dict(id=e['id'], key=e['key'], status=slots[e['id']]['status'],
                                          owner=e['owner'], source=e['source']) for e in engines]
    # Firmware HEAD is provenance, not a C selection input; commits do not force identical code to rebuild.
    stamp_inputs = dict(resolved)
    stamp_inputs['source_pins'] = {k:v for k,v in pins.items() if k!='firmware_revision'}
    stamp_inputs['collections'] = {owner: {k: v for k, v in record.items() if not (owner == 'firmware' and k == 'revision')}
                                   for owner, record in collections.items()}
    stamp = hashlib.sha256(json.dumps(stamp_inputs,sort_keys=True).encode()).hexdigest()
    resolved['selection_sha256'] = stamp
    banner = '/* generated by tools/profile.py; GPL-3.0-only; do not edit */\n'
    header = banner + '#pragma once\n' + f'#define FELUCCA_PROFILE_NAME "{name}"\n#define FELUCCA_PROFILE_SHA256 "{stamp}"\n'
    header += f'#define FELUCCA_PROFILE_NSLOTS {len(all_engines)}\n'
    for flag, value in flags.items():
        header += f'#ifndef {flag}\n#define {flag} {value}\n#endif\n'
    for e in all_engines:
        # Legacy compiler -DFELUCCA_FM4=1 enables the retired engine in host conversion fixtures.
        value = 'FELUCCA_FM4' if e['id'] == 1 else 'FELUCCA_SLICE' if e['id'] == 13 else str(int(e['id'] in selected))
        header += f"#ifdef FELUCCA_PROFILE_ENGINE_{e['id']}\n#error \"engine selection is generated; use FELUCCA_PROFILE\"\n#endif\n#define FELUCCA_PROFILE_ENGINE_{e['id']} {value}\n"
    # Test-only: engines whose state lives outside the arena; tests/union_test.c adds them to its workload.
    header += '#define FELUCCA_UNION_CONTROL_MASK 0x%xull\n' % sum(1 << e['id'] for e in all_engines if e['union_control'])
    header += '#define FELUCCA_PROFILE_NSHOWN (' + ' + '.join(f"({condition(e)})" for e in all_engines) + ' + (FELUCCA_ENG_TEST14 && FELUCCA_ENG_OMIT != FELUCCA_PROFILE_NSLOTS))\n'
    out = {'felucca_profile.h':header}
    for filename in ('engine_includes.inc','engine_registry.inc','engine_names.inc','engine_order.inc','engine_metadata.inc','engine_cc.inc','engine_categories.inc'):
        out[filename] = banner
    for e in all_engines:
        c, i = condition(e), e['id']
        # SILENT slots persist even when source is removed; order/names use the same selection.
        if i != 1:  # DIGITAL includes the retired-sound adapter first (engines.c).
            # Host catalog-omit fixtures retain native migration/UI dependencies,
            # while the registry below still marks that engine unavailable.
            source_condition = condition(e, honor_omit=e['owner'] != 'firmware')
            out['engine_includes.inc'] += f'#if {source_condition}\n#include "../../{e["source"]}"\n#endif\n'
        fallback = '&ENG_FM4_GONE' if i==1 else '&ENG_NONE'
        out['engine_registry.inc'] += f'#if {c}\n&{e["symbol"]},\n#else\n{fallback},\n#endif\n'
        out['engine_names.inc'] += f'#if {c}\n"{e["name"]}",\n#else\n"-",\n#endif\n'
        icon = icons.index(e['icon'])
        out['engine_cc.inc'] += f'#if {c}\n[{i}] = {e["cc"]},\n#endif\n'
        out['engine_categories.inc'] += f'[{i}] = "{e["preset_categories"]}",\n'
        out['engine_metadata.inc'] += f'[{i}] = {{"{e["tag"]}", "{e["preset_categories"]}", {icon}, {e["category"]}, {e["cc"]}, {e["order"]} }},\n'
    for e in sorted(all_engines,key=lambda e:e['order']):
        if e['id']==10:
            out['engine_order.inc'] += '#if FELUCCA_ENG_TEST14 && FELUCCA_ENG_OMIT != FELUCCA_PROFILE_NSLOTS\nFELUCCA_PROFILE_NSLOTS,\n#endif\n'
        out['engine_order.inc'] += f'#if {condition(e)}\n{e["id"]},\n#endif\n'
    for filename, value in [('engine_registry.inc','ENG_AT(FELUCCA_PROFILE_NSLOTS, &ENG_TEST14),'),('engine_names.inc','"TEST14",')]:
        out[filename] += f'#if FELUCCA_ENG_TEST14\n{value}\n#endif\n'
    out['resolved-profile.json'] = json.dumps(resolved,indent=2,sort_keys=True)+'\n'
    return out


def contract(root):
    """Export only the current supported recipes, using the production resolver.

    Developer feature overrides never change canonical recipes. This is a registry
    contract, not a promise that arbitrary selections or future collections build.
    """
    recipes = {}
    catalog = read_json(root / 'profiles/catalog.json')
    for name in SUPPORTED_PROFILES:
        _, recipe, engines, providers = validate_selection(root, name)
        resolved = json.loads(generated(root, name, 'm8stealth', feature_flags={
            'FELUCCA_FM4': '0', 'FELUCCA_SLICE': '1'})['resolved-profile.json'])
        reasons = {p['id']: [] for p in providers}
        for provider in recipe['providers']:
            reasons[provider].append({'kind': 'profile', 'id': name})
        for engine in engines:
            for provider in engine['requires']:
                reasons[provider].append({'kind': 'engine', 'id': engine['id']})
        for provider in providers:
            for dependency in provider['requires']:
                reasons[dependency].append({'kind': 'provider', 'id': provider['id']})
        recipes[name] = {'recipe': recipe, 'resolved': resolved,
                         'provider_reasons': reasons}
    license_paths = sorted({path for recipe in recipes.values()
                            for path in recipe['resolved']['licenses']})
    return {'schema_version': 1, 'kind': 'felucca-supported-profile-contract',
            'source_pins': source_pins(root), 'registry': catalog,
            'engine_identity_reference': read_json(root / IDENTITY_REFERENCE),
            'validation': {
                'authority': 'tools/profile.py resolve, validate_selection, generated and source_pins',
                'engine_id_min': 0, 'engine_id_max': ENGINE_ID_LIMIT - 1,
                'stable_slots_must_be_contiguous': True,
                'retired_engine_ids': [s['id'] for s in read_json(root / IDENTITY_REFERENCE)['slots'] if s['status'] == 'retired'],
                'profiles_may_select_retired_engines': False,
                'engine_keys_must_match_reviewed_reference': IDENTITY_REFERENCE,
                'boot_default_engine_ids_required': catalog['defaults'],
                'provider_dependency_cycles_allowed': False,
                'explicit_exclusions_must_not_conflict_with_selection_or_dependencies': True,
                'provider_required_engines_must_be_selected': True,
                'engine_checkout_must_match_exact_gitlink': True,
                'source_paths_must_match_collection_owner': True,
                'portable_api_must_match_firmware_requirement': True,
                'developer_boolean_flags': {'FELUCCA_FM4': ['0', '1'], 'FELUCCA_SLICE': ['0', '1']},
                'font_variants': ['m8stealth']},
            'supported_profiles': recipes,
            'canonical_features': {'FELUCCA_FM4': '0', 'FELUCCA_SLICE': '1',
                                   'FELUCCA_FONT': 'm8stealth'},
            'license_sha256': {path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                               for path in license_paths},
            'scope': 'Current supported profiles only; no cost prediction or arbitrary selection support'}


def contract_json(root):
    return json.dumps(contract(root), indent=2, sort_keys=True) + '\n'


def check_outputs(outputs, directory):
    for name, content in outputs.items():
        path = directory / name
        if not path.exists() or path.read_text() != content:
            raise ValueError(f'stale generated profile: {path}; rebuild the selected FELUCCA_PROFILE')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile',default=os.environ.get('FELUCCA_PROFILE','standard'))
    ap.add_argument('--out',type=Path,default=ROOT/'build/gen')
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--export-contract', type=Path, metavar='PATH',
                    help='export the versioned canonical supported-profile contract; --check verifies it')
    args=ap.parse_args()
    try:
        if args.export_contract is not None:
            content = contract_json(ROOT)
            if args.check:
                if args.export_contract.read_text() != content:
                    raise ValueError('stale supported-profile contract')
            else:
                args.export_contract.parent.mkdir(parents=True, exist_ok=True)
                args.export_contract.write_text(content)
            return
        font_variant = None
        if args.check and 'FELUCCA_FONT' not in os.environ:
            # Host/emulator builds have always consumed the generated font. Keep that
            # choice when no override is supplied; explicit overrides must still match.
            recorded = args.out / 'resolved-profile.json'
            if recorded.exists():
                font_variant = read_json(recorded)['asset_variant']
        outputs=generated(ROOT,args.profile,font_variant)
        if args.check:
            check_outputs(outputs, args.out)
            from font_resources import check_generated
            check_generated(ROOT, args.out)
            from build_identity import check as check_identity
            check_identity(ROOT, args.out)
        else:
            from build_identity import write as write_identity
            write_identity(ROOT, args.out)
            args.out.mkdir(parents=True,exist_ok=True)
            for name, content in outputs.items():
                (args.out/name).write_text(content)
        print(f'profile: {args.profile} ({json.loads(outputs["resolved-profile.json"])["selection_sha256"][:12]})')
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        ap.error(str(error))

if __name__=='__main__':
    main()
