/* SPDX-License-Identifier: GPL-3.0-only
 * Adapted from ordenador/Felucca, upstream PRs #264/#265 (2026). */
/* Fixed arithmetic vectors from 1.6.1, also run with strict UBSan. Negative
 * DC/lowcut feedback, FM6 velocity scaling and PHASE output keep their exact values;
 * the divide-free index and division helpers (#623) equal the C they replace. */
#define main hostsim_main
#include "hostsim.c"
#undef main

static uint32_t failures;
static void expect(const char *name, int ok)
{
    printf("signed scaling: %-58s %s\n", name, ok ? "PASS" : "FAIL");
    failures += !ok;
}

/* Frozen before the 1.7.0 arithmetic backport. Exercise the public PHASE callbacks
 * with both output signs, every wave and low/middle/high notes, FOLD off and on.
 * Strict UBSan rejects the former output shift on the first negative sample. */
static void phase_signed_output(void)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    uint32_t negative = 0, positive = 0;
    static const uint32_t folds[] = {0, 1, 127}, notes[] = {36, 69, 108};
    track_t *t = &trk[0];
    for (uint32_t wave = 0; wave < 8; wave++)
        for (uint32_t f = 0; f < NELEM(folds); f++)
            for (uint32_t note = 0; note < NELEM(notes); note++) {
                voice_t v = {0};
                vmod_t m = {0};
                memset(t, 0, sizeof *t);
                t->p[P_E0] = (int16_t)wave;
                t->p[P_E2] = 64; t->p[P_E3] = 48; t->p[P_E6] = 127;
                t->p[P_E7] = (int16_t)folds[f];
                m.pitch16 = (int32_t)notes[note] * 16;
                m.inc = pitch_inc((uint32_t)m.pitch16);
                m.shape = 64 * 256;
                m.amp0 = m.amp1 = m.envq15 = 32767;
                ENG_PHASE.note_on(t, &v);
                for (uint32_t block = 0; block < 16; block++) {
                    int32_t out[CTL] = {0};
                    ENG_PHASE.render(t, &v, out, CTL, &m);
                    for (uint32_t i = 0; i < CTL; i++) {
                        negative += out[i] < 0;
                        positive += out[i] > 0;
                        hash = (hash ^ (uint32_t)out[i]) * UINT64_C(1099511628211);
                    }
                }
            }
    expect("PHASE signed output, all waves and FOLD extremes",
           negative && positive && hash == UINT64_C(0xbe19079679d9c71d));
}

/* #623: the divide-free replacements of constant divides, each against the C it replaces: every track and voice
 * pointer, the index arithmetic for all element sizes up to 4096 B, the signed power-of-two division exhaustively
 * over +-2^20, at the boundaries and over 1M seeded int32 samples per divisor, and the bend's helpers likewise. */
static uint32_t lcg_next(uint32_t *s) { return *s = *s * 1664525u + 1013904223u; }
static int32_t bend_step_ref(int32_t d) { return d > 0 ? (d < 4 ? d : (d + 3) / 4) : (d > -4 ? d : (d - 3) / 4); }
static int32_t bend_coarse_ref(int32_t b) { return b >= 0 ? b / 16 : -((-b + 15) / 16); }
static int32_t bend_fine_ref(int32_t b) { return (b - bend_coarse_ref(b) * 16) * 2367 / 2560; }

