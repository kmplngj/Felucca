/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "../firmware/src/boot_policy.h"

static unsigned checks;
#define CHECK(c) do { checks++; if (!(c)) { \
    fprintf(stderr, "boot policy line %d: %s\n", __LINE__, #c); exit(1); \
} } while (0)

static boot_policy_guard_t guard(uint32_t failed, uint32_t pending)
{
    boot_policy_guard_t g = { BOOTGUARD_MAGIC, failed, pending };
    return g;
}

static void cold_and_invalid(void)
{
    boot_policy_guard_t g = { 0, UINT32_MAX, UINT32_MAX };
    CHECK(sizeof(g) == 12u);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_NORMAL);
    CHECK(g.magic == BOOTGUARD_MAGIC && !g.failed && g.pending == BOOT_POLICY_STARTING);
    g = guard(2, BOOT_POLICY_RESCUING);
    CHECK(boot_policy_begin(&g, 1, 0) == BOOT_POLICY_NORMAL);
    CHECK(!g.failed && g.pending == BOOT_POLICY_STARTING);
    g = guard(0, UINT32_MAX);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_RESCUE);
    CHECK(g.failed == 2 && g.pending == BOOT_POLICY_RESCUING);
    g = guard(UINT32_MAX, BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_RESCUE);
    CHECK(g.failed == 2 && g.pending == BOOT_POLICY_RESCUING);
    g = guard(UINT32_MAX, BOOT_POLICY_CLEAR);
    CHECK(boot_policy_begin(&g, 0, 0) == BOOT_POLICY_RESCUE);
    CHECK(g.failed == 2);
}

static void repeated_failures(void)
{
    boot_policy_guard_t g = guard(0, BOOT_POLICY_CLEAR);
    CHECK(boot_policy_begin(&g, 1, 0) == BOOT_POLICY_NORMAL);
    CHECK(!g.failed);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_NORMAL);
    CHECK(g.failed == 1 && g.pending == BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 0x40, 0) == BOOT_POLICY_RESCUE);
    CHECK(g.failed == 2 && g.pending == BOOT_POLICY_RESCUING);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_ROM);
    CHECK(!g.failed && !g.pending);
    CHECK(boot_policy_begin(&g, 0x40, 0) == BOOT_POLICY_NORMAL);
    /* Do not treat mixed/sticky power-on + WDT/software indications as cold. */
    g = guard(1, BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 5, 0) == BOOT_POLICY_RESCUE);
    g = guard(1, BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 0x41, 0) == BOOT_POLICY_RESCUE);
    g = guard(1, BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 1, 0x20) == BOOT_POLICY_RESCUE);
    /* Unknown, low-voltage and long-press resets do not clear a warm failure. */
    g = guard(1, BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 0x32, 0) == BOOT_POLICY_RESCUE);
}

static void physical_entry(void)
{
    unsigned keys, available;
    for (keys = 0; keys < 4; keys++) {
        for (available = 0; available < 2; available++) {
            boot_policy_guard_t g = guard(0, BOOT_POLICY_CLEAR);
            boot_policy_path_t path = boot_policy_begin(&g, 1, 0);
            path = boot_policy_select(&g, path, keys, available);
            CHECK(path == (keys == 1 ? (available ? BOOT_POLICY_RESCUE : BOOT_POLICY_ROM) : BOOT_POLICY_NORMAL));
            CHECK(g.pending == (keys == 1 ? (available ? BOOT_POLICY_RESCUING : BOOT_POLICY_CLEAR) : BOOT_POLICY_STARTING));
            g = guard(1, BOOT_POLICY_STARTING);
            path = boot_policy_begin(&g, 4, 0);
            CHECK(boot_policy_select(&g, path, keys, available) == (available ? BOOT_POLICY_RESCUE : BOOT_POLICY_ROM));
        }
    }
    {
        boot_policy_guard_t g = guard(0, BOOT_POLICY_STARTING);
        CHECK(boot_policy_select(&g, BOOT_POLICY_NORMAL, 0x81, 1) == BOOT_POLICY_RESCUE);
        CHECK(boot_policy_begin(&g, 0, 0) == BOOT_POLICY_ROM); /* fault reset, even if OCT- remains held */
        CHECK(boot_policy_select(&g, BOOT_POLICY_ROM, 1, 1) == BOOT_POLICY_ROM);
    }
}

