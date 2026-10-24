/* SPDX-License-Identifier: GPL-3.0-only */
/* Read-only boot clock evidence (#618). Raw words, not a frequency decoder or
 * clock correction. main.c captures into its stack before normal initialization,
 * then publishes into ordinary BSS after that region has been cleared. */
#pragma once
#include <stdint.h>

typedef struct {
    uint32_t r10014, r1000c, r10008, r119a8, r119ac, r119a0, r119a4;
    uint8_t valid;
} fm1_clock_snapshot_t;
static fm1_clock_snapshot_t fm1_boot_clock;  /* main.c publishes once, before USB/rescue; console only reads */

#ifndef FM1_CLOCK_READ32
#define FM1_CLOCK_READ32(a) (*(volatile const uint32_t *)(uintptr_t)(a))
#endif
static inline void fm1_clock_read(fm1_clock_snapshot_t *s)
{
    /* Separate statements preserve the observation order. No register writes,
     * waits or firmware state are needed before BSS/data initialization. */
    s->r10014 = FM1_CLOCK_READ32(0x10014u);
    s->r1000c = FM1_CLOCK_READ32(0x1000Cu);
    s->r10008 = FM1_CLOCK_READ32(0x10008u);
    s->r119a8 = FM1_CLOCK_READ32(0x119A8u);
    s->r119ac = FM1_CLOCK_READ32(0x119ACu);
    s->r119a0 = FM1_CLOCK_READ32(0x119A0u);
    s->r119a4 = FM1_CLOCK_READ32(0x119A4u);
    s->valid = 1;
}
