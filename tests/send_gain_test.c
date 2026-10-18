/* SPDX-License-Identifier: GPL-3.0-only */
/* Native send trajectory/reference and lifecycle checks, including both mixer layouts. */
#define main hostsim_main
#include FX_TEST_HOSTSIM
#undef main
#include <assert.h>

static void sums_clear(void)
{
#if FELUCCA_CPU2
    memset(&mx[0], 0, sizeof mx[0]);
#else
    memset(send_c, 0, sizeof send_c); memset(send_d, 0, sizeof send_d); memset(send_r, 0, sizeof send_r);
    memset(mix_l, 0, sizeof mix_l); memset(mix_r, 0, sizeof mix_r);
#endif
}
static void part(track_t *t, uint32_t n)
{
#if FELUCCA_CPU2
    mix_part(t, n, &mx[0]);
#else
    mix_part(t, n);
#endif
}
static void add(track_t *t, const int32_t *b, uint32_t n, const int32_t *g)
{
#if FELUCCA_CPU2
    send_add(t, b, n, g, &mx[0]);
#else
    send_add(t, b, n, g);
#endif
}
static void arithmetic(void)
{
    int32_t b[CTL], target[3]; track_t *t = &trk[0];
    t->p[P_LEVEL] = 127;
    for (uint32_t n = 1; n <= CTL; n++) for (int from = 0; from <= 127; from++) for (int to = 0; to <= 127; to++) {
        int32_t high = (from > to ? from : to) * 258, xmax = INT32_MAX / (high | 1);
        sums_clear();
        for (int k = 0; k < 3; k++) {t->send_gain[k] = from * 258; target[k] = to * 258;}
        for (uint32_t i = 0; i < n; i++) b[i] = (i & 1) ? -262136 : 262136;  /* eight full-scale voices */
        add(t, b, n, target);
        for (uint32_t i = 0; i < n; i++) {
            int32_t delta = (to - from) * 258;
            /* Mathematical floor, independent of the implementation's Q16 truncation. */
            int64_t num = (int64_t)delta * (i + 1u);
            int32_t gain = from * 258 + (int32_t)(num >= 0 ? num / n : -((-num + n - 1u) / n));
            int32_t x = clamp(((b[i] >> 2) * LEVEL_Q12[127]) >> 10, -xmax, xmax);
            int32_t want = (int32_t)(((int64_t)x * gain) >> 15), actual = send_c[i];
            /* Q16 truncation can differ by one Q15 gain unit; products stay inside signed32. */
            assert(llabs((int64_t)actual - want) <= (llabs(x) + 32767) / 32768);
            assert(actual == send_d[i] && actual == send_r[i]);
            assert(actual <= 65535 && actual >= -65536);
            if (i + 1u == n) assert(actual == (int32_t)(((int64_t)x * target[0]) >> 15));
        }
        for (int k = 0; k < 3; k++) assert(t->send_gain[k] == target[k]);
    }
    /* Four summed tracks, including descending headroom and both signs. */
    for (int sign = -1; sign <= 1; sign += 2) {
        sums_clear(); for (uint32_t i = 0; i < CTL; i++) b[i] = sign * 262136;
        for (int k = 0; k < 3; k++) target[k] = 0;
        for (int p = 0; p < 4; p++) {for (int k = 0; k < 3; k++) trk[p].send_gain[k] = 32766; trk[p].p[P_LEVEL] = 127; add(&trk[p], b, CTL, target);}
        for (uint32_t i = 0; i < CTL; i++) assert(send_c[i] <= 4 * 65535 && send_c[i] >= -4 * 65536);
    }
}
static void lifecycle(void)
{
    track_t *t = &trk[0]; int32_t g[3];
    memset(trk, 0, sizeof trk); memset(&pf, 0, sizeof pf); host_tracks_init(); host_preset(t, 0, 0);
    t->p[P_CHOR] = 127; t->p[P_DLY] = 63; t->p[P_REV] = 24;
    assert(!send_begin(t, g)); assert(t->send_gain[0] == 32766);
    t->p[P_CHOR] = 0; assert(send_begin(t, g));
    /* All shaped THROW phases (enter/hold/release) own the existing gain contract. */
    pf.thr = 1; assert(!send_begin(t, g)); assert(t->send_gain[0] == 0);
    t->p[P_REV] = 127; assert(!send_begin(t, g)); assert(t->send_gain[2] == 32766);
    pf.thr = 0; assert(!send_begin(t, g));
    /* Idle early return invalidates stale targets, including an effective MOD transaction. */
    t->p[P_ITYPE] = t->p[P_DIST] = 0;
    t->p[P_M1SRC] = MS_MODW; t->p[P_M1DST] = MD_CHO; t->p[P_M1AMT] = 63; t->mw = 127;
    t->p[P_CHOR] = 20; part(t, CTL); assert(!t->send_valid); assert(t->p[P_CHOR] == 20 && !MOD(t).on);
    trk_note_on(t, 60, 100); part(t, CTL); assert(t->send_valid && t->send_gain[0] > 20 * 258); assert(t->p[P_CHOR] == 20 && !MOD(t).on);
    /* A zero-frame call must not start MOD, inspect samples or mutate part state. */
    track_t before = *t; part(t, 0); assert(!memcmp(t, &before, sizeof before));
    for (uint32_t n = 1; n <= CTL; n++) {t->mw = n * 3; part(t, n); assert(t->p[P_CHOR] == 20 && !MOD(t).on);}
#if FELUCCA_CPU2
    /* A held worker may stop between any gain writes. Restore canonical MOD parameters and invalidate
     * that uncertain gain transaction before serial fallback; other parts retain their own history. */
    t->p[P_CHOR] = 15; c1_params(1u, 0);
    t->p[P_CHOR] = 90; t->send_gain[0] = 12345; t->send_valid = 1;
    trk[1].send_valid = 1; c1_params(1u, 1);
    assert(t->p[P_CHOR] == 15 && !t->send_valid && !MOD(t).on && trk[1].send_valid);
    assert(!send_begin(t, g) && t->send_gain[0] == 15 * 258);
#endif
    /* Same-engine preset replacement preserves continuous history; a sounding engine switch keeps
     * the old fade and its queued notes, then an idle block invalidates before reactivation. */
    host_preset_req(t, 0, 1); t->p[P_CHOR] = 127; assert(send_begin(t, g));
    t->p[P_M1SRC] = 0; trk_all_off(t); host_preset_req(t, ENGI_FM6, 0);
    engine_block(t); assert(t->xf_on);
    for (uint32_t i = 0; i < XF_BLOCKS + 2u; i++) {part(t, CTL); engine_block(t);}
    assert(t->engine == ENGI_FM6 && !t->xf_on);
    memset(t->v, 0, sizeof t->v); t->tail = 0; t->p[P_ITYPE] = 0;
    part(t, CTL); assert(!t->send_valid);
    t->p[P_CHOR] = 96; trk_note_on(t, 60, 100); part(t, CTL); assert(t->send_gain[0] == 96 * 258);
    /* Whole runtime reset starts from the next effective target. Parameter/preset replacement while
     * sounding deliberately glides; project/preset panic and engine fades retain native voice ownership. */
    memset(t, 0, sizeof *t); t->p[P_REV] = 100; assert(!send_begin(t, g)); assert(t->send_gain[2] == 25800);
    t->p[P_REV] = 0; assert(send_begin(t, g));
}
int main(void)
{
    arithmetic(); lifecycle();
    puts("send gain: all128x128 transitions at1..32frames, exact endpoints, signed/headroom/four-part bounds, MOD/idle/restart/reset/THROW policy passed");
    return 0;
}
