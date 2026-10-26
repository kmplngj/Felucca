/* SPDX-License-Identifier: GPL-3.0-only */
/* Instruction forms adapted from Joakim Eriksson's fm1-dock probes/cycles.c,
 * e177e83e560483f419baad80511d9dd1acfdeffe (GPL-3.0-only). Native registers
 * stay in the HAL. No donor module ABI, addresses, IRQ or clock writes. */
#pragma once
#include "fm1_time.h"
#include "fm1_cc.h"

FM1_INLINE int fm1_probe_ready(void)
{
    /* Accept only the native free-running TIMER4 configuration. Read only. */
    return (FM1_T4_CON & 0xFFu) == 9u && FM1_T4_PRD == 0xFFFFFFFFu;
}
FM1_INLINE uint32_t fm1_probe_mul(uint32_t a, uint32_t b)
{
    __asm__ volatile("%0 = %0 * %1" : "+r"(a) : "r"(b));
    return a;
}
FM1_INLINE uint32_t fm1_probe_div(uint32_t a, uint32_t b)
{
    /* Caller always supplies an odd, nonzero divisor. */
    __asm__ volatile("%0 = %0 / %1 (u)" : "+r"(a) : "r"(b));
    return a;
}
FM1_INLINE void fm1_probe_barrier(void) { __asm__ volatile("" ::: "memory"); }
