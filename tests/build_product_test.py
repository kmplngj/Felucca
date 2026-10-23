#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline checks of tools/build.py --product: precedence, validation, output names, no job on bad input.
No toolchain or SDK is needed: every generator, compiler and package step is mocked."""
from pathlib import Path
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as B
import fm1pkg_make


class Stop(Exception):
    pass


class Resolve(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"FELUCCA_PROFILE": "standard"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_release_refuses_diagnostic_builds(self):
        """FELUCCA_CRASH_CTX / FELUCCA_MUL64_REPRO (#425, #428) are development builds only"""
        self.assertEqual(B.DIAG_FLAGS, ("FELUCCA_CRASH_CTX", "FELUCCA_MUL64_REPRO", "FELUCCA_SCREEN_CAPTURE"))
        for flag in B.DIAG_FLAGS:
            with patch.dict(os.environ, {flag: "1"}):
                with self.assertRaises(SystemExit) as raised:
                    B.resolve(["--release", "1.0"])
                self.assertIn(flag, str(raised.exception))
                self.assertEqual(B.resolve([])["name"], "felucca.fwsc")      # a development build is fine
            with patch.dict(os.environ, {flag: "0"}):
                self.assertEqual(B.resolve(["--release", "1.0"])["product"], "FM-1_910")

    def test_default_unchanged(self):
        c = B.resolve([])
        self.assertEqual((c["product"], c["version"], c["name"], c["explicit"]), ("FM-1_900", None, "felucca.fwsc", False))

    def test_release_default_unchanged(self):
        c = B.resolve(["--release", "1.0"])
        self.assertEqual((c["product"], c["version"], c["name"], c["rel"], c["app"]),
                         ("FM-1_910", "v1.0", "felucca-1.0.fwsc", "release-1.0", "felucca-1.0-app.bin"))

    def test_precedence(self):
        self.assertEqual(B.resolve(["--release", "1.2", "--product", "FM-1_ACME"])["product"], "FM-1_ACME")
        self.assertEqual(B.resolve(["--product", "FM-1_ACME"])["product"], "FM-1_ACME")
        self.assertEqual(B.resolve(["--release", "1.2"])["product"], "FM-1_912")

    def test_version_stays_independent(self):
        c = B.resolve(["--release", "1.2-rc1", "--product", "FM-1_ACME"])
        self.assertEqual(c["version"], "v1.2-rc1")

    def test_products_do_not_share_names(self):
        a = B.resolve(["--release", "1.0", "--product", "FM-1_AAA"])
        b = B.resolve(["--release", "1.0", "--product", "FM-1_BBB"])
        d = B.resolve(["--release", "1.0"])
        for key in ("name", "rel", "app"):
            self.assertEqual(len({a[key], b[key], d[key]}), 3, key)
        self.assertNotEqual(B.resolve(["--product", "FM-1_AAA"])["name"], "felucca.fwsc")

    def test_explicit_equal_to_derived_keeps_names(self):
        c = B.resolve(["--release", "1.0", "--product", "FM-1_910"])
        self.assertEqual((c["name"], c["rel"], c["app"]), ("felucca-1.0.fwsc", "release-1.0", "felucca-1.0-app.bin"))
        self.assertEqual(B.resolve(["--product", "FM-1_900"])["name"], "felucca.fwsc")

    def test_release_digits_ascii(self):
        for r in ("\u0661.\u0662", "1.\u0662", "1.0.\u0663"):    # Arabic-Indic digits
            with self.subTest(r=r), self.assertRaises(SystemExit):
                B.resolve(["--release", r])

    def test_default_not_left_from_an_earlier_build(self):
        B.PRODUCT = "FM-1_ACME"             # as main() leaves it after a --product build
        try:
            self.assertEqual(B.resolve([])["product"], "FM-1_900")
        finally:
            B.PRODUCT = B.DEV_PRODUCT

    def test_valid(self):
        for p in ("FM-1_900", "FM-1_ACME", "FM-1_A.B-C_9", "FM-1_" + "X" * 15):
            with self.subTest(p=p):
                B.check_product(p)

    def test_invalid(self):
        bad = ["", "FM-1_", "FM-1_" + "x" * 16, "fm-1_abc", "FM-1_acme", "FM-1_Acme", "FM-2_abc", "ACME", "FM-1_a b", "FM-1_a\"b", "FM-1_a'b",
               "FM-1_a\\b", "FM-1_a\nb", "FM-1_a\tb", "FM-1_a\x00b", "FM-1_ä", "FM-1_a\u200b", " FM-1_abc",
               "FM-1_abc\n", "FM-1_a/b", "FM-1_a;b", "ota-FM-1_900", "ota-FM-1_015",
               "FM-1_015"]       # the stock identity
        for p in bad:
            with self.subTest(p=p), self.assertRaises(SystemExit):
                B.check_product(p)

    def test_marker_limit_matches_package(self):
        for c in map(chr, range(0x21, 0x7F)):       # same rule as fm1pkg_make.ufw
            p = "FM-1_" + c
            try:
                B.check_product(p)
                ok = True
            except SystemExit:
                ok = False
            if ok:
                fm1pkg_make.ufw(b"\0" * 64, b"\0" * 64, p)


class NoJobs(unittest.TestCase):
    """main() with mocked generators and compilers: bad input starts none of them, good input uses one identity."""

    def setUp(self):
        environment = patch.dict(os.environ, {"FELUCCA_PROFILE": "standard"})
        environment.start()
        self.addCleanup(environment.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        gen = Path(self.tmp.name) / "gen"
        gen.mkdir()
        (gen / "build-identity.json").write_text('{}\n')
        (gen / "resolved-profile.json").write_text('{"profile":"standard"}\n')
        self.m = {n: MagicMock(name=n) for n in ("generate", "build_loader", "build_app", "check", "mmio_check",
                                                 "tc_all", "run", "Pool")}
        self.m["build_loader"].return_value = b"ota"
        self.m["build_app"].return_value = (b"img", "", "", "", "")
        self.m["check"].return_value = ([], [])
        self.m["mmio_check"].return_value = []
        for n, new in (("generate", self.m["generate"]), ("build_loader", self.m["build_loader"]),
                       ("build_app", self.m["build_app"]), ("check", self.m["check"]),
                       ("mmio_check", self.m["mmio_check"]), ("ThreadPoolExecutor", self.m["Pool"])):
            p = patch.object(B, n, new)
            p.start()
            self.addCleanup(p.stop)
        import build_report
        self.report_mocks = {}
        for name in ('input_hashes', 'configuration', 'tool_fingerprints'):
            self.report_mocks[name] = MagicMock(return_value={})
            report_patch = patch.object(build_report, name, self.report_mocks[name])
            report_patch.start()
            self.addCleanup(report_patch.stop)
        report_patch = patch.object(build_report, 'write', side_effect=lambda *args:
                                   (out / 'resource-report.json').write_text('{}\n'))
        report_patch.start()
        self.addCleanup(report_patch.stop)
        for p in (patch('profile.contract_json', return_value='{}\n'), patch("build_identity.resolve", return_value={}), patch.object(B, "OUT", out), patch.object(B, "LDR", out / "loader"), patch.object(B, "GEN", gen),
                  patch.object(B.subprocess, "run", self.m["run"]),
                  patch.object(B.fm1pkg_make, "sdk_file", lambda rel: b""),
                  patch.object(B.fm1pkg_make, "flash_image", lambda img, key: img),
                  patch.object(B.fm1pkg_make, "ufw", self.ufw),
                  patch.object(B, "PRODUCT", B.PRODUCT), patch.object(B, "VERSION", None),
                  patch("sys.stdout", io.StringIO())):
            p.start()
            self.addCleanup(p.stop)
        self.out = out
        self.packed = []
        self.m["Pool"].return_value.__enter__.return_value.submit = lambda f: MagicMock(result=f)

    def ufw(self, flash, ota, product):
        self.packed.append(product)
        return b"pkg:" + product.encode()

    def started(self):
        return [n for n, m in self.m.items() if m.called]

    def test_invalid_starts_nothing(self):
        for argv in (["--product", ""], ["--product", "FM-1_a b"], ["--product", "FM-1_" + "x" * 16],
                     ["--product", "FM-1_ä"], ["--product", "FM-1_015"], ["--product", "FM-1_a\"b"],
                     ["--release", "1.0", "--product", "bad"], ["--release", "bad", "--product", "FM-1_ok"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                B.main(argv)
            self.assertEqual(self.started(), [])
            self.assertEqual(list(self.out.iterdir()), [])
            self.assertEqual(self.packed, [])

    def test_unknown_profile_starts_no_jobs(self):
        with patch.dict("os.environ", {"FELUCCA_PROFILE": "unknown-profile"}):
            with self.assertRaises(SystemExit): B.main([])
        self.assertEqual(self.started(), [])
        self.assertEqual(self.packed, [])

    def test_reduced_release_requires_distinct_identity(self):
        with patch.dict("os.environ", {"FELUCCA_PROFILE": "reduced-lofi"}):
            for argv in (["--release", "1.0"], ["--release", "1.0", "--product", "FM-1_910"]):
                with self.assertRaises(SystemExit): B.main(argv)
            self.assertEqual(self.started(), [])
            c = B.resolve(["--release", "1.0", "--product", "FM-1_ACME"])
            self.assertEqual(c['name'], "felucca-1.0-FM-1_ACME-reduced-lofi.fwsc")

    def test_override_packages_one_identity(self):
        with patch.object(B, "build_app", side_effect=lambda: (self.assertEqual(B.PRODUCT, "FM-1_ACME"),
                                                                self.assertEqual(B.VERSION, "v1.0"),
                                                                (b"img", "", "", "", ""))[2]):
            B.main(["--release", "1.0", "--product", "FM-1_ACME"])
        self.assertEqual(self.packed, ["FM-1_ACME"])
        rel = self.out / "release-1.0-FM-1_ACME"
        self.assertEqual((rel / "felucca-1.0-FM-1_ACME.fwsc").read_bytes(), b"pkg:FM-1_ACME")
        self.assertIn("product FM-1_ACME", (rel / "BUILD-INPUTS.txt").read_text())
        self.assertFalse((self.out / "release-1.0").exists())

    def test_default_release_outputs(self):
        B.main(["--release", "1.0"])
        self.assertEqual(self.packed, ["FM-1_910"])
        rel = self.out / "release-1.0"
        self.assertTrue((rel / "felucca-1.0.fwsc").exists())
        self.assertTrue((rel / "felucca-1.0-app.bin").exists())
        self.assertFalse((rel / "BUILD-INPUTS.txt").exists())

    def test_repeated_builds_in_one_process(self):
        B.main(["--product", "FM-1_ACME"])
        B.main([])
        self.assertEqual(self.packed, ["FM-1_ACME", "FM-1_900"])
        self.assertEqual((self.out / "felucca.fwsc").read_bytes(), b"pkg:FM-1_900")

    def test_generation_source_or_tool_change_prevents_compile_and_report(self):
        for changed in ('input_hashes', 'tool_fingerprints'):
            for mock in self.report_mocks.values():
                mock.reset_mock(return_value=True, side_effect=True)
                mock.return_value = {}
            self.m['build_app'].reset_mock()
            current = {}
            self.report_mocks[changed].side_effect = lambda *args, **kwargs: dict(current)
            self.m['generate'].side_effect = lambda: current.update(changed='during generation')
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'asset or loader'):
                B.main([])
            self.m['build_app'].assert_not_called()
            self.assertFalse((self.out / 'resource-report.json').exists())
            self.assertEqual(self.packed, [])

    def test_help_preserves_existing_report_without_starting_jobs(self):
        report = self.out / 'resource-report.json'
        content = b'{"validation":"existing evidence"}\n'
        report.write_bytes(content)
        with self.assertRaises(SystemExit) as raised:
            B.main(['--help'])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(report.read_bytes(), content)
        self.assertEqual(self.started(), [])
        self.assertEqual(self.packed, [])

    def test_failed_attempt_removes_previous_success_report(self):
        report = self.out / 'resource-report.json'
        report.write_text('{"validation":"old success"}\n')
        self.m['check'].return_value = (['target guard failed'], [])
        with self.assertRaisesRegex(SystemExit, 'checks failed'):
            B.main([])
        self.assertFalse(report.exists())
        self.assertEqual(self.packed, [])
        report.write_text('old success')
        with self.assertRaises(SystemExit):
            B.main(['--product', 'bad'])
        self.assertFalse(report.exists())

    def test_default_dev_outputs(self):
        B.main([])
        self.assertEqual(self.packed, ["FM-1_900"])
        self.assertTrue((self.out / "felucca.fwsc").exists())


class TargetDefine(unittest.TestCase):
    def test_felucca_id_define(self):
        for product, want in ((None, "FM-1_900"), ("FM-1_ACME", "FM-1_ACME")):
            with tempfile.TemporaryDirectory() as folder, self.subTest(product=product):
                out = Path(folder) / "isolated"
                out.mkdir()
                shared = Path(folder) / "shared"
                shared.mkdir()
                sentinel = shared / "fm1_cpu1.o"
                sentinel.write_bytes(b"another build owns this object")
                isolated_object = out / "fm1_cpu1.o"
                isolated_object.write_bytes(b"stale isolated object")
                with patch.object(B, "OUT", out), patch.object(B, "PRODUCT", B.PRODUCT), \
                        patch.object(B, "VERSION", None), patch.object(B, "tc_all", side_effect=Stop) as tc:
                    c = B.resolve(["--product", product] if product else [])
                    B.PRODUCT = c["product"]
                    with self.assertRaises(Stop):
                        B.build_app()
                    cmds = tc.call_args.args
                    self.assertTrue(any(f'-DFELUCCA_ID="{want}"' in cmd for cmd in cmds))
                self.assertFalse(isolated_object.exists())
                self.assertEqual(sentinel.read_bytes(), b"another build owns this object")


if __name__ == "__main__":
    unittest.main()
