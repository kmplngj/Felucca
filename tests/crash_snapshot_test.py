#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Per-word publication interleavings in the actual retained-record reader.

The fixture instruments volatile loads, models an invalidated record followed by
body/generation stores and valid-marker publication, and executes both actual
consumers. It does not model caches or qualify physical core publication.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

from crash_record_test import ROOT, function_source, recorder_source

sys.path.insert(0, str(ROOT / "tools"))
import fm1_diagnostics as diag


def reader_source():
    header = (ROOT / "firmware/hal/fm1_irq.h").read_text()
    reader = function_source(header, "static int fm1_crash_read(fm1_crash_t *copy)")
    if "const volatile fm1_crash_t *shared" not in reader:
        raise AssertionError("shared record reads must remain volatile")
    return reader


def instrument(reader):
    reader = reader.replace('__asm__ volatile("csync" ::: "memory");',
                            '__asm__ volatile("" ::: "memory");')
    reader = reader.replace("const volatile fm1_crash_t *shared = &fm1_crash;",
                            "/* shared loads are instrumented below */")
    return re.sub(r"shared->(\w+)(\[i\])?", lambda match:
                  f"read_word(offsetof(fm1_crash_t, {match.group(1)}) + i * sizeof(uint32_t))"
                  if match.group(2) else
                  f"read_word(offsetof(fm1_crash_t, {match.group(1)}))", reader)


HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define FM1_CRASH_MAGIC 0x43525348u
#define FELUCCA_CPU2 FM1_CPU1_USED
@RECORD@
static fm1_crash_t fm1_crash, old_record, new_record;
enum { WORDS = sizeof(fm1_crash_t) / sizeof(uint32_t) };
static unsigned loads, start, finish, partial, count_position, reverse;
static unsigned writing, step, console_words, absent, serial_changes;
static uint32_t word(const fm1_crash_t *record, unsigned index) {
    uint32_t value;
    memcpy(&value, (const char *)record + index * sizeof(value), sizeof(value));
    return value;
}
static void store(unsigned index, uint32_t value) {
    memcpy((char *)&fm1_crash + index * sizeof(value), &value, sizeof(value));
}
static void advance(unsigned limit) {
    /* Exercise every generation position amongst the payload stores, in both
     * payload orders. Only invalidation-first and publication-last are required. */
    while (step < limit) {
        if (!step)
            store(0, 0);
        else if (step == WORDS)
            store(0, FM1_CRASH_MAGIC);
        else if (step == count_position + 1)
            store(1, new_record.count);
        else {
            unsigned payload = step - 1 - (step > count_position + 1);
            unsigned index = reverse ? WORDS - 1 - payload : 2 + payload;
            store(index, word(&new_record, index));
        }
        step++;
    }
}
static uint32_t read_word(size_t offset) {
    unsigned index = loads++;
    if (index == start) {
        writing = 1;
        advance(partial);
    }
    if (writing && index == finish)
        advance(WORDS + 1);
    uint32_t value;
    memcpy(&value, (const char *)&fm1_crash + offset, sizeof(value));
    return value;
}
@READER@
static int valid_copy(const fm1_crash_t *copy) {
    return !memcmp(copy, &old_record, sizeof(*copy)) ||
           !memcmp(copy, &new_record, sizeof(*copy));
}
static void reset(void) {
    memcpy(&fm1_crash, &old_record, sizeof(fm1_crash));
    loads = writing = step = 0;
}
static void con_kv(const char *name, int32_t value) {
    uint32_t expected = 0;
    if (!strcmp(name, "count")) expected = old_record.count;
#if FM1_CPU1_USED
    else if (!strcmp(name, "core")) expected = old_record.core;
#endif
    else if (!strcmp(name, "uptime_ms")) expected = old_record.uptime_ms;
    else if (!strcmp(name, "early")) expected = old_record.early;
    else if (!strcmp(name, "vec")) expected = old_record.vec;
    else if (!strcmp(name, "pc")) expected = old_record.pc;
    else if (!strcmp(name, "rets")) expected = old_record.rets;
    else if (!strcmp(name, "emu")) expected = old_record.emu;
    else if (!strcmp(name, "sp")) expected = old_record.sp;
    else if (!strcmp(name, "psr")) expected = old_record.psr;
#if FELUCCA_CRASH_CTX
    else if (!strcmp(name, "ctx")) expected = old_record.ctx == (FM1_CRASH_CTX_KEY ^ old_record.count);
    else if (!strcmp(name, "usp")) expected = old_record.usp;
    else if (!strcmp(name, "ssp")) expected = old_record.ssp;
    else if (name[0] == 'r' && name[1] >= '0' && name[1] <= '9') expected = old_record.r[atoi(name + 1)];
#endif
    else { fprintf(stderr, "unexpected console field\n"); console_words = 100; return; }
    if ((uint32_t)value != expected) console_words = 100;
    console_words++;
    /* Serial output can yield to an interrupt and a worker publication. */
    if (serial_changes)
        memcpy(&fm1_crash, &new_record, sizeof(fm1_crash));
}
static void con_kx(const char *name, uint32_t value) { con_kv(name, (int32_t)value); }
static void con_puts(const char *text) { absent += !strcmp(text, "no crash record\r\n"); }
@CONSOLE@
static uint32_t crash_seen;
static uint8_t boot_clean;
static struct { uint32_t failed; } bootguard;
static struct { uint32_t p3_rst; } fm1_boot;
static uint32_t settings_leds, ui_prefs;
enum { LEDS_DIM_LO, LEDS_DIM, PREF_ANIM_OFF = 4 };
static void fm1_led_dim_level(uint32_t value) { (void)value; }
static void fm1_led_anim_start(uint32_t value) { (void)value; }
@BOOT@
int main(void) {
    uint32_t old_words[WORDS], new_words[WORDS];
    for (unsigned i = 0; i < WORDS; i++) {
        old_words[i] = 0xA0000000u + i;
        new_words[i] = 0xB0000000u + i;
    }
    old_words[0] = new_words[0] = FM1_CRASH_MAGIC;
    old_words[1] = 100;
    new_words[1] = 101;
#if FELUCCA_CRASH_CTX
    old_words[offsetof(fm1_crash_t, ctx) / 4] = FM1_CRASH_CTX_KEY ^ 100u;   /* registers belong to each record */
    new_words[offsetof(fm1_crash_t, ctx) / 4] = FM1_CRASH_CTX_KEY ^ 101u;
#endif
    memcpy(&old_record, old_words, sizeof(old_record));
    memcpy(&new_record, new_words, sizeof(new_record));
    start = finish = 1000;
    reset();
    fm1_crash_t copy;
    if (!fm1_crash_read(&copy) || !valid_copy(&copy)) return 1;
    unsigned total_loads = loads;
    unsigned cases = 0;
    for (reverse = 0; reverse < 2; reverse++)
        for (count_position = 0; count_position <= WORDS - 2; count_position++)
            for (start = 0; start <= total_loads; start++)
                for (finish = start; finish <= total_loads; finish++)
                    for (partial = 1; partial <= WORDS; partial++) {
                        reset();
                        memset(&copy, 0xCC, sizeof(copy));
                        int accepted = fm1_crash_read(&copy);
                        if ((accepted && !valid_copy(&copy)) || (!accepted && copy.magic)) {
                            fprintf(stderr, "mixed snapshot: start=%u finish=%u partial=%u count=%u reverse=%u\n",
                                    start, finish, partial, count_position, reverse);
                            return 1;
                        }
                        cases++;
                    }
    start = finish = 1000;
    reset();
    serial_changes = 1;
    con_crash();
    if (console_words != 9 + FM1_CPU1_USED + 19 * FELUCCA_CRASH_CTX || absent) return 2;
    reset();
    fm1_crash.magic = 0;
    con_crash();
    if (console_words != 9 + FM1_CPU1_USED + 19 * FELUCCA_CRASH_CTX || absent != 1) return 3;
    /* Valid boot history remains unchanged; failed reads never use live count. */
    reset();
#if FM1_CPU1_USED
    fm1_crash.core = old_record.core = 0;
#endif
    crash_seen = 99;
    boot_leds();
    if (boot_clean || crash_seen != 100) return 4;
    boot_leds();
    if (!boot_clean || crash_seen != 100) return 5;
#if FM1_CPU1_USED
    fm1_crash.core = 1;
    crash_seen = 99;
    boot_leds();
    if (!boot_clean || crash_seen != 100) return 6;
#endif
    fm1_crash.magic = 0;
    boot_leds();
    if (!boot_clean || crash_seen) return 7;
    printf("%u per-load interleavings; console and boot consumers passed\n", cases);
    return 0;
}
'''


SERIAL_HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define FM1_CRASH_MAGIC 0x43525348u
#define FELUCCA_CPU2 FM1_CPU1_USED
@RECORD@
static fm1_crash_t fm1_crash, replacement;
static unsigned replace_during_output;
@READER@
static void con_putc(char c) {
    putchar(c);
    /* Even the first byte may yield to publication of another core's record. */
    if (replace_during_output) {
        fm1_crash = replacement;
        replace_during_output = 0;
    }
}
@FORMATTERS@
@CONSOLE@
int main(int argc, char **argv) {
    if (argc != 4) return 1;
    fm1_crash.magic = atoi(argv[3]) ? FM1_CRASH_MAGIC : 0;
    fm1_crash.count = 100;
    fm1_crash.vec = 11;
    fm1_crash.pc = 0x02001234u;
    fm1_crash.rets = 0x02005678u;
    fm1_crash.emu = 0x12345678u;
    fm1_crash.sp = 0x01C60000u;
    fm1_crash.psr = 0x87654321u;
    fm1_crash.uptime_ms = 4000;
    fm1_crash.early = 0;
#if FM1_CPU1_USED
    fm1_crash.core = (uint32_t)atoi(argv[1]);
#endif
#if FELUCCA_CRASH_CTX
    for (unsigned i = 0; i < 16; i++)
        fm1_crash.r[i] = 0x01C60000u + i;
    fm1_crash.r[3] = 0x00800012u;
    fm1_crash.usp = 0x01C40000u;
    fm1_crash.ssp = 0x01C7E000u;
    fm1_crash.ctx = FM1_CRASH_CTX_KEY ^ 100u;
#endif
    replacement = fm1_crash;
    replacement.count = 101;
    replacement.vec = 12;
    replacement.pc = 0x02009000u;
    replacement.rets = 0;
    replacement.emu = 0;
    replacement.sp = 0x01C61000u;
    replacement.psr = 0;
    replacement.uptime_ms = 5000;
    replacement.early = 1;
#if FM1_CPU1_USED
    replacement.core = 1u - fm1_crash.core;
#endif
    replace_during_output = (unsigned)atoi(argv[2]);
    con_crash();
    return 0;
}
'''


