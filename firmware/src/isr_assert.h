/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Debug assertion for code that must run in the main loop, never in an interrupt (#428): flash erase/program,
 * settings/project saves, formatted console output, blocking waits, preset loads.
 *
 *   FM1_ASSERT_THREAD()   place at the entry of such a function, before it takes irq_save().
 *
 * FELUCCA_ISR_ASSERT (build.py passes FELUCCA_ISR_ASSERT=0/1 through):
 *   0  nothing: the macros expand to ((void)0), no code, no data (the default for FM-1 release/target builds)
 *   1  host tests and the browser emulator (the default off the FM-1): a depth counter driven by the simulated
 *      interrupt handlers (FM1_ISR_SIM_ENTER/LEAVE in fm1_alnk0_irq and fm1_timer5_irq); a violation prints the
 *      site and aborts, or calls fm1_isr_assert_hook when a test installs one.
 *   1  for the FM-1 (development build): hal/fm1_guard.h fm1_sp_in_isr(); a violation counts into isr_misuse
 *      (`status` shows it with the first caller's address) and carries on. No flash write, no formatted output
 *      from the interrupt. Never place the macro in .ram_text code or in an interrupt path. */
#pragma once
#include <stdint.h>

#ifndef FELUCCA_ISR_ASSERT
#ifdef __PI32V2__
#define FELUCCA_ISR_ASSERT 0
#else
#define FELUCCA_ISR_ASSERT 1
#endif
#endif

#if !FELUCCA_ISR_ASSERT
#define FM1_ISR_ASSERT_TARGET 0
#define FM1_ASSERT_THREAD() ((void)0)
#define FM1_ISR_SIM_ENTER() ((void)0)
#define FM1_ISR_SIM_LEAVE() ((void)0)
#elif defined(__PI32V2__)
#define FM1_ISR_ASSERT_TARGET 1
#include "fm1_guard.h"
static uint32_t fm1_isr_misuse_n, fm1_isr_misuse_pc;      /* .bss; `status` isr_misuse / isr_misuse_pc */
static __attribute__((noinline)) void fm1_isr_misuse(void)
{
    if (!fm1_isr_misuse_n)
        fm1_isr_misuse_pc = (uint32_t)(uintptr_t)__builtin_return_address(0);
    fm1_isr_misuse_n++;
}
#define FM1_ASSERT_THREAD() do { if (fm1_sp_in_isr()) fm1_isr_misuse(); } while (0)
#define FM1_ISR_SIM_ENTER() ((void)0)
#define FM1_ISR_SIM_LEAVE() ((void)0)
#else
#include <stdio.h>
#include <stdlib.h>
#define FM1_ISR_ASSERT_TARGET 0
static int fm1_host_isr_depth __attribute__((unused));             /* simulated interrupt handlers running (nested) */
static void (*fm1_isr_assert_hook)(const char *file, int line) __attribute__((unused));
static void fm1_host_isr_misuse(const char *file, int line) __attribute__((unused));
static void fm1_host_isr_misuse(const char *file, int line)
{
    if (fm1_isr_assert_hook) {
        fm1_isr_assert_hook(file, line);
        return;
    }
    fprintf(stderr, "FM1_ASSERT_THREAD: %s:%d runs in simulated interrupt context\n", file, line);
    abort();
}
#define FM1_ASSERT_THREAD() do { if (fm1_host_isr_depth > 0) fm1_host_isr_misuse(__FILE__, __LINE__); } while (0)
#define FM1_ISR_SIM_ENTER() (fm1_host_isr_depth++)
#define FM1_ISR_SIM_LEAVE() (fm1_host_isr_depth--)
#endif
