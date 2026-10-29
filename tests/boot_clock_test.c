/* SPDX-License-Identifier: GPL-3.0-only */
/* The real HAL reader with a read-only, ordered fake register bus. This tests
 * capture/publication, not startup timing or the actual board's clock state. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const uint32_t addresses[] = {0x10014u, 0x1000Cu, 0x10008u, 0x119A8u, 0x119ACu, 0x119A0u, 0x119A4u};
static uint32_t reads, seed;
static uint32_t read32(uint32_t address)
{
    assert(reads < 7 && address == addresses[reads]);
    return seed ^ (0x10203040u * ++reads);
}
#define FM1_CLOCK_READ32(address) read32(address)
#include "../firmware/hal/fm1_clock.h"

int main(void)
{
    uint32_t pass;
    assert(!fm1_boot_clock.valid);
    for (pass = 0; pass < 5; pass++) {
        fm1_clock_snapshot_t local;
        uint32_t expected[7], got[7], i;
        seed = pass * 0x76543210u;
        reads = 0;
        for (i = 0; i < 7; i++) expected[i] = seed ^ (0x10203040u * (i + 1u));
        memset(&local, 0xA5, sizeof local);
        fm1_clock_read(&local);
        assert(reads == 7 && local.valid == 1);
        memset(&fm1_boot_clock, 0, sizeof fm1_boot_clock);
        fm1_boot_clock = local;
        memset(&local, 0xFF, sizeof local);
        seed ^= 0xFFFFFFFFu;             /* a later clock change cannot alter the captured record */
        got[0] = fm1_boot_clock.r10014; got[1] = fm1_boot_clock.r1000c; got[2] = fm1_boot_clock.r10008;
        got[3] = fm1_boot_clock.r119a8; got[4] = fm1_boot_clock.r119ac; got[5] = fm1_boot_clock.r119a0;
        got[6] = fm1_boot_clock.r119a4;
        assert(fm1_boot_clock.valid == 1 && reads == 7 && !memcmp(expected, got, sizeof got));
    }
    puts("boot clock: seven ordered reads, raw words and immutable publication passed");
    return 0;
}
