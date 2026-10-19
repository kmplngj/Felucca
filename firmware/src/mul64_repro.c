/* SPDX-License-Identifier: GPL-3.0-only */
/* Synthetic reproducer for issue #425 (phase 2, step 1): 16-bit table loads beside inline 32x32->64 multiplies,
 * against the same arithmetic with each multiply in a noinline helper that consumes the product at once.
 * felucca-bsp docs/CPU.md (MPL-2.0) reports one-bit register corruption on the AC79/pi32v2 for the first shape and
 * none for the second; only that idea is used here, none of its text or code.
 *
 * FELUCCA_MUL64_REPRO=1 (build.py) builds it in; 0, the default, leaves this file out entirely. The main loop runs
 * mr_step() in its idle wait (main.c), so the audio interrupt, the TIMER5 scan and the UI keep their own timing. No
 * file of the size list (tools/size_fns.py) defines these functions: they are compiled at -Os like the audio
 * paths, and noinline keeps them out of the minsize main loop.
 *
 * Each step takes one of MR_SEEDS inputs and compares a checksum of both variants with a reference checksum
 * established for that input: the first time, the noinline variant runs twice and the inline variant once; the two
 * noinline results, if equal, are the reference (a differing inline result counts in inl_bad), otherwise the set-up
 * counts in ref_bad and is tried again later. The checksum takes in the loop counter, so a corrupted index that
 * ends the loop early shows as a mismatch. A mismatch keeps the variant (1 inline, 2 noinline), the step and the
 * XOR of the two checksums (one set bit: a one-bit result error).
 * `status` prints the counters (console.c, tools/fm1_diagnostics.py). */

#define MR_LEN 128u                 /* loop iterations per kernel call: 3 multiplies (2 signed MACs, 1 unsigned) each */
#define MR_SEEDS 8u
#define MR_H 64u                    /* RAM history (int16_t), as uac_tap48's rs.l / rs.r */

#ifndef MR_TEST_FAULT
#define MR_TEST_FAULT(variant, sum) (sum)   /* host test hook (tests/mul64_repro_test.c): inject a wrong result */
#endif

/* .pool (main loop only, zeroed at boot like .bss): .data/.bss keep the layout of the build without the reproducer,
 * so the audio code the compiler emits against those addresses does not change with it */
static int16_t mr_hist[MR_H] __attribute__((section(".pool")));
static struct {
    uint32_t runs;                  /* steps that compared both variants (each: 2 x MR_LEN x 3 64-bit multiplies) */
    uint32_t inl_bad, nol_bad;      /* checksum mismatches: inline variant, noinline variant */
    uint32_t ref_bad;               /* reference attempts whose two noinline results disagreed */
    uint32_t first_var, first_run, first_xor;   /* the first mismatch: 1 inline / 2 noinline / 3 reference */
    uint32_t ref_ok;                /* bit per seed: reference established */
    uint32_t ref[MR_SEEDS];
    uint32_t init;
} mr __attribute__((section(".pool")));

static uint32_t mr_seed(uint32_t k) { return 0x9E3779B9u * (k + 1u); }

static uint32_t mr_fold(int64_t al, int64_t ar, uint32_t ph, uint32_t i)
{
    return (uint32_t)al ^ (uint32_t)((uint64_t)al >> 32) * 3u ^ (uint32_t)ar * 5u ^
           (uint32_t)((uint64_t)ar >> 32) * 7u ^ ph ^ i * 0x01000193u;
}

/* Variant 1: the multiplies inline, among the loads (the shape tests/mul64_hload_check.py flags). The FIR-style
 * accumulation is uac_tap48's; the product that picks the next table index is fm6_op_run's. */
static __attribute__((noinline)) uint32_t mr_kernel_inline(uint32_t seed)
{
    int64_t al = 0, ar = 0;
    uint32_t ph = seed, i;
    for (i = 0; i < MR_LEN; i++) {
        int32_t c = SINE[ph >> 22];                         /* 16-bit load, flash table */
        int32_t x = mr_hist[(i + seed) & (MR_H - 1u)];      /* 16-bit loads, RAM */
        int32_t z = mr_hist[(i * 5u + 7u) & (MR_H - 1u)];
        al += (int64_t)c * x;                               /* rX_rY += rA * rB (s) */
        ar += (int64_t)c * z;
        ph += (uint32_t)(((uint64_t)ph * (uint32_t)(c + 32768)) >> 16) + 0x9E3779B9u;   /* rX_rY = rA * rB (u) */
    }
    return mr_fold(al, ar, ph, i);
}

/* Variant 2: the same arithmetic, each multiply in a helper that uses its product at once (the donor's clean case) */
static __attribute__((noinline)) int64_t mr_mac(int64_t acc, int32_t a, int32_t b) { return acc + (int64_t)a * b; }
static __attribute__((noinline)) uint32_t mr_mulhi(uint32_t a, uint32_t b) { return (uint32_t)(((uint64_t)a * b) >> 16); }

static __attribute__((noinline)) uint32_t mr_kernel_call(uint32_t seed)
{
    int64_t al = 0, ar = 0;
    uint32_t ph = seed, i;
    for (i = 0; i < MR_LEN; i++) {
        int32_t c = SINE[ph >> 22];
        int32_t x = mr_hist[(i + seed) & (MR_H - 1u)];
        int32_t z = mr_hist[(i * 5u + 7u) & (MR_H - 1u)];
        al = mr_mac(al, c, x);
        ar = mr_mac(ar, c, z);
        ph += mr_mulhi(ph, (uint32_t)(c + 32768)) + 0x9E3779B9u;
    }
    return mr_fold(al, ar, ph, i);
}

static void mr_miss(uint32_t variant, uint32_t got, uint32_t want)
{
    if (!mr.first_var) {
        mr.first_var = variant;
        mr.first_run = mr.runs;
        mr.first_xor = got ^ want;
    }
}

/* One bounded step (two kernel calls, about 1.5k 64-bit multiplies); main loop only */
static __attribute__((noinline)) void mr_step(void)
{
    uint32_t k = mr.runs % MR_SEEDS, seed = mr_seed(k), v;
    if (!mr.init) {
        uint32_t i, s = 0x2545F491u;
        for (i = 0; i < MR_H; i++) {
            s = s * 1664525u + 1013904223u;
            mr_hist[i] = (int16_t)(s >> 16);
        }
        mr.init = 1;
    }
    if (!(mr.ref_ok & (1u << k))) {
        uint32_t a = MR_TEST_FAULT(2u, mr_kernel_call(seed)), b = MR_TEST_FAULT(2u, mr_kernel_call(seed));
        uint32_t c = MR_TEST_FAULT(1u, mr_kernel_inline(seed));
        if (a == b) {                                   /* the two noinline runs agree: they are the reference */
            mr.ref[k] = a;
            mr.ref_ok |= 1u << k;
            if (b != c) {                               /* only the inline run differs: the reproduction itself */
                mr.inl_bad++;
                mr_miss(1u, c, a);
            }
        } else {
            mr.ref_bad++;
            mr_miss(3u, (a ^ b) | (b ^ c), 0u);         /* first_xor: every bit on which the three differ */
        }
        return;
    }
    v = MR_TEST_FAULT(1u, mr_kernel_inline(seed));
    if (v != mr.ref[k]) {
        mr.inl_bad++;
        mr_miss(1u, v, mr.ref[k]);
    }
    v = MR_TEST_FAULT(2u, mr_kernel_call(seed));
    if (v != mr.ref[k]) {
        mr.nol_bad++;
        mr_miss(2u, v, mr.ref[k]);
    }
    mr.runs++;
}
