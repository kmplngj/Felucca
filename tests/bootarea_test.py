#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Extracted from kmplngj/Felucca PR #622, a2481789d8b7e588eca7b988710ada9e20e294ac.
# Original commit: Jan Kampling; Co-Authored-By: Claude Opus 5.5.
"""tools/fm1_bootarea.py on synthetic boot areas (no vendor bytes), and on the official V15/V16
packages when build/recovery-inputs/ has them (#619). Run from the repo root:
  python3 tests/bootarea_test.py"""
import contextlib
import io
import os
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
_temporary = tempfile.TemporaryDirectory(prefix="felucca-bootarea-")
TMP = Path(_temporary.name)


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
        rc = B.main([str(TMP / n) if not n.startswith("--") else n for n in names], out=out)
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
ok(rc == 1 and "isd_config.ini data CRC mismatch" in out, "a damaged config is rejected before key/clock decoding")
rc, out, err = run(put("short.bin", head[:0x1000]))
ok(rc == 2 and "shorter than the 16 KiB" in err, "a file shorter than the boot area -> exit 2")
pkg = put("pkg.fwsc", M.ufw(head + b"\xFF" * (0x93000 - B.HEAD), b"\x00" * 0x40, "FM-1_015"))
rc, out, err = run(pkg)
ok("package FM-1_015" in out and "UNKNOWN" in out, "a package: its flash.bin boot area")


def record_edit(data, index, **fields):
    data = bytearray(data)
    off = 32 + index * 32
    rec = I.jl_dec(data[off:off + 32])
    for field, value in fields.items():
        pos, fmt = {"dcrc": (2, "H"), "offset": (4, "I"), "size": (8, "I"), "last": (14, "H")}[field]
        struct.pack_into("<" + fmt, rec, pos, value)
    struct.pack_into("<H", rec, 0, I.crc16(rec[2:]))
    data[off:off + 32] = I.jl_dec(rec)
    return bytes(data)


def config_replace(data, blob):
    off = B.records(data)[1][1]
    data = bytearray(data)
    data[off:off + len(blob)] = blob
    return record_edit(data, 1, size=len(blob), dcrc=I.crc16(blob))


def package_edit(raw, index=None, **fields):
    image = bytearray(I.logical_image(raw))
    header = I.jl_dec(image[:I.UFW_HDR])
    if index is not None:
        pos = I.UFW_HDR + index * I.UFW_ENT
        entry = I.jl_dec(image[pos:pos + I.UFW_ENT])
        for field, value in fields.items():
            off, fmt = {"type": (0, "H"), "offset": (8, "I"), "size": (12, "I")}[field]
            struct.pack_into("<" + fmt, entry, off, value)
        image[pos:pos + I.UFW_ENT] = I.jl_dec(entry)
        struct.pack_into("<H", header, 2, I.crc16(image[I.UFW_HDR:I.UFW_HDR + 2 * I.UFW_ENT]))
    else:
        for field, value in fields.items():
            off, fmt = {"size": (4, "I"), "count": (8, "H")}[field]
            struct.pack_into("<" + fmt, header, off, value)
    struct.pack_into("<H", header, 0, I.crc16(header[2:]))
    image[:I.UFW_HDR] = I.jl_dec(header)
    return I.package_bytes(image, "FM-1_015")


# Keep a recognized synthetic SPL for failures where exit status otherwise already
# fails because the original test head is unknown (causal negative controls).
B.KNOWN_SPL[(spl_rec[3], spl_rec[2])] = "TEST SPL"
rc, out, err = run("--raw", dump)
ok(rc == 0, "explicit raw selector reads the same recognized head")
rc, out, err = run("--package", dump)
ok(rc == 2 and "UFW header CRC mismatch" in err, "explicit package never falls back to raw")
rc, out, err = run("--raw", pkg)
ok(rc == 1 and "flash header CRC mismatch" in out, "explicit raw never parses a package by filename")
rc, out, err = run(put("renamed.data", (TMP / pkg).read_bytes()))
ok(rc == 0 and "package FM-1_015" in out, "automatic package selection ignores filename suffix")
rc, out, err = run(put("renamed.fwsc", head))
ok(rc == 0 and "flash dump" in out, "automatic raw selection ignores .fwsc suffix")

raw_pkg = (TMP / pkg).read_bytes()
for label, data, expected in (
        ("header-crc", bytes([raw_pkg[0] ^ 1]) + raw_pkg[1:], "header CRC mismatch"),
        ("list-crc", raw_pkg[:0x41] + bytes([raw_pkg[0x41] ^ 1]) + raw_pkg[0x42:], "entry list CRC mismatch"),
        ("data-crc", raw_pkg[:-1] + bytes([raw_pkg[-1] ^ 1]), "data CRC mismatch"),
        ("truncated-package", raw_pkg[:-1], "declared size"),
        ("count-zero", package_edit(raw_pkg, count=0), "entry count"),
        ("count-too-many", package_edit(raw_pkg, count=12), "entry count"),
        ("size-lie", package_edit(raw_pkg, size=0xFFFFFFFF), "declared size"),
        ("flash-outside", package_edit(raw_pkg, 0, offset=0xFFFFFF00), "extent outside"),
        ("flash-metadata", package_edit(raw_pkg, 0, offset=0), "extent outside"),
        ("flash-too-short", package_edit(raw_pkg, 0, size=B.HEAD - 1), "data CRC mismatch"),
        ("no-flash", package_edit(raw_pkg, 0, type=1), "without a flash.bin"),
        ("duplicate-flash", package_edit(raw_pkg, 1, type=0), "second flash.bin"),
        ("overlap", package_edit(raw_pkg, 1, offset=0x400), "overlapping")):
    rc, out, err = run(put(label, data))
    ok(rc == 2 and expected in err, f"package {label}: refused before boot-area findings")

