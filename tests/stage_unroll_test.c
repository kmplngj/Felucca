/* SPDX-License-Identifier: GPL-3.0-only */
/* Compare the unrolled DSP with the unchanged loops from main eca5224.
 * Check PCM and complete persistent state after every block, including fades,
 * wrap, parameter jumps and silence. No host instruction-cost claim. */
#define main hostsim_main
#include "hostsim.c"
#undef main

static __attribute__((noinline)) void rev_spring_ref(const int32_t *rev_in, int32_t *out, uint32_t n)
{
    uint32_t i, k, s = (uint32_t)song.g[G_RSIZE];
    int32_t g = 19661 + (int32_t)s * 85;                /* the loop's gain: 0.6 .. 0.93 */
    int32_t kl = 26000 - song.g[G_RDAMP] * 160;         /* its low-pass: ~9 kHz .. ~1.3 kHz */
    int32_t len = (int32_t)(1323u + ((s * 1323u) >> 7)) << 8, L, L2, L3, f, w;
    int16_t *ln = rev_comb;
    int32_t *ap = rev_u.sp;
    if (!fx.sp_size)
        fx.sp_size = len;
    fx.sp_size += clamp(len - fx.sp_size, -256, 256);   /* SIZE glides (a sample a block at most) */
    L = fx.sp_size >> 8;
    fx.sp_ph += 2u * LFO_INC[24];                       /* the wobble: a slow sine, 1.5 samples deep */
    w = (fx.sp_size >> 1) + ((osc_sine(fx.sp_ph) * 3) >> 8);   /* the far end, Q8 */
    L2 = w >> 8;
    f = w & 255;
    L3 = (L * 3) >> 2;
    for (i = 0; i < n; i++) {
        uint32_t wp = fx.sp_w, j = (wp & 3u) * (SP_N + 1u);
        int32_t x = mulq15(rev_in[i], 2580), r = ln[(wp - (uint32_t)L) & SP_MASK], p, o;
        int32_t t0 = ln[(wp - (uint32_t)L2) & SP_MASK], t1 = ln[(wp - (uint32_t)L2 - 1u) & SP_MASK];
        fx.sp_lp += mulq15(r - fx.sp_lp, kl);
        o = fx.sp_lp * g;
        x += (o + ((o >> 31) & 32767)) >> 15;           /* towards 0: a loop of floors would hold an offset */
        o = x - fx.sp_hp + fx.sp_he;                    /* the low cut, its step's remainder kept (as */
        fx.sp_he = o & 63;                              /* dc_block): no dead band to hold an offset in the loop */
        fx.sp_hp += o >> 6;
        x -= fx.sp_hp;
        p = ap[j];                                      /* the chain: ap[j + k], stage k's output 4 samples ago */
        ap[j] = x;
        for (k = 1; k <= SP_N; k++) {                   /* (lossless: bounded by the loop's input, no clamp) */
            int32_t v = (x - ap[j + k]) * SP_A;         /* towards 0, as the loop's gain: floors would feed */
            o = ap[j + k];                              /* the loop a little offset and noise for ever */
            x = ((v + ((v >> 31) & 4095)) >> 12) + p;
            p = o;
            ap[j + k] = x;
        }
        ln[wp & SP_MASK] = (int16_t)clamp(x, -32768, 32767);
        fx.sp_w = (uint16_t)(wp + 1u);
        out[i] += (t0 + (((t1 - t0) * f) >> 8)) * 4 + ln[(wp - (uint32_t)L3) & SP_MASK] * 2;
    }
}

