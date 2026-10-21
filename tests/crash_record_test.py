#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Execute the real exception recorder with retained-RAM and MMIO fixtures.

Only target barriers, fixed MMIO addresses and the terminal park are replaced.
Each barrier observes whether the record is invalid or completely published.
This checks record semantics on the host, not device exception delivery.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function_source(header, signature):
    body = header[header.index(signature):]
    depth = 0
    for pos in range(body.index("{"), len(body)):
        if body[pos] == "{":
            depth += 1
        elif body[pos] == "}":
            depth -= 1
            if depth == 0:
                body = body[:pos + 1]
                break
    return body


def recorder_source():
    header = (ROOT / "firmware/hal/fm1_irq.h").read_text()
    record = re.search(r"typedef struct \{.*?\} fm1_crash_t;", header, re.S).group()
    record = re.search(r"^#define FM1_CRASH_CTX_KEY .*$", header, re.M).group() + "\n" + record
    body = function_source(header, "void fm1_fault_c(uint32_t *f)")
    body = body.replace('__asm__ volatile("csync" ::: "memory");', "observe_barrier();")
    body = body.replace("*(volatile uint32_t *)0x10804u", "test_timer_ticks")
    body = body.replace("*(volatile uint32_t *)0x10000u", "test_reset")
    body, parks = re.subn(r"for \(;;\)\s*;", "return;", body)
    if parks != 2:
        raise AssertionError("exception recorder must retain both terminal parks")
    return record, body


def guard_source(barrier="((void)0)"):
    """The retained CPU1 guard (#410) exactly as hal/fm1_sys.h builds it; only the target barrier is replaced."""
    header = (ROOT / "firmware/hal/fm1_sys.h").read_text()
    start = header.index("#define FM1_C1G_MAGIC")
    end = header.index("#define FM1_RESET_PREP() fm1_cpu1_halt()")
    guard = header[start:end]
    # Host: no retained RAM, and Mach-O clang rejects a bare section name, so drop it from this copy only.
    noinit = ' __attribute__((section(".noinit")))'
    assert guard.count(noinit) == 1, "fm1_sys.h guard no longer carries the expected .noinit attribute"
    guard = guard.replace(noinit, "")
    return guard.replace('__asm__ volatile("csync" ::: "memory")', barrier)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define FM1_CRASH_MAGIC 0x43525348u
