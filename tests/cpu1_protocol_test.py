#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Execute the actual HAL mailbox protocol with deterministic ordering hooks.

Volatile observations expose publication markers before payload; only a following
barrier makes payload visible. Store hooks require a preceding release. The real
worker/start/run/wait bodies run without pthread synchronization. This verifies
software ordering under the HAL CSYNC contract, not physical cache coherence or
real-device deadlines.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from crash_record_test import ROOT, function_source, guard_source


def protocol_source():
    header = (ROOT / "firmware/hal/fm1_cpu1.h").read_text()
    record = re.search(r"typedef struct \{.*?\} fm1_c1_mb_t;", header, re.S).group()
    signatures = ("void __attribute__((section(\".c1_text\"), noreturn, used)) fm1_c1_main(void)",
                  "static void fm1_cpu1_hold(void)", "static int fm1_cpu1_start(void)",
                  "static inline int fm1_cpu1_run(void (*fn)(uint32_t), uint32_t arg)",
                  "static inline int fm1_cpu1_wait(void)")
    return record, "\n".join(function_source(header, signature) for signature in signatures)


def instrument(body):
    body = body.replace('__attribute__((section(".c1_text"), noreturn, used)) ', "")
    body = body.replace("FM1_C1_SYNC();", "barrier();")
    body = body.replace("*(volatile uint32_t *)(0x1EEF300u + 4u * i)", "irq_bank[i]")
    addresses = {}
    def mmio(match):
        address = match.group(1)
        return f"registers[{addresses.setdefault(address, len(addresses))}]"
    body = re.sub(r"\*\(volatile uint32_t \*\)(0x[0-9A-Fa-f]+u)", mmio, body)
    body = body.replace("fm1_c1_mb.bad++;", "STORE(bad, LOAD(bad) + 1u);")
    body = re.sub(r"fm1_c1_trace = ([^;]+);", r"STORE_TRACE(\1);", body)
    # Keep lvalue stores distinct from observations, including == comparisons.
    body = re.sub(r"fm1_c1_mb\.(\w+)\s*=(?!=)\s*([^;]+);",
                  r"STORE(\1, \2);", body)
    body = re.sub(r"fm1_c1_mb\.(\w+)", r"LOAD(\1)", body)
    body = body.replace("LOAD(job)", "LOAD_JOB()")
    return body


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
@RECORD@
static fm1_c1_mb_t fm1_c1_mb;
static uint32_t fm1_c1_trace, fm1_c1_wait_max;
static uint8_t fm1_c1_on, fm1_c1_gave_up, fm1_c1_marked;
static uint32_t _c1_ustack[1024], _c1_sstack_top[1], registers[16], irq_bank[32];
#define FM1_C1_STACK_WORDS 1024u
#define FM1_C1_MARK 0x43314D4Bu
#define FM1_C1_CHECK(fn, arg, job) ((uint32_t)(uintptr_t)(fn) ^ (arg) ^ (job) * 0x9E3779B1u)
static uint32_t clock_register, control_register, ticks;
#define FM1_C1_CLK clock_register
#define FM1_C1_CON control_register
#define FM1_C1_T4 timer()
static unsigned scenario, worker, sequence, last_sync, body_store, work_store;
static unsigned observation, acquired, job_reads, calls, halts, pending, payload, trace_store, boot_done_load;
static uint32_t initial_done, next_job, argument;
static uint32_t observed_job[2], backing_job[2];
static jmp_buf worker_exit;
static void fm1_c1_entry(void) {}
static uint32_t timer(void) { ticks += 120001u; return ticks; }
static void work(uint32_t arg) {
    assert(worker && acquired && arg == argument);
    calls++;
    work_store = ++sequence;
}
static void barrier(void) {
    last_sync = ++sequence;
    if (pending) {
        acquired = 1;
        pending = 0;
        payload = 0xCAFEu;
        if (worker) {
            fm1_c1_mb.fn = work;
            fm1_c1_mb.arg = argument;
            fm1_c1_mb.check = FM1_C1_CHECK(work, argument, next_job);
        }
    }
}
static void observe_load(const char *field) {
    sequence++;
    if (worker && !strcmp(field, "job")) {
        if (job_reads++ == (scenario >= 11 ? 2u : 1u)) longjmp(worker_exit, 1);
        if (scenario == 13 || scenario == 14) return;
        fm1_c1_mb.job = next_job;
        pending = 1;
        acquired = 0;
        observation = sequence;
    } else if (worker && !strcmp(field, "done")) {
        assert(last_sync > trace_store);
        boot_done_load = sequence;
    } else if (!worker && !strcmp(field, "done") && scenario == 0) {
        fm1_c1_mb.done = fm1_c1_mb.job;
        pending = 1;
        acquired = 0;
        observation = sequence;
    } else if (!worker && !strcmp(field, "bad") && scenario == 1) {
        fm1_c1_mb.bad = 1;
        pending = 1;
        acquired = 0;
        observation = sequence;
    } else if (!worker && !strcmp(field, "alive") && scenario == 3) {
        assert(last_sync > body_store);
        fm1_c1_mb.alive = 1;
        pending = 1;
        acquired = 0;
        observation = sequence;
    }
    if (worker && (!strcmp(field, "fn") || !strcmp(field, "arg") || !strcmp(field, "check")))
        assert(acquired && last_sync > observation);
}
static uint32_t job_observation(void) {
    uint32_t value = fm1_c1_mb.job;
    if (worker && (scenario == 13 || scenario == 14)) {
        unsigned i = job_reads - 1u;
        assert(i < 2u);
        backing_job[i] = value;
        /* Model a bad read, not a write to RAM; a later read may see the real word again. */
        if (scenario == 14 || !i) value ^= 0x10000000u;
        observed_job[i] = value;
    }
    return value;
}
static void observe_store(const char *field) {
    sequence++;
    if (!strcmp(field, "job")) assert(last_sync > body_store);
    else if (!strcmp(field, "fn") || !strcmp(field, "arg") || !strcmp(field, "check") ||
             !strcmp(field, "bad_fn") || !strcmp(field, "bad_job") || !strcmp(field, "bad_done"))
        body_store = sequence;
    else if (worker && !strcmp(field, "done")) assert(last_sync > work_store);
    else if (worker && !strcmp(field, "bad")) assert(last_sync > body_store);
    else if (worker && !strcmp(field, "alive")) assert(last_sync > boot_done_load);
}
#define LOAD(field) (observe_load(#field), fm1_c1_mb.field)
#define LOAD_JOB() (observe_load("job"), job_observation())
#define STORE(field, value) do { observe_store(#field); fm1_c1_mb.field = (value); } while (0)
#define STORE_TRACE(value) do { trace_store = ++sequence; fm1_c1_trace = (value); } while (0)
#pragma GCC diagnostic ignored "-Wunused-function"
@GUARD@
static uint32_t guard_at_halt = 0xFFFFFFFFu;
static void fm1_cpu1_halt(void) {
    if (scenario == 1) assert(acquired && payload == 0xCAFEu && last_sync > observation);
    guard_at_halt = fm1_c1g_read(0);
    halts++;
}
@PROTOCOL@
int main(int argc, char **argv) {
    assert(argc == 2);
    scenario = (unsigned)atoi(argv[1]);
    fm1_c1_on = 1;
    fm1_c1_mb.job = 17;
    fm1_c1_mb.done = 16;
    if (scenario == 15) {
        fm1_c1_mb.done = fm1_c1_mb.job;
        fm1_c1_mb.bad = 1;
        assert(fm1_cpu1_wait() == -1 && !fm1_c1_on && halts == 1 && fm1_c1_gave_up == 1);
        assert(fm1_c1_mb.done == fm1_c1_mb.job);
        assert(guard_at_halt == FM1_C1X_BAD_JOB && fm1_c1g_read(0) == FM1_C1X_BAD_JOB);
    } else if (scenario <= 2) {
        int result = fm1_cpu1_wait();
        if (!scenario) assert(!result && acquired && payload == 0xCAFEu && last_sync > observation && !halts &&
                              fm1_c1g_read(0) == FM1_C1X_NONE);
        else {
            assert(result == -1 && !fm1_c1_on && halts == 1 && fm1_c1_gave_up == scenario);
            /* the exclusion is retained before the worker is held, and survives as the first reason */
            assert(guard_at_halt == (scenario == 1 ? FM1_C1X_BAD_JOB : FM1_C1X_TIMEOUT));
            assert(fm1_c1g_read(0) == guard_at_halt);
        }
    } else if (scenario <= 4) {
        fm1_c1_on = 0;
        int result = fm1_cpu1_start();
        assert(fm1_c1_marked && fm1_c1_mb.done == fm1_c1_mb.job && !fm1_c1_mb.fn);
        if (scenario == 3) assert(!result && fm1_c1_on && acquired && last_sync > observation &&
                                  fm1_c1g_read(0) == FM1_C1X_ACTIVE && guard_at_halt == FM1_C1X_NONE);
        else assert(result == -1 && !fm1_c1_on && halts == 2 && fm1_c1g_read(0) == FM1_C1X_NONE);
        for (unsigned i = 0; i < FM1_C1_STACK_WORDS; i++) assert(_c1_ustack[i] == FM1_C1_MARK);
    } else if (scenario == 5) {
        assert(fm1_cpu1_run(work, 23));
        assert(fm1_c1_mb.job == 18 && fm1_c1_mb.fn == work && fm1_c1_mb.arg == 23);
        assert(fm1_c1_mb.check == FM1_C1_CHECK(work, 23u, 18u));
        fm1_c1_on = 0;
        uint32_t job = fm1_c1_mb.job;
        assert(!fm1_cpu1_run(work, 24) && fm1_c1_mb.job == job);
    } else {
        worker = 1;
        initial_done = scenario == 10 ? UINT32_MAX : 17u;
        fm1_c1_mb.done = initial_done;
        if (scenario == 13 || scenario == 14) fm1_c1_mb.job = initial_done;
        next_job = initial_done + (scenario == 7 ? 0u : scenario == 8 || scenario == 11 ? 2u : 1u);
        argument = 23u;
        if (!setjmp(worker_exit)) fm1_c1_main();
        assert(fm1_c1_trace == 0xC1000002u && fm1_c1_mb.alive && job_reads == (scenario >= 11 ? 3u : 2u));
        if (scenario == 6 || scenario == 10 || scenario == 12) assert(calls == 1 && fm1_c1_mb.done == next_job && !fm1_c1_mb.bad);
        else if (scenario == 7) assert(!calls && !fm1_c1_mb.bad && fm1_c1_mb.done == initial_done);
        else if (scenario == 13 || scenario == 14) {
            assert(!calls && fm1_c1_mb.bad == 1 && fm1_c1_mb.bad_fn == 0);
            assert(fm1_c1_mb.bad_job == (initial_done ^ 0x10000000u) && fm1_c1_mb.bad_done == initial_done);
            assert(fm1_c1_mb.job == initial_done && fm1_c1_mb.done == initial_done);
            assert(backing_job[0] == initial_done && backing_job[1] == initial_done);
            assert(observed_job[0] == (initial_done ^ 0x10000000u));
            assert(observed_job[1] == (scenario == 13 ? initial_done : initial_done ^ 0x10000000u));
            worker = 0;
            assert(fm1_cpu1_wait() == -1 && !fm1_c1_on && halts == 1 && fm1_c1_gave_up == 1);
            assert(guard_at_halt == FM1_C1X_BAD_JOB && fm1_c1g_read(0) == FM1_C1X_BAD_JOB);
        } else assert(!calls && fm1_c1_mb.bad == 1 && fm1_c1_mb.bad_job == next_job && fm1_c1_mb.bad_done == initial_done);
    }
    return 0;
}
'''


class Cpu1Protocol(unittest.TestCase):
    def compile_run(self, body, scenarios):
        record, _ = protocol_source()
        source = (HARNESS.replace("@RECORD@", record).replace("@PROTOCOL@", instrument(body))
                  .replace("@GUARD@", guard_source()))
        # A corrupted check must exercise the actual worker's refusal path.
        if 9 in scenarios:
            source = source.replace("fm1_c1_mb.check = FM1_C1_CHECK(work, argument, next_job);",
                                    "fm1_c1_mb.check = scenario == 9 ? 0u : FM1_C1_CHECK(work, argument, next_job);")
        with tempfile.TemporaryDirectory(prefix="felucca-cpu1-protocol-") as temporary:
            path = Path(temporary)
            (path / "fixture.c").write_text(source)
            executable = path / "protocol"
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O2",
                            "-Wall", "-Wextra", "-Werror", str(path / "fixture.c"),
                            "-o", str(executable)], check=True)
            return [subprocess.run([str(executable), str(scenario)], capture_output=True, text=True)
                    for scenario in scenarios]

    def test_actual_mailbox_paths(self):
        _, body = protocol_source()
        for scenario, result in enumerate(self.compile_run(body, range(13))):
            self.assertEqual(result.returncode, 0, f"scenario {scenario}: {result.stderr}")

    def test_faulty_job_observations_preserve_bad_job_exclusion(self):
        """Host fault injection checks refusal semantics, not physical read-error reproduction."""
        _, body = protocol_source()
        for scenario, result in zip((13, 14), self.compile_run(body, (13, 14))):
            with self.subTest(persistent=scenario == 14):
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_job_wins_over_matching_completion(self):
        _, body = protocol_source()
        result = self.compile_run(body, [15])[0]
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_acquires_are_detected(self):
        _, body = protocol_source()
        for comment, scenario in (("acquire its finished payload", 0), ("acquire its failure details", 1),
                                  ("acquire the worker's published boot state", 3),
                                  ("acquire core 0's boot state", 6)):
            with self.subTest(comment=comment):
                mutant, count = re.subn(r"^.*FM1_C1_SYNC\(\);[^\n]*" + re.escape(comment) + r"[^\n]*\n", "", body, flags=re.M)
                self.assertEqual(count, 1)
                self.assertNotEqual(self.compile_run(mutant, [scenario])[0].returncode, 0)
        mutant = body.replace("uint32_t j = fm1_c1_mb.job;\n        FM1_C1_SYNC();",
                              "uint32_t j = fm1_c1_mb.job;")
        self.assertNotEqual(mutant, body)
        self.assertNotEqual(self.compile_run(mutant, [6])[0].returncode, 0)

    def test_missing_payload_releases_are_detected(self):
        _, body = protocol_source()
        mutant, count = re.subn(r"^.*FM1_C1_SYNC\(\);[^\n]*release the guards/trace[^\n]*\n", "", body, flags=re.M)
        self.assertEqual(count, 1)
        self.assertNotEqual(self.compile_run(mutant, [6])[0].returncode, 0)
        for marker, scenario in (("fm1_c1_mb.job = job;", 5), ("fm1_c1_mb.done = j;", 6),
                                 ("fm1_c1_mb.bad++;", 8)):
            with self.subTest(marker=marker):
                mutant = body.replace("FM1_C1_SYNC();\n" + " " * (4 if scenario == 5 else 16 if scenario == 6 else 12) + marker, marker)
                self.assertNotEqual(mutant, body)
                self.assertNotEqual(self.compile_run(mutant, [scenario])[0].returncode, 0)

    def test_exclusion_recorded_before_hold(self):
        _, body = protocol_source()
        for marker, scenario in (("fm1_c1g_mark(FM1_C1X_BAD_JOB);", 1), ("fm1_c1g_mark(FM1_C1X_TIMEOUT);", 2)):
            with self.subTest(marker=marker):
                mutant, count = re.subn(r"^.*" + re.escape(marker) + r"[^\n]*\n", "", body, flags=re.M)
                self.assertEqual(count, 1)
                self.assertNotEqual(self.compile_run(mutant, [scenario])[0].returncode, 0)
        late = body.replace("fm1_c1g_mark(FM1_C1X_BAD_JOB);      /* retained first: no later reset restarts it (a ON preference cannot) */\n            fm1_cpu1_hold();",
                            "fm1_cpu1_hold();\n            fm1_c1g_mark(FM1_C1X_BAD_JOB);")
        self.assertNotEqual(late, body)
        self.assertNotEqual(self.compile_run(late, [1])[0].returncode, 0)

LIFECYCLE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#pragma GCC diagnostic ignored "-Wunused-function"
@GUARD@
/* The reset classes of fm1_boot.p3_rst (hal/fm1_sys.h): bit0 power-on, 2 WDT, 4 long press, 6 soft */
#define POR 0x01u
#define WDT 0x04u
#define LONG 0x10u
#define SOFT 0x40u
/* One FM-1 session as main.c runs it (fm1_cstart -> fm1_main): the preference lives in "flash" (pref_flash) and is
 * cleared by the main loop only after it has seen the failure (the deferred save); a reset can come before that. */
static int pref_flash, started;
static uint32_t refused_why;
static void boot_g(uint32_t p3, int pref, int bootguard_failed)
{
    pref_flash = pref;
    fm1_c1g_boot(p3);
    started = 0;
    refused_why = 0;
    if (pref_flash) {                      /* main.c: read whether or not bootguard.failed */
        refused_why = fm1_c1g_refuse();
        if (!bootguard_failed && !refused_why) {
            started = 1;
            fm1_c1g_active();              /* fm1_cpu1_start answered */
        }
    }
}
static void boot(uint32_t p3, int pref) { boot_g(p3, pref, 0); }
static void main_loop_notices(void)        /* main.c: the notice, and the ON preference cleared (settings_later) */
{
    if (refused_why) pref_flash = 0;
}
static uint32_t reason(void) { return fm1_c1g_read(0); }
static uint32_t count(void) { uint32_t n; fm1_c1g_read(&n); return n; }
static void garbage(uint32_t a, uint32_t b) { fm1_c1_guard.magic = a; fm1_c1_guard.state = b; }

int main(int argc, char **argv)
{
    int sc = argc > 1 ? atoi(argv[1]) : -1;
    uint32_t i;
    switch (sc) {
    case 0:  /* invalid retained state: no magic is no record (cold RAM), a wrong rest is refused, never trusted */
        for (i = 0; i < 64u; i++) {
            garbage(0xA5A5A5A5u ^ i, 0xFFFFFFFFu * (i & 1u));
            boot(POR, 1);
            assert(started && reason() == FM1_C1X_ACTIVE && !refused_why);
        }
        garbage(FM1_C1G_MAGIC, 0xA5A5A5A5u);                 /* the magic, a check that does not match */
        assert(reason() == FM1_C1X_CORRUPT);
        boot(SOFT, 1);
        assert(!started && refused_why == FM1_C1X_CORRUPT && reason() == FM1_C1X_CORRUPT && count() == 1u);
        garbage(FM1_C1G_MAGIC, fm1_c1g_pack(9u, 0));         /* a valid check on a reason no code writes */
        boot(SOFT, 1);
        assert(!started && refused_why == FM1_C1X_CORRUPT);
        garbage(FM1_C1G_MAGIC, fm1_c1g_pack(0u, 0));         /* reason 0 is no state */
        boot(SOFT, 1);
        assert(!started && refused_why == FM1_C1X_CORRUPT);
        garbage(FM1_C1G_MAGIC, fm1_c1g_pack(FM1_C1X_FAULT, 4u) ^ 0x10000u);   /* one flipped check bit */
        boot(WDT, 1);
        assert(!started && refused_why == FM1_C1X_CORRUPT && count() == 1u);
        break;
    case 1:  /* cold boot: zeroed RAM, preference OFF and ON; OFF never touches the record */
        garbage(0, 0);
        boot(POR, 0);
        assert(!started && reason() == FM1_C1X_NONE);
        boot(POR, 1);
        assert(started && reason() == FM1_C1X_ACTIVE);
        break;
    case 2: case 3:  /* core 0 faults while the worker answers: early (2) or late (3) is the same record */
        garbage(0, 0);
        boot(POR, 1);
        assert(started);
        fm1_c1g_fault();
        assert(reason() == FM1_C1X_FAULT);
        boot(SOFT, 1);                                       /* the reset after the fault report */
        assert(!started && refused_why == FM1_C1X_FAULT);
        main_loop_notices();
        assert(!pref_flash);
        boot(SOFT, 0);                                       /* OFF afterwards: still held, nothing starts */
        assert(!started && reason() == FM1_C1X_FAULT);
        break;
    case 4: case 5:  /* a bad job (4) or a timeout (5) in the audio ISR, then a reset before the deferred save */
        garbage(0, 0);
        boot(POR, 1);
        fm1_c1g_mark(sc == 4 ? FM1_C1X_BAD_JOB : FM1_C1X_TIMEOUT);
        /* no main_loop_notices(): the reset came first, the flash still says ON */
        boot(SOFT, pref_flash);
        assert(pref_flash == 1 && !started && refused_why == (sc == 4 ? FM1_C1X_BAD_JOB : FM1_C1X_TIMEOUT));
        main_loop_notices();
        assert(!pref_flash);
        fm1_c1g_fault();                                     /* a later fault while held changes nothing */
        fm1_c1g_mark(FM1_C1X_HANG);
        assert(reason() == (sc == 4 ? FM1_C1X_BAD_JOB : FM1_C1X_TIMEOUT));
        break;
    case 6:  /* successful operation: every reset that is not a watchdog leaves no record */
        for (i = 0; i < 4u; i++) {
            static const uint32_t cls[] = {POR, LONG, SOFT, POR | LONG};
            garbage(0, 0);
            boot(POR, 1);
            assert(started && reason() == FM1_C1X_ACTIVE);
            boot(cls[i], 1);                                 /* power-off / planned reboot / update / UBOOT */
            assert(started && !refused_why && reason() == FM1_C1X_ACTIVE);
            fm1_c1g_boot(cls[i]);
            assert(reason() == FM1_C1X_NONE);
        }
        garbage(0, 0);
        boot(POR, 1);
        boot(WDT, 1);                                        /* a hang while it answered */
        assert(!started && refused_why == FM1_C1X_HANG);
        break;
    case 7:  /* repeated warm reset: held across every reset class, counted, saturating, never cleared by time */
        garbage(0, 0);
        boot(POR, 1);
        fm1_c1g_mark(FM1_C1X_TIMEOUT);
        for (i = 1; i <= 600u; i++) {
            static const uint32_t cls[] = {SOFT, WDT, LONG, POR, POR | WDT, 0};
            boot(cls[i % 6u], 1);
            assert(!started && refused_why == FM1_C1X_TIMEOUT);
            assert(count() == (i < 255u ? i : 255u));
        }
        boot(SOFT, 0);                                       /* OFF never counts a refusal or clears it */
        assert(reason() == FM1_C1X_TIMEOUT && count() == 255u);
        break;
    case 8:  /* explicit recovery: only an excluded record, only once, then the worker may start again */
        garbage(0, 0);
        assert(!fm1_c1g_recover());
        boot(POR, 1);
        assert(!fm1_c1g_recover() && reason() == FM1_C1X_ACTIVE);     /* it is answering: nothing to clear */
        fm1_c1g_mark(FM1_C1X_BAD_JOB);
        assert(fm1_c1g_recover() && reason() == FM1_C1X_NONE && !fm1_c1g_recover());
        boot(SOFT, 1);
        assert(started && reason() == FM1_C1X_ACTIVE);
        garbage(FM1_C1G_MAGIC, 0x12345678u);                 /* a corrupt record is recoverable too */
        assert(fm1_c1g_recover());
        boot(SOFT, 1);
        assert(started);
        break;
    case 9:  /* a core 1 fault alone: core 0 does not fault, the record stays ACTIVE until its wait fails */
        garbage(0, 0);
        boot(POR, 1);
        assert(reason() == FM1_C1X_ACTIVE);
        fm1_c1g_mark(FM1_C1X_TIMEOUT);                       /* fm1_cpu1_wait: the parked worker never finishes */
        boot(SOFT, 1);
        assert(!started && refused_why == FM1_C1X_TIMEOUT);
        break;
    case 10: /* a reset between the two stores of a record leaves no record, never a half one */
        for (i = 0; i < 32u; i++) {
            garbage(0x5A5A0000u + i, fm1_c1g_pack(FM1_C1X_FAULT, 1u));   /* state stored, magic not yet */
            boot(SOFT, 1);
            assert(started);
        }
        garbage(0, 0);
        boot(POR, 1);
        fm1_c1g_set(FM1_C1X_FAULT, 0);
        fm1_c1_guard.magic = 0;                              /* the clear cut after its one store */
        boot(SOFT, 1);
        assert(started);
        break;
    case 11: /* the worker's watchdog reset is also a bootguard failure: the hang is still recorded and shown */
        garbage(0, 0);
        boot(POR, 1);
        boot_g(WDT, 1, 1);
        assert(!started && refused_why == FM1_C1X_HANG && reason() == FM1_C1X_HANG && count() == 1u);
        main_loop_notices();
        assert(!pref_flash);                                 /* a lost RAM no longer finds the saved ON */
        boot_g(POR, pref_flash, 0);
        assert(!started);
        break;
    case 12: /* another exclusion together with a bootguard failure: one refusal counted, the preference cleared */
        garbage(0, 0);
        boot(POR, 1);
        fm1_c1g_mark(FM1_C1X_TIMEOUT);
        boot_g(WDT, 1, 1);
        assert(!started && refused_why == FM1_C1X_TIMEOUT && count() == 1u);
        main_loop_notices();
        assert(!pref_flash);
        break;
    case 13: /* a bootguard failure alone: not started, no notice, preference and record untouched */
        garbage(0, 0);
        boot_g(POR, 1, 1);
        assert(!started && !refused_why && reason() == FM1_C1X_NONE && count() == 0u);
        main_loop_notices();
        assert(pref_flash == 1);
        boot(POR, 1);                                        /* the failure passed: it starts */
        assert(started);
        break;
    default:
        return 2;
    }
    return 0;
}
'''


