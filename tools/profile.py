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
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
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


def resolve(catalog, profile):
    if catalog['schema_version'] != 1 or profile['schema_version'] != 1:
        raise ValueError('unsupported profile schema')
    ids = unique([e['id'] for e in catalog['engines']], 'engine IDs in registry')
    if any(type(i) is not int or not 0 <= i < 64 for i in ids):
        raise ValueError('engine IDs must be in stable range 0..63')
    if ids != set(range(max(ids) + 1)):
        raise ValueError('missing reserved stable slot in registry')
    unique([e['name'] for e in catalog['engines']], 'engine names')
    for e in catalog['engines']:
        for facet in ('tag', 'icon', 'category', 'preset_categories', 'cc', 'order', 'kit', 'source', 'symbol', 'render', 'budget_functions', 'tests', 'assets', 'requires'):
            if facet not in e or e[facet] is None:
                raise ValueError(f"engine {e['id']} missing metadata: {facet}")
        if not e['tag'] or len(e['tag']) > 4 or not 0 <= e['category'] < 9 or not 0 <= e['cc'] <= 255:
            raise ValueError(f"engine {e['id']} invalid identity metadata")
        if any(letter not in 'BLPUKDFO' for letter in e['preset_categories']):
            raise ValueError(f"engine {e['id']} invalid category letters")
    unique([e['order'] for e in catalog['engines']], 'display orders')
    selected = unique(profile['engines'], 'selected engine IDs')
    excluded = unique(profile.get('exclude', []), 'excluded engine IDs')
    if (selected | excluded) - ids:
        raise ValueError(f'unknown engine IDs: {sorted((selected | excluded) - ids)}')
    if selected & excluded:
        raise ValueError('dependency conflict: selected engine explicitly excluded')
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


def validate_selection(root, name):
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in name):
        raise ValueError('invalid profile name')
    catalog_path, profile_path = root / 'profiles/catalog.json', root / f'profiles/{name}.json'
    catalog, profile = read_json(catalog_path), read_json(profile_path)
    if profile['name'] != name:
        raise ValueError('profile filename/name mismatch')
    engines, providers = resolve(catalog, profile)
    return catalog, profile, engines, providers


