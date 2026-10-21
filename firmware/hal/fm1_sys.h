/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* FM-1 system HAL: P33 access, watchdog, reset reason, reboot / UBOOT entry
 * No vendor code; call with interrupts off
 * (no IRQs are enabled yet, so nothing else touches P33).
 *
 *   fm1_reset_reason()   snapshot P3_RST_SRC / RST_SRC (call first thing)
 *   fm1_wdt_arm(t)       reset-mode watchdog, t = 0xA 1 s .. 0xF 32 s
 *   fm1_wdt_feed()       in the main loop
 *   fm1_reboot()         chip reset through P33 (P3_PR_PWR bit 4)
 *   fm1_enter_uboot()    "usb_update_mode" at 0x01C7FD80 + chip reset
 *   fm1_enter_update(p)  112-byte UPDATA_PARM record at 0x01C7FD88 + core reset
 *                        (the SPL then runs the staged update loader)
 *   fm1_core_reset()     PWR_CON core reset
 *   (FM1_CPU1_USED, FELUCCA_CPU2 built in: each of these holds the second core first, fm1_cpu1_halt; registers only,
 *   harmless when it never ran: MENU > 2ND CORE OFF)
 *   fm1_updata_parm_clear()  zero the record (CRC 0: ignored on a warm reset)
 *   fm1_mailbox_clear()  zero 0x01C7FD80..0x01C7FDFF (boot info, mailbox) at cold start
 *   fm1_mem_readable(a, n) / fm1_peek8(a)   debug reads of RAM / XIP only
 */
#pragma once
#include <stdint.h>
#include "fm1_cc.h"

#define FM1_P33_CON (*(volatile uint32_t *)0x13E08u)
#define FM1_P33_DAT (*(volatile uint32_t *)0x13E0Cu)
#define FM1_RST_SRC (*(volatile uint32_t *)0x100C0u)
#define FM1_BOOT_STATE ((volatile uint8_t *)0x01C7FD80u)
#define FM1_PWR_CON (*(volatile uint32_t *)0x10000u)
#define FM1_UPDATA_PARM ((volatile uint8_t *)0x01C7FD88u)
#define FM1_UPDATA_PARM_LEN 112u

static uint32_t fm1_p33_timeouts;

/* ------------------------------------------------------- second core --- */
/* FM1_CPU1_USED (src/felucca.c: FELUCCA_CPU2, built in by default since 1.6.1; fm1_cpu1.h): the second core may be running. Every
 * reset below holds it first: its waiting loop sits in RAM that the ROM, the SPL and the update loader use at boot, and
 * a core left running there would execute whatever they put in it. Hold: C1_CON bit 1 set, then bit 3 (enable)
 * cleared; registers only, safe when it never ran. Without FM1_CPU1_USED none of this is built.
 *
 * The bus-invalid traps are off around the hold. Holding core 1 cuts the read it has on the bus (its waiting loop
 * reads the mailbox all the time), and the chip flags that a few instructions later as an AXI read invalid
 * (DBG_MSG bit 4): with the traps on (fm1_guard.h FM1_GUARD_BUS) core 0 took the exception, so 1 in 6 updates
 * with 2ND CORE ON ended in a crash report and a plain reboot before the update record was written, and the SPL
 * started Felucca instead of the update loader ("the update loader did not appear"). So: traps off, hold, wait for
 * the flag, clear it, traps back as they were */
#ifndef FM1_CPU1_USED
#define FM1_CPU1_USED 0
#endif
#if FM1_CPU1_USED
#define FM1_C1_CON (*(volatile uint32_t *)0x1EEE004u)
#define FM1__DBG_WR_EN (*(volatile uint32_t *)0x1EEE240u)  /* (fm1_irq.h FM1_DBG_*: this header comes first) */
#define FM1__DBG_MSG_CLR (*(volatile uint32_t *)0x1EEE248u)
#define FM1__DBG_EN (*(volatile uint32_t *)0x1EEE340u)
#define FM1__DBG_BUS 0x003F0030u                 /* bus-invalid traps: AXI rd/wr (4, 5), C0/C1 fetch/rd/wr (16..21) */
FM1_INLINE void fm1_cpu1_halt(void)
{
    uint32_t locked = !(FM1__DBG_WR_EN & 1u), en, bus = FM1__DBG_BUS;
    volatile uint32_t n;
    __asm__("" : "+r"(bus));                     /* (~bus as a constant is 0xFFC0FFCF: build.py's stock-helper check) */
    if (locked)
        FM1__DBG_WR_EN = 0xE7u;                  /* unlock (as fm1_guard.h) */
    en = FM1__DBG_EN;
    FM1__DBG_EN = en & ~bus;
    __asm__ volatile("csync" ::: "memory");
    FM1_C1_CON |= 0x2u;
    FM1_C1_CON &= ~0x8u;
    __asm__ volatile("csync" ::: "memory");
    for (n = 0; n < 256u; n++)                   /* the flag comes some instructions after the hold */
        ;
    FM1__DBG_MSG_CLR = FM1__DBG_BUS;
    __asm__ volatile("csync" ::: "memory");
    FM1__DBG_EN = en;
    if (locked && (FM1__DBG_WR_EN & 1u))
        FM1__DBG_WR_EN = 0xE7u;                  /* lock again */
    __asm__ volatile("csync" ::: "memory");
}

