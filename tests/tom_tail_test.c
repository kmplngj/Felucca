/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The tom / conga run once its stick has rung out (src/drum_voice.c dv_tom_run: a block entered with es <= 1 leaves
 * out the stick's term, which is exactly 0 from there until the next strike) against the run as it was (dv_tom_ref
 * below, a copy): every block's samples and the whole voice state the same, over every type that plays through the
 * tom run (Felucca's TOM, CONGA, each model kit's lane), the corners of TUNE DECAY TONE SNAP accent LEVEL, random
 * block lengths (1..CTL), and while it rings: parameter edits, retriggers (ratchets), the lane taken by another
 * drum (dv_init) and given back, the coefficients of another type (the voice falls silent), chokes.
 *   build/host/tom_tail_test */
#define main hostsim_main
#include "hostsim.c"
#undef main

/* dv_tom_run before the stick's zero was left out */
static void dv_tom_ref(const dv_coef_t *c, dv_voice_t *v, int32_t *y, uint32_t n)
{
    uint32_t i, ph = v->ph[0], es = v->e[0], bs = c->span[0] >> 16;
    int32_t a, d, lp = v->s[2];
    dv_slow(&v->q[0], c->kb[0], &a, &d);
    for (i = 0; i < n; i++) {
        int32_t al, x, nz;
        a += d;
        al = a >> 5;
        ph += c->inc[0] + bs * (uint32_t)((al * al) >> 14);
        x = (sine_i(ph) * al) >> 15;
        nz = DV_NOISE(v);
        lp += ((nz - lp) * c->hp) >> 15;
        x += ((((lp * c->g[0]) >> 15) + (((nz - lp) * c->g[2]) >> 15)) * (int32_t)(es >> 1)) >> 15;
        es = (es * c->k[0]) >> 15;
        if (c->g[1])
            x = softclip((x * c->g[1]) >> 12);
        y[i] = x;
    }
    v->ph[0] = ph, v->e[0] = es, v->s[2] = lp;
    v->live = v->q[0] > DV_QUIET;
}

/* dv_run with the reference tom run (the other types: dv_run itself) */
static void ref_run(const dv_coef_t *c, dv_voice_t *v, int32_t *y, uint32_t n)
{
    uint32_t i;
    if (c->type != DVT_TOM && c->type != DVT_CONGA) {
        dv_run(c, v, y, y, n);                           /* (the metal: any block, the same for both) */
        return;
    }
    if (v->trig)
        dv_strike(c, v);
    if (!v->live || v->type != c->type) {
        for (i = 0; i < n; i++)
            y[i] = 0;
        v->live = 0;
        return;
    }
    dv_tom_ref(c, v, y, n);
    dv_out(c, y, n);
}

static uint32_t rs = 1;
static uint32_t rnd(uint32_t m)
{
    rs = rs * 1664525u + 1013904223u;
    return (rs >> 8) % m;
}

static int fails;
static uint64_t nblk, ntail, nedge, nsamp;               /* blocks compared; entered rung out; entered at es 2..3 */

/* Exercise the exact boundary independently of the random hits: an empty block must
 * not advance es, and k == 32768 keeps es == 1 while any smaller k takes it to zero. */
static void boundary(uint32_t type)
{
    static const uint32_t env[] = {0, 1, 2, 3, 65536};
    static const uint32_t len[] = {0, 1, CTL};
    static const uint32_t coef[] = {0, 32767, 32768};
    dv_param_t p;
    dv_coef_t c;
    uint32_t e, l, k;
    dv_default(&p, type);
    dv_setup(&c, &p);
    for (e = 0; e < sizeof env / sizeof env[0]; e++)
        for (l = 0; l < sizeof len / sizeof len[0]; l++)
            for (k = 0; k < sizeof coef / sizeof coef[0]; k++) {
                dv_voice_t a, b;
                int32_t ya[CTL], yb[CTL];
                dv_init(&a, type);
                dv_strike(&c, &a);
                a.e[0] = env[e];
                a.s[2] = -12345;
                b = a;
                c.k[0] = coef[k];
                dv_tom_run(&c, &a, ya, len[l]);
                dv_tom_ref(&c, &b, yb, len[l]);
                if (memcmp(ya, yb, len[l] * sizeof ya[0]) || memcmp(&a, &b, sizeof a)) {
                    printf("FAIL boundary type %02x es %u k %u n %u\n", type, env[e], coef[k], len[l]);
                    fails++;
                }
            }
}