static void exact_divides(void)
{
    static const int32_t edges[] = {INT32_MIN, INT32_MIN + 1, INT32_MIN + 15, INT32_MIN + 16, -65536, -4097, -4096,
                                    -4095, -17, -16, -15, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 15, 16, 17, 4095,
                                    4096, 65535, INT32_MAX - 16, INT32_MAX - 3, INT32_MAX - 1, INT32_MAX};
    uint32_t i, j, sz, bad = 0, n = 0, seed = 0x6237u;
    int32_t x;
    for (i = 0; i < NTRK; i++) {                         /* every track, every voice of it */
        bad += trk_index(&trk[i]) != i;
        for (j = 0; j < NVOICE; j++)
            bad += voice_index(&trk[i], &trk[i].v[j]) != j;
    }
    bad += C1_PI(&trk[NTRK - 1]) != (NTRK - 1) % C1_NP;
    expect("trk_index / voice_index: every track and voice", !bad);
    for (sz = 1, bad = 0; sz <= 4096; sz++) {            /* EXACT_INDEX's arithmetic for any element size */
        uint32_t k = IDX_SH(sz), inv = IDX_INV(IDX_ODD(sz));
        for (i = 0; i < 1024; i++, n++)
            bad += (uint32_t)(((uintptr_t)i * sz) >> k) * inv != i;
    }
    for (i = 0; i < 65536; i++, n += 2)                  /* the two real sizes, far beyond the arrays */
        bad += ((i * (uint32_t)sizeof(track_t)) >> IDX_SH(sizeof(track_t))) * IDX_INV(IDX_ODD(sizeof(track_t))) != i ||
               ((i * (uint32_t)sizeof(voice_t)) >> IDX_SH(sizeof(voice_t))) * IDX_INV(IDX_ODD(sizeof(voice_t))) != i;
    expect("EXACT_INDEX: element sizes 1..4096 B, 1024 elements each", !bad && n == 4096u * 1024u + 131072u);
    for (sz = 0, bad = 0, n = 0; sz <= 30; sz++) {       /* sdiv_pow2: d = 1 .. 2^30 */
        int32_t d = (int32_t)(1u << sz);
        for (x = -(1 << 20); x <= 1 << 20; x++, n++)
            bad += sdiv_pow2(x, 1u << sz) != x / d;
        for (i = 0; i < NELEM(edges); i++, n++)
            bad += sdiv_pow2(edges[i], 1u << sz) != edges[i] / d;
        for (i = 0; i < 1u << 20; i++, n++) {
            x = (int32_t)lcg_next(&seed);
            bad += sdiv_pow2(x, 1u << sz) != x / d;
        }
    }
    expect("sdiv_pow2 = C division toward zero, d = 2^0..2^30",
           !bad && n == 31u * ((2u << 20) + 1u + (uint32_t)NELEM(edges) + (1u << 20)));
    for (x = -32768, bad = 0; x <= 32767; x++)           /* FORMANT: (960 - pitch) / 4, every int16 pitch */
        bad += sdiv_pow2(60 * 16 - x, 4) != (60 * 16 - x) / 4;
    expect("FORMANT (960 - pitch) / 4, every int16 pitch", !bad);
    for (x = -(1 << 20), bad = 0; x <= 1 << 20; x++)     /* the bend (voice.c): its domain is |x| < 2^17 */
        bad += bend_step(x) != bend_step_ref(x) || bend_coarse(x) != bend_coarse_ref(x) ||
               bend_fine_of(x) != bend_fine_ref(x);
    for (i = 0; i < NELEM(edges) + (1u << 20); i++) {
        x = i < NELEM(edges) ? edges[i] : (int32_t)lcg_next(&seed);
        if (x > INT32_MIN + 15)                          /* (-x + 15: the reference's own domain) */
            bad += bend_coarse(x) != bend_coarse_ref(x) || bend_fine_of(x) != bend_fine_ref(x);
        if (x >= INT32_MIN + 3 && x <= INT32_MAX - 3)
            bad += bend_step(x) != bend_step_ref(x);
    }
    expect("bend step / coarse / fine = their divisions", !bad);
}

int main(int argc, char **argv)
{
    if (!(argc == 2 && !strcmp(argv[1], "--fm6"))) {
        phase_signed_output();
        exact_divides();
        int32_t dc = 10000, err = 0;
        int32_t out = dc_block(0, &dc, &err);
        expect("DC negative feedback remainder", out == -156 && dc == 9997 && err == 2288);
        dc = err = 0; out = dc_block(-1, &dc, &err);
        expect("DC negative input preserves error feedback", out == -1 && dc == -1 && err == 4032);
        dc = err = 0; out = dc_block(-32768, &dc, &err);
        expect("DC negative full-scale input", out == -32760 && dc == -512 && err == 0);
        dc = 100; err = 0; out = lowcut1(0, &dc, &err, 4);
        expect("lowcut negative feedback remainder", out == -93 && dc == 93 && err == 12);
        dc = err = 0; out = lowcut1(-32768, &dc, &err, 6);
        expect("lowcut negative full-scale input", out == -32256 && dc == -512 && err == 0);
    }
    expect("FM6 zero velocity / maximum sensitivity", fm6_scale_vel(0, 7) == -3344);
    expect("FM6 upper velocity / maximum sensitivity", fm6_scale_vel(127, 7) == 224);
    expect("FM6 velocity inputs clamped", fm6_scale_vel(-10, 7) == -3344 && fm6_scale_vel(130, 7) == 224);
    expect("FM6 zero sensitivity", fm6_scale_vel(0, 0) == 0 && fm6_scale_vel(127, 0) == 0);
    int32_t out[FM6_N] = {0}, in[FM6_N];
    for (uint32_t i = 0; i < FM6_N; i++) in[i] = 100000;
    fm6_op_run(out, in, INT32_MAX - 100, 1234, 1 << 20, 1 << 20, 0);
    uint64_t h = UINT64_C(14695981039346656037);
    for (uint32_t i = 0; i < FM6_N; i++) h = (h ^ (uint32_t)out[i]) * UINT64_C(1099511628211);
    expect("FM6 modulated phase crosses signed boundary", h == UINT64_C(0xedef9f78c8ca7e65));
    int32_t fb[2] = {100000, 100000};
    fm6_op_fb(out, INT32_MAX - 100, 1234, 1 << 20, 1 << 20, fb, 0, 0);
    h = UINT64_C(14695981039346656037);
    for (uint32_t i = 0; i < FM6_N; i++) h = (h ^ (uint32_t)out[i]) * UINT64_C(1099511628211);
    expect("FM6 feedback phase crosses signed boundary", h == UINT64_C(0x496218ec62e956e5));
    fm6_lfo_t l = {0}; l.wave = 4; l.phase = 0xc0000000u;
    expect("FM6 sine LFO negative half", fm6_lfo_sample(&l) == 256);
    puts(failures ? "SIGNED AUDIO SCALING FAILED" : "SIGNED AUDIO SCALING PASSED");
    return failures != 0;
}
