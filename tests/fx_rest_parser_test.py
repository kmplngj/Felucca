#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Keep incomplete FX render coverage from qualifying as mutation detection."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import fx_rest_test as fx


class CompareTest(unittest.TestCase):
    def setUp(self):
        ids = sorted({f"{model}/boundary/{sign}" for model in range(3) for sign in (-1, 1)} |
                     {f"0/fixed/{lp}/{fb}/{color}"
                      for lp in (-1, 1) for fb in (0, 127) for color in (0, 127)})
        self.normal = [[i, "0123456789abcdef", "fedcba9876543210", "1", "1", "1", "1", "0"]
                       for i in ids]
        self.forced = [row[:3] + ["0"] * 5 for row in self.normal]

    def compare(self):
        results = [subprocess.CompletedProcess([], 0, "\n".join(" ".join(row) for row in rows), "")
                   for rows in (self.normal, self.forced)]
        with patch.object(fx.subprocess, "run", side_effect=results):
            return fx.compare(Path("unused"), True, 1, boundary=True)

    def test_complete_coverage(self):
        self.assertEqual(self.compare(), [14] * 4)

    def test_mismatch_with_complete_coverage(self):
        for field in (1, 2, 7):
            with self.subTest(field=field):
                self.setUp()
                self.normal[0][field] = "1" if field == 7 else "0" * 16
                with self.assertRaises(fx.EquivalenceMismatch):
                    self.compare()

    def test_missing_skip_coverage(self):
        # Require every bus for which the selected model has a rest path.
        for model, bus in ((0, 0), (0, 1), (1, 3), (2, 2)):
            for mismatch in (None, 1, 2, 7):
                with self.subTest(model=model, bus=bus, mismatch=mismatch):
                    self.setUp()
                    row = next(row for row in self.normal if row[0].startswith(f"{model}/"))
                    row[3 + bus] = "0"
                    if mismatch is not None:
                        self.normal[-1][mismatch] = "1" if mismatch == 7 else "0" * 16
                    with self.assertRaises(ValueError) as caught:
                        self.compare()
                    self.assertNotIsInstance(caught.exception, fx.EquivalenceMismatch)
                    self.assertIn(f"bus {bus} never skipped", str(caught.exception))

    def test_forced_skip_coverage(self):
        for mismatch in (None, 1, 2, 7):
            with self.subTest(mismatch=mismatch):
                self.setUp()
                self.forced[0][3] = "1"
                if mismatch is not None:
                    self.normal[-1][mismatch] = "1" if mismatch == 7 else "0" * 16
                with self.assertRaises(ValueError) as caught:
                    self.compare()
                self.assertNotIsInstance(caught.exception, fx.EquivalenceMismatch)
                self.assertIn("forced-off path still skips", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
