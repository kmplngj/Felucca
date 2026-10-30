#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Freeze the audited donor address assignments and generated public native bounds.

Usage: python3 tests/midi_nrpn_registry_test.py build/midi_nrpn_test
The argument must be a freshly compiled production-source NRPN harness.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
source = (root / 'firmware/src/midi_nrpn_map.h').read_text()
frozen = json.loads((root / 'tests/midi_nrpn_registry.json').read_text())
common, engine = source.split('#define MIDI_NRPN_ENGINE(X)')
for section, text in [('common', common), ('engine', engine)]:
    actual = [[int(a), b, c] for a, b, c in re.findall(r'X\((\d+), (P_\w+), "([^"]+)"\)', text)]
    assert actual == frozen[section], f'{section} wire registry changed'
map_text = subprocess.check_output([sys.argv[1], '--map'], text=True).strip()
doc = (root / 'docs/midi-530.md').read_text()
assert doc.split('<!-- NRPN_MAP_BEGIN -->\n')[1].split('\n<!-- NRPN_MAP_END -->')[0] == map_text, 'public bounds differ from native descriptors'
print('NRPN frozen donor registry and generated native public bounds: PASS')
