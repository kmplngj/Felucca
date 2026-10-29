#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded native-probe contracts and console output; no physical timing evidence."""
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fm1_chip_probes as client


class ChipProbesTest(unittest.TestCase):
    def test_run_guards_bounds_wrap_and_reference(self):
        with tempfile.TemporaryDirectory(prefix="chip-probes-") as directory:
            binary = Path(directory) / "probe"
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c99", "-O1", "-Wall", "-Wextra",
                            "-Wno-unused-function", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                            "tests/chip_probes_test.c", "-o", str(binary)], cwd=ROOT, check=True)
            result = subprocess.check_output([str(binary)], cwd=ROOT, timeout=10).decode()
        mask = 0xFFFFFFFF
        a = 12345
        for i in range(256):
            a = (((a + i) & mask) * 679 & mask) // 679 ^ 0xA5A5A5A5
        expected = [0, 256, a]
        for stride in (1, 8, 32):
            expected.append(sum(((i * stride % 256) * 0x9E3779B9 + 0x01234567) & mask
                                for i in range(256)) & mask)
        expected += expected[3:]
        lines = result.splitlines()
        self.assertEqual(len(lines), 18)
        for i, line in enumerate(lines):
            index, checksum = line.split()
            self.assertEqual(int(index), i)
            self.assertEqual(int(checksum, 16), expected[i // 2])

    def test_console_enabled_disabled_and_strict_arguments(self):
        with tempfile.TemporaryDirectory(prefix="chip-probe-console-") as directory:
            for enabled in (0, 1):
                binary = Path(directory) / f"console-{enabled}"
                subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c99", "-O1", "-Wall", "-Wextra",
                                "-Wno-unused-function", "-Wno-unused-variable", f"-DFELUCCA_CHIP_PROBES={enabled}",
                                "tests/chip_probes_console_test.c", "-o", str(binary)], cwd=ROOT, check=True)
                def command(text, *args):
                    return subprocess.check_output([str(binary), text, *args], timeout=5).decode().replace("\r", "")
                if not enabled:
                    self.assertNotIn("PROBE", command("probe caps"))
                    self.assertNotIn("PROBE", command("probe run"))
                    continue
                caps = command("probe caps")
                self.assertIn("version=1 reps=256 passes=2 kinds=9 footprint=1024", caps)
                self.assertIn("irq=enabled clock=unavailable commit=unknown", caps)
                output = command("probe run")
                self.assertEqual(output.count("PROBE SAMPLE"), 18)
                self.assertTrue(output.endswith("PROBE END complete\n> "))
                for kind in range(9):
                    for sample_pass in range(2):
                        self.assertIn(f"kind={kind} pass={sample_pass} ticks=00000000 checksum=00000000 reference=00000000", output)
                for text in ("probe", "probe run 0", "probe run 4294967296", "probe run x", "probe caps extra", "probe runner"):
                    self.assertIn("PROBE ERROR argument", command(text))
                for rc in range(1, 5):
                    output = command("probe run", str(rc))
                    self.assertIn(f"PROBE ERROR {rc}", output)
                    self.assertNotIn("PROBE SAMPLE", output)
                    self.assertNotIn("PROBE END", output)
                    if rc == 4:
                        self.assertIn("samples=5 last_ticks=00000000 checksum=00000000 reference=00000000", output)