@RECORD@
#if FM1_CPU1_USED
#pragma GCC diagnostic ignored "-Wunused-function"
@GUARD@
static uint32_t expected_guard;
#endif
fm1_crash_t fm1_crash;
static const char fm1_fatal_stubs[256];
static uint32_t test_timer_ticks, test_reset, frame[26];
#if FM1_CPU1_USED
static uint32_t worker_stacks[64];
#define _c1_ustack worker_stacks
#define _c1_sstack_top (worker_stacks + 64)
#endif
static uint32_t test_emu = 0x12345678u, test_dbg = 0x87654321u;
static uint32_t test_etm[4] = {0x56780000u, 0x56780001u, 0x56780002u, 0x56780003u};
#define FM1_EMU_MSG test_emu
#define FM1_DBG_MSG test_dbg
#define FM1_ETM_PC(i) test_etm[i]
static unsigned phase, reports, halts;
static uint32_t expected_count, expected_early, expected_core;
#if FM1_CPU1_USED
static void test_halt(void) {
    assert(!expected_core && phase == 0 && !halts);
    assert(fm1_c1g_read(0) == expected_guard);   /* the exclusion is recorded before the worker is held and the chip reset */
    halts++;
    /* A last worker publication may finish before the hold. Main must read
     * retained history after it, and preserve MMIO diagnostics before it. */
    fm1_crash.count = 31u;
    fm1_crash.early = 0;
    test_emu = test_dbg = 0;
    memset(test_etm, 0, sizeof(test_etm));
}
#define FM1_RESET_PREP() test_halt()
#else
#define FM1_RESET_PREP() ((void)0)
#endif
static void fm1_irq_off(void) {}
static void complete_record(void) {
    assert(fm1_crash.count == expected_count);
    assert(fm1_crash.vec == 11u);
    assert(fm1_crash.pc == frame[16]);
    assert(fm1_crash.rets == frame[25]);
    assert(fm1_crash.sp == frame[24]);
    assert(fm1_crash.psr == frame[20]);
    assert(fm1_crash.icfg == frame[21]);
    assert(fm1_crash.uptime_ms == test_timer_ticks / 24000u);
    assert(fm1_crash.early == expected_early);
    assert(fm1_crash.emu == (expected_core ? 0u : 0x12345678u));
    assert(fm1_crash.dbg == (expected_core ? 0u : 0x87654321u));
    for (unsigned i = 0; i < 4; i++)
        assert(fm1_crash.etm[i] == (expected_core ? 0u : 0x56780000u + i));
#if FM1_CPU1_USED
    assert(fm1_crash.core == expected_core);
#endif
#if FELUCCA_CRASH_CTX
    /* #428 diagnostic build: the faulting core's r0..r15, usp, ssp, keyed to this record's count */
    for (unsigned i = 0; i < 16; i++)
        assert(fm1_crash.r[i] == frame[i]);
    assert(fm1_crash.usp == frame[22] && fm1_crash.ssp == frame[23]);
    assert(fm1_crash.ctx == (FM1_CRASH_CTX_KEY ^ expected_count));
#endif
}
static void observe_barrier(void) {
    /* First invalidate the poisoned old record. Then all fields must be ready
     * while invalid, and only the final barrier may observe the valid marker. */
    assert(phase < 3);
    assert(halts == (FM1_CPU1_USED && !expected_core));
    assert(fm1_crash.magic == (phase == 2 ? FM1_CRASH_MAGIC : 0u));
    if (phase)
        complete_record();
    else
        assert(fm1_crash.pc == 0xA5A5A5A5u);
    phase++;
}
static void fm1_fault(const fm1_crash_t *c) {
#if FM1_CPU1_USED
    assert(fm1_c1g_read(0) == expected_guard);
#endif
    assert(c == &fm1_crash);
    assert(phase == 3 && c->magic == FM1_CRASH_MAGIC);
    complete_record();
    reports++;
}
@RECORDER@
int main(int argc, char **argv) {
    assert(argc == 5);
    expected_core = (uint32_t)atoi(argv[1]);
    const unsigned valid = (unsigned)atoi(argv[2]);
    const uint32_t ms = (uint32_t)atoi(argv[3]);
#if FM1_CPU1_USED
    /* argv[4]: the retained guard before the fault: 0 none, 1 the worker answers, 2 an earlier bad job. A fault on
     * core 0 while it answers is recorded (FAULT); the worker's own fault (core 1) changes nothing: core 0's wait
     * decides (BAD_JOB / TIMEOUT), or the watchdog does (HANG at the next boot). */
    unsigned before = (unsigned)atoi(argv[4]);
    if (before == 1u) fm1_c1g_set(FM1_C1X_ACTIVE, 0);
    else if (before == 2u) fm1_c1g_set(FM1_C1X_BAD_JOB, 3u);
    expected_guard = before == 1u ? (expected_core ? FM1_C1X_ACTIVE : FM1_C1X_FAULT)
                                  : before == 2u ? FM1_C1X_BAD_JOB : FM1_C1X_NONE;
#endif
    memset(&fm1_crash, 0xA5, sizeof(fm1_crash));
    fm1_crash.magic = valid ? FM1_CRASH_MAGIC : 0xA5A5A5A5u;
    fm1_crash.count = 23u;
    fm1_crash.early = 7u;
    expected_count = valid ? 24u : 1u;
    expected_early = expected_core || ms >= 3000u ? 0u : valid ? 8u : 1u;
#if FM1_CPU1_USED
    if (!expected_core && valid) {
        expected_count = 32u;
        expected_early = ms < 3000u ? 1u : 0u;
    }
#endif
    test_timer_ticks = ms * 24000u;
    for (unsigned i = 0; i < 26; i++)
        frame[i] = 0xC0000000u + i;
    frame[19] = (uint32_t)(uintptr_t)fm1_fatal_stubs + 6u * 12u;
    frame[24] = 0;
#if FM1_CPU1_USED
    if (expected_core)
        frame[24] = (uint32_t)(uintptr_t)(worker_stacks + 32);
    assert(sizeof(fm1_crash_t) == 68u + (FELUCCA_CRASH_CTX ? 76u : 0u));
#else
    assert(!expected_core && sizeof(fm1_crash_t) == 64u + (FELUCCA_CRASH_CTX ? 76u : 0u));
#endif
    fm1_fault_c(frame);
    assert(phase == 3 && reports == !expected_core && !test_reset);
#if FM1_CPU1_USED
    assert(fm1_c1g_read(0) == expected_guard);
    if (before == 2u) { uint32_t n; fm1_c1g_read(&n); assert(n == 3u); }
#endif
    assert(fm1_crash.magic == FM1_CRASH_MAGIC);
    complete_record();
    return 0;
}
'''


class CrashRecord(unittest.TestCase):
    def test_poisoned_record_and_publication_order(self):
        record, recorder = recorder_source()
        source = (HARNESS.replace("@RECORD@", record).replace("@RECORDER@", recorder)
                  .replace("@GUARD@", guard_source()))
        with tempfile.TemporaryDirectory(prefix="felucca-crash-record-") as temporary:
            path = Path(temporary)
            (path / "fixture.c").write_text(source)
            for cpu1, ctx in ((0, 0), (1, 0), (0, 1), (1, 1)):    # ctx: FELUCCA_CRASH_CTX (#428)
                executable = path / f"crash-{cpu1}-{ctx}"
                subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11",
                                "-Wall", "-Wextra", "-Werror", "-O2",
                                f"-DFM1_CPU1_USED={cpu1}", f"-DFELUCCA_CRASH_CTX={ctx}",
                                str(path / "fixture.c"), "-o", str(executable)], check=True)
                for core in range(cpu1 + 1):
                    for valid in (0, 1):
                        for uptime in (100, 3000):
                            for guard in range(3 if cpu1 else 1):
                                with self.subTest(cpu1=cpu1, ctx=ctx, core=core, valid=valid, uptime=uptime,
                                                  guard=guard):
                                    subprocess.run([str(executable), str(core), str(valid),
                                                    str(uptime), str(guard)], check=True)


if __name__ == "__main__":
    unittest.main()
