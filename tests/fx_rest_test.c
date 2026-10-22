/* SPDX-License-Identifier: GPL-3.0-only */
/* Built by fx_rest_test.py with a temporary, instrumented hostsim include.
 * Run each deterministic trajectory twice: normal rest paths, then forced off.
 * Digests include every sample and every persistent state after each block.
 * Unlike a frozen golden, the reference follows intentional sound changes. */
#define main hostsim_main
#include FX_TEST_HOSTSIM
#undef main

static uint32_t gate_errors;

/* These are one-way obligations: an input sample or recorded live history
 * forbids skipping. A zero counter alone does not prove that skipping is safe. */
static void checked_buses(const int32_t *c, const int32_t *d, const int32_t *r, int32_t *w, uint32_t n)
{
    uint64_t before[4];
    uint32_t i;
    int input[3] = {0}, live[4] = {fx.cho_live != 0,
        fx.dly_live || mulq15(-fx.dly_lp, 2000 + song.g[G_DCOLOR] * 240) ||
                       mulq15(fx.dly_lp, song.g[G_DFDBK] * 230),
        hl.live || hl.x || hl.hp || hl.m || hl.s, 0};
#if FX_TEST_SPRING
    live[3] = fx.sp_live != 0;
#endif
    memcpy(before, fx_test_skips, sizeof before);
    for (i = 0; i < HL_NL; i++)
        live[2] |= hl.lp[i] != 0;
    for (i = 0; i < n; i++) {
        input[0] |= c[i] != 0;
        input[1] |= d[i] != 0;
        input[2] |= r[i] != 0;
    }
    fx_buses(c, d, r, w, n);
    for (i = 0; i < 4u; i++)
        if (fx_test_skips[i] != before[i] && (!n || live[i] || input[i < 2u ? i : 2u]))
            gate_errors++;
}

static void reset(uint32_t model)
{
    memset(&fx, 0, sizeof fx);
    memset(&hl, 0, sizeof hl);
    memset(&pf, 0, sizeof pf);
    memset(dly_buf, 0, sizeof dly_buf);
    memset(cho_buf, 0, sizeof cho_buf);
    memset(rev_comb, 0, sizeof rev_comb);
    memset(&rev_u, 0, sizeof rev_u);
    memset(fx_test_skips, 0, sizeof fx_test_skips);
    gate_errors = 0;
    host_tracks_init();
    song.g[G_RTYPE] = (int16_t)model;
    fx.rtype = (uint8_t)model;
}

static void result(const char *id, uint64_t audio, uint64_t state)
{
    printf("%s %016llx %016llx %llu %llu %llu %llu %u\n", id,
           (unsigned long long)audio, (unsigned long long)state,
           (unsigned long long)fx_test_skips[0], (unsigned long long)fx_test_skips[1],
           (unsigned long long)fx_test_skips[2], (unsigned long long)fx_test_skips[3], gate_errors);
}

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

/* A zero-length call must also preserve cached coefficients and scratch that
 * ordinary rest/reference comparisons intentionally mask. */
static uint64_t exact_state_digest(uint64_t h)
{
    h = digest(h, &fx, sizeof fx);
    h = digest(h, &hl, sizeof hl);
    h = digest(h, dly_buf, sizeof dly_buf);
    h = digest(h, cho_buf, sizeof cho_buf);
    h = digest(h, rev_comb, sizeof rev_comb);
    h = digest(h, &rev_u, sizeof rev_u);
    h = digest(h, part_buf, sizeof part_buf);
    return digest(h, fx_test_skips, sizeof fx_test_skips);
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
    char id[64];
    reset(model);
    /* Keep the original model-install transition in the long matrix. */
    fx.rtype = 0;
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
        pf.rw = pf.rw1 = pf.ew1;
        for (i = 0; i < CTL; i++) {
            int32_t x = amp == 1 || amp == 4 ? ((i & 1u) ? -amp : amp) : noise(amp);
            c[i] = sends & 1u ? x : 0;
            d[i] = sends & 2u ? x : 0;
            r[i] = sends & 4u ? x : 0;
            dry[i] = x;
        }
        /* Actual REV/ECHO THROW contributions arrive after ordinary track sends. */
        if (pf.ew1)
            perf_throw(&trk[0], dry, d, r, CTL);
        checked_buses(c, d, r, w, CTL);
        for (i = 0; i < CTL; i++)
            side[i] = hl.side ? rev_side[i] : 0;
        audio = digest(audio, w, sizeof w);
        audio = digest(audio, side, sizeof side);
        state = state_digest(state, b, end - 1u);
    }
    snprintf(id, sizeof id, "%u/%u/%u/%u", model, feedback, sends, corner);
    result(id, audio, state);
}

/* Short focused probes also serve the negative controls. HALL's implementation
 * explicitly requires n=CTL; only ROOM/SPRING exercise partial and odd blocks. */
