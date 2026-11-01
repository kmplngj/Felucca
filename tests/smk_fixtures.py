#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generate NON-INSTALLABLE synthetic SMK packages for host protocol tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fm1pkg_make as P

out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'build/host/smk-fixtures')
tools = out / 'synthetic-sdk/cpu/wl82/tools'
(tools / 'cfg').mkdir(parents=True, exist_ok=True)
(tools / 'uboot.boot').write_bytes(bytes(range(32)))
(tools / 'cfg_tool.bin').write_bytes(b'C' * 32)
(tools / 'cfg/eq_cfg_hw.bin').write_bytes(b'E' * 32)
P.SDK = tools.parents[2]
flash = P.flash_image(bytes(range(256)) * 4, P.KEY, board='smk37')
# Structurally valid private loader envelope, with inert synthetic bytes.
import struct
body = bytearray(4096)
struct.pack_into('<II', body, 4, 0x1000, 0x01C0A800)
body[0x30:0x40] = b'FELUCCA-LOADER-1'
struct.pack_into('<H', body, 0, P.crc16(body[2:32]))
outer = bytearray(32)
struct.pack_into('<HII', outer, 2, P.crc16(body), 32, len(body))
outer[12] = 0x41
struct.pack_into('<H', outer, 0, P.crc16(outer[2:]))
loader = outer + body
for model, name in [('pro', 'SMK-37 Pro'), ('elite', 'SMK-37 Elite'), ('mke', 'MKE-P37')]:
    (out / f'{model}.fwsc').write_bytes(P.ufw(flash, bytes(loader), name + '_900'))
(out / 'NOT-INSTALLABLE.txt').write_text('Synthetic host test packages. No working bootloader, app or updater. NEVER INSTALL.\n')
print(f'Synthetic NON-INSTALLABLE SMK fixtures: {out}')
