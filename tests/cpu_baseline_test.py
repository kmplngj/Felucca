#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compiler/host separation and compatibility fixtures for CPU baselines."""
import unittest
from cpu_baseline import baseline_paths


GCC = {"__GNUC__": "13", "__GNUC_MINOR__": "3", "__GNUC_PATCHLEVEL__": "0",
       "__VERSION__": '"13.3.0"'}
CLANG = {"__clang__": "1", "__clang_major__": "17", "__clang_minor__": "0",
         "__clang_patchlevel__": "6", "__clang_version__": '"17.0.6 (vendor build)"', **GCC}


class Baselines(unittest.TestCase):
    def test_compilers_versions_and_vendor_builds_are_separate(self):
        compilers = [GCC, CLANG, {**GCC, "__GNUC__": "14", "__VERSION__": '"14.1.0"'},
                     {**GCC, "__VERSION__": '"13.3.0 (another vendor)"'}]
        paths = [baseline_paths("Linux", "x86_64", c) for c in compilers]
        self.assertEqual(len(set(paths)), len(compilers))
        for normal, size in paths:
            self.assertTrue(normal.startswith("tests/cpu_baseline_linux_x86_64_"))
            self.assertEqual(size, normal[:-4] + "_os.txt")

    def test_host_separation_and_alias_stability(self):
        self.assertEqual(baseline_paths("Linux", "x86_64", GCC),
                         baseline_paths("Linux", "x86_64", dict(GCC)))
        self.assertNotEqual(baseline_paths("Linux", "x86_64", GCC),
                            baseline_paths("Linux", "aarch64", GCC))
        self.assertNotEqual(baseline_paths("Linux", "x86_64", GCC),
                            baseline_paths("FreeBSD", "x86_64", GCC))

    def test_legacy_mac_only_for_apple_clang(self):
        apple = {**CLANG, "__apple_build_version__": "21000334"}
        self.assertEqual(baseline_paths("Darwin", "arm64", apple),
                         ("tests/cpu_baseline.txt", "tests/cpu_baseline_os.txt"))
        for compiler in (GCC, CLANG):
            self.assertNotEqual(baseline_paths("Darwin", "arm64", compiler)[0],
                                "tests/cpu_baseline.txt")

    def test_unknown_compiler_fails_explicitly(self):
        with self.assertRaises(ValueError):
            baseline_paths("Linux", "x86_64", {})


if __name__ == "__main__":
    unittest.main()
