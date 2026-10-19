/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* FM-1 interrupt / exception HAL.
 *
 *   fm1_irq_init()        first thing in cstart: all ICFG off, pendings and
 *                         exception causes cleared, all 128 vectors -> fatal
 *                         stubs (fm1_vec.S), vector 1 (CPU
 *                         exception) enabled at prio 7, ETM on, div0 trap
 *                         off (see below).
 *   fm1_irq_attach(n, h, prio)   h = asm wrapper (fm1_isr.S), prio 0..7
 *   fm1_irq_enable_all()  icfg bit 8 + sti, after every source is set up
 *
 * The application supplies fm1_fault(const fm1_crash_t *) which reports the
 * crash (LCD) and resets; the record survives in .noinit for the next boot.
 */
#pragma once
#include <stdint.h>
#define FM1_IRQ_TARGET 1

#define FM1_VEC ((volatile uint32_t *)0x01C7FE00u)
#define FM1_ICFG(n) (*(volatile uint32_t *)(0x1EEF100u + 4u * ((n) >> 3)))
#define FM1_IPND(i) (*(volatile uint32_t *)(0x1EEF180u + 4u * (i)))
#define FM1_ILAT_SET (*(volatile uint32_t *)0x1EEF1A0u)
#define FM1_ILAT_CLR (*(volatile uint32_t *)0x1EEF1A4u)
#define FM1_EMU_CON (*(volatile uint32_t *)0x1EEF0D0u)
#define FM1_EMU_MSG (*(volatile uint32_t *)0x1EEF0D4u)
#define FM1_ETM_CON (*(volatile uint32_t *)0x1EEF1C0u)
#define FM1_ETM_PC(i) (*(volatile uint32_t *)(0x1EEF1C4u + 4u * (i)))
#define FM1_DBG_WR_EN (*(volatile uint32_t *)0x1EEE240u)
#define FM1_DBG_MSG (*(volatile uint32_t *)0x1EEE244u)
#define FM1_DBG_MSG_CLR (*(volatile uint32_t *)0x1EEE248u)
#define FM1_DBG_EN (*(volatile uint32_t *)0x1EEE340u)

enum { FM1_IRQ_EXCEPTION = 1, FM1_IRQ_ALNK0 = 11, FM1_IRQ_SPI1 = 16, FM1_IRQ_UART1 = 20,
       FM1_IRQ_SARADC = 24, FM1_IRQ_SPI2 = 37, FM1_IRQ_TIMER5 = 63, FM1_IRQ_SOFT0 = 120 };

static inline uint32_t fm1_icfg(void) { uint32_t v; __asm__ volatile("%0 = icfg" : "=r"(v)); return v; }
static inline void fm1_icfg_set(uint32_t v) { __asm__ volatile("icfg = %0" ::"r"(v) : "memory"); }
static inline void fm1_irq_off(void) { __asm__ volatile("cli" ::: "memory"); }
static inline void fm1_irq_on(void) { __asm__ volatile("csync\n\tsti" ::: "memory"); }

#define FM1_CRASH_MAGIC 0x43525348u          /* "CRSH" */
/* FELUCCA_CRASH_CTX=1 (build.py; a diagnostic build for the #425 soak, #428): the record also keeps the faulting
 * core's r0..r15, usp and ssp (+76 B NOINIT, below the 100 B spare floor that release and standard builds keep).
 * `ctx` = FM1_CRASH_CTX_KEY ^ count marks registers written with this record, not left by another firmware whose
 * record sat at the same address. 0 (the default): none of it, the record and its code as before. */
#ifndef FELUCCA_CRASH_CTX
#define FELUCCA_CRASH_CTX 0
#endif
#define FM1_CRASH_CTX_KEY 0x43545852u        /* "CTXR" */
typedef struct {
    uint32_t magic, count, vec, pc, rets, emu, dbg, sp, psr, icfg, uptime_ms;
    uint32_t etm[4];
    uint32_t early;                          /* consecutive crashes < 3 s after boot */
#if FM1_CPU1_USED
    uint32_t core;                           /* 1 = the second core's (its sp on its stacks, hal/fm1_cpu1.h) */
#endif
#if FELUCCA_CRASH_CTX
    uint32_t ctx;                            /* FM1_CRASH_CTX_KEY ^ count: r/usp/ssp belong to this record */
    uint32_t r[16], usp, ssp;                /* the faulting core's registers as fm1_fatal_common saved them */
#endif
} fm1_crash_t;
/* Not static: .noinit holds whatever the last run (or power-on) left, and a
 * file-local object would let the compiler assume its zero initial value and
 * fold the magic check away. */
fm1_crash_t fm1_crash __attribute__((section(".noinit")));