/* ---------------------------------------------------- retained CPU1 guard --- */
/* An opt-in worker that failed must not start again just because a reset came before the ON preference was saved
 * off, or because the failure was core 0's own fault or hang while it ran (#410; the idea and the 8-byte retained
 * record are fm1-x0x's ed35a452, github.com/charlesvestal/fm1-x0x, GPL-3.0, rewritten for this HAL and policy).
 *
 * Two words in .noinit (8 B, only with the second core built in): MAGIC, and a state word
 * reason | count << 8 | ~(reason | count << 8) << 16. Reasons: 1 BAD_JOB and 2 TIMEOUT (fm1_cpu1_wait, recorded
 * before the worker is held), 3 FAULT (core 0 faulted while the worker answered), 4 HANG (a watchdog reset while it
 * answered, found at the next boot), 5 CORRUPT (the magic matched, the rest did not: refused, not trusted), 0x0F
 * ACTIVE (it answers; no failure yet). Any other magic is the same as no record: the cold-RAM case, nothing refuses.
 * Each store is one word and the state is stored before the magic, so a reset between two stores leaves either no
 * record or a whole one. Written by core 0 only (the audio ISR, the fault handler, the main loop); never by the
 * worker and never in flash.
 *
 * Policy: an exclusion (1..5) stays through every reset class, power-on included, because decay of NOINIT after
 * power-off is not established on this device. Only fm1_c1g_recover (MENU > 2ND CORE set ON again by the player)
 * clears it; the deferred ON preference is cleared by main.c but never decides this. ACTIVE is consumed at every
 * boot: a WDT reset means HANG, anything else (power-off, UBOOT, update, planned reboot) leaves no record. */
#define FM1_C1G_MAGIC 0x43315847u                /* "C1XG" */
enum { FM1_C1X_NONE = 0, FM1_C1X_BAD_JOB = 1, FM1_C1X_TIMEOUT = 2, FM1_C1X_FAULT = 3, FM1_C1X_HANG = 4,
       FM1_C1X_CORRUPT = 5, FM1_C1X_ACTIVE = 0x0Fu };
typedef struct { volatile uint32_t magic, state; } fm1_c1g_t;
/* Not static: .noinit holds whatever the last run left, and the compiler must not fold the magic check away. */
fm1_c1g_t fm1_c1_guard __attribute__((section(".noinit")));

static uint32_t fm1_c1g_pack(uint32_t reason, uint32_t count)
{
    uint32_t low = (reason & 0xFFu) | (count & 0xFFu) << 8;
    return low | (~low & 0xFFFFu) << 16;
}

/* the record's reason (NONE without a matching magic; CORRUPT for a bad check or an unknown reason); *count: how
 * many starts it has refused, saturating at 255 */
static uint32_t fm1_c1g_read(uint32_t *count)
{
    uint32_t st, r;
    if (count)
        *count = 0;
    if (fm1_c1_guard.magic != FM1_C1G_MAGIC)
        return FM1_C1X_NONE;
    st = fm1_c1_guard.state;
    r = st & 0xFFu;
    if ((st >> 16) != (~st & 0xFFFFu) || !((r >= FM1_C1X_BAD_JOB && r <= FM1_C1X_CORRUPT) || r == FM1_C1X_ACTIVE))
        return FM1_C1X_CORRUPT;
    if (count)
        *count = (st >> 8) & 0xFFu;
    return r;
}

static void fm1_c1g_set(uint32_t reason, uint32_t count)
{
    fm1_c1_guard.state = fm1_c1g_pack(reason, count);
    __asm__ volatile("csync" ::: "memory");
    fm1_c1_guard.magic = FM1_C1G_MAGIC;
    __asm__ volatile("csync" ::: "memory");
}