for label, flash in (("short-flash", head[:-1]), ("large-flash", bytes(I.FL_MAX + 1))):
    rc, out, err = run("--package", put(label, M.ufw(flash, bytes(64), "FM-1_015")))
    ok(rc == 2 and "flash.bin size outside" in err, f"package {label}: actual data respects survey size limits")
rc, out, err = run("--package", put("head-only-package", M.ufw(head, bytes(64), "FM-1_015")))
ok(rc == 0, "16 KiB head with unknown loader is surveyable without installer permission")

# The original script treated a marker anywhere as proof of a Felucca loader and
# returned success even for damaged package contents. Pin that bypass closed.
spoof = M.ufw(head, b"FELUCCA-LOADER-1", "FM-1_900")
spoof = spoof[:-1] + bytes([spoof[-1] ^ 1])
rc, out, err = run(put("marker-spoof", spoof))
ok(rc == 2 and "data CRC mismatch" in err and "app area only" not in out,
   "arbitrary loader marker cannot bypass package validation")

for field in B.CLOCKS:
    for length in range(4):
        data = config_replace(head, M.key_blob(0x980F) + b"\x04" + field.encode() + b"\0" + b"\x01" * length)
        rc, out, err = run(put("clock-cut", data))
        ok(rc == 1 and f"{field} value cut off" in out and f"{field} 0" not in out,
           f"config {field}: {length}/4 value bytes are never zero-extended")
blob = M.key_blob(0x980F) + (b"\x04SYS_CLK\0" + (320_000_000).to_bytes(4, "little")) * 2
rc, out, err = run(put("clock-duplicate", config_replace(head, blob)))
ok(rc == 1 and "duplicate SYS_CLK" in out, "ambiguous duplicate clock fields are refused")
bad_blob = bytearray(M.key_blob(0x980F))
bad_blob[0] ^= 1
rc, out, err = run(put("key-inner-crc", config_replace(head, bad_blob)))
ok(rc == 1 and "chip key blob DAMAGED" in out, "bad key-blob CRC with valid record CRC is not decoded")
for label, data, expected in (
        ("config-outside", record_edit(head, 1, offset=B.HEAD - 4), "extent outside"),
        ("config-overlap", record_edit(head, 1, offset=B.SPL_OFF), "extent outside"),
        ("config-too-small", record_edit(head, 1, size=33), "extent outside"),
        ("spl-crc", record_edit(head, 0, dcrc=spl_rec[3] ^ 1), "SPL boot record CRC mismatch"),
        ("spl-too-big", record_edit(head, 0, size=B.HEAD), "not an SPL"),
        ("record-unterminated", record_edit(head, 3, last=0), "no last boot record")):
    rc, out, err = run(put(label, data))
    ok(rc == 1 and expected in out, f"raw {label}: damaged finding")

for n in (0, 31, 32, B.HEAD - 1):
    rc, out, err = run(put("raw-cut", head[:n]))
    ok(rc == 2 and "shorter than" in err, f"raw {n} bytes: incomplete input")
rc, out, err = run(put("oversize", bytes(I.MAX_PKG + 1)))
ok(rc == 2 and "exceeds" in err, "oversized saved file is bounded before parsing")
rc, out, err = run(str(TMP))
ok(rc == 2 and "regular saved file" in err, "directory is refused as non-file input")
if hasattr(os, "mkfifo"):
    os.mkfifo(TMP / "fifo")
    rc, out, err = run("fifo")
    ok(rc == 2 and "regular saved file" in err, "FIFO is refused before opening or waiting for bytes")
rc, out, err = run("missing.bin")
ok(rc == 2 and "No such file" in err, "unreadable input exits 2 without a traceback")
rc, out, err = run("--raw", dump, "mboot-smk.bin")
ok(rc == 1 and "TEST SPL" in out and "smk37" in out, "multiple files retain an unknown/damaged exit result")
del B.KNOWN_SPL[(spl_rec[3], spl_rec[2])]

# Import and run under transport tripwires: no MIDI dependency, enumeration,
# network, loader execution or subprocess is required by this offline entry point.
import subprocess
probe = '''import runpy, socket, sys
from unittest.mock import patch
sys.modules['mido'] = None
sys.modules['rtmidi'] = None
sys.argv = ['tools/fm1_bootarea.py', '--raw', sys.argv[1]]
with patch('subprocess.Popen', side_effect=AssertionError('subprocess')), patch.object(socket, 'socket', side_effect=AssertionError('network')):
    runpy.run_path('tools/fm1_bootarea.py', run_name='__main__')
'''
result = subprocess.run([sys.executable, "-c", probe, str(TMP / "mboot.bin")], cwd=ROOT,
                        capture_output=True, text=True)
ok(result.returncode == 0 and "m-bootloader" in result.stdout, "CLI runs without MIDI, network or subprocess access")


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
