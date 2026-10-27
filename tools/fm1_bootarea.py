#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Extracted from kmplngj/Felucca PR #622, a2481789d8b7e588eca7b988710ada9e20e294ac.
# Original commit: Jan Kampling; Co-Authored-By: Claude Opus 5.5.
# Offline input validation adapted here; see docs/boot-area-survey.md.
"""Name the boot area of an FM-1 flash dump or package; read-only (#619 survey, #618 clock).

  fm1_bootarea.py [--raw | --package] FILE [FILE ...]

FILE is a flash dump from address 0 (at least the 16 KiB boot area, e.g. the 1 MiB read
of FM-1 Transporter or M-Flasher) or a .fwsc package (its flash.bin's boot area). For
each it prints which boot area it is (M-VAVE V15's, V16's, m-bootloader's, or unknown),
whether its records and the SPL container are intact, the chip key, and the clock its
isd_config.ini declares. Nothing is written and no device is accessed.

The SPL container checks follow the format as felucca-bsp's chip/ota.c (afd83ede) and
m-bootloader document it: a single-bank BANKCB container at 0xA0, loaded at 0x01C02000,
its 16-byte header and its payload each JieLi-ENC'd from key 0xFFFF; m-bootloader names
itself with "AC79BLID" and the board at payload +0x40.

Names based on SPL CRC/size or AC79BLID are format hints, not authentication.
Only a whole-boot-area SHA-256 match establishes equality to a reference head.
This survey does not authorize installation or measure the live system clock.

Exit codes: 0 recognized boot-area format and checked fields intact;
1 unknown/damaged boot area; 2 unreadable, oversized or malformed input.
"""
import argparse
import hashlib
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fm1_install as I  # noqa: E402
from fm1pkg_make import chipkey_decode  # noqa: E402

HEAD = 0x4000
SPL_OFF, SPL_LOAD = 0xA0, 0x01C02000
# M-VAVE's SPLs by their boot record (data CRC16, size); the whole boot areas of the official packages by SHA-256
# (firmware/src/ota.c OTA_STOCK pins the same two digests on the device; tests/install_test.py checks they agree)
KNOWN_SPL = {(0x71C8, 0x3830): "M-VAVE V15", (0xDCC8, 0x3898): "M-VAVE V16"}
KNOWN_HEAD = {"d9f43191777656de01c7bed4f9e9ba2e34e94832c5d2ed02c3fc7ab7a6d9bd67": "FM-1_015",
              "8f5228c2d6ea2068838ef4916f946bea877d14b07e6cfca49e41957f4c7b234f": "FM-1_016"}
CLOCKS = ("SYS_CLK", "OSC_FREQ", "HSB_DIV", "LSB_DIV")


# Same ENC operation; reuse the installer's pure format helper, without MIDI setup.
jl_enc = I.jl_dec


def package_head(raw):
    """Bounded UFW survey, independent of the installer's loader allowlist.

    Reuses its format primitives. Unlike ufw_damage(), this does not require a
    supported OTA loader: a saved package can be surveyed without being installable.
    """
    if len(raw) < I.BLOCKS * I.BLK:
        raise ValueError("shorter than the package marker area")
    img = I.logical_image(raw)
    if len(img) < I.UFW_HDR:
        raise ValueError("shorter than the UFW header")
    h = I.jl_dec(img[:I.UFW_HDR])
    if I.crc16(h[2:]) != I.u16(h, 0):
        raise ValueError("UFW header CRC mismatch")
    if h[16:22] != b"AC791N":
        raise ValueError("UFW chip is not AC791N")
    nent = I.u16(h, 8)
    if not 1 <= nent <= I.UFW_MAXENT:
        raise ValueError("UFW entry count outside 1..11")
    lend = I.UFW_HDR + nent * I.UFW_ENT
    if lend > len(img):
        raise ValueError("UFW entry list cut off")
    if I.u32(h, 4) != len(img):
        raise ValueError("UFW declared size does not match saved bytes")
    if I.crc16(img[I.UFW_HDR:lend]) != I.u16(h, 2):
        raise ValueError("UFW entry list CRC mismatch")
    flash, extents = None, []
    for i in range(nent):
        e = I.jl_dec(img[I.UFW_HDR + i * I.UFW_ENT:I.UFW_HDR + (i + 1) * I.UFW_ENT])
        typ, off, size = I.u16(e, 0), I.u32(e, 8), I.u32(e, 12)
        if off < lend or off + size > len(img):
            raise ValueError(f"UFW file {i}: extent outside saved bytes")
        if any(off < end and start < off + size for start, end in extents):
            raise ValueError(f"UFW file {i}: overlapping file extent")
        extents.append((off, off + size))
        if I.crc16(img[off:off + size]) != I.u16(e, 4):
            raise ValueError(f"UFW file {i}: data CRC mismatch")
        if typ == 0:
            if flash is not None:
                raise ValueError("a second flash.bin (type 0)")
            if not HEAD <= size <= I.FL_MAX:
                raise ValueError("flash.bin size outside 16 KiB..1 MiB")
            flash = bytes(img[off:off + HEAD])
    if flash is None:
        raise ValueError("a package without a flash.bin boot area")
    return f"package {I.printable(I.product_of(raw).encode('latin1'))}", flash


def boot_area(raw, file_type="auto"):
    """-> (kind, 16 KiB boot area). Explicit selection never falls back."""
    if file_type == "auto" and len(raw) >= I.BLOCKS * I.BLK:
        h = I.jl_dec(I.logical_image(raw)[:I.UFW_HDR])
        # A recognizable package remains a package even if its header CRC is bad.
        if h[16:22] == b"AC791N" or I.product_of(raw).startswith("FM-1_"):
            file_type = "package"
    if file_type == "package":
        return package_head(raw)
    if len(raw) < HEAD:
        raise ValueError(f"{len(raw)} B: shorter than the 16 KiB boot area")
    return "flash dump", bytes(raw[:HEAD])


