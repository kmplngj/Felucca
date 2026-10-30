/* SPDX-License-Identifier: GPL-3.0-only */
/* mix_part's specialised non-SPREAD loops (fx.c, #185 / #458) against its general loop: the same scenario, built
 * with FELUCCA_MIX_FAST=1 and =0 (tests/mix_fast_test.py), prints one hash per block of the stereo PCM, the dry
 * sums and sends, every part, the FX layer and the SLICERs; the two outputs must be identical. The fast build also
 * reports which loops ran (FX_MIX_PATH), so a scenario that never reaches one fails.
 *   mix_fast_test SEED [adv]   adv: the probe rewrites some blocks to samples at the Q12 unity-pan bound
 *                              (|x| = 2^19 +- 1); built with -fwrapv, so the reference's wrap is defined */
#ifdef C1_HOST
#include "c1_host.h"
#endif
#include <stdint.h>
static uint32_t mix_hits[8];
static int mix_adv;
static uint32_t mix_rng = 1;
static uint32_t mix_rand(void)
{
    mix_rng ^= mix_rng << 13;
    mix_rng ^= mix_rng >> 17;
    mix_rng ^= mix_rng << 5;
    return mix_rng;
}
struct track;
static void mix_probe(const struct track *t, int32_t *b, uint32_t n, int path);
#define FX_MIX_PATH(t, b, n, path) mix_probe(t, b, n, path)
#define main hostsim_main
#include FX_TEST_HOSTSIM
#undef main
#include <assert.h>

/* the samples of a block, rewritten (adv) on both builds alike: the boundaries of x = ((b >> 2) * lvl) >> 10 where
 * x * 4096 leaves signed 32 bits; b stays below where (b >> 2) * lvl itself would */
static uint32_t adv_rng = 7;
static void mix_probe(const track_t *t, int32_t *b, uint32_t n, int path)
{
    uint32_t i;
    mix_hits[path & 7]++;
    if (!mix_adv || path >= 4)
        return;
    adv_rng = adv_rng * 1103515245u + 12345u;
    if ((adv_rng >> 16) % 3u)
        return;
    int32_t lvl = LEVEL_Q12[t->p[P_LEVEL] & 127];
    if (!lvl)
        return;
    for (i = 0; i < n; i++) {
        static const int32_t XT[6] = {524287, 524288, -524288, -524289, 600000, -700000};
        adv_rng = adv_rng * 1103515245u + 12345u;
        int32_t xt = XT[(adv_rng >> 16) % 6u];
        if ((adv_rng >> 8) % 4u == 0u) {
            b[i] = (int32_t)((adv_rng >> 4) % 1600000u) - 800000;
            continue;
        }
        int32_t q = (int32_t)(((int64_t)xt * 1024) / lvl), k;
        for (k = -2; k <= 2; k++)                       /* (b >> 2) * lvl >> 10 == xt, if one of these gives it */
            if ((((q + k) * lvl) >> 10) == xt)
                break;
        b[i] = (q + (k > 2 ? 0 : k)) * 4 + (int32_t)((adv_rng >> 20) & 3u);
    }
}

static uint64_t hs = UINT64_C(14695981039346656037);
static void hb(const void *p, size_t len)
{
    const uint8_t *c = p;
    while (len--) {
        hs ^= *c++;
        hs *= UINT64_C(1099511628211);
    }
}

static const uint8_t PANS[] = {0, 0, 0, 1, 127, 63, 64, 65, 100, 20};    /* (int8: 0, 1, -1, 63, -64, -63, ...) */
static const uint8_t SENDS[] = {0, 0, 0, 0, 1, 64, 127};
static const uint8_t LEVELS[] = {0, 1, 64, 100, 127, 127};

