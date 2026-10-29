/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Fuzz harness: mutated / random project stores (with and without a valid hash, FUN1..FUN10 magics, any length)
 * through proj_decode -> project_restore_runtime -> render, the runtime half of a project load (the codec alone, without
 * the UI: tests/fuzz_proj.c). run_tests.sh runs it briefly under ASan / UBSan with a fixed seed.
 *   fuzz_proj_restore [ITERATIONS [SEED]] */
#define EDITOR_TEST_NO_MAIN 1
#include "editor_test.c"                                /* hostsim, the stubs, RAM flash, reset() */
#include "old_pack.h"
static uint32_t rs = 0x2545F491u;
static uint32_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 17; rs ^= rs << 5; return rs; }
int main(int argc, char **argv)
{
    static project_t a, c;
    static project_store_t st;
    static int32_t o[CTL * 2 + 16];
    uint32_t iters = argc > 1 ? (uint32_t)atoi(argv[1]) : 20000u, i, j, k, n, imported = 0;
    uint32_t restored[4] = {0};                         /* FUN10, FUN9, FUN8, FUN7, including real restore + render */
    if (argc > 2) rs = (uint32_t)atoi(argv[2]) | 1u;
    reset();
    for (i = 0; i < iters; i++) {
        uint32_t mode = i < 4u ? 1u : rnd() % 8u;
        uint32_t format = i < 4u ? i : rnd() % 4u;
        memset(&st, 0, sizeof st);
        if (mode == 0) {                                            /* fully random bytes */
            for (j = 0; j < sizeof st.raw; j++) st.raw[j] = (uint8_t)rnd();
            if (rnd() & 1u) { uint32_t m = 0x46554E30u + 1u + rnd() % 8u; memcpy(st.raw, &m, 4); }   /* "FUN1".."FUN8" */
        } else {                                                    /* a valid store, mutated */
            for (j = 0; j < NTRK; j++) if (rnd() & 1u) trk_note_on(&trk[j], 48u + rnd() % 36u, 1u + rnd() % 127u);
            project_capture(&a);
            if (format) {
                static const uint32_t M[3] = {OLD_FUN9, OLD_FUN8, OLD_FUN7};
                static const uint32_t NP[3] = {99u, 91u, 89u};
                n = old_pack(st.raw, &a, M[format - 1u], NP[format - 1u]);
                if (!n) continue;
            } else {
                if (!proj_encode(&st, &a)) continue;
                n = PROJ_STORE_SIZE;
            }
            k = i < 4u ? 0u : 1u + rnd() % 48u;       /* guaranteed accepted seeds before random mutations */
            for (j = 0; j < k; j++) {
                uint32_t off = rnd() % 4u == 0 ? rnd() % 200u : rnd() % sizeof st.raw;
                st.raw[off] = (uint8_t)(rnd() % 4u == 0 ? 0xFF : rnd() % 4u == 0 ? 0x7F : rnd());
            }
        }
        if (mode == 0 || (i >= 4u && rnd() % 8u == 0))
            n = rnd() % (PROJ_STORE_SIZE + 64u);
        if ((i < 4u || rnd() % 2u) && n >= 8u && n <= PROJ_STORE_SIZE) { /* hash follows the selected length */
            uint32_t sum = proj_hash(st.raw, n - 4u);
            memcpy(st.raw + n - 4u, &sum, 4);
        }
        if (proj_decode(&c, &st, (int)n)) {
            imported++;
            if (project_restore_runtime(&c)) {
                printf("fuzz_proj_restore FAILED: decoded input rejected by restore at %u\n", i);
                return 1;
            }
            for (j = 0; j < NTRK; j++) trk_note_on(&trk[j], 48u + rnd() % 36u, 100);
            for (j = 0; j < 12u; j++) mix_block(o, CTL);
            if (mode != 0) restored[format]++;
        } else if (i < 4u) {
            printf("fuzz_proj_restore FAILED: valid format seed %u rejected\n", format);
            return 1;
        }
        if (i < 4u || rnd() % 64u == 0) reset();
    }
    if (!imported || (iters >= 4u && (!restored[0] || !restored[1] || !restored[2] || !restored[3]))) {
        printf("fuzz_proj_restore FAILED: missing current or legacy restore coverage\n");
        return 1;
    }
    printf("fuzz_proj_restore ok: %u iterations, %u imported\n", iters, imported);
    printf("restored/rendered: FUN10 %u, FUN9 %u, FUN8 %u, FUN7 %u\n", restored[0], restored[1], restored[2], restored[3]);
    return 0;
}