static __attribute__((noinline)) void ins_swept_ref(ins_t *s, const track_t *t, int32_t *b, uint32_t n, int32_t tw)
{
    uint32_t i, inc = LFO_INC[clamp(t->p[P_IA], 0, 127)] / CTL, dep = (uint32_t)clamp(t->p[P_IB], 0, 127);
    int32_t c = clamp(t->p[P_IC], 0, 127);
    if (s->type == IT_PHASER) {                         /* the coefficients a block at a time (at its middle) */
        uint32_t tr = pf_tri(s->ph + (n >> 1) * inc), q = 32768u + (uint32_t)(((int32_t)tr - 32768) * (int32_t)dep / 127);
        int32_t a = PH_A[q >> 11] + (((PH_A[(q >> 11) + 1u] - PH_A[q >> 11]) * (int32_t)(q & 2047u)) >> 11);
        int32_t fbk = c * 180;                          /* 0 .. 0.7, Q15 */
        for (i = 0; i < n; i++) {
            int32_t x = b[i], xs = clamp((x + 4) >> 3, -16383, 16383), u = xs + ((s->fb * fbk + 16384) >> 15), y = u;
            uint32_t st;
            s->w += clamp(tw - s->w, -SL_SLOPE, SL_SLOPE);
            for (st = 0; st < PH_ST; st++) {            /* y = a (u - y1) + u1 */
                y = clamp(s->px[st] + ((a * (u - s->py[st]) + 8192) >> 14), -65535, 65535);
                s->px[st] = u;
                s->py[st] = y;
                u = y;
            }
            s->fb = clamp(y, -32767, 32767);
            y <<= 2;                                    /* (y: at an eighth) */
            s->dc += ((y << 8) - s->dc) >> 9;           /* DC blocker, ~14 Hz (a clipped loud input is lopsided) */
            b[i] = pf_mix(x, (x >> 1) + y - (s->dc >> 8), s->w);   /* (dry + all-passed) / 2 */
        }
        s->ph += n * inc;
        return;
    }
    {
        int32_t chorus = s->type == IT_CHORUS, fbk = c * (chorus ? 103 : 219);   /* 0 .. 0.4 / 0 .. 0.85, Q15 */
        uint32_t dq = dep * 516u;                       /* DEPTH, Q16 */
        for (i = 0; i < n; i++, s->ph += inc) {
            int32_t x = b[i], r0, r1, v, fr;
            uint32_t d;                                 /* the delay, Q16 samples */
            s->w += clamp(tw - s->w, -SL_SLOPE, SL_SLOPE);
            if (chorus) {
                d = (uint32_t)((140 << 16) + ((osc_sine(s->ph) * (int32_t)dep * 50) >> 5));   /* 3.2 +- 2.3 ms */
            } else {
                uint32_t tr = pf_tri(s->ph), sw = (tr * tr) >> 16;   /* longer near the short end (perform.c) */
                d = (11u << 16) + 209u * (((sw >> 1) * dq) >> 15);  /* 0.25 .. 5 ms */
            }
            r0 = (int32_t)(s->wp - (d >> 16)) & (int32_t)(IL_LEN - 1u);
            r1 = (r0 - 1) & (int32_t)(IL_LEN - 1u);
            fr = (int32_t)((d >> 1) & 0x7FFFu);
            v = s->line[r0] + (((s->line[r1] - s->line[r0]) * fr) >> 15);
            s->line[s->wp] = (int16_t)clamp((x >> 2) + softclip(mulq15(v, fbk)), -32767, 32767);
            s->wp = (uint16_t)((s->wp + 1u) & (IL_LEN - 1u));
            v <<= 1;                                    /* (v: at a quarter) */
            s->dc += ((v << 8) - s->dc) >> 9;           /* DC blocker (the line's clip on a loud lopsided wave) */
            b[i] = pf_mix(x, (x >> 1) + v - (s->dc >> 8), s->w);   /* (dry + delayed) / 2 */
        }
    }
}

