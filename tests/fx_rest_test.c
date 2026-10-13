/* SPDX-License-Identifier: GPL-3.0-only */
/* Built by fx_rest_test.py with a temporary, instrumented hostsim include.
 * Run each deterministic trajectory twice: normal rest paths, then forced off.
 * Digests include every sample and every persistent state after each block.
 * Unlike a frozen golden, the reference follows intentional sound changes. */
#define main hostsim_main
#include FX_TEST_HOSTSIM
#undef main

static uint64_t digest(uint64_t h, const void *data, size_t n)
{
    const uint8_t *p = data;
    while (n--) {
        h ^= *p++;
        h *= UINT64_C(1099511628211);
    }
    return h;
}

static uint64_t state_digest(uint64_t h, uint32_t block, uint32_t last)
{
    __typeof__(hl) persistent = hl;
    /* Cached coefficients are recomputed before sounding. The side flag and
     * block work arrays are consumed only when HALL actually ran this block.
     * Mask those fields, keeping future persistent fields in the comparison. */
    memset(persistent.g, 0, sizeof persistent.g);
    persistent.sz = persistent.side = 0;
    memset(persistent.sd, 0, sizeof persistent.sd);
    memset(persistent.bx, 0, sizeof persistent.bx);
    memset(persistent.l, 0, sizeof persistent.l);
    memset(persistent.r, 0, sizeof persistent.r);
    memset(persistent.y, 0, sizeof persistent.y);
    h = digest(h, &fx, sizeof fx);
    h = digest(h, &persistent, sizeof persistent);
    /* Check full delay lines periodically and at the end, as well as their
     * indices/filters every block. Avoid hashing 150 KB at audio block rate. */
    if (block % 257u == 0u || block == last) {
        h = digest(h, dly_buf, sizeof dly_buf);
        h = digest(h, cho_buf, sizeof cho_buf);
        h = digest(h, rev_comb, sizeof rev_comb);
        h = digest(h, &rev_u, sizeof rev_u);
    }
    return h;
}

static uint32_t fx_test_rng;
static int32_t noise(int32_t amp)
{
    fx_test_rng ^= fx_test_rng << 13;
    fx_test_rng ^= fx_test_rng >> 17;
    fx_test_rng ^= fx_test_rng << 5;
    return (int32_t)(((int64_t)(int32_t)fx_test_rng * amp) >> 31);
}

static void trajectory(uint32_t model, uint32_t feedback, uint32_t sends, uint32_t corner)
{
    const uint32_t sec = (FS + CTL - 1u) / CTL;
    const uint32_t end = 27u * sec;
    int32_t c[CTL], d[CTL], r[CTL], w[CTL], side[CTL], dry[CTL];
    uint64_t audio = UINT64_C(14695981039346656037), state = audio;
    uint32_t b, i;
    memset(&fx, 0, sizeof fx);
    memset(&hl, 0, sizeof hl);
    memset(&pf, 0, sizeof pf);
    memset(dly_buf, 0, sizeof dly_buf);
    memset(cho_buf, 0, sizeof cho_buf);
    memset(rev_comb, 0, sizeof rev_comb);
    memset(&rev_u, 0, sizeof rev_u);
    memset(fx_test_skips, 0, sizeof fx_test_skips);
    host_tracks_init();
    song.g[G_RTYPE] = (int16_t)model;
    song.g[G_DFDBK] = (int16_t)feedback;
    song.g[G_DMIX] = 127;
    song.g[G_CDEPTH] = corner ? 127 : 0;
    song.g[G_CRATE] = corner ? 127 : 0;
    song.g[G_RSIZE] = corner ? 127 : 40;
    song.g[G_RDAMP] = corner == 1u ? 127 : corner == 2u ? 0 : 60;
    song.g[G_DCOLOR] = corner ? 127 : 0;
    song.g[G_DTIME] = corner ? 12 : 11;  /* dotted longest/shortest */
    fx_test_rng = 0x2468aceu;
    for (b = 0; b < end; b++) {
        /* A loud burst, 20 seconds of silence, then tiny sends at both signs,
         * a SIZE glide interrupted three blocks in, and model switches. */
        int32_t amp = b >= sec && b < sec + 8u ? 262144 :
                      b >= 21u * sec + 8u && b < 21u * sec + 12u ? 1 :
                      b >= 22u * sec + 3u && b < 22u * sec + 11u ? 4 :
                      b >= 25u * sec && b < 25u * sec + 8u ? 65536 : 0;
        if (b == 22u * sec) {
            song.g[G_RSIZE] = corner ? 0 : 127;
            song.g[G_RDAMP] = corner == 1u ? 0 : 127;
            song.g[G_DTIME] = 12;
        }
        if (b >= 24u * sec)
            song.g[G_RTYPE] = (int16_t)((model + (b - 24u * sec) / (sec / 3u)) % 3u);
        pf.ew = pf.ew1 = b >= 25u * sec && b < 25u * sec + 12u ? 32768 : 0;
        for (i = 0; i < CTL; i++) {
            int32_t x = amp == 1 || amp == 4 ? ((i & 1u) ? -amp : amp) : noise(amp);
            c[i] = sends & 1u ? x : 0;
            d[i] = sends & 2u ? x : 0;
            r[i] = sends & 4u ? x : 0;
            dry[i] = x;
        }
        /* Actual ECHO THROW contribution arrives after ordinary track sends. */
        if (pf.ew1)
            perf_throw(&trk[0], dry, d, r, CTL);
        fx_buses(c, d, r, w, CTL);
        for (i = 0; i < CTL; i++)
            side[i] = hl.side ? rev_side[i] : 0;
        audio = digest(audio, w, sizeof w);
        audio = digest(audio, side, sizeof side);
        state = state_digest(state, b, end - 1u);
    }
    printf("%u/%u/%u/%u %016llx %016llx %llu %llu %llu %llu\n", model, feedback, sends, corner,
           (unsigned long long)audio, (unsigned long long)state,
           (unsigned long long)fx_test_skips[0], (unsigned long long)fx_test_skips[1],
           (unsigned long long)fx_test_skips[2], (unsigned long long)fx_test_skips[3]);
}

int main(int argc, char **argv)
{
    static const uint32_t feedbacks[] = {0, 60, 120};
    uint32_t model, fb, sends;
    fx_test_force = argc > 1 && atoi(argv[1]);
    for (model = 0; model < 3u; model++)
        for (fb = 0; fb < 3u; fb++)
            for (sends = 1; sends < 8u; sends++)
                trajectory(model, feedbacks[fb], sends, (fb + sends) % 3u);
    return 0;
}
