#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable positive/negative fixtures for the production firmware build guards."""
from pathlib import Path
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as B


def symbols(values):
    return "".join(f"{v:08x} g .bss 00000000 {name}\n" for name, v in values.items())


NOINIT_ORG, NOINIT_LEN = 0x01C7C000, 0x3D50     # as firmware/app.ld


def noinit_symbols(used):
    """`objdump -t` rows of a .noinit holding two objects that end `used` B into the region"""
    return (f"{NOINIT_ORG:08x} l    d  .noinit\t\t 00000000 .noinit\n"
            f"{NOINIT_ORG:08x} g       .noinit\t\t 00000040 first\n"
            f"{NOINIT_ORG + 0x40:08x} l       .noinit\t\t {used - 0x40:08x} last\n")


def noinit_header(extent):
    """`objdump -h` rows of the app ELF with a .noinit section that spans `extent` B of its region"""
    return ("Sections:\nIdx Name          Size      VMA       LMA       File off  Algn\n"
            "  0 .text         00001000  02000120  02000120  00000100  2**2\n"
            "                  CONTENTS, ALLOC, LOAD, READONLY, CODE\n"
            f"  5 .noinit       {extent:08x}  {NOINIT_ORG:08x}  {NOINIT_ORG:08x}  00040000  2**2\n"
            "                  ALLOC\n")