class ProbeClientTest(unittest.TestCase):
    def lines(self):
        # Independent fixed checksum fixture; validated against Python reference above.
        sums = [0, 256, 0xA5974C62, 0xC4650A80, 0x023B0300, 0x68865700,
                0xC4650A80, 0x023B0300, 0x68865700]
        return ["PROBE BEGIN version=1"] + [
            f"PROBE SAMPLE kind={kind} pass={sample_pass} ticks=00000012 checksum={value:08X} reference={value:08X}"
            for kind, value in enumerate(sums) for sample_pass in range(2)] + ["PROBE END complete"]

    def test_semantics_and_complete_order(self):
        lines = self.lines()
        self.assertEqual(len(client.parse_samples(lines)), 18)
        for bad in (lines[:-1], lines[1:], lines[:3] + lines[2:],
                    [line.replace("A5974C62", "A5974C63") for line in lines],
                    [line.replace("pass=1", "pass=0") for line in lines],
                    ["PROBE ERROR 2"]):
            with self.assertRaises(ValueError):
                client.parse_samples(bad)

    def test_transport_bounds_and_echo(self):
        class Transport:
            def __init__(self, data): self.data, self.writes = list(data), []
            def read(self, timeout): return self.data.pop(0)
            def write(self, data, timeout): self.writes.append(data)
        reply = b"probe caps\r\nPROBE CAPS test\r\n> "
        raw = io.BytesIO()
        transport = Transport([bytes([b]) for b in reply])
        console = client.Console(transport, raw)
        self.assertEqual(console.request("probe caps"), ["PROBE CAPS test"])
        self.assertEqual(raw.getvalue(), reply)
        self.assertEqual(transport.writes, [b"probe caps\r"])
        with self.assertRaises(ValueError): console.request("status")
        self.assertEqual(len(transport.writes), 1)
        for bad in (b"probe run\r\nPROBE CAPS test\r\n> ", b"\xFF\r\n> ", b"x" * 8193):
            raw = io.BytesIO()
            with self.assertRaises(ValueError): client.Console(Transport([bad]), raw).request("probe caps")
            self.assertEqual(raw.getvalue(), bad)
        times = iter((0, 3))
        with self.assertRaises(TimeoutError):
            client.Console(Transport([]), io.BytesIO(), clock=lambda: next(times)).request("probe run")

    def test_capture_preserves_partial_failure_and_restore_error(self):
        root_build = ROOT / "build"
        root_build.mkdir(exist_ok=True)
        commit = "a" * 40
        caps = f"PROBE CAPS version=1 reps=256 passes=2 kinds=9 footprint=1024 limit_ticks=2400000 irq=enabled clock=unavailable commit={commit}"
        class Transport:
            def __init__(self, fail=False, restore=False):
                self.fail, self.restore, self.writes, self.closed = fail, restore, [], False
                self.data = [b"\r\nFelucca fixture console - 'help'\r\n> "]
            def write(inner, data, timeout):
                inner.writes.append(data)
                if data == b"probe caps\r": inner.data += [("probe caps\r\n" + caps + "\r\n> ").encode()]
                else: inner.data += [b"probe run\r\npartial" if inner.fail else
                                     ("probe run\r\n" + "\r\n".join(self.lines()) + "\r\n> ").encode()]
            def read(self, timeout):
                if not self.data: raise OSError("disconnect")
                return self.data.pop(0)
            def close(self):
                self.closed = True
                return "restore failed" if self.restore else None
        with tempfile.TemporaryDirectory(prefix="probe-client-", dir=root_build) as temp:
            base = Path(temp)
            manifest = base / "manifest.json"; manifest.write_text("{}")
            for fail, restore in ((False, False), (True, False), (False, True)):
                transport = Transport(fail, restore)
                output = base / f"capture-{fail}-{restore}"
                result = client.main(["--port", "fixture", "--firmware-revision", commit,
                                      "--manifest", str(manifest), "--runs", "1", "--output", str(output)],
                                     transport_factory=lambda port: transport)
                summary = json.loads((output / "summary.json").read_text())
                self.assertEqual(result, int(fail or restore))
                self.assertEqual(summary["complete"], not (fail or restore))
                self.assertTrue(transport.closed)
                self.assertEqual(transport.writes, [b"probe caps\r", b"probe run\r"])
                if fail: self.assertTrue((output / "console.raw").read_bytes().endswith(b"partial"))


if __name__ == "__main__":
    unittest.main()
