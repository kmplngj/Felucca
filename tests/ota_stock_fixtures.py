#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic stand-ins for M-VAVE's official packages, for tests/ota_test.c (#619).

No vendor bytes: each package has a loader shaped like M-VAVE's update loader (its
head and body CRC16s and length, forged with two free bytes each) and a flash.bin of
a pinned size whose data CRC16 matches firmware/src/ota.c OTA_STOCK, read from the
source so the fixtures follow the table. The boot area's SHA-256 cannot be forged:
tests/ota_test.c pins the stand-ins' own boot areas (v15, v16) in its copy of the table.
One cause is changed at a time; "forged" is v16 with 512 bytes of its boot area zeroed
and both CRC16s (the boot area's and flash.bin's) forged back to v16's.

  ota_stock_fixtures.py OUTDIR    -> OUTDIR/{v15,v16,head,forged,flcrc,size,unknown}.fwsc
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fm1_install as I  # noqa: E402
import fm1pkg_make as M  # noqa: E402

HEAD = 0x4000
LDR_HCRC, LDR_DCRC, LDR_LEN = 0xEBAA, 0x5881, 0x4DE1


def stock_pins():
    """[(fl_len, fl_crc, key, boot-area SHA-256 hex)] from ota.c's OTA_STOCK table"""
    src = (ROOT / "firmware/src/ota.c").read_text()
    start = src.index("OTA_STOCK[] = {")
    table = src[start:src.index("\n};", start)]
    rows = re.findall(r"\{(0x[0-9A-F]+)u, (0x[0-9A-F]+)u, (0x[0-9A-F]+)u,[^{]*\{([^}]*)\}\}", table)
    out = []
    for fl_len, fl_crc, key, sha in rows:
        digest = bytes(int(v, 16) for v in re.findall(r"0x([0-9A-F]{2})u", sha))
        assert len(digest) == 32, (fl_len, sha)
        out.append((int(fl_len, 16), int(fl_crc, 16), int(key, 16), digest.hex()))
    return out


def forge(buf, end, want, start=0):
    """set buf[end-2:end] so that crc16(buf[start:end]) == want"""
    state = I.crc16(buf[start:end - 2])
    for v in range(0x10000):
        if I.crc16(v.to_bytes(2, "little"), state) == want:
            buf[end - 2:end] = v.to_bytes(2, "little")
            return
    raise SystemExit("ota_stock_fixtures: no CRC16 forgery")


def synth(n, seed):
    return bytearray((i * seed + (i >> 9) * 31 + seed) & 0xFF for i in range(n))


def official_loader():
    """ota.bin shaped like M-VAVE's: outer head (dcrc, len, attr 0x41) and inner head (load 0x01C0A800)"""
    body = synth(LDR_LEN, 23)
    inner = bytearray(32)
    inner[4:8] = (LDR_LEN - 32).to_bytes(4, "little")
    inner[8:12] = (0x01C0A800).to_bytes(4, "little")
    inner[0:2] = I.crc16(inner[2:]).to_bytes(2, "little")
    body[0:32] = inner
    forge(body, len(body), LDR_DCRC)
    outer = bytearray(32)
    outer[2:4] = LDR_DCRC.to_bytes(2, "little")
    outer[4:8] = (0x20).to_bytes(4, "little")
    outer[8:12] = LDR_LEN.to_bytes(4, "little")
    outer[12], outer[13] = 0x41, 0xFF
    outer[16:28] = b"usb_ota.bin\0"
    forge(outer, 32, LDR_HCRC, start=2)
    outer[0:2] = LDR_HCRC.to_bytes(2, "little")
    return bytes(outer + body)


def flash(fl_len, fl_crc, seed):
    f = synth(fl_len, seed)
    forge(f, fl_len, fl_crc)
    return bytes(f)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pins = stock_pins()
    assert len(pins) == 2 and pins[0][0] == 0x93000 and pins[1][0] == 0xA9000, pins
    ldr = official_loader()
    v15, v16 = (flash(p[0], p[1], 7 + i) for i, p in enumerate(pins))
    head = bytearray(v16)
    head[0x200] ^= 1                                     # the boot area differs, flash.bin's CRC kept true
    forge(head, len(head), pins[1][1], start=0)
    forged = bytearray(v16)                              # the review's case: 512 bytes of the boot area zeroed,
    forged[0x100:0x300] = bytes(0x200)                   # its CRC16 and flash.bin's forged back to v16's
    forge(forged, HEAD, I.crc16(v16[:HEAD]))
    forge(forged, len(forged), pins[1][1])
    assert I.crc16(forged[:HEAD]) == I.crc16(v16[:HEAD]) and I.crc16(forged) == I.crc16(v16) and forged[:HEAD] != v16[:HEAD]
    flcrc = flash(pins[1][0], pins[1][1] ^ 0x0101, 9)
    size = flash(0x9D000, pins[1][1], 9)
    unknown = bytearray(ldr)
    unknown[2:4] = (LDR_DCRC ^ 1).to_bytes(2, "little")   # another loader body: its heads stay well made
    unknown[0:2] = I.crc16(unknown[2:32]).to_bytes(2, "little")
    files = {"v15": (v15, ldr, "FM-1_015"), "v16": (v16, ldr, "FM-1_016"), "head": (bytes(head), ldr, "FM-1_016"),
             "forged": (bytes(forged), ldr, "FM-1_016"),
             "flcrc": (flcrc, ldr, "FM-1_016"), "size": (size, ldr, "FM-1_016"), "unknown": (v16, bytes(unknown), "FM-1_016")}
    for name, (fl, ota, product) in files.items():
        (out / f"{name}.fwsc").write_bytes(M.ufw(fl, ota, product))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