class RestartOptions(unittest.TestCase):
    def preprocess(self, *options):
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("C preprocessor unavailable")
        source = (ROOT / "firmware/src/felucca.c").read_text().split("#include <stdint.h>", 1)[0]
        return subprocess.run([compiler, "-E", "-P", "-x", "c", *options, "-"],
                              input=source + "FELUCCA_RESTART\n", capture_output=True, text=True)

    def test_restart_follows_ota_and_preserves_explicit_disable(self):
        for options, expected in (((), "1"), (("-DFELUCCA_OTA=0",), "0"),
                                  (("-DFELUCCA_RESTART=0",), "0")):
            with self.subTest(options=options):
                result = self.preprocess(*options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_restart_without_editor_transport_is_rejected(self):
        result = self.preprocess("-DFELUCCA_OTA=0", "-DFELUCCA_RESTART=1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FELUCCA_RESTART needs FELUCCA_OTA", result.stderr)


class AppGuards(unittest.TestCase):
    def setUp(self):
        cpu_patch = patch.object(B, "CPU2", False)
        cpu_patch.start()
        self.addCleanup(cpu_patch.stop)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        self.addCleanup(self.tmp.cleanup)
        fw = Path(self.tmp.name)
        (fw / "app.ld").write_text("""MEMORY {
 RAM (rwx) : ORIGIN = 0x01C08000, LENGTH = 72K
 POOL (rw) : ORIGIN = 0x01C1A000, LENGTH = 0x5A000
 NOINIT (rw) : ORIGIN = 0x01C7C000, LENGTH = 0x3D50
}
""")
        self.patch = patch.object(B, "FW", fw)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.values = {"_start": 0x02000120, "_bss_end": 0x01C08000 + 256,
                       "_pool_start": 0x01C1A000, "_pool_end": 0x01C1A000 + 256}
        self.noinit_used = 15564       # the real build's .noinit: 132 B spare
        self.img = bytes.fromhex("04818000") + bytes(12)
        self.dis = " 2000120: 00 00 \tr0 = 0\n"
        self.rt = " 1c00000: 00 00 \tret\n"

    def check(self, **kw):
        return self.run_check(**kw)[0]

    def run_check(self, **kw):
        return B.check(kw.get("img", self.img), kw.get("hdr", noinit_header(self.noinit_used)),
                       kw.get("syms", symbols(self.values) + noinit_symbols(self.noinit_used)),
                       kw.get("dis", self.dis), kw.get("rt", self.rt))

    def test_valid_neighbors(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check(rt="file format ELF32-pi32v2\n"), [])  # explicitly empty RAM section

    def test_soft_double_arithmetic_comparison_and_conversion_exports(self):
        names = ("__adddf3 __subdf3 __muldf3 __divdf3 __negdf2 __powidf2 "
                 "__eqdf2 __nedf2 __gedf2 __gtdf2 __ledf2 __ltdf2 __unorddf2 "
                 "__extendsfdf2 __truncdfsf2 __truncdfhf2 "
                 "__fixdfsi __fixdfdi __fixunsdfsi __fixunsdfdi "
                 "__floatsidf __floatdidf __floatunsidf __floatundidf __muldc3 __divdc3").split()
        for name in names:
            with self.subTest(name=name):
                errors, notes = self.run_check(syms=symbols(self.values) + noinit_symbols(self.noinit_used) +
                                               f"02000200 g     F .text\t00000040 {name}\n")
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("soft-double helpers defined in final executable sections: " + name + ";", errors[0])
                self.assertNotIn("no known soft-double", " ".join(notes))

    def test_soft_double_defined_local_weak_alias_and_section_variants(self):
        for section in (".text", ".ram_text", ".c1_text", ".custom_exec"):
            hdr = noinit_header(self.noinit_used)
            if section != ".text":
                hdr += f" 6 {section} 00000040 01c00000 02001120 00001100 2**2\n  CONTENTS, ALLOC, LOAD, CODE\n"
            for flags in ("g     F", "l     F", " w    F", "g", "", "g\tF", "g     O"):
                for size in ("00000000", "00000040"):
                    with self.subTest(section=section, flags=flags, size=size):
                        syms = symbols(self.values) + noinit_symbols(self.noinit_used)
                        syms += f"  01C00000\t{flags}  {section}\t {size} __floatundidf\n"
                        self.assertIn("__floatundidf;", " ".join(self.check(hdr=hdr, syms=syms)))

    def test_soft_double_exact_names_and_unrelated_helpers_pass(self):
        names = ("__muldi3 __divdi3 __udivdi3 __umoddi3 __ashldi3 __ashrdi3 __lshrdi3 "
                 "__cmpdi2 __ucmpdi2 __addsf3 __divsf3 __fixsfdi __floatdisf "
                 "double_buffer double __adddf3_extra prefix__adddf3 __ADDDF3").split()
        syms = symbols(self.values) + noinit_symbols(self.noinit_used)
        syms += "".join(f"02000200 g F .text 00000040 {name}\n" for name in names)
        errors, notes = self.run_check(syms=syms)
        self.assertEqual(errors, [])
        self.assertIn("no known soft-double helpers defined in final executable sections", notes)

    def test_soft_double_nondefinitions_and_nonexecutable_records_pass(self):
        hdr = noinit_header(self.noinit_used)
        hdr += (" 6 .debug_info 00000040 00000000 00000000 00001100 2**0\n  CONTENTS, READONLY, DEBUGGING\n"
                " 7 .data 00000040 01c08000 02001120 00001200 2**2\n  CONTENTS, ALLOC, LOAD, DATA\n"
                " 8 .nonalloc 00000040 00000000 00000000 00001300 2**2\n  CONTENTS, CODE\n")
        for flags, section in (("", "*UND*"), ("g", "*ABS*"), ("", "*COM*"),
                               ("g F", ".debug_info"), ("g O", ".data"), ("g F", ".nonalloc"),
                               ("l d", ".text"), ("l df", "*ABS*"), ("l f", ".text")):
            with self.subTest(flags=flags, section=section):
                syms = symbols(self.values) + noinit_symbols(self.noinit_used)
                syms += f"00000000 {flags} {section} 00000000 __adddf3\n"
                self.assertEqual(self.check(hdr=hdr, syms=syms), [])
        # Discarded input/source and debug strings never enter the final symbol rows.
        self.assertEqual(self.check(dis=self.dis + " 2000122: 00 00 \tr0 = 0 <double_buffer>\n"), [])

    def test_soft_double_diagnostic_is_sorted_deduplicated_and_aggregated(self):
        syms = symbols(self.values) + noinit_symbols(self.noinit_used)
        for name in ("__truncdfsf2", "__adddf3", "__truncdfsf2"):
            syms += f"02000200 g F .text 00000040 {name}\n"
        self.noinit_used = NOINIT_LEN - 99
        errors = self.check(syms=syms, img=bytes(4), rt=" 1c00000: 00 00 \tcall r0\n")
        self.assertIn("__adddf3, __truncdfsf2;", errors[0])
        self.assertEqual(sum("soft-double" in e for e in errors), 1)
        for message in ("not the entry stub", ".ram_text contains calls", "NOINIT headroom 99 B"):
            self.assertIn(message, " ".join(errors))

    def test_soft_double_matching_malformed_rows_or_sections_fail_closed(self):
        for row in ("garbage g F .text 00000040 __adddf3", "02000200 g F .text invalid __adddf3",
                    "02000200 badflags .text 00000040 __adddf3", "__adddf3",
                    "02000200 g F .text __adddf3"):
            with self.subTest(row=row):
                errors, notes = self.run_check(syms=symbols(self.values) + noinit_symbols(self.noinit_used) + row + "\n")
                self.assertIn("soft-double: malformed symbol row", " ".join(errors))
                self.assertNotIn("no known soft-double", " ".join(notes))
        syms = symbols(self.values) + noinit_symbols(self.noinit_used) + "02000200 g F .missing 00000000 __adddf3\n"
        for hdr in (noinit_header(self.noinit_used),
                    noinit_header(self.noinit_used) + " 6 .missing bad 00000000\n  ALLOC, CODE\n"):
            self.assertIn("soft-double: missing or malformed section evidence", " ".join(self.check(hdr=hdr, syms=syms)))

    def test_soft_double_gnu_unknown_or_malformed_attributes_fail_closed(self):
        syms = symbols(self.values) + noinit_symbols(self.noinit_used)
        syms += "02000200 g F .text 00000040 __adddf3\n"
        for attrs in ("CONTENTS, ALLOC, LOAD, READONLY, COD",
                      "CONTENTS, ALLOC, LOAD, READONLY, CODE, UNKNOWN",
                      "ALLOC, UNKNOWN", "", "CONTENTS, , ALLOC, CODE"):
            with self.subTest(attrs=attrs):
                hdr = noinit_header(self.noinit_used).replace(
                    "CONTENTS, ALLOC, LOAD, READONLY, CODE", attrs)
                errors, notes = self.run_check(hdr=hdr, syms=syms)
                self.assertIn("soft-double: missing or malformed section evidence", " ".join(errors))
                self.assertNotIn("no known soft-double", " ".join(notes))

    def test_soft_double_gnu_known_nonexecutable_attributes_pass(self):
        syms = symbols(self.values) + noinit_symbols(self.noinit_used)
        syms += "02000200 g F .text 00000040 __adddf3\n"
        # The section name alone cannot establish ALLOC or CODE.
        for attrs in ("CODE", "CONTENTS, CODE", "ALLOC",
                      "CONTENTS, ALLOC, LOAD, DATA", "CONTENTS, READONLY, DEBUGGING"):
            with self.subTest(attrs=attrs):
                hdr = noinit_header(self.noinit_used).replace(
                    "CONTENTS, ALLOC, LOAD, READONLY, CODE", attrs)
                errors, notes = self.run_check(hdr=hdr, syms=syms)
                self.assertEqual(errors, [])
                self.assertIn("no known soft-double helpers defined in final executable sections", notes)

    def test_soft_double_native_jieli_section_headers(self):
        for section in (".text", ".ram_text", ".c1_text"):
            hdr = ("probe.elf:\tfile format ELF32-pi32v2\n\nSections:\n"
                   "Idx Name          Size      Address          Type\n"
                   "  0               00000000 0000000000000000 \n"
                   f"  1 {section} 00000d2e 0000000001c0a800 TEXT DATA \n"
                   "  2 .bss 0000002c 0000000001c0ba30 BSS\n"
                   "  3 .symtab 00000370 0000000000000000 \n")
            syms = f"01c0a8da g     F {section}\t\t 0000028c __adddf3\n"
            errors, _ = B.soft_double_check(hdr, syms)
            self.assertIn("helpers defined in final executable sections: __adddf3;", " ".join(errors))
            padded_hdr = hdr.replace("Idx Name          Size      Address          Type", " \tIdx\tName  Size\tAddress  Type ")
            self.assertEqual(B.soft_double_check(padded_hdr, syms)[0], errors)
            self.assertEqual(B.soft_double_check(hdr, "01c0ba30 g .bss 00000000 __adddf3\n")[0], [])
            self.assertEqual(B.soft_double_check(hdr, "00000000 l d .symtab 00000000 __adddf3\n")[0], [])
            for damaged in (hdr.replace("00000d2e", "bad-size"),
                            hdr.replace("TEXT DATA", "BAD"), hdr.replace(section, ".unknown_text")):
                row = syms.replace(section, ".unknown_text") if ".unknown_text" in damaged else syms
                self.assertIn("missing or malformed section evidence", " ".join(B.soft_double_check(damaged, row)[0]))

    def test_soft_double_native_missing_section_type_fails_closed(self):
        hdr = ("Sections:\nIdx Name          Size      Address          Type\n"
               "  0 .text         00000010 0000000002000120\n")
        syms = "02000120 g     F .text\t\t 00000000 __adddf3\n"
        errors, notes = B.soft_double_check(hdr, syms)
        self.assertIn("missing or malformed section evidence", " ".join(errors))
        self.assertNotIn("no known soft-double", " ".join(notes))

    def test_second_core_ram_section_is_required_and_only_calls_the_job(self):
        section = "Disassembly of section .c1_text:\n 1c01000: 00 00 \tcall r0\n"
        ram = "Disassembly of section .ram_text:\n" + self.rt
        with patch.object(B, "CPU2", True):
            self.assertEqual(self.check(rt=ram + section), [])
            self.assertIn("waiting loop is missing", " ".join(self.check(rt=ram)))
            for instruction in ("call 4 <f: 2000120 >", ".word 0x1234", "unknown"):
                self.assertTrue(self.check(rt=ram + section.replace("call r0", instruction)))
            self.assertIn(".ram_text contains calls", " ".join(self.check(rt=ram.replace("ret", "call r0") + section)))
        self.assertIn("second-core code or data", " ".join(self.check(rt=ram + section)))

    def test_empty_flash_ram_with_second_core_needs_elf_proof(self):
        rt = ("build/felucca.elf:\tfile format ELF32-pi32v2\n\n"
              "Disassembly of section .c1_text:\nfm1_c1_main:\n 1c00000: 00 00 \tcall r0\n")
        hdr = noinit_header(self.noinit_used) + " 2 .ram_text 00000000 01c00000 DATA\n"
        syms = symbols(dict(self.values, _rt_start=0x01C00000, _rt_end=0x01C00000)) + noinit_symbols(self.noinit_used)
        with patch.object(B, "CPU2", True):
            self.assertEqual(self.check(hdr=hdr, syms=syms, rt=rt), [])
            self.assertEqual(self.check(hdr=hdr, rt=rt), [])       # zero section size is sufficient
            self.assertEqual(self.check(syms=syms, rt=rt), [])     # equal linker bounds also prove empty
            self.assertIn("missing or malformed .ram_text", " ".join(self.check(rt=rt)))
            for nonempty_hdr, nonempty_syms in (
                    (hdr.replace("00000000 01c00000", "00000004 01c00000"), syms),
                    (hdr, syms.replace("01c00000 g .bss 00000000 _rt_end", "01c00004 g .bss 00000000 _rt_end"))):
                with self.subTest(hdr=nonempty_hdr, syms=nonempty_syms):
                    self.assertIn("missing or malformed .ram_text", " ".join(
                        self.check(hdr=nonempty_hdr, syms=nonempty_syms, rt=rt)))

    def test_empty_ram_proof_does_not_allow_damaged_disassembly(self):
        rt = ("file format ELF32-pi32v2\nDisassembly of section .c1_text:\n"
              "fm1_c1_main:\n 1c00000: 00 00 \tcall r0\n")
        hdr = noinit_header(self.noinit_used) + " 2 .ram_text 00000000 01c00000 DATA\n"
        with patch.object(B, "CPU2", True):
            for damaged in ("", "file format ELF32-pi32v2\n", rt.replace("file format ELF32-pi32v2\n", ""),
                            "garbage\n" + rt, rt + "garbage\n", rt.replace("call r0", ""),
                            rt.replace("00 00", "zz 00"), rt.replace("call r0", ".word 0x1234"),
                            rt.replace("call r0", "unknown"), rt.replace("call r0", "call 4 <f: 2000120 >"),
                            rt + "Disassembly of section .other:\n 1c01000: 00 00 \tcall r0\n"):
                with self.subTest(rt=damaged):
                    self.assertTrue(self.check(hdr=hdr, rt=damaged))
            ram = "Disassembly of section .ram_text:\n 1c00000: 00 00 \tcall r0\n"
            self.assertIn(".ram_text contains calls", " ".join(self.check(hdr=hdr, rt=rt + ram)))

    def test_standalone_empty_ram_still_rejects_nonempty_elf_evidence(self):
        rt = "file format ELF32-pi32v2\n"
        self.assertEqual(self.check(rt=rt), [])   # retain existing standalone objdump fixture
        hdr = noinit_header(self.noinit_used) + " 2 .ram_text 00000004 01c00000 DATA\n"
        self.assertIn("missing or malformed .ram_text", " ".join(self.check(hdr=hdr, rt=rt)))
        syms = symbols(dict(self.values, _rt_start=0x01C00000, _rt_end=0x01C00004)) + noinit_symbols(self.noinit_used)
        self.assertIn("missing or malformed .ram_text", " ".join(self.check(syms=syms, rt=rt)))

    def test_empty_ram_section_and_linker_evidence(self):
        hdr = " 2 .ram_text 00000000 01c00000 DATA\n"
        syms = "01c00000 .ram_text 00000000 _rt_start\n01c00000 .ram_text 00000000 _rt_end\n"
        self.assertIsNone(B.ram_text_empty("", ""))
        self.assertTrue(B.ram_text_empty(hdr, syms))
        self.assertFalse(B.ram_text_empty(hdr.replace("00000000", "00000004"), syms))
        self.assertFalse(B.ram_text_empty(hdr, syms.replace("01c00000 .ram_text 00000000 _rt_end", "01c00004 .ram_text 00000000 _rt_end")))
        self.assertFalse(B.ram_text_empty(hdr.replace("00000000", "invalid"), syms))
        self.assertFalse(B.ram_text_empty(hdr, syms.replace("01c00000 .ram_text 00000000 _rt_end", "invalid .ram_text 00000000 _rt_end")))
        self.assertFalse(B.ram_text_empty(hdr, syms.splitlines()[0] + "\n"))

    def test_entry_and_stub(self):
        self.values["_start"] += 2
        self.assertIn("_start is not at", " ".join(self.check()))
        del self.values["_start"]
        self.assertIn("_start is not at", " ".join(self.check()))
        for img in (b"", bytes(4), bytes.fromhex("04818001")):
            with self.subTest(img=img):
                self.assertIn("not the entry stub", " ".join(self.check(img=img)))

    def test_real_objdump_data_rows_and_malformed_neighbors(self):
        rows = [" 20783e0:\t 5d 03 39 03 16 03 f4 02         ].9.....\n",
                " 203df30:\t 20 5b 07 02 08 00 00 00          [......\n",
                " 2013e90:    07 02     < 519 : 0x207 >\n",
                " 2003db0:    02     < 2 : 0x2 >\n"]
        self.assertEqual(self.check(dis=self.dis + "".join(rows)), [])
        for row in rows:
            self.assertTrue(self.check(rt=row))  # no skipped undecoded RAM code
        for row in (rows[0].replace("].9.....", "........"),
                    rows[2].replace("519", "518"), rows[0].replace("5d", "zz")):
            self.assertTrue(self.check(dis=self.dis + row))
        self.assertTrue(self.check(dis="".join(rows)))  # data cannot replace all instructions

    def test_app_slot_boundary(self):
        self.assertEqual(self.check(img=self.img + bytes(B.APP_SLOT - len(self.img))), [])
        self.assertIn("exceeds the app slot", " ".join(self.check(img=self.img + bytes(B.APP_SLOT + 1 - len(self.img)))))

    def test_exact_ram_pool_margins_and_one_byte_failure(self):
        self.values["_bss_end"] = 0x01C08000 + 72 * 1024 - 4096
        self.values["_pool_end"] = 0x01C1A000 + 0x5A000 - 8192
        self.assertEqual(self.check(), [])
        self.values["_bss_end"] += 1
        self.assertIn("RAM headroom 4095 B", " ".join(self.check()))
        self.values["_bss_end"] -= 1
        self.values["_pool_end"] += 1
        self.assertIn("pool headroom 8191 B", " ".join(self.check()))

    def test_crash_ctx_diagnostic_build_floor(self):
        """FELUCCA_CRASH_CTX=1 (#428): only that build may put its 76 B register context below the 100 B floor"""
        self.assertEqual(B.CRASH_CTX_NOINIT, 76)
        with patch.dict(os.environ, {"FELUCCA_CRASH_CTX": "1"}):
            self.noinit_used = NOINIT_LEN - 24                   # 24 B spare: the floor of this build
            errors, notes = self.run_check()
            self.assertEqual(errors, [])
            self.assertIn("NOINIT floor 24 B: FELUCCA_CRASH_CTX=1", " ".join(notes))
            self.noinit_used += 1
            self.assertEqual(self.check(), ["NOINIT headroom 23 B < 24 B"])
        for env in ({"FELUCCA_CRASH_CTX": "0"}, {}):
            with patch.dict(os.environ, env):
                if not env:
                    os.environ.pop("FELUCCA_CRASH_CTX", None)
                self.noinit_used = NOINIT_LEN - 99               # standard and release builds: still 100 B
                self.assertEqual(self.check(), ["NOINIT headroom 99 B < 100 B"])
                self.noinit_used = NOINIT_LEN - 100
                errors, notes = self.run_check()
                self.assertEqual(errors, [])
                self.assertNotIn("NOINIT floor", " ".join(notes))

    def test_noinit_spare_floor_and_one_byte_failure(self):
        floor = NOINIT_LEN - B.NOINIT_SPARE_MIN
        self.assertEqual(B.NOINIT_SPARE_MIN, 100)
        self.assertEqual(self.check(), [])                       # the real build: 132 B spare
        self.noinit_used = floor                                 # exactly 100 B spare
        errors, notes = self.run_check()
        self.assertEqual(errors, [])
        self.assertIn("NOINIT 15596 B of 15696 (100 B spare)", " ".join(notes))
        self.noinit_used = floor + 1                             # 99 B spare
        self.assertEqual(self.check(), ["NOINIT headroom 99 B < 100 B"])
        self.noinit_used = NOINIT_LEN                            # full, still inside its region
        self.assertEqual(self.check(), ["NOINIT headroom 0 B < 100 B"])

    def test_noinit_floor_is_independent_of_ram_and_pool(self):
        self.noinit_used = NOINIT_LEN - 99
        self.values["_bss_end"] = 0x01C08000 + 72 * 1024 - 4095
        self.values["_pool_end"] = 0x01C1A000 + 0x5A000 - 8191
        errors = " ".join(self.check())
        for msg in ("RAM headroom 4095 B", "pool headroom 8191 B", "NOINIT headroom 99 B"):
            self.assertIn(msg, errors)

    def test_noinit_extent_is_the_larger_of_section_and_symbols(self):
        hdr = noinit_header(15564)
        self.assertEqual(B.noinit_used(hdr, noinit_symbols(15564), NOINIT_ORG), 15564)
        rows = noinit_symbols(15564) + f"{NOINIT_ORG + 0x80:08x} g .bss 00004000 other_section\n"
        self.assertEqual(B.noinit_used(hdr, rows, NOINIT_ORG), 15564)  # other sections do not count
        self.assertEqual(B.noinit_used(noinit_header(15600), noinit_symbols(15564), NOINIT_ORG), 15600)  # tail padding
        self.assertEqual(B.noinit_used(noinit_header(100), noinit_symbols(15564), NOINIT_ORG), 15564)    # symbols reach further
        self.assertIsNone(B.noinit_used("", noinit_symbols(15564), NOINIT_ORG))   # no .noinit section header
        self.assertIsNone(B.noinit_used("Sections:\n  0 .text 00001000 02000120 02000120 00000100 2**2\n", "", NOINIT_ORG))

    def test_noinit_padding_without_a_symbol_still_counts(self):
        floor = NOINIT_LEN - B.NOINIT_SPARE_MIN
        symbols_only = noinit_symbols(floor)                     # the symbols alone leave exactly 100 B
        errors, _ = B.check(self.img, noinit_header(floor), symbols(self.values) + symbols_only, self.dis, self.rt)
        self.assertEqual(errors, [])
        errors, _ = B.check(self.img, noinit_header(floor + 1), symbols(self.values) + symbols_only, self.dis, self.rt)
        self.assertEqual(errors, ["NOINIT headroom 99 B < 100 B"])  # one anonymous byte in the section is enough

    def test_noinit_missing_or_out_of_region(self):
        self.assertIn("missing .noinit section", " ".join(self.check(hdr="Sections:\n")))
        self.noinit_used = NOINIT_LEN + 4                        # beyond the region (the linker would refuse)
        self.assertIn("NOINIT section is outside its region", " ".join(self.check()))
        self.assertIn("NOINIT section is outside its region", " ".join(self.check(    # below the region
            hdr=noinit_header(0).replace(f"{NOINIT_ORG:08x}", f"{NOINIT_ORG - 4:08x}"), syms=symbols(self.values))))

    def test_missing_malformed_and_reversed_symbols(self):
        for name in ("_bss_end", "_pool_start", "_pool_end"):
            with self.subTest(name=name):
                values = dict(self.values)
                del values[name]
                self.assertIn(f"missing symbol {name}", " ".join(self.check(syms=symbols(values) + noinit_symbols(15564))))
        self.assertIn("missing symbol _pool_end", " ".join(self.check(syms=symbols(self.values).replace("01c1a100", "garbage"))))
        for name, value in (("_bss_end", 0x01C07FFF), ("_pool_start", 0x01C1A001),
                            ("_pool_end", 0x01C19FFF)):
            with self.subTest(name=name):
                values = dict(self.values, **{name: value})
                self.assertIn("outside their regions or reversed", " ".join(self.check(syms=symbols(values) + noinit_symbols(15564))))

    def test_memory_layout_inputs(self):
        p = B.FW / "app.ld"
        text = p.read_text()
        p.write_text(text.replace("0x01C1A000", "0x01C1A001"))
        self.assertIn("POOL does not start where RAM ends", " ".join(self.check()))
        for contents in ("", text.replace("POOL (rw)", "OTHER (rw)"), text.replace("72K", "0"),
                         text.replace("NOINIT (rw)", "OTHER (rw)"), text.replace("0x3D50", "0")):
            p.write_text(contents)
            self.assertIn("missing or empty RAM/POOL/NOINIT", " ".join(self.check()))
        p.write_text(text.replace("72K", "72Z"))
        self.assertIn("invalid memory regions", " ".join(self.check()))
        p.unlink()
        self.assertIn("invalid memory regions", " ".join(self.check()))

    def test_mandatory_disassembly_and_ram_calls(self):
        self.assertIn("missing or malformed app disassembly", " ".join(self.check(dis="")))
        self.assertIn("missing or malformed .ram_text disassembly", " ".join(self.check(rt="")))
        for text in ("garbage", " 2000120: bad bytes\n", " 2000120: 00 00 \t\n"):
            self.assertTrue(self.check(dis=text))
            self.assertTrue(self.check(rt=text))
        self.assertTrue(self.check(rt="file format ELF32-pi32v2\ngarbage\n"))
        self.assertTrue(self.check(rt=" 1c00000: 00 00 \t.word 0x1234\n"))
        self.assertIn(".ram_text contains calls", " ".join(self.check(rt=" 1c00000: 00 00 \tcall 4 <f: 2000120 >\n")))

    def test_rom_boundaries_signed_unsigned_hex_and_calls(self):
        for addr, bad in ((0xFFBFFFFF, False), (0xFFC00000, True), (0xFFCFFFFF, True), (0xFFD00000, False)):
            for text in (f"r0 = {addr}", f"r0 = {addr - 0x100000000}", f"r0 = {addr:#x}",
                         f"call -4 <f: {addr:x} >", f"call 4 <f: {addr:X} >"):
                with self.subTest(text=text):
                    errors = self.check(dis=f" 2000120: 00 00 \t{text}\n")
                    self.assertEqual(any("reference to ROM" in e for e in errors), bad, errors)
        self.assertEqual(self.check(dis=" 2000120: 00 00 \tif r0 == 4290772992 goto 4 <f: 2000130 >\n"), [])
        self.assertEqual(self.check(dis=" 2000120: 00 00 \tr0 &= 4290772992\n"), [])


class LoaderGuards(unittest.TestCase):
    def setUp(self):
        self.lo, self.hi = 0x01C0A800, 0x01C1E800
        self.hdr = " 1 .text 00000020 01c0a800 TEXT DATA\n 2 .bss 00000010 01c0a820 BSS\n 3 .symtab 00000040 00000000\n"
        self.values = {"_start": self.lo, "_bss_start": self.lo + 32, "_bss_end": self.lo + 48}

    def test_valid_sections_and_metadata(self):
        self.assertEqual(B.loader_check(self.hdr, symbols(self.values)), [])
        self.assertEqual(B.loader_check(self.hdr + " 4 .empty 00000000 02000000 DATA\n", symbols(self.values)), [])

    def test_wrapped_loader_fits_native_staging_reserve(self):
        for image in (b"", b"x" * (0x14000 + 1)):
            with self.assertRaisesRegex(SystemExit, "image empty or too big"):
                B.ldr_wrap(image)
        # A compressible RAM image fits even when larger than staging; an
        # incompressible one must be refused before packaging/staging it.
        self.assertLessEqual(len(B.ldr_wrap(bytes(0x14000))) - 32, 0x4E00)
        with patch.object(B.lz4blk, "compress", side_effect=lambda raw: raw), \
                patch.object(B.lz4blk, "decompress", side_effect=lambda raw: raw):
            self.assertLessEqual(len(B.ldr_wrap(bytes(0x4000))) - 32, 0x4E00)
            with self.assertRaisesRegex(SystemExit, "exceeds native staging"):
                B.ldr_wrap(bytes(0x5000))

    def test_section_window_boundaries(self):
        for addr, size, bad in ((self.lo, 1, False), (self.hi - 1, 1, False),
                                (self.lo - 1, 1, True), (self.hi - 1, 2, True),
                                (self.hi, 1, True), (0x02000000, 1, True)):
            for typ in ("TEXT", "DATA", "BSS"):
                with self.subTest(addr=addr, size=size, typ=typ):
                    hdr = self.hdr + f" 4 .custom {size:08x} {addr:08x} {typ}\n"
                    errors = B.loader_check(hdr, symbols(self.values))
                    self.assertEqual(any("outside RAM" in e for e in errors), bad, errors)

    def test_missing_and_malformed_inputs(self):
        self.assertIn("missing or empty .text", " ".join(B.loader_check("", symbols(self.values))))
        self.assertIn("malformed section row", " ".join(B.loader_check(" 1 .text bad-value 01c0a800 TEXT\n", symbols(self.values))))
        self.assertIn("malformed section row", " ".join(B.loader_check(" 1 .text -1 01c0a800 TEXT\n", symbols(self.values))))
        for name in self.values:
            values = dict(self.values)
            del values[name]
            self.assertIn(f"missing symbol {name}", " ".join(B.loader_check(self.hdr, symbols(values))))
        for name, value in (("_start", self.lo + 2), ("_bss_start", self.lo),
                            ("_bss_end", self.lo + 1), ("_bss_end", self.hi + 1)):
            values = dict(self.values, **{name: value})
            self.assertTrue(B.loader_check(self.hdr, symbols(values)))
        self.assertIn(".text does not start", " ".join(B.loader_check(
            self.hdr.replace("01c0a800", "01c0a804"), symbols(dict(self.values, _bss_start=self.lo + 36)))))


class TargetSetupPolicy(unittest.TestCase):
    def test_absent_default_skips_but_explicit_bad_configuration_fails(self):
        smoke = runpy.run_path(str(ROOT / "tests/build_guard_target_test.py"))["TargetArithmetic"]
        env = dict(os.environ)
        env.pop("JIELI_TOOLCHAIN", None)
        with patch.dict(os.environ, env, clear=True), patch.object(Path, "exists", return_value=False):
            with self.assertRaises(unittest.SkipTest):
                smoke.setUpClass()
        with patch.dict(os.environ, {"JIELI_TOOLCHAIN": "/missing-configured-toolchain"}), patch.object(Path, "exists", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "configured JieLi toolchain"):
                smoke.setUpClass()


class HalGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        self.addCleanup(self.tmp.cleanup)
        fw = Path(self.tmp.name)
        for d in ("hal", "src", "loader"):
            (fw / d).mkdir()
        (fw / "hal" / "regs.h").write_text("#define REG (*(volatile unsigned *)0x50000)\n#define ALIAS REG\n#define NEXT ALIAS\n#define MULTI \\\n (*(volatile unsigned *)0x50004)\n#define VIA_MULTI MULTI\n")
        self.patch = patch.object(B, "FW", fw)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_allowed_neighbors_comments_objects_and_barrier(self):
        (B.FW / "src" / "valid.c").write_text("""/* 0x50000 asm volatile pointer: comments are not accesses */
// REG and 0x02000000
extern char _bss_start[];
void f(void) { int x; (void)*(volatile int *)&x; }
#define RING_PUBLISH() __asm__ volatile ("" ::: "memory")
unsigned a = 0x0ffff, b = 0x14000, c = 0x44000, d = 0x52000, e = 0x02100000;
""")
        self.assertEqual(B.mmio_check(), [])

    def test_register_window_boundaries(self):
        ranges = ((0x10000, 0x13FFF), (0x40000, 0x43FFF), (0x50000, 0x51FFF),
                  (0x1EE0000, 0x1EEFFFF), (0x1C7F000, 0x1C7FFFF), (0x2000000, 0x20FFFFF))
        p = B.FW / "src" / "bad.c"
        for lo, hi in ranges:
            for v, bad in ((lo - 1, False), (lo, True), (hi, True), (hi + 1, False)):
                p.write_text(f"unsigned x = 0x{v:08X}UL;\n")
                errors = B.mmio_check()
                self.assertEqual(bool(errors), bad, (v, errors))
                if bad:
                    self.assertIn("src/bad.c:1: register/window address", errors[0])

    def test_cast_asm_and_transitive_macro_rejections(self):
        for folder in ("src", "loader"):
            for code, message in (("int *p = (volatile int *)1;", "volatile pointer cast"),
                                  ('void f(void) { __asm__("nop"); }', "inline asm"),
                                  ("int x = NEXT;", "HAL register macro"),
                                  ("int x = VIA_MULTI;", "HAL register macro")):
                with self.subTest(folder=folder, code=code):
                    p = B.FW / folder / "bad.c"
                    p.write_text(code)
                    errors = B.mmio_check()
                    self.assertTrue(any(f"{folder}/bad.c:1: {message}" in e for e in errors), errors)
                    p.unlink()


if __name__ == "__main__":
    (ROOT / "build").mkdir(exist_ok=True)
    unittest.main()
