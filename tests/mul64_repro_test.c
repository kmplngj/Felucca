/* SPDX-License-Identifier: GPL-3.0-only */
/* Host checks of the #425 synthetic reproducer (firmware/src/mul64_repro.c, FELUCCA_MUL64_REPRO=1): both variants
 * compute the same checksum, the reference and comparison counters work, and an injected wrong result is counted
 * and recorded with its variant, step and XOR. It proves the bookkeeping, not anything about the pi32v2: the
 * hardware question is answered only by running the target build on an FM-1 (docs/mul64-hload-audit.md).
 *   cc -O2 -Ibuild/gen -Ifirmware/src tests/mul64_repro_test.c -o build/host/mul64_repro_test */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "felucca_tables.h"

static uint32_t fault_variant, fault_after, fault_bits, fault_calls[3];
static uint32_t test_fault(uint32_t variant, uint32_t sum)
{
    if (variant == fault_variant && ++fault_calls[variant] == fault_after)
        sum ^= fault_bits;
    return sum;
}
#define MR_TEST_FAULT(variant, sum) test_fault((variant), (sum))
#define __attribute__(x)          /* as hostsim.c: no Mach-O section names (.pool); noinline is a target matter */
#include "mul64_repro.c"
#undef __attribute__

static int failures;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); failures++; } } while (0)

static void reset(uint32_t variant, uint32_t after, uint32_t bits)
{
    memset(&mr, 0, sizeof mr);
    memset(fault_calls, 0, sizeof fault_calls);
    fault_variant = variant;
    fault_after = after;
    fault_bits = bits;
}

int main(void)
{
    uint32_t k, i, s = 1u, distinct = 0, prev = 0;
    reset(0, 0, 0);
    mr_step();                                           /* fills mr_hist */
    for (k = 0; k < 4096u; k++) {                        /* both variants agree on many inputs and histories */
        uint32_t seed = k < MR_SEEDS ? mr_seed(k) : (s = s * 1664525u + 1013904223u);
        uint32_t a = mr_kernel_inline(seed), b = mr_kernel_call(seed);
        CHECK(a == b);
        distinct += a != prev;
        prev = a;
        if (k % 512u == 511u)
            for (i = 0; i < MR_H; i++)
                mr_hist[i] = (int16_t)(mr_hist[i] * 31 + (int16_t)k);
    }
    CHECK(distinct > 4000u);                             /* the checksum depends on the input */

    reset(0, 0, 0);                                      /* clean: 8 reference steps, then comparisons */
    for (k = 0; k < MR_SEEDS + 1000u; k++)
        mr_step();
    CHECK(mr.ref_ok == (1u << MR_SEEDS) - 1u);
    CHECK(mr.runs == 1000u && !mr.inl_bad && !mr.nol_bad && !mr.ref_bad && !mr.first_var && !mr.first_xor);
    for (k = 0; k < MR_SEEDS; k++)
        CHECK(mr.ref[k] == mr_kernel_call(mr_seed(k)));

    /* A reference is set up when its seed first comes round: ref 0, run 0, ref 1, run 1, ... ref 7, run 7, run 8, ...
     * so the inline variant's call 2 * MR_SEEDS + n is run 7 + n, the noinline one's 3 * MR_SEEDS + n run 7 + n */
    reset(1, 2u * MR_SEEDS + 5u, 0x00800000u);          /* inline wrong once, after every reference */
    for (k = 0; k < MR_SEEDS + 100u; k++)
        mr_step();
    CHECK(mr.inl_bad == 1u && !mr.nol_bad && !mr.ref_bad);
    CHECK(mr.first_var == 1u && mr.first_run == 12u && mr.first_xor == 0x00800000u);

    reset(2, 2u * MR_SEEDS + 40u, 0x4u);                /* noinline variant wrong once */
    for (k = 0; k < MR_SEEDS + 100u; k++)
        mr_step();
    CHECK(mr.nol_bad == 1u && !mr.inl_bad && !mr.ref_bad);
    CHECK(mr.first_var == 2u && mr.first_run == 39u && mr.first_xor == 0x4u);

    reset(1, 1u, 0x10u);                                 /* a wrong result while the reference is set up */
    for (k = 0; k < MR_SEEDS + 1u + 10u; k++)
        mr_step();
    CHECK(mr.ref_bad == 1u && mr.first_var == 3u && mr.first_xor == 0x10u && mr.first_run == 0u);
    CHECK(mr.ref_ok == (1u << MR_SEEDS) - 1u && mr.runs == 10u && !mr.inl_bad && !mr.nol_bad);
    CHECK(mr.ref[0] == mr_kernel_call(mr_seed(0)));      /* retried, then established from agreeing results */

    reset(1, 2u * MR_SEEDS + 1u, 0x1u);                  /* only the first mismatch is kept */
    for (k = 0; k < 2u * MR_SEEDS + 3u; k++)
        mr_step();
    fault_calls[1] = 0;
    fault_after = 2u;
    fault_bits = 0x80000000u;
    for (k = 0; k < 5u; k++)
        mr_step();
    CHECK(mr.inl_bad == 2u && mr.first_xor == 0x1u && mr.first_run == 8u);

    printf("mul64 reproducer: %s (%u failures)\n", failures ? "FAIL" : "ok", (unsigned)failures);
    return failures != 0;
}