/* A worker may replace this record while core 0 requests diagnostics. Use
 * volatile word loads and the HAL's CSYNC ordering, not the live object while
 * formatting output. The pre-copy marker check rejects an already invalidated
 * record whose new count was read; the final marker/count reject replacement
 * during copying, including valid -> invalid -> valid. One bounded attempt;
 * a failed copy is invalid and may be retried by the caller later. This does
 * not claim cache invalidation or qualify the device's dual-core reliability. */
static int fm1_crash_read(fm1_crash_t *copy)
{
    const volatile fm1_crash_t *shared = &fm1_crash;
    uint32_t count, i;
    copy->magic = 0;
    __asm__ volatile("csync" ::: "memory");
    if (shared->magic != FM1_CRASH_MAGIC)
        return 0;
    count = shared->count;
    __asm__ volatile("csync" ::: "memory");
    if (shared->magic != FM1_CRASH_MAGIC)
        return 0;
    __asm__ volatile("csync" ::: "memory");
    copy->count = count;
    copy->vec = shared->vec;
    copy->pc = shared->pc;
    copy->rets = shared->rets;
    copy->emu = shared->emu;
    copy->dbg = shared->dbg;
    copy->sp = shared->sp;
    copy->psr = shared->psr;
    copy->icfg = shared->icfg;
    copy->uptime_ms = shared->uptime_ms;
    for (i = 0; i < 4u; i++)
        copy->etm[i] = shared->etm[i];
    copy->early = shared->early;
#if FM1_CPU1_USED
    copy->core = shared->core;
#endif
#if FELUCCA_CRASH_CTX
    copy->ctx = shared->ctx;
    for (i = 0; i < 16u; i++)
        copy->r[i] = shared->r[i];
    copy->usp = shared->usp;
    copy->ssp = shared->ssp;
#endif
    __asm__ volatile("csync" ::: "memory");
    if (shared->magic != FM1_CRASH_MAGIC)
        return 0;
    __asm__ volatile("csync" ::: "memory");
    if (shared->count != count)
        return 0;
    copy->magic = FM1_CRASH_MAGIC;
    return 1;
}

extern const char fm1_fatal_stubs[];
static void fm1_fault(const fm1_crash_t *c);   /* application: report, then reset */

static void fm1_irq_init(void)
{
    uint32_t i;
    for (i = 0; i < 32u; i++)
        *(volatile uint32_t *)(0x1EEF100u + 4u * i) = 0;   /* every source off (CPU0 bank) */
    FM1_ILAT_CLR = 0xFFu;
    FM1_EMU_MSG = 0xFFFFFFFFu;
    if (!(FM1_DBG_WR_EN & 1u))
        FM1_DBG_WR_EN = 0xE7u;                              /* unlock */
    FM1_DBG_MSG_CLR = 0xFFFFFFFFu;
    for (i = 0; i < 128u; i++)
        FM1_VEC[i] = (uint32_t)(uintptr_t)(fm1_fatal_stubs + 6u * i);
    FM1_ICFG(1) = (FM1_ICFG(1) & ~0xF0u) | 0xF0u;           /* exception: enable, prio 7 */
    /* div0 trap off (cleared, in case a reset kept it from a build that armed it): this compiler treats a
     * divide as harmless and runs a loop-invariant one ahead of the test that guards it (#61: fm4_convert at boot, after PR #111 by spinkham),
     * and the build has some 300 divides by a register. Off, such a divide gives a value nobody uses; the cost:
     * a real divide by 0 gives a wrong value instead of a crash report (the host tests trap on one) */
    FM1_EMU_CON &= ~(1u << 2);
    FM1_ETM_CON |= 1u;                                      /* branch trace for the report */
}

static void fm1_irq_attach(uint32_t n, void (*h)(void), uint32_t prio)   /* IRQs off */
{
    uint32_t sh = (n & 7u) * 4u;
    FM1_VEC[n] = (uint32_t)(uintptr_t)h;
    FM1_ICFG(n) = (FM1_ICFG(n) & ~(0xFu << sh)) | ((((prio & 7u) << 1) | 1u) << sh);
}
static void fm1_irq_mask(uint32_t n) { FM1_ICFG(n) &= ~(1u << ((n & 7u) * 4u)); }

static void fm1_irq_enable_all(void)
{
    fm1_icfg_set(fm1_icfg() | 0x100u);
    fm1_irq_on();
}

/* called from fm1_fatal_common (fm1_vec.S) with the saved frame:
 * f[0..15] r0..r15, f[16] reti, f[17] rete, f[18] retx, f[19] stub+6,
 * f[20] psr, f[21] icfg, f[22] usp, f[23] ssp, f[24] sp, f[25] interrupted rets */