static void ambiguous_reset_sources(void)
{
    /* VDDIO low, VCM, long press, 1.2 V low and unknown sources, both alone
     * and mixed with POR; WDT/software mixtures likewise retain the failure. */
    const uint32_t causes[] = { 0x02, 0x03, 0x08, 0x09, 0x10, 0x11, 0x20, 0x21,
                                0x80, 0x81, 0x05, 0x41, 0x43, 0x45 };
    unsigned i;
    for (i = 0; i < sizeof(causes) / sizeof(causes[0]); i++) {
        boot_policy_guard_t g = guard(0, BOOT_POLICY_STARTING);
        CHECK(boot_policy_begin(&g, causes[i], 0) == BOOT_POLICY_NORMAL);
        CHECK(g.failed == 1 && g.pending == BOOT_POLICY_STARTING);
        g = guard(1, BOOT_POLICY_STARTING);
        CHECK(boot_policy_begin(&g, causes[i], 0) == BOOT_POLICY_RESCUE);
        CHECK(g.failed == 2 && g.pending == BOOT_POLICY_RESCUING);
        g = guard(2, BOOT_POLICY_RESCUING);
        CHECK(boot_policy_begin(&g, causes[i], 0) == BOOT_POLICY_ROM);
        CHECK(!g.failed && !g.pending);
    }
    {
        boot_policy_guard_t g = guard(0, BOOT_POLICY_RESCUING);
        CHECK(boot_policy_begin(&g, 1, 0x20) == BOOT_POLICY_ROM);
        CHECK(!g.failed && !g.pending);
    }
}

static void deliberate_resets(void)
{
    unsigned pending, reason;
    const uint32_t p3[] = { 0x40, 0 };
    const uint32_t src[] = { 0, 0x20 };
    for (pending = BOOT_POLICY_STARTING; pending <= BOOT_POLICY_RESCUING; pending++) {
        for (reason = 0; reason < 2; reason++) {
            boot_policy_guard_t g = guard(2, pending);
            boot_policy_intentional(&g);       /* both OTA loader and deliberate ROM transitions */
            CHECK(!g.pending && !g.failed);
            CHECK(boot_policy_begin(&g, p3[reason], src[reason]) == BOOT_POLICY_NORMAL);
            CHECK(!g.failed && g.pending == BOOT_POLICY_STARTING);
        }
    }
}

static void live_window(void)
{
    boot_policy_guard_t g = guard(1, BOOT_POLICY_STARTING);
    boot_policy_live_t live = { 0, 0 };
    boot_policy_service(&g, &live, 90000);       /* a future chooser can wait indefinitely */
    CHECK(g.failed == 1 && g.pending == BOOT_POLICY_STARTING);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_RESCUE); /* failure during activation still counted */
    g = guard(1, BOOT_POLICY_STARTING);
    boot_policy_live_begin(&live, 90000);
    boot_policy_service(&g, &live, 90001);
    CHECK(g.failed == 1 && g.pending == BOOT_POLICY_STARTING);
    boot_policy_service(&g, &live, 120000);
    CHECK(g.pending == BOOT_POLICY_STARTING);  /* old policy used >, not >= */
    boot_policy_service(&g, &live, 120001);
    CHECK(!g.pending && !g.failed);
    CHECK(boot_policy_begin(&g, 4, 0) == BOOT_POLICY_NORMAL);
    CHECK(!g.failed);
    g = guard(1, BOOT_POLICY_STARTING);
    boot_policy_live_begin(&live, UINT32_MAX - 10000u);
    boot_policy_service(&g, &live, 19999);
    CHECK(g.pending == BOOT_POLICY_STARTING);
    boot_policy_service(&g, &live, 20000);
    CHECK(!g.pending && !g.failed);
    g = guard(2, BOOT_POLICY_RESCUING);
    boot_policy_live_begin(&live, 0);
    boot_policy_service(&g, &live, 60000);
    CHECK(g.failed == 2 && g.pending == BOOT_POLICY_RESCUING);
    g = guard(1, BOOT_POLICY_STARTING);
    boot_policy_live_begin(&live, 0);           /* ordinary boot retains its strict 30 s window */
    boot_policy_service(&g, &live, 30000);
    CHECK(g.pending == BOOT_POLICY_STARTING);
    boot_policy_service(&g, &live, 30001);
    CHECK(!g.failed && !g.pending);
}

static void repeated_chooser_activation_failure(void)
{
    boot_policy_guard_t g = guard(0, BOOT_POLICY_CLEAR);
    unsigned attempt;
    CHECK(boot_policy_begin(&g, 1, 0) == BOOT_POLICY_NORMAL);
    for (attempt = 0; attempt < 2; attempt++) {
        boot_policy_live_t live = { 0, 0 };    /* reset BSS; no live start before activation succeeds */
        CHECK(g.failed == attempt);
        boot_policy_service(&g, &live, 60000);
        boot_policy_service(&g, &live, 120000);
        CHECK(g.pending == BOOT_POLICY_STARTING);
        CHECK(boot_policy_begin(&g, 4, 0) == (attempt ? BOOT_POLICY_RESCUE : BOOT_POLICY_NORMAL));
    }
    CHECK(g.failed == 2 && g.pending == BOOT_POLICY_RESCUING);
}

int main(void)
{
    cold_and_invalid();
    repeated_failures();
    ambiguous_reset_sources();
    physical_entry();
    deliberate_resets();
    live_window();
    repeated_chooser_activation_failure();
    printf("boot policy: %u checks passed\n", checks);
    return 0;
}