static void param(dv_param_t *p, uint32_t type, uint32_t corner)
{
    static const uint8_t V[3] = {0, 64, 127};
    static const int16_t T[3] = {-400, 0, 400};
    dv_default(p, type);
    p->decay = V[corner % 3u];
    p->tone = V[corner / 3u % 3u];
    p->extra = V[corner / 9u % 3u];
    p->tune = T[corner / 27u % 3u];
    p->accent = (corner / 81u) & 1u ? 127 : 0;
    p->level = (corner / 81u) & 1u ? 127 : 0;
}

/* one hit and its whole ring (and a little after), random events between blocks; ev 0: blocks only */
static void scenario(uint32_t type, uint32_t corner, int ev, uint32_t fixed)
{
    dv_coef_t c, cx;
    dv_voice_t a, b;
    dv_param_t p;
    int32_t ya[CTL], yb[CTL];
    uint32_t t, quiet = 0, i, done = 0;
    param(&p, type, corner);
    dv_setup(&c, &p);
    dv_init(&a, type);
    dv_trigger(&a);
    b = a;
    for (t = 0; done < FS * 6u && quiet < 64u; t++) {
        uint32_t n = fixed ? fixed : 1u + rnd(CTL), r = ev ? rnd(1000) : 1000;
        const dv_coef_t *cc = &c;
        if (r < 6) {                                     /* an edit while it rings */
            param(&p, type, rnd(162));
            dv_setup(&c, &p);
        } else if (r < 9) {                              /* a retrigger / a ratchet */
            dv_trigger(&a), dv_trigger(&b);
        } else if (r < 10) {                             /* the lane taken by another drum, then this one again */
            dv_init(&a, DVT_SNARE), dv_init(&b, DVT_SNARE);
            dv_init(&a, type), dv_init(&b, type);
            dv_trigger(&a), dv_trigger(&b);
        } else if (r < 12) {                             /* another type's coefficients for a block */
            dv_param_t q;
            dv_default(&q, rnd(2) ? DVT_RIM : DVT_TOM + DVT_CONGA - c.type);
            dv_setup(&cx, &q);
            cc = &cx;
        } else if (r < 14) {
            dv_choke(&a), dv_choke(&b);
        }
        if (a.live && a.type == cc->type && !a.trig) {
            ntail += a.e[0] <= 1u;
            nedge += a.e[0] - 2u < 2u;
        }
        dv_run(cc, &a, ya, ya, n);
        ref_run(cc, &b, yb, n);
        nblk++, nsamp += n, done += n;
        if (memcmp(ya, yb, n * sizeof ya[0]) || memcmp(&a, &b, sizeof a)) {
            for (i = 0; i < n && ya[i] == yb[i]; i++)
                ;
            printf("FAIL type %02x corner %u ev %d n %u block %u: sample %u %d / %d, e0 %u / %u, s2 %d / %d, rng %d / %d\n",
                   type, corner, ev, n, t, i, i < n ? ya[i] : 0, i < n ? yb[i] : 0, a.e[0], b.e[0], a.s[2], b.s[2],
                   a.rng, b.rng);
            fails++;
            return;
        }
        quiet = a.live ? 0 : quiet + 1;
        if (!a.live && ev && rnd(8) == 0)                /* rung out: struck again now and then */
            dv_trigger(&a), dv_trigger(&b), quiet = 0;
    }
}

int main(void)
{
    uint32_t k, l, t, corner, ntype = 0;
    for (k = 0; k <= DV_NKIT; k++)
        for (l = 0; l < (k ? DV_NLANE : DVT_COUNT); l++) {
            t = k ? DV_KTYPE(k, l) : l;
            if (dv_run_type(t) != DVT_TOM && dv_run_type(t) != DVT_CONGA)
                continue;
            ntype++;
            boundary(t);
            for (corner = 0; corner < 162u; corner++)
                scenario(t, corner, 0, 0);
            for (corner = 0; corner < 162u; corner += 7u)
                scenario(t, corner, 1, 0);
            scenario(t, 40, 0, 1);                       /* one sample a block: every es met at a block start */
            scenario(t, 40, 0, CTL);
            scenario(t, 0, 1, 1);
        }
    printf("%u types, %llu blocks (%llu samples), %llu entered rung out, %llu at es 2..3\n", ntype,
           (unsigned long long)nblk, (unsigned long long)nsamp, (unsigned long long)ntail, (unsigned long long)nedge);
    if (ntype != DV_NKIT + 2u || !ntail || !nedge) {
        printf("FAIL coverage\n");
        fails++;
    }
    printf(fails ? "TOM TAIL: %d FAILED\n" : "TOM TAIL: PASS\n", fails);
    return fails != 0;
}
