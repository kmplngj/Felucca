/* SPDX-License-Identifier: GPL-3.0-only */
/* The independent safety net must hold even with an overbroad caller policy. */
#include <stdint.h>
#include <stdio.h>
#define BOARD_SMK37 1
#define FL_RANGE_OK(off, n) 1
#include "../firmware/hal/fm1_flash_map.h"
int main(void)
{
    uint32_t a, n; int bad = 0;
    for (a = 0; a < 0x100000u; a++) {
        int protected = a < 0x4000u || (a >= 0xC0000u && a < 0xC2000u) ||
                        (a >= 0xF4000u && a < 0xFE000u) || a >= 0xFF000u;
        if (protected && FL_GUARD(a, 1)) bad++;
    }
    for (a = 0x4000u; a <= 0xFF000u; a += 0x1000u)
        for (n = 1; n < 0x100000u; n <<= 1) {
            uint64_t end = (uint64_t)a + n;
            int hits = end > 0xFF000u || (a < 0xC2000u && end > 0xC0000u) ||
                       (a < 0xFE000u && end > 0xF4000u);
            if (hits && FL_GUARD(a, n)) bad++;
        }
    if (FL_GUARD(0xFFFFF000u, 0x4000u) || FL_GUARD(0x4000u, UINT32_MAX)) bad++;
    if (!FL_GUARD(0x4000u, 0x99000u) || !FL_GUARD(0xC2000u, 0x28000u)) bad++;
    puts(bad ? "SMK FLASH GUARD FAILED" : "SMK independent flash guard passed");
    return bad ? 1 : 0;
}