static void event(uint32_t k)
{
    track_t *t = &trk[mix_rand() % NPART];
    uint32_t e = mix_rand() % 40u;
    switch (e) {
    case 0: case 1: case 2: case 3: case 4: case 5:
        trk_note_on(t, 36u + mix_rand() % 48u, 1u + mix_rand() % 127u); break;
    case 6: case 7: case 8:
        trk_note_off(t, 36u + mix_rand() % 48u); break;
    case 9: trk_all_off(t); break;
    case 10: case 11: t->p[P_PAN] = (int8_t)PANS[mix_rand() % sizeof PANS]; break;
    case 12: case 13: case 14:                          /* all sends at once: settled 0, 0 -> n and n -> 0 ramps */
        t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = SENDS[mix_rand() % sizeof SENDS]; break;
    case 15: t->p[P_CHOR] = SENDS[mix_rand() % sizeof SENDS]; break;
    case 16: t->p[P_DLY] = SENDS[mix_rand() % sizeof SENDS]; break;
    case 17: t->p[P_REV] = SENDS[mix_rand() % sizeof SENDS]; break;
    case 18: t->p[P_LEVEL] = LEVELS[mix_rand() % sizeof LEVELS]; break;
    case 19: t->p[P_DIST] = (mix_rand() & 1u) ? 0 : (int16_t)(mix_rand() % 128u); break;
    case 20: t->p[P_ITYPE] = (mix_rand() & 1u) ? 0 : (int16_t)(mix_rand() % IT_N); t->p[P_IMIX] = 100; break;
    case 21: t->p[P_SLCR] = (int16_t)(mix_rand() % 3u); break;
    case 22: t->p[P_SPRD] = (mix_rand() & 1u) ? 0 : 90; break;
    case 23: t->p[P_VOICE] = (int16_t)(mix_rand() % 4u); break;
    case 24: perf_press(PF_M1 + (uint32_t)(t - trk), 1); break;
    case 25: perf_press(PF_M1 + (uint32_t)(t - trk), 0); break;
    case 26: perf_press(PF_RTHR, (int)(mix_rand() & 1u)); break;
    case 27: perf_press(PF_ETHR, (int)(mix_rand() & 1u)); break;
    case 28:                                            /* the matrix: an LFO on PAN or on a send, or the wheel */
        t->p[P_M1SRC] = (int16_t)((mix_rand() & 1u) ? MS_LFO : MS_MODW);
        t->p[P_M1DST] = (int16_t)(MD_PAN + mix_rand() % 5u);       /* PAN, DIST, CHO, DLY, REV */
        t->p[P_M1AMT] = (int16_t)(mix_rand() % 128u) - 64; break;
    case 29: t->mw = (uint8_t)(mix_rand() % 128u); break;
    case 30: t->p[P_M1SRC] = 0; break;
    case 31: sound_load_factory(t, mix_rand() % NENGINES, mix_rand() % 4u, (mix_rand() & 1u) ? SND_PANIC : 0u); break;
    default: break;
    }
    (void)k;
}

static void hash_block(const int32_t *out, uint32_t n)
{
    hb(out, 2u * n * sizeof *out);
#if FELUCCA_CPU2
    hb(mx, sizeof mx);
#else
    hb(mix_l, sizeof mix_l); hb(mix_r, sizeof mix_r);
    hb(send_c, sizeof send_c); hb(send_d, sizeof send_d); hb(send_r, sizeof send_r);
#endif
    hb(part_buf, sizeof part_buf);
    hb(trk, sizeof trk);
    hb(&pf, sizeof pf);
    hb(sl, sizeof sl);
}

int main(int argc, char **argv)
{
    static int32_t out[2 * CTL];
    uint32_t seed = argc > 1 ? (uint32_t)atoi(argv[1]) : 1u, k, p, blocks = 6000;
    mix_adv = argc > 2 && !strcmp(argv[2], "adv");
    mix_rng = seed * 2654435761u | 1u;
    host_tracks_init();
    for (p = 0; p < NPART; p++) {
        host_preset(&trk[p], (seed + p * 3u) % NENGINES, p % 4u);
        trk[p].p[P_SUS] = 127;
        trk[p].p[P_CHOR] = trk[p].p[P_DLY] = trk[p].p[P_REV] = 0;
        trk[p].p[P_PAN] = 0;
        trk[p].p[P_LEVEL] = 127;
    }
    for (p = 0; p < 6u; p++)                            /* a heavy chord on the first part from the start */
        trk_note_on(&trk[0], 48u + 4u * p, 127);
    for (k = 0; k < blocks; k++) {
        uint32_t n = (mix_rand() & 3u) ? CTL : 1u + mix_rand() % CTL, e = mix_rand() % 4u;
        while (e--)
            event(k);
        mix_block(out, n);
        hash_block(out, n);
        if (k % 3u)
            for (p = 0; p < NPART; p++)
                trk[p].peak = 0;                        /* as the meters take it (ui_graph.c): each block's own */
        if (k % 64u == 63u || k + 1u == blocks)
            printf("block %u %016llx\n", k, (unsigned long long)hs);
    }
    /* the loops this build ran: compared by mix_fast_test.py, not part of the reference trace */
    fprintf(stderr, "paths %u %u %u %u %u\n", mix_hits[0], mix_hits[1], mix_hits[2], mix_hits[3], mix_hits[4]);
    return 0;
}
