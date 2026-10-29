#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Survey native-loader record-shaped bytes in a saved raw FM-1 flash file.

Usage: python3 tools/fm1_update_records.py --raw FILE

--raw asserts that FILE starts at flash address zero. Only regular files with
complete 4 KiB sectors, from 4 KiB to 1 MiB, are accepted. No devices, packages,
decryption, network access or writes. Output is deterministic JSON. Exit 0 means
the survey completed, including when no matches were observed; exit 2 means an
input/argument error. See docs/update-record-survey.md for interpretation limits.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fm1_install as I  # noqa: E402; pure format helpers, no MIDI initialization

SECTOR = 0x1000
RECORD_OFFSET, RECORD_SIZE = 0xF00, 80
MAX_RAW = I.FL_MAX
LIMITATIONS = [
    "Matches describe only the native loader's nonzero CRC16 and marker predicate; "
    "the external SPL's bounds, required fields, selection and failure behavior remain unknown.",
    "No matches do not prove SPL safety, including outside the supplied byte coverage.",
    "Bytes are inspected as supplied, without decryption or logical-image conversion; "
    "raw flash bytes and ciphered/logical views may differ.",
    "CRC and marker matches are observations, not authentication, bootability or installation permission.",
]


def read_raw(path):
    """Read a bounded saved regular file; reject symlinks and FIFOs before opening."""
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("expected a regular saved file (no symlinks or special files)")
    # NONBLOCK also prevents a replacement FIFO from blocking between lstat/open.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        current = os.fstat(source.fileno())
        if not stat.S_ISREG(current.st_mode) or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("input changed or is not a regular saved file")
        if current.st_size > MAX_RAW:
            raise ValueError(f"saved file exceeds {MAX_RAW} B limit")
        raw = source.read(MAX_RAW + 1)
        if len(raw) > MAX_RAW:
            raise ValueError(f"saved file exceeds {MAX_RAW} B limit")
        after = os.fstat(source.fileno())
        if len(raw) != current.st_size or (current.st_size, current.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("input changed during read")
    return raw


def survey(raw):
    """Inspect each sector tail; this is a byte predicate, not the cleanup scan policy."""
    size = len(raw)
    if not SECTOR <= size <= MAX_RAW:
        raise ValueError(f"raw input must contain {SECTOR}..{MAX_RAW} B starting at address zero")
    if size % SECTOR:
        raise ValueError("raw input ends in a partial 4096 B sector; supply complete sectors from address zero")
    candidates = []
    for sector in range(0, size, SECTOR):
        offset = sector + RECORD_OFFSET
        record = raw[offset:offset + RECORD_SIZE]
        stored = I.u16(record, 0)
        if stored and I.u16(record, 6) == 0x5441 and stored == I.crc16(record[2:80]):
            candidates.append({
                "sector_offset": sector,
                "record_offset": offset,
                "crc16": stored,
                "word_at_2": I.u16(record, 2),
                "word_at_4": I.u16(record, 4),
                "marker_at_6": I.u16(record, 6),
                "name_bytes_8_19_hex": record[8:20].hex(),
                "address_at_72": I.u32(record, 72),
                "record_80_bytes_hex": record.hex(),
            })
    return {
        "schema": "felucca-update-record-survey-v1",
        "interpretation": "supplied raw bytes, asserted flash start address zero",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "coverage": {"start": 0, "end_exclusive": size, "bytes": size,
                     "sector_bytes": SECTOR, "complete_sectors": size // SECTOR,
                     "not_supplied": ([{"start": size, "end_exclusive": MAX_RAW}] if size < MAX_RAW else [])},
        "predicate": "u16le(+0) != 0 and u16le(+0) == CRC16-XMODEM(bytes[2:80], init=0) "
                     "and u16le(+6) == 0x5441, at each sector + 0xF00",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "limitations": LIMITATIONS,
    }


def main(argv=None, out=None, err=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, metavar="FILE",
                        help="saved raw bytes from flash address zero (required assertion; no format detection)")
    args = parser.parse_args(argv)
    try:
        result = survey(read_raw(args.raw))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr if err is None else err)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True), file=sys.stdout if out is None else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