class CrashSnapshot(unittest.TestCase):
    def test_actual_console_serialization_and_parser(self):
        record, _ = recorder_source()
        console = (ROOT / "firmware/src/console.c").read_text()
        formatters = "\n".join(function_source(console, signature) for signature in (
            "static void con_puts(const char *s)",
            "static void con_hex(uint32_t v, uint32_t digits)",
            "static void con_dec(int32_t v)",
            "static void con_kv(const char *k, int32_t v)",
            "static void con_kx(const char *k, uint32_t v)"))
        source = (SERIAL_HARNESS.replace("@RECORD@", record)
                  .replace("@READER@", reader_source().replace(
                      '__asm__ volatile("csync" ::: "memory");',
                      '__asm__ volatile("" ::: "memory");'))
                  .replace("@FORMATTERS@", formatters)
                  .replace("@CONSOLE@", function_source(console, "static void con_crash(void)")))
        expected = {"count": 100, "vec": 11, "pc": 0x02001234, "rets": 0x02005678,
                    "emu": 0x12345678, "sp": 0x01C60000, "psr": 0x87654321,
                    "uptime_ms": 4000, "early": 0, "record_present": True}
        payload = ("vec 0x0000000B\r\npc 0x02001234\r\nrets 0x02005678\r\n"
                   "emu 0x12345678\r\nsp 0x01C60000\r\npsr 0x87654321\r\n"
                   "uptime_ms 4000\r\nearly 0\r\n")
        with tempfile.TemporaryDirectory(prefix="felucca-crash-console-") as temporary:
            path = Path(temporary)
            (path / "fixture.c").write_text(source)
            for cpu1, ctx in ((0, 0), (1, 0), (0, 1), (1, 1)):    # ctx: FELUCCA_CRASH_CTX (#428)
                executable = path / f"console-{cpu1}-{ctx}"
                subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O2",
                                "-Wall", "-Wextra", "-Werror", f"-DFM1_CPU1_USED={cpu1}",
                                f"-DFELUCCA_CRASH_CTX={ctx}",
                                str(path / "fixture.c"), "-o", str(executable)], check=True)
                regs = [0x00800012 if i == 3 else 0x01C60000 + i for i in range(16)]
                ctx_raw = ("ctx 1\r\n" + "".join(f"r{i} 0x{v:08X}\r\n" for i, v in enumerate(regs)) +
                           "usp 0x01C40000\r\nssp 0x01C7E000\r\n") if ctx else ""
                ctx_fields = dict({f"r{i}": v for i, v in enumerate(regs)}, ctx=1, usp=0x01C40000,
                                  ssp=0x01C7E000) if ctx else {}
                for core in range(cpu1 + 1):
                    for replace in (0, 1):
                        for valid in (0, 1):
                            with self.subTest(cpu1=cpu1, ctx=ctx, core=core, replace=replace, valid=valid):
                                result = subprocess.run([str(executable), str(core), str(replace),
                                                         str(valid)], capture_output=True, check=True)
                                raw = ("count 100\r\n" + (f"core {core}\r\n" if cpu1 else "") +
                                       payload + ctx_raw) if valid else "no crash record\r\n"
                                self.assertEqual(result.stdout, raw.encode())
                                parsed = diag.parse_response("crash", result.stdout)
                                fields = dict(expected, **({"core": core} if cpu1 else {}),
                                              **ctx_fields) if valid else {"record_present": False}
                                self.assertEqual(parsed, {"fields": fields, "unknown_lines": [], "issues": []})

    def test_emulator_shim_validity_and_local_copy(self):
        emulator = (ROOT / "web/emu/felucca_web.c").read_text()
        start = emulator.index("#if FELUCCA_CPU2\ntypedef struct { uint32_t magic, count")
        end = emulator.index("static struct { uint8_t p3_rst", start)
        source = '''#include <stdint.h>
#include <string.h>
#include <assert.h>
''' + emulator[start:end] + '''
int main(void) {
    fm1_crash_t copy, expected;
    memset(&fm1_crash, 0xA5, sizeof(fm1_crash));
    memset(&copy, 0xCC, sizeof(copy));
    assert(!fm1_crash_read(&copy) && !copy.magic);
    fm1_crash.magic = FM1_CRASH_MAGIC;
    expected = fm1_crash;
    assert(fm1_crash_read(&copy));
    memset(&fm1_crash, 0, sizeof(fm1_crash));
    assert(!memcmp(&copy, &expected, sizeof(copy)));
    assert(!fm1_crash_read(&copy) && !copy.magic);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="felucca-crash-emu-") as temporary:
            path = Path(temporary)
            (path / "fixture.c").write_text(source)
            for cpu1 in (0, 1):
                executable = path / f"emulator-{cpu1}"
                subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11",
                                "-O2", "-Wall", "-Wextra", "-Werror",
                                f"-DFELUCCA_CPU2={cpu1}", str(path / "fixture.c"),
                                "-o", str(executable)], check=True)
                subprocess.run([str(executable)], check=True)

    def compile_run(self, reader, cpu1, ctx=0):
        record, _ = recorder_source()
        console = function_source((ROOT / "firmware/src/console.c").read_text(),
                                  "static void con_crash(void)")
        boot = function_source((ROOT / "firmware/src/main.c").read_text(),
                               "static void boot_leds(void)")
        source = (HARNESS.replace("@RECORD@", record).replace("@READER@", instrument(reader))
                  .replace("@CONSOLE@", console).replace("@BOOT@", boot))
        with tempfile.TemporaryDirectory(prefix="felucca-crash-snapshot-") as temporary:
            path = Path(temporary)
            (path / "fixture.c").write_text(source)
            executable = path / "snapshot"
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O2",
                            "-Wall", "-Wextra", "-Werror", f"-DFM1_CPU1_USED={cpu1}",
                            f"-DFELUCCA_CRASH_CTX={ctx}",
                            str(path / "fixture.c"), "-o", str(executable)], check=True)
            return subprocess.run([str(executable)], capture_output=True, text=True)

    def test_per_load_interleavings_and_actual_consumers(self):
        for cpu1, ctx in ((0, 0), (1, 0), (0, 1), (1, 1)):    # ctx: FELUCCA_CRASH_CTX (#428)
            with self.subTest(cpu1=cpu1, ctx=ctx):
                result = self.compile_run(reader_source(), cpu1, ctx)
                self.assertEqual(result.returncode, 0, result.stderr)
                print(result.stdout.strip())

    def test_missing_pre_copy_check_is_detected(self):
        reader = reader_source()
        check = "    if (shared->magic != FM1_CRASH_MAGIC)\n        return 0;"
        first = reader.index(check)
        pre_copy = reader.index(check, first + len(check))
        reader = reader[:pre_copy] + reader[pre_copy:].replace(check, "", 1)
        result = self.compile_run(reader, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mixed snapshot", result.stderr)

    def test_missing_generation_check_is_detected(self):
        reader = reader_source().replace("    if (shared->count != count)\n        return 0;", "")
        for ctx in (0, 1):
            with self.subTest(ctx=ctx):
                result = self.compile_run(reader, 1, ctx)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mixed snapshot", result.stderr)

    def test_reversed_final_acquire_order_is_detected(self):
        reader = reader_source()
        marker = "    if (shared->magic != FM1_CRASH_MAGIC)\n        return 0;"
        generation = "    if (shared->count != count)\n        return 0;"
        barrier = '    __asm__ volatile("csync" ::: "memory");'
        reader = reader.replace(marker + "\n" + barrier + "\n" + generation,
                                generation + "\n" + barrier + "\n" + marker)
        result = self.compile_run(reader, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mixed snapshot", result.stderr)


if __name__ == "__main__":
    unittest.main()