static void boundary(uint32_t model, int sign)
{
    static const uint32_t sizes[] = {1u, 2u, CTL / 2u, CTL - 1u, CTL};
    static const int32_t amps[] = {1, 4, 65536};
    int32_t c[CTL], d[CTL], r[CTL], w[CTL], side[CTL];
    uint64_t audio = UINT64_C(14695981039346656037), state = audio;
    uint32_t episode, b, i, block = 0;
    char id[64];
    reset(model);
    for (episode = 0; episode < 15u; episode++) {
        uint64_t skips[4];
        uint32_t errors = gate_errors;
        uint32_t n = model == 2u ? CTL : sizes[episode % 5u];
        memcpy(skips, fx_test_skips, sizeof skips);
        reset(model);                   /* each final-sample wake starts empty */
        memcpy(fx_test_skips, skips, sizeof skips);
        gate_errors = errors;
        song.g[G_DFDBK] = 0;
        song.g[G_DTIME] = 3;             /* 1/8: audible history within the probe */
        song.g[G_CDEPTH] = song.g[G_CRATE] = sign > 0 ? 127 : 0;
        song.g[G_RSIZE] = song.g[G_RDAMP] = sign > 0 ? 127 : 0;
        for (b = 0; b < (DLY_LEN + FS / 4u) / CTL + 16u; b++, block++) {
            uint32_t count = b < 3u ? n : CTL;
            memset(c, 0, sizeof c);
            memset(d, 0, sizeof d);
            memset(r, 0, sizeof r);
            if (b == 1u)
                c[count - 1u] = d[count - 1u] = r[count - 1u] = sign * amps[episode / 5u];
            /* Return gain is zero at the write, then re-enabled while that
             * history is still live. The input/live obligations apply at zero. */
            song.g[G_DMIX] = b < 3u ? 0 : 127;
            if (b == 3u && episode >= 5u && !fx.dly_live)
                gate_errors++;          /* the re-enable must really have a tail */
            checked_buses(c, d, r, w, count);
            for (i = 0; i < count; i++)
                side[i] = hl.side ? rev_side[i] : 0;
            audio = digest(audio, &count, sizeof count);
            audio = digest(audio, w, count * sizeof *w);
            audio = digest(audio, side, count * sizeof *side);
            state = state_digest(state, block, UINT32_MAX);
        }
        state = state_digest(state, 0, 0);   /* include every line before resetting */
    }
    /* n=0 must be an exact no-op even with arbitrary output scratch contents. */
    memset(w, 0x5a, sizeof w);
    {
        uint64_t before = exact_state_digest(0);
        /* The no-op contract includes a pending model change: rev_switch
         * would divide by n if the entry guard were removed. */
        song.g[G_RTYPE] = (int16_t)((model + 1u) % 3u);
        checked_buses(c, d, r, w, 0);
        if (before != exact_state_digest(0)) {
            fprintf(stderr, "boundary: zero block changed state\n");
            exit(1);
        }
        for (i = 0; i < CTL; i++)
            if (w[i] != 0x5a5a5a5a) {
                fprintf(stderr, "boundary: zero block changed output\n");
                exit(1);
            }
    }
    state = state_digest(state, 0, 0);
    snprintf(id, sizeof id, "%u/boundary/%d", model, sign);
    result(id, audio, state);
}

static void fixed_delay(int32_t lp, uint32_t feedback, uint32_t color)
{
    int32_t z[CTL] = {0}, w[CTL];
    uint64_t audio = UINT64_C(14695981039346656037), state = audio;
    uint32_t b;
    char id[64];
    reset(0);
    song.g[G_DMIX] = 127;
    song.g[G_DFDBK] = (int16_t)feedback;
    song.g[G_DCOLOR] = (int16_t)color;
    checked_buses(z, z, z, w, CTL);       /* witness the legitimate empty skip */
    /* Consistent zero lines/counters plus a seeded filter endpoint. This probes
     * gate arithmetic; it does not claim every seed is reachable from audio. */
    fx.dly_lp = lp;
    for (b = 0; b < DLY_LEN / CTL + 16u; b++) {
        uint64_t before = fx_test_skips[1];
        checked_buses(z, z, z, w, CTL);
        if (!b && !fx_test_force) {
            int rests = !mulq15(-lp, 2000 + (int32_t)color * 240) &&
                        !mulq15(lp, (int32_t)feedback * 230);
            if ((fx_test_skips[1] != before) != rests)
                gate_errors++;
        }
        audio = digest(audio, w, sizeof w);
        state = state_digest(state, b, DLY_LEN / CTL + 15u);
    }
    snprintf(id, sizeof id, "0/fixed/%d/%u/%u", lp, feedback, color);
    result(id, audio, state);
}

int main(int argc, char **argv)
{
    static const uint32_t feedbacks[] = {0, 60, 120};
    uint32_t model, fb, sends;
    fx_test_force = argc > 1 && atoi(argv[1]);
    if (argc < 3 || strcmp(argv[2], "boundary"))
        for (model = 0; model < 3u; model++)
            for (fb = 0; fb < 3u; fb++)
                for (sends = 1; sends < 8u; sends++)
                    trajectory(model, feedbacks[fb], sends, (fb + sends) % 3u);
    for (model = 0; model < 3u; model++) {
        boundary(model, 1);
        boundary(model, -1);
    }
    for (fb = 0; fb < 2u; fb++)
        for (sends = 0; sends < 2u; sends++) {
            fixed_delay(-1, fb ? 127 : 0, sends ? 127 : 0);
            fixed_delay(1, fb ? 127 : 0, sends ? 127 : 0);
        }
    return 0;
}
