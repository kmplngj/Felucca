#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Name the boot area of an FM-1 flash dump or package; read-only (#619 survey, #618 clock).

  fm1_bootarea.py FILE [FILE ...]

FILE is a flash dump from address 0 (at least the 16 KiB boot area, e.g. the 1 MiB read
of FM-1 Transporter or M-Flasher) or a .fwsc package (its flash.bin's boot area). For
each it prints which boot area it is (M-VAVE V15's, V16's, m-bootloader's, or unknown),
whether its records and the SPL container are intact, the chip key, and the clock its
isd_config.ini declares. Nothing is written and no device is accessed.

The SPL container checks follow the format as felucca-bsp's chip/ota.c (afd83ede) and
m-bootloader document it: a single-bank BANKCB container at 0xA0, loaded at 0x01C02000,
its 16-byte header and its payload each JieLi-ENC'd from key 0xFFFF; m-bootloader names
itself with "AC79BLID" and the board at payload +0x40.

Exit codes: 0 every file is a known, intact boot area; 1 one is unknown or damaged;
2 a file could not be read.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fm1_install as I  # noqa: E402

HEAD = 0x4000
SPL_OFF, SPL_LOAD = 0xA0, 0x01C02000
# M-VAVE's SPLs by their boot record (data CRC16, size); the whole boot areas of the official packages by SHA-256
KNOWN_SPL = {(0x71C8, 0x3830): "M-VAVE V15", (0xDCC8, 0x3898): "M-VAVE V16"}
KNOWN_HEAD = {"d9f43191777656de01c7bed4f9e9ba2e34e94832c5d2ed02c3fc7ab7a6d9bd67": "FM-1_015",
              "8f5228c2d6ea2068838ef4916f946bea877d14b07e6cfca49e41957f4c7b234f": "FM-1_016"}
CLOCKS = ("SYS_CLK", "OSC_FREQ", "HSB_DIV", "LSB_DIV")


def jl_enc(data, key=0xFFFF):
    out = bytearray(data)
    for i in range(len(out)):
        out[i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return out


def boot_area(raw):
    """-> (kind, the 16 KiB boot area); a package's flash.bin, else the dump itself"""
    if len(raw) >= I.BLOCKS * I.BLK + I.UFW_HDR:
        img = I.logical_image(raw)
        h = I.jl_dec(img[:I.UFW_HDR])
        if I.crc16(h[2:]) == I.u16(h, 0) and h[16:22] == b"AC791N":
            for i in range(min(I.u16(h, 8), I.UFW_MAXENT)):
                e = I.jl_dec(img[I.UFW_HDR + i * I.UFW_ENT:I.UFW_HDR + (i + 1) * I.UFW_ENT])
                if I.u16(e, 0) == 0 and I.u32(e, 12) >= HEAD:
                    return f"package {I.product_of(raw)}", bytes(img[I.u32(e, 8):I.u32(e, 8) + HEAD])
            raise ValueError("a package without a flash.bin boot area")
    if len(raw) < HEAD:
        raise ValueError(f"{len(raw)} B: shorter than the 16 KiB boot area")
    return "flash dump", bytes(raw[:HEAD])


def records(head):
    """the flash header's CRC and the JLFS entries after it: [(name, offset, size, data CRC16)], or a problem"""
    hdr = I.jl_dec(head[:32])
    if I.crc16(hdr[2:]) != I.u16(hdr, 0):
        return "flash header CRC mismatch"
    out = []
    for off in range(32, 0x400, 32):
        e = I.jl_dec(head[off:off + 32])
        if I.crc16(e[2:]) != I.u16(e, 0):
            return f"boot record at {off:#x}: CRC mismatch"
        out.append((I.printable(e[16:32].split(b"\0")[0]), I.u32(e, 4), I.u32(e, 8), I.u16(e, 2)))
        if I.u16(e, 14):                                   # the last top-level entry
            return out
    return "no last boot record"


def container_header(h, size):
    """a single-bank BANKCB header: one bank of size - 16 bytes at offset 16, loaded at SPL_LOAD, its own CRC"""
    return (I.crc16(h[:14]) == I.u16(h, 14) and I.u16(h, 0) == 1 and I.u16(h, 2) + 16 == size
            and I.u32(h, 4) == SPL_LOAD and I.u32(h, 8) == 16)


def spl(head, rec):
    """the SPL container at 0xA0 -> (problem or None, its payload)"""
    name, off, size, dcrc = rec
    if off != SPL_OFF or not 16 + 0x50 <= size <= HEAD - SPL_OFF:
        return f"first boot record {name!r} is not an SPL at {SPL_OFF:#x}", b""
    c = head[SPL_OFF:SPL_OFF + size]
    h = jl_enc(c[:16])
    payload = jl_enc(c[16:])
    if not container_header(h, size):
        if container_header(c[:16], size):
            return "SPL container unciphered, as in the SDK file: not one the ROM starts", c[16:]
        return "SPL container header damaged", payload
    if I.crc16(payload) != I.u16(h, 12):
        return "SPL payload CRC mismatch", payload
    if I.crc16(bytes(h) + bytes(payload)) != dcrc:
        return "SPL boot record CRC mismatch", payload
    return None, payload


def isd_config(head, recs):
    """chip key and clock fields of the isd_config.ini the boot area carries"""
    for name, off, size, _ in recs:
        if name == "isd_config.ini" and off + size <= HEAD:
            blob = head[off:off + size]
            info = {}
            if size >= 34 and I.crc16(blob[:32]) == I.u16(blob, 32):
                s = sum(blob[:16]) & 0xFF
                s = 0xAA if s >= 0xE0 else 0x55 if s <= 0x10 else s
                info["key"] = sum(1 << i for i in range(16) if (blob[16 + i] ^ blob[15 - i]) < s)
            for field in CLOCKS:
                at = blob.find(b"\x04" + field.encode() + b"\0")
                if at >= 0:
                    v = at + len(field) + 2
                    info[field] = I.u32(blob, v)
            return info
    return None


def describe(path):
    """-> (ok, lines)"""
    try:
        raw = Path(path).read_bytes()
        kind, head = boot_area(raw)
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}")
    lines, ok = [], True
    if kind.startswith("package") and I.LOADER_MARK in raw:
        return True, [f"{path} ({kind}): a Felucca package; its loader writes the app area only, never this boot area "
                      "(the device keeps its own: dump it to name it)"]
    recs = records(head)
    if isinstance(recs, str):
        return False, [f"{path} ({kind}): DAMAGED boot area: {recs}"]
    problem, payload = spl(head, recs[0])
    blid = payload[0x40:0x48] == b"AC79BLID"
    if blid:
        board = I.printable(payload[0x48:0x58].split(b"\0")[0])
        name = f"m-bootloader (AC79BLID, board {board!r})"
        ok = board == "fm1"
    else:
        name = KNOWN_SPL.get((recs[0][3], recs[0][2]), "UNKNOWN")
        ok = name != "UNKNOWN"
    same = KNOWN_HEAD.get(hashlib.sha256(head).hexdigest())
    lines.append(f"{path} ({kind}): boot area {name}" + (f", identical to the official {same} package's" if same else ""))
    lines.append(f"  SPL {recs[0][2]:#x} B, record CRC {recs[0][3]:#06x}: "
                 + (f"DAMAGED: {problem}" if problem else "records and container CRCs intact"))
    ok = ok and problem is None
    cfg = isd_config(head, recs)
    if cfg is None:
        lines.append("  no isd_config.ini in the boot area")
        return False, lines
    clock = ", ".join(f"{k} {cfg[k] / 1e6:g} MHz" if k in ("SYS_CLK", "OSC_FREQ") else f"{k} {cfg[k]}"
                      for k in CLOCKS if k in cfg)
    key = f"chip key {cfg['key']:#06x}" if "key" in cfg else "chip key blob DAMAGED"
    lines.append(f"  {key}; isd_config.ini declares {clock or 'no clock fields'}"
                 + ("" if not blid else " (m-bootloader configures the clock itself: see #618)"))
    return ok and "key" in cfg, lines


def main(argv=None, out=sys.stdout):
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    rc = 0
    for path in paths:
        try:
            good, lines = describe(path)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print("\n".join(lines), file=out)
        rc |= not good
    return rc


if __name__ == "__main__":
    sys.exit(main())
