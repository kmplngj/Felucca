#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline update-record survey contracts, with synthetic bytes only.

Run: python3 tests/update_records_test.py
"""
import binascii
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fm1_update_records as U  # noqa: E402


def record(marker=0x5441):
    """Independent bitwise-library CRC oracle; arbitrary fields need no magic/name."""
    raw = bytearray((i * 37 + 11) % 256 for i in range(80))
    struct.pack_into("<H", raw, 6, marker)
    struct.pack_into("<H", raw, 0, binascii.crc_hqx(raw[2:], 0))
    return raw


def image(*sectors, size=U.MAX_RAW, rec=None):
    raw = bytearray(b"\xff" * size)
    for sector in sectors:
        at = sector + 0xF00
        raw[at:at + 80] = record() if rec is None else rec
    return raw


class SurveyTest(unittest.TestCase):
    def test_crc_oracle_and_native_fixture_context(self):
        self.assertEqual(U.I.crc16(b"123456789"), 0x31C3)
        self.assertEqual(binascii.crc_hqx(b"123456789", 0), 0x31C3)
        # Native record fields used by tests/update_record_fixture.h, not vendor data.
        native = bytearray(112)
        native[:8] = bytes.fromhex("1d b7 0d 5a 01 5a 41 54")
        native[8:19] = b"ota-FM-1_015"
        struct.pack_into("<I", native, 72, 0xE0000)
        self.assertEqual(binascii.crc_hqx(native[2:80], 0), 0xB71D)
        raw = image(0x9F000, rec=native[:80])
        raw[0x9FF50:0x9FF70] = native[80:112]
        found = U.survey(raw)["candidates"][0]
        self.assertEqual(found["crc16"], 0xB71D)
        self.assertEqual(found["word_at_2"], 0x5A0D)
        self.assertEqual(found["word_at_4"], 0x5A01)
        self.assertEqual(found["address_at_72"], 0xE0000)
        self.assertEqual(found["name_bytes_8_19_hex"], native[8:20].hex())

    def test_all_sectors_including_protected_and_bounds(self):
        # Survey coverage is deliberately independent of loader cleanup exclusions.
        sectors = (0, 0x93000, 0x97000, 0x9F000, 0xE4000, 0xE5000, 0xE7000, 0xFE000, 0xFF000)
        raw = image(*sectors)
        result = U.survey(raw)
        self.assertEqual([r["sector_offset"] for r in result["candidates"]], list(sectors))
        self.assertEqual(result["candidate_count"], len(sectors))
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["coverage"], {"start": 0, "end_exclusive": U.MAX_RAW,
                         "bytes": U.MAX_RAW, "sector_bytes": 4096, "complete_sectors": 256, "not_supplied": []})
        for found in result["candidates"]:
            self.assertEqual(found["record_80_bytes_hex"], record().hex())
            self.assertEqual(found["record_offset"], found["sector_offset"] + 0xF00)

    def test_exact_predicate_and_alignment(self):
        raw = image(0, size=0x5000)
        # A match at a non-sector offset must not be reported.
        raw[0x1F01:0x1F51] = record()
        # Independently valid CRC, wrong marker.
        raw[0x2F00:0x2F50] = record(marker=0x5440)
        # Changed covered byte, original stored CRC.
        damaged = record()
        damaged[79] ^= 1
        raw[0x3F00:0x3F50] = damaged
        # CRC matches zero but the native loader explicitly rejects it.
        zero = bytearray(80)
        struct.pack_into("<H", zero, 6, 0x5441)
        for suffix in range(65536):
            struct.pack_into("<H", zero, 78, suffix)
            if binascii.crc_hqx(zero[2:], 0) == 0:
                break
        self.assertEqual(binascii.crc_hqx(zero[2:], 0), 0)
        raw[0x4F00:0x4F50] = zero
        self.assertEqual([r["sector_offset"] for r in U.survey(raw)["candidates"]], [0])
        # Bytes beyond the 80-byte predicate have no effect.
        raw[0xF50:0x1000] = bytes(range(176))
        self.assertEqual(U.survey(raw)["candidate_count"], 1)

    def test_partial_coverage_and_no_matches(self):
        result = U.survey(bytes(4096))
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["coverage"]["not_supplied"], [{"start": 4096, "end_exclusive": U.MAX_RAW}])
        self.assertTrue(any("No matches do not prove SPL safety" in text for text in result["limitations"]))
        self.assertTrue(any("without decryption" in text for text in result["limitations"]))
        for size in (0, 80, 4095, 4097, U.MAX_RAW + 1, U.MAX_RAW + 4096):
            with self.subTest(size=size), self.assertRaises(ValueError):
                U.survey(bytes(size))

    def test_cli_deterministic_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.bin"
            raw = image(0, size=4096)
            path.write_bytes(raw)
            before = path.stat()
            outputs = []
            for _ in range(2):
                out, err = io.StringIO(), io.StringIO()
                self.assertEqual(U.main(["--raw", str(path)], out=out, err=err), 0)
                self.assertEqual(err.getvalue(), "")
                outputs.append(out.getvalue())
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(json.loads(outputs[0])["candidate_count"], 1)
            self.assertNotIn(str(path), outputs[0])
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            path.write_bytes(bytes(4096))
            self.assertEqual(U.main(["--raw", str(path)], out=io.StringIO()), 0)

    def test_cli_rejects_bad_files_and_special_files_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "empty").touch()
            (base / "partial").write_bytes(bytes(4097))
            with (base / "oversized").open("wb") as source:
                source.truncate(U.MAX_RAW + 1)
            (base / "symlink").symlink_to(base / "partial")
            os.mkfifo(base / "fifo")
            for name in ("missing", "empty", "partial", "oversized", "symlink", "fifo", "."):
                with self.subTest(name=name):
                    proc = subprocess.run([sys.executable, str(ROOT / "tools/fm1_update_records.py"),
                                           "--raw", str(base / name)], capture_output=True, timeout=5)
                    self.assertEqual(proc.returncode, 2)
                    self.assertEqual(proc.stdout, b"")
                    self.assertIn(b"error:", proc.stderr)
            for args in ([], [str(base / "partial")], ["--package", str(base / "partial")]):
                proc = subprocess.run([sys.executable, str(ROOT / "tools/fm1_update_records.py"), *args],
                                      capture_output=True, timeout=5)
                self.assertEqual(proc.returncode, 2)

    def test_file_growth_during_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "growing"
            path.write_bytes(bytes(4096))
            original_fstat = os.fstat
            calls = 0

            def grow_after_stat(fd):
                nonlocal calls
                result = original_fstat(fd)
                calls += 1
                if calls == 1:
                    with path.open("ab") as target:
                        target.write(bytes(4096))
                return result

            with patch.object(U.os, "fstat", side_effect=grow_after_stat):
                with self.assertRaisesRegex(ValueError, "input changed during read"):
                    U.read_raw(path)

    def test_replaced_file_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, replacement = Path(tmp) / "old", Path(tmp) / "replacement"
            old.write_bytes(bytes(4096))
            replacement.write_bytes(bytes(4096))
            original_open = os.open

            def replace_then_open(path, flags):
                replacement.replace(old)
                return original_open(path, flags)

            with patch.object(U.os, "open", side_effect=replace_then_open):
                with self.assertRaisesRegex(ValueError, "input changed"):
                    U.read_raw(old)


if __name__ == "__main__":
    unittest.main()