static inline int32_t ph_side_ref(uint32_t c, int32_t x, int32_t a)
{
    int32_t xs = clamp((x + 2) >> 2, -16383, 16383), u = xs + ((pf.pfb[c] * PH_FB + 16384) >> 15), y = u;
    uint32_t s;
    for (s = 0; s < PH_ST; s++) {                       /* y = a (u - y1) + u1 */
        y = clamp(pf.px[c][s] + ((a * (u - pf.py[c][s]) + 8192) >> 14), -65535, 65535);
        pf.px[c][s] = u;
        pf.py[c][s] = y;
        u = y;
    }
    pf.pfb[c] = clamp(y, -32767, 32767);
    u = xs + y;                                         /* (x + y) / 2 * 0.9, x 4 (>> 2 above): (x + y) * 1.8 */
    return pf_mix(x, u + mulq16(u, 52429u), pf.pw);
}

static __attribute__((noinline)) void perf_phaser_ref(int32_t *bl, int32_t *br, uint32_t n)
{
    uint32_t i, c, inc, q = perf_lfo(8u, n, &inc) + (n >> 1) * inc;
    int32_t tw = pf.act & PF_BIT(PF_PHS) ? perf_mod_depth() : 0, *const b[2] = {bl, br};
    int32_t a[2] = {ph_coef(q), ph_coef(q - 0x40000000u)};   /* (the right a quarter of the sweep behind) */
    if (!pf.pw) {                                       /* starting: the stages from rest */
        memset(pf.px, 0, sizeof pf.px);
        memset(pf.py, 0, sizeof pf.py);
        pf.pfb[0] = pf.pfb[1] = 0;
    }
    for (i = 0; i < n; i++) {
        pf.pw += clamp(tw - pf.pw, -SL_SLOPE, SL_SLOPE);
        for (c = 0; c < 2u; c++)
            b[c][i] = ph_side_ref(c, b[c][i], a[c]);
    }
}
static int mutate;
static uint32_t seed = 0x1234567u;
static int32_t input(int32_t amplitude)
{
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return (int32_t)(((int64_t)(int32_t)seed * amplitude) >> 31);
}
static int equal(const void *a, const void *b, size_t n, const char *path, uint32_t block)
{
    if (!memcmp(a, b, n)) return 1;
    fprintf(stderr, "stage unroll: %s differs at block %u%s\n", path, block, mutate ? " (expected injected mutation)" : "");
    return 0;
}
static int spring(void)
{
    static unsigned char old_fx[sizeof fx], next_fx[sizeof fx];
    static unsigned char old_comb[sizeof rev_comb], next_comb[sizeof rev_comb];
    static unsigned char old_ap[sizeof rev_u], next_ap[sizeof rev_u];
    const int values[] = {0, 64, 127};
    int32_t in[CTL], out[CTL], ref[CTL];
    uint32_t size, damp, block, i;
    for (size = 0; size < 3; size++) for (damp = 0; damp < 3; damp++) {
        memset(&fx, 0, sizeof fx); memset(rev_comb, 0, sizeof rev_comb); memset(&rev_u, 0, sizeof rev_u);
        for (block = 0; block < 512; block++) {
            uint32_t n = block % 4 == 0 ? 1 : block % 4 == 1 ? 17 : CTL;
            song.g[G_RSIZE] = values[(size + block / 64) % 3]; song.g[G_RDAMP] = values[damp];
            for (i = 0; i < n; i++) { in[i] = block % 128 < 64 ? input(90000) : 0; out[i] = ref[i] = input(1000); }
            memcpy(old_fx, &fx, sizeof fx); memcpy(old_comb, rev_comb, sizeof rev_comb); memcpy(old_ap, &rev_u, sizeof rev_u);
            rev_spring(in, out, n);
            memcpy(next_fx, &fx, sizeof fx); memcpy(next_comb, rev_comb, sizeof rev_comb); memcpy(next_ap, &rev_u, sizeof rev_u);
            memcpy(&fx, old_fx, sizeof fx); memcpy(rev_comb, old_comb, sizeof rev_comb); memcpy(&rev_u, old_ap, sizeof rev_u);
            rev_spring_ref(in, ref, n);
            if (mutate) ref[0]++;
            if (!equal(out, ref, n * sizeof *out, "SPRING PCM", block) || !equal(next_fx, &fx, sizeof fx, "SPRING scalars", block) ||
                !equal(next_comb, rev_comb, sizeof rev_comb, "SPRING line", block) || !equal(next_ap, &rev_u, sizeof rev_u, "SPRING stages", block)) return 0;
        }
    }
    puts("stage unroll: SPRING 4608 blocks PCM/state identical"); return 1;
}
static int insert(void)
{
    const int values[] = {0, 64, 127};
    ins_t actual, reference;
    track_t t;
    int32_t out[CTL], ref[CTL];
    uint32_t rate, depth, feedback, block, i;
    for (rate = 0; rate < 3; rate++) for (depth = 0; depth < 3; depth++) for (feedback = 0; feedback < 3; feedback++) {
        memset(&actual, 0, sizeof actual); memset(&reference, 0, sizeof reference); memset(&t, 0, sizeof t);
        actual.type = reference.type = IT_PHASER; actual.ph = reference.ph = 0xfffff000u;
        t.p[P_IA] = values[rate]; t.p[P_IB] = values[depth]; t.p[P_IC] = values[feedback];
        for (block = 0; block < 256; block++) {
            uint32_t n = block % 4 == 0 ? 1 : block % 4 == 1 ? 17 : CTL;
            int32_t wet = block % 64 < 32 ? 32768 : 0;
            for (i = 0; i < n; i++) out[i] = ref[i] = block % 64 < 48 ? input(1 << 22) : 0;
            ins_swept(&actual, &t, out, n, wet); ins_swept_ref(&reference, &t, ref, n, wet);
            if (mutate) reference.py[0]++;
            if (!equal(out, ref, n * sizeof *out, "INSERT PCM", block) || !equal(&actual, &reference, sizeof actual, "INSERT state", block)) return 0;
        }
    }
    puts("stage unroll: INSERT PHASR 6912 blocks PCM/state identical"); return 1;
}
static int performance(void)
{
    static unsigned char before[sizeof pf], after[sizeof pf];
    const int tempos[] = {60, 120, 240}, depths[] = {0, 50, 100};
    int32_t l[CTL], r[CTL], rl[CTL], rr[CTL];
    uint32_t tempo, depth, block, i;
    for (tempo = 0; tempo < 3; tempo++) for (depth = 0; depth < 3; depth++) {
        memset(&pf, 0, sizeof pf); song.g[G_BPM] = tempos[tempo]; pf.P = FS * 60u / (uint32_t)tempos[tempo] / 4u; perf_k[3] = depths[depth];
        for (block = 0; block < 256; block++) {
            uint32_t n = block % 4 == 0 ? 1 : block % 4 == 1 ? 17 : CTL;
            pf.act = block % 64 < 32 ? PF_BIT(PF_PHS) : 0;
            for (i = 0; i < n; i++) { l[i] = rl[i] = block % 64 < 48 ? input(1 << 22) : 0; r[i] = rr[i] = block % 128 < 64 ? input(1 << 22) : 0; }
            pf.ph += n;
            memcpy(before, &pf, sizeof pf); perf_phaser(l, r, n); memcpy(after, &pf, sizeof pf);
            memcpy(&pf, before, sizeof pf); perf_phaser_ref(rl, rr, n);
            if (mutate) pf.pfb[0]++;
            if (!equal(l, rl, n * sizeof *l, "FX PHASER left", block) || !equal(r, rr, n * sizeof *r, "FX PHASER right", block) || !equal(after, &pf, sizeof pf, "FX PHASER state", block)) return 0;
        }
    }
    puts("stage unroll: FX PHASER 2304 blocks PCM/state identical"); return 1;
}
int main(void)
{
    if (!spring() || !insert() || !performance()) return 1;
    mutate = 1;
    if (spring() || insert() || performance()) return 1;
    puts("stage unroll: injected SPRING PCM and both PHASER state mutations detected");
    return 0;
}