static void fm1_c1g_clear(void)
{
    fm1_c1_guard.magic = 0;
    __asm__ volatile("csync" ::: "memory");
}

static int fm1_c1g_excluded(uint32_t r)
{
    return r >= FM1_C1X_BAD_JOB && r <= FM1_C1X_CORRUPT;
}

/* first thing at boot (fm1_cstart), p3 = the P33 reset source (bit 2: WDT). Settles the record for this session */
static void fm1_c1g_boot(uint32_t p3)
{
    uint32_t n, r = fm1_c1g_read(&n);
    if (r == FM1_C1X_NONE)
        fm1_c1g_clear();                         /* cold RAM or never used: a clean record from here */
    else if (r == FM1_C1X_ACTIVE) {
        if (p3 & 4u)
            fm1_c1g_set(FM1_C1X_HANG, 0);        /* the worker answered and the chip reset on the watchdog */
        else
            fm1_c1g_clear();                     /* power-off or a planned reset: not a failure */
    } else if (r == FM1_C1X_CORRUPT)
        fm1_c1g_set(FM1_C1X_CORRUPT, 0);         /* normalised: one whole record that stays refused */
}

/* the worker answers: record it, unless an earlier failure is still held (that stays) */
static void fm1_c1g_active(void)
{
    if (!fm1_c1g_excluded(fm1_c1g_read(0)))
        fm1_c1g_set(FM1_C1X_ACTIVE, 0);
}

/* a failure, before the worker is held or the system resets: the first reason is kept */
static void fm1_c1g_mark(uint32_t reason)
{
    if (!fm1_c1g_excluded(fm1_c1g_read(0)))
        fm1_c1g_set(reason, 0);
}

/* core 0 faulted (fm1_fault_c): only while the worker answered */
static void fm1_c1g_fault(void)
{
    if (fm1_c1g_read(0) == FM1_C1X_ACTIVE)
        fm1_c1g_set(FM1_C1X_FAULT, 0);
}

/* 0: the worker may start; else the reason it is refused (the count of refusals is kept, bounded) */
static uint32_t fm1_c1g_refuse(void)
{
    uint32_t n, r = fm1_c1g_read(&n);
    if (!fm1_c1g_excluded(r))
        return 0;
    fm1_c1g_set(r, n < 255u ? n + 1u : n);
    return r;
}

/* the player's explicit retry: 1 = an exclusion was cleared */
static int fm1_c1g_recover(void)
{
    if (!fm1_c1g_excluded(fm1_c1g_read(0)))
        return 0;
    fm1_c1g_clear();
    return 1;
}
#define FM1_RESET_PREP() fm1_cpu1_halt()
#else
#define FM1_RESET_PREP() ((void)0)
#endif

static uint8_t fm1__p33_xfer(uint8_t b)
{
    uint32_t n = 100000u;
    FM1_P33_DAT = b;
    FM1_P33_CON |= 1u << 4;
    (void)FM1_P33_CON;                           /* stands in for csync */
    while (FM1_P33_CON & (1u << 1))
        if (--n == 0) {
            fm1_p33_timeouts++;
            break;
        }
    return (uint8_t)FM1_P33_DAT;
}

static void fm1__p33_cs(uint32_t a)
{
    if (a & 0x8000u) {
        FM1_P33_CON |= (1u << 0) | (1u << 8);    /* RTC domain */
    } else {
        FM1_P33_CON &= ~(1u << 8);
        FM1_P33_CON |= 1u << 0;
    }
}

static void fm1__p33_op(uint32_t op, uint32_t a, uint8_t d)   /* 0 wr, 1 or, 2 and, 3 xor */
{
    fm1__p33_cs(a);
    fm1__p33_xfer((uint8_t)((op << 5) | ((a >> 8) & 3u)));
    fm1__p33_xfer((uint8_t)a);
    fm1__p33_xfer(d);
    FM1_P33_CON &= ~((1u << 0) | (1u << 8));
}

static uint8_t fm1_p33_read(uint32_t a)
{
    uint8_t v;
    fm1__p33_cs(a);
    fm1__p33_xfer((uint8_t)(0x80u | ((a >> 8) & 3u)));
    fm1__p33_xfer((uint8_t)a);
    v = fm1__p33_xfer(0x5E);
    FM1_P33_CON &= ~((1u << 0) | (1u << 8));
    return v;
}
static void fm1_p33_write(uint32_t a, uint8_t d) { fm1__p33_op(0, a, d); }
static void fm1_p33_or(uint32_t a, uint8_t d) { fm1__p33_op(1, a, d); }
static void fm1_p33_and(uint32_t a, uint8_t d) { fm1__p33_op(2, a, d); }

