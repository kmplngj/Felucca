#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Reviewed native font contract; target allocation is verified again after linking."""
import hashlib
import json
import os
import re

POLICY = 'assets/fonts/m8stealth/resource-policy.json'
MANIFEST = 'ui-font-manifest.json'
INPUTS = ('assets/fonts/m8stealth/m8stealth57.woff2',
          'assets/fonts/m8stealth/m8stealth89.woff2', 'tools/gen_bitmap_font.py',
          'tools/ui_font_data.py', 'tools/aa_raster.py', 'tools/font_resources.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def serialize(value):
    return json.dumps(value, indent=2, sort_keys=True) + '\n'


def inventory(root, header):
    """Read generated declarations, including unreferenced payloads/extra faces.

    Sizes describe pi32v2's reviewed 32-bit ABI, never the host Python/C ABI.
    The exact header hash also pins every glyph bearing, advance and bitmap bit.
    """
    if os.environ.get('FELUCCA_FONT', 'm8stealth') != 'm8stealth':
        raise ValueError('font resource gate requires FELUCCA_FONT=m8stealth')
    if '#define UI_FONT_M8STEALTH 1' not in header:
        raise ValueError('font resource gate requires M8Stealth header')
    sizes, glyph_types = {}, {}
    for typ, name, count in re.findall(r'static const (uint8_t|aag_t|aag_fixed_t) (AF_\w+)\[(\d+)\]', header):
        if name in sizes:
            raise ValueError('duplicate font array: ' + name)
        record_bytes = {'uint8_t': 1, 'aag_t': 8, 'aag_fixed_t': 6}[typ]
        sizes[name] = int(count) * record_bytes
        if typ != 'uint8_t':
            glyph_types[name] = (typ, int(count))
    faces = {}
    for name, fields in re.findall(r'static const aafont_t AF_(\w+) = \{([^}]+)\};', header):
        values = [v.strip() for v in fields.split(',')]
        if name in faces or len(values) not in (14, 15):
            raise ValueError('duplicate or unsupported font descriptor: ' + name)
        fixed = int(values[13]) if len(values) == 15 else 0
        glyph_type, glyph_count = glyph_types.get(values[6], (None, 0))
        if fixed < 0 or fixed > 65535 or (fixed and (glyph_type != 'aag_fixed_t' or
                int(values[11]) != 0 or int(values[12]) == 0)) or (not fixed and glyph_type != 'aag_t'):
            raise ValueError('font glyph representation disagrees with descriptor: ' + name)
        faces[name] = dict(height=int(values[0]), baseline=int(values[1]),
                           first=int(values[2]), last=int(values[3]), extras=int(values[4]),
                           glyph_array=values[6], bitmap_array=values[7], scale=int(values[12]))
        extras = re.search(r'AF_' + name + r'_EX\[\d+\] = \{([^}]*)\}', header)
        if extras is None:
            raise ValueError('missing font extra-code array: ' + name)
        codes = [int(v.strip(), 0) for v in extras[1].split(',') if v.strip()]
        faces[name]['extra_codes'] = codes
        faces[name]['glyph_count'] = glyph_count
        table = re.search(re.escape(values[6]) + r'\[\d+\] = \{(.*?)\};', header, re.S)
        if table is None:
            raise ValueError('missing font glyph array: ' + name)
        rows = re.findall(r'\{([^{}]+)\}', table[1])
        if len(rows) != glyph_count or any(len(row.split(',')) != (5 if fixed else 6) for row in rows):
            raise ValueError('font glyph records disagree with declaration: ' + name)
        faces[name]['advances_sixteenths_px'] = ([fixed] if fixed else
                sorted({int(row.split(',')[1]) for row in rows}))
        for metric in ('Y', 'H'):
            cap = re.search(r'^#define AF_' + name + r'_CAP_' + metric + r' (\d+)$', header, re.M)
            if cap is None:
                raise ValueError('missing font capital metric: ' + name)
            faces[name]['cap_' + metric.lower()] = int(cap[1])
        sizes['AF_' + name] = 36
    if set(faces) != set('SMLNX'):
        raise ValueError('font face set must be S/M/L/N/X')
    payloads = {name for name in sizes if name.endswith('_DATA')}
    if payloads != {'AF_S_DATA', 'AF_M_DATA'} or any(
            faces[name]['bitmap_array'] != 'AF_M_DATA' for name in 'LNX'):
        raise ValueError('L/N/X must share M payload; only S/M bitmap arrays are allowed')
    abi = dict(pointer_bytes=4, glyph_record_bytes=8, descriptor_bytes=36)
    if any(typ == 'aag_fixed_t' for typ, _ in glyph_types.values()):
        abi['compact_glyph_record_bytes'] = 6
    return dict(schema_version=1, kind='felucca-native-font-resources', family='m8stealth',
                input_sha256={name: sha((root / name).read_bytes()) for name in INPUTS},
                header_sha256=sha(header.encode()), faces=faces, symbol_bytes=sizes,
                target_abi=abi,
                array_descriptor_bytes=sum(sizes.values()))


def checked(root, header):
    actual = inventory(root, header)
    policy = json.loads((root / POLICY).read_text())
    if policy.get('schema_version') != 1 or type(policy.get('max_array_descriptor_bytes')) is not int:
        raise ValueError('unsupported native font resource policy')
    if actual != policy.get('expected'):
        raise ValueError('native font contract changed; review inputs/metrics/payloads and update ' + POLICY)
    if actual['array_descriptor_bytes'] > policy['max_array_descriptor_bytes']:
        raise ValueError('native font array/descriptor budget exceeded')
    return actual


def check_generated(root, directory):
    actual = checked(root, (directory / 'ui_fonts.h').read_text())
    if (directory / MANIFEST).read_text() != serialize(actual):
        raise ValueError('stale native font manifest; regenerate assets')
    return actual


def linked(root, directory, syms):
    """Check actual AF object sizes; report other named UI costs separately.

    Code groups contain emitted symbols only: inlined code belongs to its caller.
    These groups are subsets of the existing whole-image/region accounting.
    """
    manifest = check_generated(root, directory)
    rows = {}
    groups = {name: {} for name in ('text_arrays_descriptors', 'keycaps', 'icons',
                                   'decoder_ramp_code', 'ramp_caches')}
    for line in syms.splitlines():
        p = line.split()
        if not p:
            continue
        name = p[-1]
        group = ('text_arrays_descriptors' if name.startswith('AF_') else
                 'keycaps' if name == 'KC' or name.startswith('KC_') else
                 'icons' if re.match(r'AI(?:12|16|24)_', name) else
                 'decoder_ramp_code' if name in ('cv_alpha', 'cv_alpha_hc', 'cv_bitmap', 'ramp', 'kc_ramp') else
                 'ramp_caches' if name in ('rc', 'kr') else None)
        if group is None:
            continue
        if len(p) < 5 or name in rows or not re.fullmatch('[0-9a-fA-F]+', p[-2]) or not p[-3].startswith('.'):
            raise ValueError('invalid or duplicate UI resource symbol: ' + name)
        entry = dict(section=p[-3], bytes=int(p[-2], 16))
        rows[name] = entry
        groups[group][name] = entry
    actual = {name: row['bytes'] for name, row in groups['text_arrays_descriptors'].items()}
    if actual != manifest['symbol_bytes'] or any(
            row['section'] != '.text' for row in groups['text_arrays_descriptors'].values()):
        raise ValueError('linked native font symbols differ from reviewed target sizes')
    return dict(manifest=manifest, groups={name: dict(symbols=entries,
                    bytes=sum(e['bytes'] for e in entries.values()) if entries else None,
                    status='emitted named symbols' if entries else 'not emitted or not identified')
                    for name, entries in groups.items()},
                scope='Named symbol bytes, excluding inter-object padding; subsets of app/RAM/POOL totals',
                code_limit='Emitted decoder/ramp symbols only; inlined code remains in callers')