def records(head):
    """the flash header's CRC and the JLFS entries after it: [(name, offset, size, data CRC16)], or a problem"""
    if len(head) != HEAD:
        return "incomplete 16 KiB boot area"
    hdr = I.jl_dec(head[:32])
    if I.crc16(hdr[2:]) != I.u16(hdr, 0):
        return "flash header CRC mismatch"
    out = []
    for off in range(32, SPL_OFF, 32):
        e = I.jl_dec(head[off:off + 32])
        if I.crc16(e[2:]) != I.u16(e, 0):
            return f"boot record at {off:#x}: CRC mismatch"
        out.append((I.printable(e[16:32].split(b"\0")[0]), I.u32(e, 4), I.u32(e, 8), I.u16(e, 2)))
        if I.u16(e, 14):                                   # the last top-level entry
            return out
    return "no last boot record"


def container_header(h, size):
    """a single-bank BANKCB header: one bank of size - 16 bytes at offset 16, loaded at SPL_LOAD, its own CRC"""
    return (len(h) == 16 and I.crc16(h[:14]) == I.u16(h, 14) and I.u16(h, 0) == 1 and I.u16(h, 2) + 16 == size
            and I.u32(h, 4) == SPL_LOAD and I.u32(h, 8) == 16)


def spl(head, rec):
    """the SPL container at 0xA0 -> (problem or None, its payload)"""
    name, off, size, dcrc = rec
    if off != SPL_OFF or not 16 + 0x50 <= size <= HEAD - SPL_OFF:
        return f"first boot record {name!r} is not an SPL at {SPL_OFF:#x}", b""
    c = head[SPL_OFF:SPL_OFF + size]
    if len(c) != size:
        return "SPL container cut off", b""
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
    matches = [r for r in recs if r[0] == "isd_config.ini"]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("duplicate isd_config.ini records")
    _, off, size, dcrc = matches[0]
    spl_end = recs[0][1] + recs[0][2]
    if off < spl_end or size < 34 or off + size > len(head):
        raise ValueError("isd_config.ini extent outside boot-area config space")
    blob = head[off:off + size]
    if I.crc16(blob) != dcrc:
        raise ValueError("isd_config.ini data CRC mismatch")
    info = {}
    if I.crc16(blob[:32]) == I.u16(blob, 32):
        info["key"] = chipkey_decode(blob[:32])
    for field in CLOCKS:
        marker = b"\x04" + field.encode() + b"\0"
        at = blob.find(marker, 34)
        if at >= 0:
            v = at + len(marker)
            if v + 4 > len(blob):
                raise ValueError(f"isd_config.ini {field} value cut off")
            if blob.find(marker, v + 4) >= 0:
                raise ValueError(f"isd_config.ini duplicate {field} field")
            info[field] = I.u32(blob, v)
    return info


def describe(path, file_type="auto"):
    """-> (ok, lines)"""
    try:
        if not stat.S_ISREG(Path(path).stat().st_mode):
            raise ValueError("expected a regular saved file")
        with Path(path).open("rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("expected a regular saved file")
            raw = source.read(I.MAX_PKG + 1)
        if len(raw) > I.MAX_PKG:
            raise ValueError(f"saved file exceeds {I.MAX_PKG} B limit")
        kind, head = boot_area(raw, file_type)
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}")
    lines, ok = [], True
    recs = records(head)
    if isinstance(recs, str):
        return False, [f"{path} ({kind}): DAMAGED boot area: {recs}"]
    problem, payload = spl(head, recs[0])
    blid = payload[0x40:0x48] == b"AC79BLID"
    if blid:
        if len(payload) < 0x58:
            problem = problem or "AC79BLID board field cut off"
        board = I.printable(payload[0x48:0x58].split(b"\0")[0])
        name = f"m-bootloader (AC79BLID, board {board!r})"
        ok = board == "fm1"
    else:
        name = KNOWN_SPL.get((recs[0][3], recs[0][2]), "UNKNOWN")
        ok = name != "UNKNOWN"
    same = KNOWN_HEAD.get(hashlib.sha256(head).hexdigest())
    lines.append(f"{path} ({kind}): boot area {name}" + (f", identical to the official {same} package's" if same else ""))
    lines.append(f"  SPL {recs[0][2]:#x} B, record CRC {recs[0][3]:#06x}: "
                 + (f"DAMAGED: {problem}" if problem else "record headers and SPL container CRCs intact"))
    ok = ok and problem is None
    if not same:
        lines.append("  format identification only; no exact reference boot-area hash match")
    if kind.startswith("package"):
        lines.append("  package bytes do not establish the device boot area or installer acceptance")
    try:
        cfg = isd_config(head, recs)
    except ValueError as e:
        lines.append(f"  DAMAGED: {e}")
        return False, lines
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
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--raw", action="store_const", const="raw", dest="file_type",
                       help="read bytes from flash address zero; ignore filename")
    group.add_argument("--package", action="store_const", const="package", dest="file_type",
                       help="require an AC791N UFW package; never fall back to raw")
    parser.add_argument("paths", nargs="+")
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return e.code
    paths = args.paths
    rc = 0
    for path in paths:
        try:
            good, lines = describe(path, args.file_type or "auto")
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print("\n".join(lines), file=out)
        rc |= not good
    return rc


if __name__ == "__main__":
    sys.exit(main())