def generated(root, name, font_variant=None):
    catalog, profile, engines, providers = validate_selection(root, name)
    selected = {e['id'] for e in engines}
    # Existing developer options remain independent; DIGITAL's retired implementation can be requested.
    flags = {f: os.environ.get(f, d) for f, d in [('FELUCCA_FM4','0'), ('FELUCCA_SLICE','1')]}
    if any(v not in ('0','1') for v in flags.values()):
        raise ValueError('FELUCCA_FM4 and FELUCCA_SLICE must be 0 or 1')
    if flags['FELUCCA_FM4'] == '1':
        selected.add(1)
    if flags['FELUCCA_SLICE'] == '0':
        selected.discard(13)
    all_engines = sorted(catalog['engines'], key=lambda e: e['id'])
    engines = [e for e in all_engines if e['id'] in selected]
    icons = read_json(root / 'assets/icons.json')['names']
    inputs = ['profiles/catalog.json', f'profiles/{name}.json', 'assets/icons.json', 'tools/profile.py']
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
    font_variant = font_variant if font_variant is not None else os.environ.get('FELUCCA_FONT', 'm8stealth')
    if font_variant not in {'m8stealth', 'tamzen', 'inter-tight'}:
        raise ValueError('FELUCCA_FONT must be inter-tight, tamzen or m8stealth')
    resolved = dict(schema_version=1, profile=name, asset_variant=font_variant, standard_base=catalog['standard_base'],
                    source_pins=pins, engine_ids=sorted(selected), portable_engine_ids=[e['id'] for e in engines if e['owner']=='portable-mit'],
                    firmware_native_engine_ids=[e['id'] for e in engines if e['owner']=='firmware'],
                    includes=[e['source'] for e in engines], providers=[p['id'] for p in providers],
                    defaults=catalog['defaults'], engine_budget_functions=sorted(set(f for e in engines for f in e['budget_functions'])),
                    excluded_engine_budget_functions=sorted(set(f for e in all_engines if e['id'] not in selected and e['id'] != 1 for f in e['budget_functions'])), build_flags=flags, fixed_owners=catalog['fixed_owners'],
                    assets=sorted(set(catalog['shared_assets'] + [a for e in engines for a in e['assets']])),
                    generator_inputs=sorted(set(i for p in providers for i in p['generator_inputs'])),
                    tests=sorted(set(catalog['shared_tests'] + [t for e in engines for t in e['tests']] + [t for p in providers for t in p.get('tests',[])])),
                    licenses=sorted(set([l for p in providers for l in p['licenses']] + ['LICENSING.md', 'assets/samples-cc0/ATTRIBUTION.txt'] + [str(p.relative_to(root)) for p in (root/'LICENSES').glob('*.txt')])), input_sha256=hashes)
    # Firmware HEAD is provenance, not a C selection input; commits do not force identical code to rebuild.
    stamp_inputs = dict(resolved)
    stamp_inputs['source_pins'] = {k:v for k,v in pins.items() if k!='firmware_revision'}
    stamp = hashlib.sha256(json.dumps(stamp_inputs,sort_keys=True).encode()).hexdigest()
    resolved['selection_sha256'] = stamp
    banner = '/* generated by tools/profile.py; GPL-3.0-only; do not edit */\n'
    header = banner + '#pragma once\n' + f'#define FELUCCA_PROFILE_NAME "{name}"\n#define FELUCCA_PROFILE_SHA256 "{stamp}"\n'
    header += f'#define FELUCCA_PROFILE_NSLOTS {len(all_engines)}\n'
    header += '#if FELUCCA_ENG_TEST14 && FELUCCA_PROFILE_NSLOTS != 14\n#error \"test14 fixture requires the original 14-slot registry\"\n#endif\n'
    for flag, value in flags.items():
        header += f'#ifndef {flag}\n#define {flag} {value}\n#endif\n'
    for e in all_engines:
        # Legacy compiler -DFELUCCA_FM4=1 enables the retired engine in host conversion fixtures.
        value = 'FELUCCA_FM4' if e['id'] == 1 else 'FELUCCA_SLICE' if e['id'] == 13 else str(int(e['id'] in selected))
        header += f"#ifdef FELUCCA_PROFILE_ENGINE_{e['id']}\n#error \"engine selection is generated; use FELUCCA_PROFILE\"\n#endif\n#define FELUCCA_PROFILE_ENGINE_{e['id']} {value}\n"
    header += '#define FELUCCA_PROFILE_NSHOWN (' + ' + '.join(f"({condition(e)})" for e in all_engines) + ' + (FELUCCA_ENG_TEST14 && FELUCCA_ENG_OMIT != 14))\n'
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
        out['engine_metadata.inc'] += f'[{i}] = {{"{e["tag"]}", "{e["preset_categories"]}", {icon}, {e["category"]}, {e["cc"]}, {e["order"]}, {int(e["kit"])} }},\n'
    for e in sorted(all_engines,key=lambda e:e['order']):
        if e['id']==10:
            out['engine_order.inc'] += '#if FELUCCA_ENG_TEST14 && FELUCCA_ENG_OMIT != 14\n14,\n#endif\n'
        out['engine_order.inc'] += f'#if {condition(e)}\n{e["id"]},\n#endif\n'
    for filename, value in [('engine_registry.inc','ENG_AT(14, &ENG_TEST14),'),('engine_names.inc','"TEST14",')]:
        out[filename] += f'#if FELUCCA_ENG_TEST14\n{value}\n#endif\n'
    out['resolved-profile.json'] = json.dumps(resolved,indent=2,sort_keys=True)+'\n'
    return out


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
    args=ap.parse_args()
    try:
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
        else:
            args.out.mkdir(parents=True,exist_ok=True)
            for name, content in outputs.items():
                (args.out/name).write_text(content)
        print(f'profile: {args.profile} ({json.loads(outputs["resolved-profile.json"])["selection_sha256"][:12]})')
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        ap.error(str(error))

if __name__=='__main__':
    main()
