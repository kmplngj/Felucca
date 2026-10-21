/* SPDX-License-Identifier: GPL-3.0-only */
/* Pure early-boot decisions. No HAL, initialized data, or additional retained RAM. */
#ifndef FELUCCA_BOOT_POLICY_H
#define FELUCCA_BOOT_POLICY_H

#include <stdint.h>

#define BOOTGUARD_MAGIC 0x42475244u
#define BOOT_POLICY_FAILURE_LIMIT 2u
#define BOOT_POLICY_HEALTHY_MS 30000u

/* Keep the existing retained layout and magic: old pending=1 boots remain failures.
 * Volatile prevents folding reads of RAM that startup deliberately does not clear. */
typedef struct {
    volatile uint32_t magic, failed, pending;
} boot_policy_guard_t;

enum {
    BOOT_POLICY_CLEAR = 0,
    BOOT_POLICY_STARTING = 1,
    BOOT_POLICY_RESCUING = 2
};

typedef enum {
    BOOT_POLICY_NORMAL,
    BOOT_POLICY_RESCUE,
    BOOT_POLICY_ROM
} boot_policy_path_t;

/* Ordinary BSS, never NOINIT. A chooser must leave active=0 until the chosen
 * workflow has activated and musical input can be enabled. */
typedef struct {
    uint32_t since_ms, active;
} boot_policy_live_t;

static inline void boot_policy_intentional(boot_policy_guard_t *g)
{
    g->failed = 0;
    g->pending = BOOT_POLICY_CLEAR;
}

/* fm1_sys.h: P33 bit 0 is power-on, bit 2 WDT, bit 6 software;
 * RST_SRC bit 5 is the other software-reset path. The HAL does not define mixed
 * cause precedence: only exact P33 power-on without a software reset discards
 * retained failures. Mixed, unknown, brownout and long-press causes remain warm;
 * an explicit updater/ROM request clears pending before its deliberate reset.
 * This does not read or alter the independent CPU1 exclusion guard. */
static inline boot_policy_path_t boot_policy_begin(boot_policy_guard_t *g,
                                                  uint32_t p3_rst, uint32_t rst_src)
{
    if (g->magic != BOOTGUARD_MAGIC ||
        (p3_rst == 1u && !(rst_src & 0x20u))) {
        g->magic = BOOTGUARD_MAGIC;
        boot_policy_intentional(g);
    }
    if (g->failed > BOOT_POLICY_FAILURE_LIMIT)
        g->failed = BOOT_POLICY_FAILURE_LIMIT;
    if (g->pending == BOOT_POLICY_RESCUING) {
        boot_policy_intentional(g);             /* never loop in a broken application rescue */
        return BOOT_POLICY_ROM;
    }
    if (g->pending > BOOT_POLICY_RESCUING)
        g->failed = BOOT_POLICY_FAILURE_LIMIT; /* corrupt range: bounded recovery, never overflow */
    else if (g->pending == BOOT_POLICY_STARTING && g->failed < BOOT_POLICY_FAILURE_LIMIT)
        g->failed++;
    if (g->failed >= BOOT_POLICY_FAILURE_LIMIT) {
        g->pending = BOOT_POLICY_RESCUING;       /* arm before any rescue initialization can fault */
        return BOOT_POLICY_RESCUE;
    }
    g->pending = BOOT_POLICY_STARTING;
    return BOOT_POLICY_NORMAL;
}

/* physical_oct_mask: bit 0 OCT-, bit 1 OCT+, before saved panel mappings.
 * Both keys keep calibration on an ordinary boot. Existing recovery always
 * wins; calibration/optional workflows cannot bypass a failed rescue or loop. */
static inline boot_policy_path_t boot_policy_select(boot_policy_guard_t *g,
                                                   boot_policy_path_t early,
                                                   uint32_t physical_oct_mask,
                                                   uint32_t rescue_available)
{
    if (early == BOOT_POLICY_ROM)
        return early;
    if (early == BOOT_POLICY_RESCUE || (physical_oct_mask & 3u) == 1u) {
        if (!rescue_available) {
            boot_policy_intentional(g);
            return BOOT_POLICY_ROM;
        }
        g->pending = BOOT_POLICY_RESCUING;
        return BOOT_POLICY_RESCUE;
    }
    return BOOT_POLICY_NORMAL;
}

static inline void boot_policy_live_begin(boot_policy_live_t *live, uint32_t now_ms)
{
    live->since_ms = now_ms;
    live->active = 1;
}

/* Preserve the former strict >30 s boundary, measured from explicit live start.
 * Call regularly; unsigned subtraction handles one timer wrap. Rescue must
 * remain armed indefinitely, even if this service is called accidentally. */
static inline void boot_policy_service(boot_policy_guard_t *g,
                                       const boot_policy_live_t *live, uint32_t now_ms)
{
    if (live->active && g->pending == BOOT_POLICY_STARTING &&
        (uint32_t)(now_ms - live->since_ms) > BOOT_POLICY_HEALTHY_MS)
        boot_policy_intentional(g);
}

#endif