/* ------------------------------------------------------------ watchdog --- */
#define FM1_P3_WDT_CON 0x80u
#define FM1_P3_VLD_KEEP 0x17u
#define FM1_P3_RST_SRC 0x12u
#define FM1_P3_PR_PWR 0xA0u

static void fm1_wdt_arm(uint8_t t)
{
    fm1_p33_write(FM1_P3_WDT_CON, 0);
    fm1_p33_and(FM1_P3_VLD_KEEP, (uint8_t)~0x40u);           /* WDT_EXPT_EN = 0: plain reset */
    fm1_p33_write(FM1_P3_WDT_CON, (uint8_t)((t & 0x0Fu) | 0x40u));   /* timeout, reset mode, clear */
    fm1_p33_or(FM1_P3_WDT_CON, 0x10);                        /* enable */
}
static void fm1_wdt_feed(void) { fm1_p33_or(FM1_P3_WDT_CON, 0x40); }
static void fm1_wdt_stop(void) { fm1_p33_write(FM1_P3_WDT_CON, 0); }

/* ---------------------------------------------------- reset and reboot --- */
static struct {
    uint8_t p3_rst;      /* bit0 power-on, 1 VDDIO low, 2 WDT, 3 VCM, 4 long press, 5 1.2 V, 6 soft (P33) */
    uint32_t rst_src;    /* bit5 soft (PWR_CON) */
    uint8_t wdt_con;     /* as found at boot */
} fm1_boot;

static void fm1_reset_reason(void)
{
    fm1_boot.p3_rst = fm1_p33_read(FM1_P3_RST_SRC);
    fm1_boot.rst_src = FM1_RST_SRC;
    fm1_boot.wdt_con = fm1_p33_read(FM1_P3_WDT_CON);
}

static void fm1_reboot(void)
{
    __asm__ volatile("cli");
    FM1_RESET_PREP();
    fm1_p33_or(FM1_P3_PR_PWR, 0x10);
    for (;;)
        ;
}

static void fm1_enter_uboot(void)
{
    static const char k[16] = "usb_update_mode";
    uint32_t i;
    __asm__ volatile("cli");
    FM1_RESET_PREP();
    /* CPU0 write limits (fm1_guard.h) may cover the mailbox: drop them all */
    if (!(*(volatile uint32_t *)0x1EEE240u & 1u))
        *(volatile uint32_t *)0x1EEE240u = 0xE7u;
    *(volatile uint32_t *)0x1EEE348u = 0;
    for (i = 0; i < 16u; i++)
        FM1_BOOT_STATE[i] = (uint8_t)k[i];
    fm1_p33_or(FM1_P3_PR_PWR, 0x10);
    for (;;)
        ;
}

FM1_INLINE void fm1_core_reset(void)
{
    FM1_RESET_PREP();
    FM1_PWR_CON |= 0x10u;
    for (;;)
        ;
}

FM1_INLINE void fm1_enter_update(const uint8_t *parm)
{
    uint32_t i;
    __asm__ volatile("cli");
    FM1_RESET_PREP();                                   /* (again in fm1_core_reset: before the record is written) */
    if (!(*(volatile uint32_t *)0x1EEE240u & 1u))       /* drop CPU0 write limits, as fm1_enter_uboot */
        *(volatile uint32_t *)0x1EEE240u = 0xE7u;
    *(volatile uint32_t *)0x1EEE348u = 0;
    for (i = 0; i < FM1_UPDATA_PARM_LEN; i++)
        FM1_UPDATA_PARM[i] = parm[i];
    fm1_core_reset();
}

FM1_INLINE void fm1_updata_parm_clear(void)
{
    uint32_t i;
    for (i = 0; i < FM1_UPDATA_PARM_LEN; i++)
        FM1_UPDATA_PARM[i] = 0;
}

FM1_INLINE void fm1_mailbox_clear(void)   /* before fm1_guard_enable (it write-protects the top) */
{
    uint32_t *s;
    for (s = (uint32_t *)0x01C7FD80u; s < (uint32_t *)0x01C7FE00u; s++)
        *s = 0;
}

/* RAM and the XIP window only: SFR reads can have side effects */
static int fm1_mem_readable(uint32_t a, uint32_t n)
{
    return (a >= 0x01C00000u && a + n <= 0x01C80000u && a + n >= a) ||
           (a >= 0x02000000u && a + n <= 0x02100000u && a + n >= a);
}
FM1_INLINE uint8_t fm1_peek8(uint32_t a) { return *(const volatile uint8_t *)a; }