#if FM1_CPU1_USED
extern uint32_t _c1_ustack[], _c1_sstack_top[];  /* fm1_cpu1.S */
#endif
void fm1_fault_c(uint32_t *f)
{
    static volatile uint32_t in_fault;
    uint32_t i, count, early, emu, dbg, etm[4];
#if FM1_CPU1_USED
    if (f[24] >= (uint32_t)(uintptr_t)_c1_ustack && f[24] <= (uint32_t)(uintptr_t)_c1_sstack_top) {
        /* the second core faulted (after Jangada): this runs on it. Its record only, no screen and no reset from
         * here (a reset from core 1 would hold core 1 first, itself: a frozen FM-1). It stops; core 0's next wait
         * times out (fm1_cpu1_wait), holds it, and the FM-1 goes on with one core */
        /* Invalidate the retained record before replacing it. The CPU0 diagnostic
         * registers below cannot describe this worker fault; clear their fields
         * and the boot-crash streak (the worker parks, it does not reboot). */
        count = fm1_crash.magic == FM1_CRASH_MAGIC ? fm1_crash.count : 0;
        fm1_crash.magic = 0;
        __asm__ volatile("csync" ::: "memory");
        fm1_crash.count = count + 1u;
        fm1_crash.core = 1;
        fm1_crash.vec = (f[19] - (uint32_t)(uintptr_t)fm1_fatal_stubs) / 6u - 1u;
        fm1_crash.pc = f[16];
        fm1_crash.rets = f[25];
        fm1_crash.sp = f[24];
        fm1_crash.psr = f[20];
        fm1_crash.icfg = f[21];
        fm1_crash.uptime_ms = *(volatile uint32_t *)0x10804u / 24000u;
        fm1_crash.emu = 0;
        fm1_crash.dbg = 0;
        for (i = 0; i < 4u; i++)
            fm1_crash.etm[i] = 0;
        fm1_crash.early = 0;
#if FELUCCA_CRASH_CTX
        for (i = 0; i < 16u; i++)
            fm1_crash.r[i] = f[i];
        fm1_crash.usp = f[22];
        fm1_crash.ssp = f[23];
        fm1_crash.ctx = FM1_CRASH_CTX_KEY ^ (count + 1u);
#endif
        __asm__ volatile("csync" ::: "memory");
        fm1_crash.magic = FM1_CRASH_MAGIC;
        __asm__ volatile("csync" ::: "memory");
        for (;;)
            ;
    }
#endif
    fm1_irq_off();
#if FM1_CPU1_USED
    fm1_c1g_fault();                          /* core 0's own fault while the worker answered: refuse its restart (#410) */
#endif
    if (in_fault++) {                         /* fault while reporting: reset at once */
        FM1_RESET_PREP();
        *(volatile uint32_t *)0x10000u |= 1u << 4;
    }
    /* Preserve the exception causes before halt clears bus-debug flags. Stop
     * the worker before reading or replacing its shared retained record: the
     * main core owns it exclusively through reporting and reboot from here. */
    emu = FM1_EMU_MSG;
    dbg = FM1_DBG_MSG;
    for (i = 0; i < 4u; i++)
        etm[i] = FM1_ETM_PC(i);
    FM1_RESET_PREP();
    count = fm1_crash.magic == FM1_CRASH_MAGIC ? fm1_crash.count : 0;
    early = fm1_crash.magic == FM1_CRASH_MAGIC ? fm1_crash.early : 0;
    fm1_crash.magic = 0;
    __asm__ volatile("csync" ::: "memory");
    fm1_crash.count = count + 1u;
    fm1_crash.vec = (f[19] - (uint32_t)(uintptr_t)fm1_fatal_stubs) / 6u - 1u;
    fm1_crash.pc = f[16];
    fm1_crash.rets = f[25];
    fm1_crash.emu = emu;
    fm1_crash.dbg = dbg;
    fm1_crash.sp = f[24];
    fm1_crash.psr = f[20];
    fm1_crash.icfg = f[21];
    fm1_crash.uptime_ms = *(volatile uint32_t *)0x10804u / 24000u;   /* TIMER4 since boot */
    for (i = 0; i < 4u; i++)
        fm1_crash.etm[i] = etm[i];
    fm1_crash.early = fm1_crash.uptime_ms < 3000u ? early + 1u : 0u;
#if FM1_CPU1_USED
    fm1_crash.core = 0;
#endif
#if FELUCCA_CRASH_CTX
    for (i = 0; i < 16u; i++)
        fm1_crash.r[i] = f[i];
    fm1_crash.usp = f[22];
    fm1_crash.ssp = f[23];
    fm1_crash.ctx = FM1_CRASH_CTX_KEY ^ (count + 1u);
#endif
    __asm__ volatile("csync" ::: "memory");
    fm1_crash.magic = FM1_CRASH_MAGIC;
    __asm__ volatile("csync" ::: "memory");
    fm1_fault(&fm1_crash);
    for (;;)
        ;
}