class Cpu1GuardLifecycle(unittest.TestCase):
    """The actual retained-guard functions of hal/fm1_sys.h across simulated resets (#410). Host fixtures:
    they say nothing about whether the device's NOINIT survives a particular reset or a power-off."""

    SCENARIOS = {0: "invalid retained state", 1: "cold boot", 2: "early CPU0 fault", 3: "late CPU0 fault",
                 4: "bad job, reset before the deferred save", 5: "timeout, reset before the deferred save",
                 6: "successful operation", 7: "repeated warm reset", 8: "explicit recovery",
                 9: "core 1 fault alone", 10: "reset between the stores",
                 11: "hang with a bootguard failure", 12: "timeout with a bootguard failure",
                 13: "bootguard failure alone"}

    def compile_run(self, source):
        with tempfile.TemporaryDirectory(prefix="felucca-cpu1-guard-") as temporary:
            path = Path(temporary)
            (path / "fixture.c").write_text(source)
            executable = path / "guard"
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(path / "fixture.c"), "-o", str(executable)], check=True)
            return {n: subprocess.run([str(executable), str(n)], capture_output=True, text=True)
                    for n in self.SCENARIOS}

    def source(self):
        return LIFECYCLE.replace("@GUARD@", guard_source())

    def test_reset_lifecycle(self):
        for n, result in self.compile_run(self.source()).items():
            self.assertEqual(result.returncode, 0, f"{self.SCENARIOS[n]}: {result.stderr}")

    def test_startup_order_in_main(self):
        main = (ROOT / "firmware/src/main.c").read_text()
        cstart = main[main.index("void fm1_cstart(void)"):]
        self.assertLess(cstart.index("fm1_c1g_boot(p3)"), cstart.index("_bss_start"))
        self.assertLess(cstart.index("fm1_reset_reason()"), cstart.index("fm1_c1g_boot(p3)"))
        gate = main[main.index("c1_refused = fm1_c1g_refuse();"):]
        self.assertIn("if (ui_prefs2 & (PREF_CPU2_ON >> 16)) {\n", main[main.index("kb_boot_hold = 1;"):main.index("c1_refused = fm1_c1g_refuse();")])
        self.assertNotIn("bootguard", main[main.index("kb_boot_hold = 1;"):main.index("c1_refused = fm1_c1g_refuse();")].split("*/")[-1])
        self.assertIn("if (!bootguard.failed && !c1_refused) {", gate[:gate.index("fm1_cpu1_start();")])
        self.assertLess(gate.index("fm1_c1g_refuse"), gate.index("fm1_cpu1_start();"))
        self.assertIn("settings_later();", main[main.index("if (!c1_told)"):main.index("ui_message(c1_held_msg(why))")])
        self.assertNotIn("settings_later", main[main.index("c1_refused = fm1_c1g_refuse();"):main.index("fm1_cpu1_start();")])
        table = main[main.index("static const char *c1_held_msg"):]
        messages = re.findall(r'"(2ND CORE[^"]*)"', table[:table.index("return m[")])
        self.assertEqual(len(messages), 6)
        for text in messages + re.findall(r'"(2ND CORE RETRY[^"]*)"', (ROOT / "firmware/src/menu_items.c").read_text()):
            self.assertLessEqual(len(text), 23, text)     # ui.msg holds 23 characters

    def test_a_policy_regression_is_detected(self):
        source = self.source()
        mutants = {
            "an invalid record trusted": source.replace("return FM1_C1X_CORRUPT;\n    if (count)", "return FM1_C1X_NONE;\n    if (count)"),
            "a hang forgotten": source.replace("fm1_c1g_set(FM1_C1X_HANG, 0);", "fm1_c1g_clear();"),
            "a refused start cleared": source.replace("fm1_c1g_set(r, n < 255u ? n + 1u : n);\n    return r;", "fm1_c1g_clear();\n    return r;"),
            "the first reason replaced": source.replace("if (!fm1_c1g_excluded(fm1_c1g_read(0)))\n        fm1_c1g_set(reason, 0);", "fm1_c1g_set(reason, 0);"),
        }
        for name, mutant in mutants.items():
            with self.subTest(name):
                self.assertNotEqual(mutant, source)
                self.assertTrue(any(r.returncode for r in self.compile_run(mutant).values()))


if __name__ == "__main__":
    unittest.main()
