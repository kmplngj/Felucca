#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run a compiled emulator_nor_test.c against its actual storage adapter.

Example after asset generation:
  cc -O2 -ffp-contract=off -w -Ibuild/gen -Ifirmware/src \
    tests/emulator_nor_test.c -lm -o build/host/emulator_nor
  python3 tests/emulator_nor_test.py build/host/emulator_nor
"""
import argparse
from pathlib import Path
import struct
import subprocess
import unittest

NOR_BYTES = 0x100000
SNAPSHOT_BYTES = NOR_BYTES + 8 * 4 + 240 * 240 * 2 + 256 * 4


class EmulatorNorTests(unittest.TestCase):
    def run_case(self, mode=None, data=None):
        return subprocess.run([str(BINARY), *([mode] if mode else [])], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def snapshot(self, result):
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(len(result.stdout), SNAPSHOT_BYTES)
        nor = result.stdout[:NOR_BYTES]
        state = struct.unpack_from("=8I", result.stdout, NOR_BYTES)
        pcm = struct.unpack_from("=256f", result.stdout, SNAPSHOT_BYTES - 256 * 4)
        self.assertTrue(any(abs(value) > 0 for value in pcm), "saved sound must render audible samples")
        return nor, state

    def test_bounds_rounding_and_counts(self):
        result = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"bounds, rounding, AND, zero-length and write counts passed", result.stdout)

    def test_shared_page_guard(self):
        result = self.run_case("page-wrap")
        self.assertEqual(result.returncode, 1, result.stderr.decode(errors="replace"))
        self.assertIn(b"page wrap at 0xff", result.stdout)
        self.assertNotIn(b"page-spanning write was accepted", result.stderr)

    def test_panel_save_and_fresh_instance_restore(self):
        saved, state = self.snapshot(self.run_case("save"))
        self.assertGreater(state[0], 0, "panel save must actually write NOR")
        self.assertEqual(state[4], 1, "panel save must populate the selected user preset")
        restored, next_state = self.snapshot(self.run_case("load", saved))
        self.assertEqual(restored, saved, "fresh boot/load must preserve every saved NOR byte")
        self.assertEqual(next_state[0], 0, "restore/load must not rewrite saved flash")
        self.assertEqual(next_state[4:6], state[4:6], "saved preset and engine must return")

    def test_factory_restore_control(self):
        # A process with no saved bank must reject the restore assertion. This
        # distinguishes a real persisted preset from unconditional occupancy.
        result = self.run_case("load", bytes([0xFF]) * NOR_BYTES)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"web_test_user_preset(0)", result.stderr)


class WasmNorTests(unittest.TestCase):
    def test_actual_wasm_guard_without_host_imports(self):
        script = """
import fs from 'node:fs';
import assert from 'node:assert/strict';
const mod = new WebAssembly.Module(fs.readFileSync(process.argv[1]));
assert.deepEqual(WebAssembly.Module.imports(mod), []);
const ex = new WebAssembly.Instance(mod, {}).exports;
ex._initialize();
ex.web_nor_erase();
let nor = new Uint8Array(ex.memory.buffer, ex.web_nor(), ex.web_nor_size());
assert.equal(ex.emulator_nor_program(0xfe, 2), 0);
assert.equal(nor[0xfe], 0x35);
assert.equal(nor[0xff], 0x69);
assert.equal(nor[0x100], 0xff);
assert.equal(ex.web_flash_writes_count(), 1);
ex.web_nor_erase();
assert.throws(() => ex.emulator_nor_program(0xff, 2), WebAssembly.RuntimeError);
assert.equal(nor[0xff], 0xff);
assert.equal(nor[0x100], 0xff);
assert.equal(ex.web_flash_writes_count(), 1);
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(WASM)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromTestCase(EmulatorNorTests)
    if WASM is not None:
        suite.addTests(loader.loadTestsFromTestCase(WasmNorTests))
    return suite


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="compiled tests/emulator_nor_test.c")
    parser.add_argument("--wasm", type=Path, help="same fixture compiled as standalone test Wasm")
    args = parser.parse_args()
    BINARY = args.binary.resolve()
    WASM = args.wasm.resolve() if args.wasm else None
    unittest.main(argv=[__file__])
