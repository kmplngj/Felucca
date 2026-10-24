#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""tools/fm1_bootarea.py on synthetic boot areas (no vendor bytes), and on the official V15/V16
packages when build/recovery-inputs/ has them (#619). Run from the repo root:
  python3 tests/bootarea_test.py"""
import contextlib
import io
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fm1_bootarea as B  # noqa: E402
import fm1_install as I  # noqa: E402
import fm1pkg_make as M  # noqa: E402

failed = 0
TMP = Path(tempfile.mkdtemp(prefix="felucca-bootarea-"))


def ok(cond, what):
    global failed
    print(f"{what:<72} {'ok' if cond else 'FAIL'}")
    failed += not cond


def boot_area(payload=bytes(range(256)) * 20, clock=360_000_000, key=0x980F, cipher=True):
    """flash header, an SPL container at 0xA0 (ENC'd as on M-VAVE's flash), isd_config.ini with clock fields"""
    payload = bytes(payload)
    h = bytearray(16)
    struct.pack_into("<HHIIH", h, 0, 1, len(payload), B.SPL_LOAD, 16, I.crc16(payload))
    h[14:16] = I.crc16(h[:14]).to_bytes(2, "little")
    container = (B.jl_enc(h) + B.jl_enc(payload)) if cipher else bytes(h) + payload
    isd = M.key_blob(key) + b"\x04OSC_FREQ\x00" + (24_000_000).to_bytes(4, "little") + \
        b"\x04SYS_CLK\x00" + clock.to_bytes(4, "little") + b"\x04HSB_DIV\x00" + (1).to_bytes(4, "little")
    isd_off = B.SPL_OFF + len(container)
    head = bytearray(b"\xFF" * B.HEAD)
    hdr = struct.pack("<H", I.crc16(M.FLASH_HDR)) + M.FLASH_HDR
    top = (M.entry(I.crc16(bytes(h) + payload), B.SPL_OFF, len(container), 0, 0, 0, "uboot.boot") +
           M.entry(I.crc16(isd), isd_off, len(isd), 0x02, 0x80, 0, "isd_config.ini") +
           M.entry(0xFFFF, 0x4000, 0xFFFFFFFF, 0x81, 0xFF, 0, "app_dir_head") +
           M.entry(0xFFFF, 0xFF000, 0x1000, 0x12, 0x01, 0xFFFF, "key_mac"))
    meta = bytearray(hdr + top)
    for o in range(0, len(meta), 32):
        M.enc(meta, o, 32)
    head[:len(meta)] = meta
    head[B.SPL_OFF:B.SPL_OFF + len(container)] = container
    head[isd_off:isd_off + len(isd)] = isd
    return bytes(head)


def run(*names):
    out = io.StringIO()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        rc = B.main([str(TMP / n) for n in names], out=out)
    return rc, out.getvalue(), err.getvalue()


def put(name, data):
    (TMP / name).write_bytes(data)
    return name


head = boot_area()
dump = put("dump.bin", head + b"\xFF" * (0x100000 - B.HEAD))
rc, out, err = run(dump)
ok(rc == 1 and "flash dump" in out and "UNKNOWN" in out and "CRCs intact" in out and "SYS_CLK 360 MHz" in out
   and "chip key 0x980f" in out, "1 MiB dump: unknown SPL named UNKNOWN, CRCs and isd_config read")
spl_rec = B.records(head)[0]
B.KNOWN_SPL[(spl_rec[3], spl_rec[2])] = "TEST SPL"
rc, out, err = run(dump)
ok(rc == 0 and "boot area TEST SPL" in out, "an SPL known by its boot record (data CRC16, size) is named")
del B.KNOWN_SPL[(spl_rec[3], spl_rec[2])]

payload = bytearray(range(256)) * 20
payload[0x40:0x58] = b"AC79BLID" + b"fm1".ljust(16, b"\0")
rc, out, err = run(put("mboot.bin", boot_area(payload, clock=320_000_000)))
ok(rc == 0 and "m-bootloader" in out and "'fm1'" in out and "SYS_CLK 320 MHz" in out and "#618" in out,
   "m-bootloader: AC79BLID + board fm1 named, the clock note added")
payload[0x48:0x50] = b"smk37\0\0\0"
rc, out, err = run(put("mboot-smk.bin", boot_area(payload)))
ok(rc == 1 and "'smk37'" in out, "m-bootloader for another board -> not ok")

bad = bytearray(head)
bad[B.SPL_OFF + 0x200] ^= 1
rc, out, err = run(put("spl-bad.bin", bytes(bad)))
ok(rc == 1 and "DAMAGED: SPL payload CRC mismatch" in out, "a flipped SPL byte -> payload CRC mismatch")
bad = bytearray(head)
bad[0x30] ^= 1
rc, out, err = run(put("rec-bad.bin", bytes(bad)))
ok(rc == 1 and "DAMAGED boot area: boot record at 0x20" in out, "a flipped boot record byte -> its CRC mismatch")
rc, out, err = run(put("plain.bin", boot_area(cipher=False)))
ok(rc == 1 and "unciphered" in out, "an unciphered SPL container (the SDK file as is) is not a bootable one")
bad = bytearray(head)
isd = B.records(head)[1][1]
bad[isd] ^= 1
rc, out, err = run(put("key-bad.bin", bytes(bad)))
ok(rc == 1 and "chip key blob DAMAGED" in out, "a damaged key blob is reported, not decoded")
rc, out, err = run(put("short.bin", head[:0x1000]))
ok(rc == 2 and "shorter than the 16 KiB" in err, "a file shorter than the boot area -> exit 2")
pkg = put("pkg.fwsc", M.ufw(head + b"\xFF" * (0x93000 - B.HEAD), b"\x00" * 0x40, "FM-1_015"))
rc, out, err = run(pkg)
ok("package FM-1_015" in out and "UNKNOWN" in out, "a package: its flash.bin boot area")

for version, sys_clk in (("15", 360), ("16", 320)):
    path = ROOT / f"build/recovery-inputs/FM-1_v{version}.fwsc"
    if not path.exists():
        print(f"official V{version} boot area: skipped (needs {path.relative_to(ROOT)})")
        continue
    out = io.StringIO()
    rc = B.main([str(path)], out=out)
    text = out.getvalue()
    ok(rc == 0 and f"M-VAVE V{version}, identical to the official FM-1_0{version}" in text
       and f"SYS_CLK {sys_clk} MHz" in text and "chip key 0x980f" in text,
       f"official V{version}: named, intact, key 0x980f, SYS_CLK {sys_clk} MHz")

print(f"BOOT AREA TESTS FAILED ({failed})" if failed else "boot area tests passed")
sys.exit(1 if failed else 0)
