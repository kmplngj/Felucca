/* SPDX-License-Identifier: MPL-2.0
 * Copyright (c) 2026 Julius Vitkauskas */
/* Adapted from felucca-bsp aceed7e0095e9fa8da425f3ecf29e5213f4c5097, PR #12.
 * Host model of fm1_flash_wait.h, the completion wait of fm1_flash.h's erase and page program: a NOR part that
 * stays busy for a set time after the command (or for ever), TIMER4 advancing with each status read, and the
 * driver's sequence around the wait (command, fl_wait_issued, then XIP back on). Checks that XIP never comes back
 * while the part is busy, the return codes at the normal bound, the reset at (and only at) the extended bound, and
 * the same across the TIMER4 wrap.
 *
 * tests/flash_wait_test.py supplies the actual RAM driver, app wrappers and loader
 * hook bodies against the low-level model below. No target assembly is emulated.
 * Run: python3 tests/flash_wait_test.py
 */
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>

#define RAMINL static inline
static uint32_t now;                    /* TIMER4: 24 ticks per us */
static uint32_t ready_at;               /* the tick BUSY clears at */
static int stuck;                       /* never clears */
static uint32_t poll_ticks = 24;        /* what one status read costs */
static uint32_t status_reads;
static jmp_buf reset_point;
static uint32_t operation_busy_us, command_start, commands, exits, irq_windows;
static int issued_command, xip_off, xip_on_while_busy, wel = 1;
static uint8_t command;
static unsigned mode;

static int part_busy(void) { return stuck || (int32_t)(ready_at - now) > 0; }
static uint8_t fl_rdsr(uint8_t cmd)
{
    uint8_t sr = !issued_command ? (wel ? 2u : 0u) :
        (part_busy() ? 0x03u : 0x00u);   /* BUSY | WEL while the operation runs */
    (void)cmd;
    status_reads++;
    now += poll_ticks;                  /* the read itself takes time; the status is the one at its start */
    return sr;
}
#define T4_CNT now
/* Exercise the real reset wrapper against the native reset helper's host hook. */
static _Noreturn void fm1_core_reset(void) { longjmp(reset_point, 1); }
#include "flash_reset.inc"
#include "../firmware/hal/fm1_flash_wait.h"

/* Only low-level hardware operations are replaced. The generated include is
 * copied from current production function bodies, including the loader hooks. */
#define RAMFN
#define FL_FAR(fn) (fn)
/* Valid test subsets of the unchanged app-store and loader-app policies. */
#define FL_RANGE_OK(off, n) (mode < 2 ? \
    ((off) >= 0x97000u && (off) <= 0xE0000u && (n) <= 0xE0000u - (off)) : \
    ((off) >= 0x4000u && (off) <= 0x97000u && (n) <= 0x97000u - (off)))
typedef struct { uint32_t unused; } fl_saved_t;
static int fl_enter(fl_saved_t *s) { (void)s; xip_off = 1; return 0; }
static void fl_exit(const fl_saved_t *s)
{
    (void)s;
    xip_on_while_busy |= issued_command && part_busy();
    xip_off = 0;
    exits++;
}
static void fl_wren(void) { }
static void fl_cs(int high)
{
    if (!high) { command = 0; command_start = now; }
    else if (command == 0x20 || command == 0x02) {
        ready_at = command_start + 24u * operation_busy_us;
        now += 24u * 10u;       /* command transfer */
        issued_command = 1;
        commands++;
    }
}
static void fl_tx(uint8_t b) { if (!command) command = b; }
static void fl_addr(uint32_t off) { (void)off; }
static void fl_inval(uint32_t off, uint32_t n)
{
    (void)off; (void)n;
    now += 24u * 10u;           /* cache invalidation */
}
static uint32_t irq_save(void) { irq_windows++; return 0; }
static void irq_restore(uint32_t f) { (void)f; }
#include "flash_driver.inc"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

typedef struct { int reset, rc, xip_on_while_busy; uint32_t took, elapsed_us; } result_t;

/* Actual application wrappers and loader direct-call hooks. The NOR command
 * transfer/invalidation and status-read costs advance the simulated TIMER4. */
static result_t operation(uint32_t start, uint32_t busy_us, int never)
{
    result_t r = {0, 0, 0, 0xFFFFFFFFu, 0};
    uint8_t src[16] = {0};
    uint32_t off = mode < 2 ? 0x97000u : 0x4000u;
    now = start;
    stuck = never;
    operation_busy_us = busy_us;
    issued_command = xip_off = xip_on_while_busy = 0;
    commands = exits = irq_windows = 0;
    if (setjmp(reset_point)) {
        r.reset = 1;
        r.xip_on_while_busy = xip_on_while_busy || !xip_off || exits != 0 || commands != 1;
        r.elapsed_us = (now - command_start) / 24u;
        return r;
    }
    switch (mode) {
    case 0: r.rc = fl_erase4k(off, &r.took); break;
    case 1: r.rc = fl_write(off, src, sizeof src); break;
    case 2: r.rc = ldr_erase(off); break;
    default: r.rc = ldr_prog(off, src, sizeof src); break;
    }
    r.xip_on_while_busy = xip_on_while_busy || xip_off || exits != 1 || commands != (wel ? 1u : 0u) ||
        irq_windows != (mode < 2 ? 1u : 0u);
    r.elapsed_us = (now - command_start) / 24u;
    if (mode != 0) r.took = r.elapsed_us;  /* wrapper/loader timing output is local */
    return r;
}

static void bounds(uint32_t normal, uint32_t extended, uint32_t start)
{
    result_t r;
    r = operation(start, 100u, 0);                 /* quick */
    CHECK(!r.reset && r.rc == 0 && !r.xip_on_while_busy && r.took >= 100u && r.took <= 102u);
    r = operation(start, normal - 2u, 0);          /* seen idle by the normal bound */
    CHECK(!r.reset && r.rc == 0 && !r.xip_on_while_busy && r.took <= normal);
    r = operation(start, normal + 2u, 0);          /* just past it: late, but only once idle */
    CHECK(!r.reset && r.rc == FL_ERR_LATE_READY && !r.xip_on_while_busy && r.took > normal);
    r = operation(start, extended - 3u, 0);        /* just inside the extended bound */
    CHECK(!r.reset && r.rc == FL_ERR_LATE_READY && !r.xip_on_while_busy && r.took < extended);
    r = operation(start, 0, 1);                    /* stuck: reset at the extended bound */
    CHECK(r.reset && r.elapsed_us >= extended && r.elapsed_us <= extended + 2u);
    r = operation(start, extended + 1000u, 0);     /* would clear later: reset all the same */
    CHECK(r.reset && r.elapsed_us >= extended && r.elapsed_us <= extended + 2u);
}

int main(void)
{
    uint32_t seed = 12345u, i;
    CHECK(FL_ERR_LATE_READY == -4);             /* fl_wait_ready's code for a part busy at the bound */
    for (mode = 0; mode < 4; mode++) {
        uint32_t normal = mode & 1u ? 10000u : 500000u, extended = mode & 1u ? 50000u : 2000000u;
        poll_ticks = 24;
        bounds(normal, extended, 1000u);
        bounds(normal, extended, 0xFFFFFFFFu - 24u * (normal / 2u)); /* TIMER4 wrap */
        wel = 0;
        result_t refused = operation(1000u, 0u, 0);
        CHECK(refused.rc == -3 && !refused.reset && !refused.xip_on_while_busy);
        wel = 1;
        /* any busy time and poll cost: never XIP while busy; reset only with the part busy at or past the extended
         * bound; 0 exactly when the part was seen idle within the normal bound */
        for (i = 0; i < 20000u; i++) {
            uint32_t busy, start;
            result_t r;
            seed = seed * 1664525u + 1013904223u; busy = seed % (extended + extended / 4u);
            seed = seed * 1664525u + 1013904223u; start = seed;
            seed = seed * 1664525u + 1013904223u; poll_ticks = 1u + seed % (24u * 500u);
            r = operation(start, busy, (seed >> 20) % 50u == 0u);
            CHECK(!r.xip_on_while_busy);
            if (r.reset)
                CHECK(r.elapsed_us >= extended && (stuck || busy >= extended - 500u));
            else
                CHECK(r.took >= busy && r.took < extended + 500u &&
                      r.rc == (r.took <= normal ? 0 : FL_ERR_LATE_READY));
            if (fails) break;
        }
    }
    printf(fails ? "%d failed\n" : "flash_wait: four actual app/loader paths passed (80000 randomized cases; %u status reads)\n",
           fails ? (unsigned)fails : (unsigned)status_reads);
    return fails != 0;
}
