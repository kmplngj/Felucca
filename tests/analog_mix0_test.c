/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Host test of ANALOG's MIX 0 path (#138, eng_analog.c analog_render_1: OSC 2's waveform left out when its level is
 * exactly 0), same sources as the firmware (hostsim.c):
 *   build/host/analog_mix0_test      (run_tests.sh builds and runs it)
 * The render against a reference copy of WAVE 0..4's loop as it was (analog_osc_ref below: both oscillators always),
 * call for call on twin voices: every block's PCM and the whole voice afterwards (both phases, the filter, the noise
 * state) bit for bit. Every WAVE 0..4 (and SYNC / SUB, untouched) x LP / BP / HP, MIX 0 / 1 / 64 / 127 held and
 * 0 -> x -> 0 changes mid-phrase (then random ones), DTN 0 / 127, NOIS DRV RES CUT at their corners, low / high
 * notes, glide and bend (pitch and fine per block), PWM width modulation (shape), retrigger (note-on on a sounding
 * voice), a new note on a fresh voice, legato pitch jumps, three unison voices into one buffer. */
#define main hostsim_main
#include "hostsim.c"
#undef main

/* Deliberate reference faults verify sensitivity to gain rounding and silent OSC 2 phase. */
static uint32_t ref_fault;

/* eng_analog.c analog_osc before #138, renamed (the reference: OSC 2 computed and mixed at every MIX) */
static void analog_osc_ref(track_t *t, voice_t *v, int32_t *out, uint32_t n, const vmod_t *m, uint32_t ft)
{
    const int16_t *p = t->p;
    uint32_t wave = (uint32_t)p[P_E0], i;
    int32_t det = p[P_E1], mix = p[P_E2], noise = p[P_E3];
    int32_t cut = (p[P_E4] << 8) + m->cutoff + (p[P_E7] * (v->pitch16 - 60 * 16) >> 4);
    tsvf_t flt;
    int32_t drive = 32768 + p[P_E6] * 512;
    uint32_t inc1 = m->inc;
    uint32_t inc2 = det ? cents_inc(m->pitch16, det, 0) : inc1;
    uint32_t pw = 0x80000000u + (uint32_t)((m->shape - (64 << 8)) << 15);
    int32_t m2 = mix * 258, m1 = 32767 - m2;
    int32_t nz = noise * 200, drv = p[P_E6];
    uint32_t ph0 = v->ph[0], ph1 = v->ph[1];
    int32_t ic1 = v->s[0], ic2 = v->s[1], nst = v->s[2];
    int32_t fk = ft ? ANALOG_K(p[P_E5]) : 0;
    tsvf_coef(&flt, cut, p[P_E5]);
    for (i = 0; i < n; i++) {
        int32_t a, b, s;
        switch (wave) {
        case 1:
            a = osc_pulse(ph0, inc1, 0x80000000u);
            b = osc_pulse(ph1, inc2, 0x80000000u);
            break;
        case 2:
            a = osc_tri(ph0);
            b = osc_tri(ph1);
            break;
        case 3:
            a = osc_sine(ph0);
            b = osc_sine(ph1);
            break;
        case 4:
            a = osc_pulse(ph0, inc1, pw);
            b = osc_pulse(ph1, inc2, pw);
            break;
        default:
            a = osc_saw(ph0, inc1);
            b = osc_saw(ph1, inc2);
            break;
        }
        ph0 += inc1;
        if (!(ref_fault == 2u && !mix))
            ph1 += inc2;
        s = ref_fault == 1u && !mix ? a : mulq15(a, m1) + mulq15(b, m2);
        if (nz)
            s += mulq15((int32_t)(noise32(&nst) >> 17) - 16384, nz);
        if (drv)
            s = softclip(((s >> 2) * (drive >> 2)) >> 11);
        {
            int32_t y = ft ? analog_tap(&flt, fk, s >> 1, &ic1, &ic2, ft) : tsvf_lp(&flt, s >> 1, &ic1, &ic2);
            int32_t a = y < 0 ? -y : y;
            if (a > 16000) {
                a = 16000 + (softclip((a - 16000) * 2) >> 1);
                y = y < 0 ? -a : a;
            }
            s = y << 1;
        }
        out[i] += voice_amp(s, m, i) << 1;
    }
    v->ph[0] = ph0;
    v->ph[1] = ph1;
    v->s[0] = ic1;
    v->s[1] = ic2;
    v->s[2] = nst;
}
/* Independent current-main SYNC/SUB reference; these paths must stay unchanged. */
static __attribute__((noinline)) void analog_render_x_ref(track_t *t, voice_t *v, int32_t *out, uint32_t n,
                                                      const vmod_t *m)
{
    const int16_t *p = t->p;
    uint32_t sub = p[P_E0] == AW_SUB, i;
    int32_t det = p[P_E1], mix = p[P_E2], noise = p[P_E3];
    int32_t cut = (p[P_E4] << 8) + m->cutoff + (p[P_E7] * (v->pitch16 - 60 * 16) >> 4);
    tsvf_t flt;
    int32_t drive = 32768 + p[P_E6] * 512;
    int32_t m2 = mix * 258, m1 = 32767 - m2;
    int32_t nz = noise * 200, drv = p[P_E6];
    uint32_t ph0 = v->ph[0], ph1 = v->ph[1], inc1 = m->inc, inc2;
    int32_t ic1 = v->s[0], ic2 = v->s[1], nst = v->s[2];
    int32_t jl = v->s[3];                             /* SYNC: 1 + the step of a restart a sample ago (16 bits), 0 none */
    if (sub) {                                        /* an octave below OSC 1, DTN as OSC 2 always had it */
        inc2 = (det ? cents_inc(m->pitch16, det, 0) : inc1) >> 1;
    } else {                                          /* DTN and the shape above OSC 1, 3/16 semitone a step */
        inc2 = pitch_inc(clamp(m->pitch16 + det * 3 + (((m->shape - (64 << 8)) * 3) >> 8), 0, 2047));
        if (m->fine)
            inc2 += (uint32_t)((int32_t)(inc2 >> 12) * m->fine);
    }
    uint32_t ft = (uint32_t)p[P_FTYPE];
    int32_t fk = ANALOG_K(p[P_E5]);
    tsvf_coef(&flt, cut, p[P_E5]);
    for (i = 0; i < n; i++) {
        int32_t a = osc_saw(ph0, inc1), b, s;
        if (sub) {
            b = osc_pulse(ph1, inc2, 0x80000000u);
        } else {
            int32_t bl = blep(ph1, inc2);
            if (jl) {                                 /* just restarted: the step was jl - 1, not a whole cycle */
                bl = (bl * ((jl - 1) >> 1)) >> 15;
                jl = 0;
            }
            b = (int32_t)(ph1 >> 16) - 32768 - bl;
            if (ph0 > 0xFFFFFFFFu - inc1)             /* OSC 1 restarts it before the next sample: round that step */
                b -= (blep(ph0, inc1) * (int32_t)(ph1 >> 17)) >> 15;
        }
        ph0 += inc1;
        ph1 += inc2;
        if (!sub && ph0 < inc1) {                     /* OSC 1 wrapped: OSC 2 restarts at the same point */
            uint32_t f = ph0 / ((inc1 >> 16) | 1u);   /* the part of a sample since, 0..65535 */
            uint32_t at = ph1 - f * (inc2 >> 16);     /* OSC 2 at the wrap */
            jl = (int32_t)(at >> 16) + 1;
            ph1 = f * (inc2 >> 16);
        }
        s = mulq15(a, m1) + mulq15(b, m2);
        if (nz)
            s += mulq15((int32_t)(noise32(&nst) >> 17) - 16384, nz);
        if (drv)
            s = softclip(((s >> 2) * (drive >> 2)) >> 11);
        s = soft_knee(analog_tap(&flt, fk, s >> 1, &ic1, &ic2, ft), 16000) << 1;
        out[i] += voice_amp(s, m, i) << 1;
    }
    v->ph[0] = ph0;
    v->ph[1] = ph1;
    v->s[0] = ic1;
    v->s[1] = ic2;
    v->s[2] = nst;
    v->s[3] = jl;
}

static void analog_render_ref(track_t *t, voice_t *v, int32_t *out, uint32_t n, const vmod_t *m)
{
    if (t->p[P_E0] >= AW_SYNC)
        analog_render_x_ref(t, v, out, n, m);
    else
        analog_osc_ref(t, v, out, n, m, (uint32_t)t->p[P_FTYPE]);
}

static int bad;
static uint64_t ncmp;
static void check(const char *what, int ok)
{
    printf("analog_mix0: %-70s %s\n", what, ok ? "ok" : "FAIL");
    bad += !ok;
}

static uint32_t rs = 0x9E3779B9u;
static uint32_t rnd(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 17;
    rs ^= rs << 5;
    return rs;
}
static int32_t rr(int32_t lo, int32_t hi) { return lo + (int32_t)(rnd() % (uint32_t)(hi - lo + 1)); }
static int32_t pick(const int32_t *v, uint32_t n) { return v[rnd() % n]; }

#define NV 3                                      /* unison voices into one buffer */
#define NBLK 240

/* one phrase: track parameters p0 (MIX by schedule ms), voices twinned, rendered by both; 1 if all equal */
static int phrase(const int16_t *p0, uint32_t ms, int32_t pbase)
{
    static track_t tc, tr;
    voice_t vc[NV], vr[NV];
    int32_t oc[CTL], orf[CTL], pitch[NV], target[NV], fine[NV], amp[NV];
    uint32_t b, k, i, nmix = 0;
    int32_t mixv = rr(1, 127), lfo = rr(-32767, 32767), dl = rr(500, 4000);
    memset(&tc, 0, sizeof tc);
    for (i = 0; i < 8u; i++)
        tc.p[P_E0 + i] = p0[i];
    tc.p[P_FTYPE] = p0[8];
    memset(vc, 0, sizeof vc);
    for (k = 0; k < NV; k++) {
        vc[k].age = rnd();
        vc[k].ph[0] = rnd();
        vc[k].pitch16 = pitch[k] = target[k] = clamp(pbase + rr(-24, 24), 0, 2047);
        fine[k] = k ? rr(-300, 300) : 0;
        amp[k] = 0;
        analog_note_on(&tc, &vc[k]);
    }
    memcpy(vr, vc, sizeof vc);
    for (b = 0; b < NBLK; b++) {
        int32_t mix;
        if ((rnd() & 31) == 0)                    /* a DTN / NOIS / CUT / RES / DRV / KTR change between blocks */
            tc.p[P_E1 + (rnd() % 7)] = (int16_t)pick((const int32_t[]){0, 127, rr(0, 127)}, 3);
        switch (ms) {                             /* the MIX schedule */
        case 0: mix = 0; break;
        case 1: mix = 1; break;
        case 2: mix = 64; break;
        case 3: mix = 127; break;
        default:                                  /* 0, then x, then 0, then random changes */
            if (b < 60)
                mix = 0;
            else if (b < 120)
                mix = mixv;
            else if (b < 160)
                mix = 0;
            else {
                if (!(rnd() & 7))
                    nmix = (rnd() & 1) ? 0u : (uint32_t)rr(1, 127);
                mix = (int32_t)nmix;
            }
            break;
        }
        tc.p[P_E2] = (int16_t)mix;
        memcpy(&tr, &tc, sizeof tc);
        for (i = 0; i < CTL; i++)
            oc[i] = orf[i] = (int32_t)rnd() >> 8;
        lfo += dl;
        if (lfo > 32767 || lfo < -32767)
            dl = -dl, lfo = clamp(lfo, -32767, 32767);
        for (k = 0; k < NV; k++) {
            vmod_t m;
            uint32_t ev = rnd() % 64u;
            if (ev == 0) {                        /* retrigger on the sounding voice */
                target[k] = clamp(pbase + rr(-36, 36), 0, 2047);
                vc[k].pitch16 = vr[k].pitch16 = target[k];
                vc[k].age = vr[k].age = rnd();
                analog_note_on(&tc, &vc[k]);
                analog_note_on(&tr, &vr[k]);
            } else if (ev == 1) {                 /* a new note on a fresh voice */
                uint32_t ph = rnd();
                vc[k].ph[0] = vr[k].ph[0] = ph;
                vc[k].s[2] = vr[k].s[2] = 0;
                vc[k].age = vr[k].age = rnd();
                vc[k].pitch16 = vr[k].pitch16 = pitch[k] = target[k] = clamp(pbase + rr(-36, 36), 0, 2047);
                analog_note_on(&tc, &vc[k]);
                analog_note_on(&tr, &vr[k]);
            } else if (ev == 2) {                 /* legato: a new pitch, no note-on (glides) */
                target[k] = clamp(pbase + rr(-48, 48), 0, 2047);
                vc[k].pitch16 = vr[k].pitch16 = target[k];
            }
            if (pitch[k] != target[k])            /* glide */
                pitch[k] += pitch[k] < target[k] ? 1 + (target[k] - pitch[k]) / 8 : -1 - (pitch[k] - target[k]) / 8;
            m.pitch16 = clamp(pitch[k] + (lfo >> 12), 0, 2047);   /* + vibrato / bend */
            m.inc = pitch_inc((uint32_t)m.pitch16);
            m.fine = fine[k] + ((lfo * 147) >> 15);   /* unison detune + bend's residual */
            if (m.fine)
                m.inc += (uint32_t)((int32_t)(m.inc >> 12) * m.fine);
            m.amp0 = amp[k];
            m.amp1 = amp[k] = (rnd() & 15) ? rr(0, 32767) : 32767;
            m.cutoff = (lfo * 127) >> 7;
            m.shape = (64 << 8) + ((lfo * 127) >> 7) + (int32_t)(rnd() % 4000u) - 2000;   /* PWM swept */
            m.envq15 = rr(0, 32767);
            analog_render(&tc, &vc[k], oc, CTL, &m);
            analog_render_ref(&tr, &vr[k], orf, CTL, &m);
        }
        ncmp++;
        if (memcmp(oc, orf, sizeof oc) || memcmp(vc, vr, sizeof vc) || memcmp(&tc, &tr, sizeof tc))
            return 0;
    }
    return 1;
}

int main(void)
{
    static const char *const MS[] = {"MIX 0", "MIX 1", "MIX 64", "MIX 127", "MIX 0 -> x -> 0 -> random"};
    static const int32_t CORNER[] = {0, 127};
    uint32_t w, ft, ms, r;
    char what[96];
    {
        const int16_t p[] = {0, 127, 0, 127, 127, 127, 127, 64, 0};
        ref_fault = 1u;
        check("detect omitted OSC 1 Q15 gain rounding", !phrase(p, 0, 960));
        ref_fault = 2u;
        check("detect missing silent OSC 2 phase advancement", !phrase(p, 0, 960));
        ref_fault = 0;
        rs = 0x9E3779B9u;
        ncmp = 0;
    }
    for (w = 0; w < 7u; w++)
        for (ft = 0; ft < 3u; ft++)
            for (ms = 0; ms < 5u; ms++) {
                int ok = 1;
                for (r = 0; r < 24u && ok; r++) {
                    int16_t p[9];
                    int32_t pb = r % 3u == 0 ? rr(0, 200) : r % 3u == 1 ? rr(1850, 2047) : rr(400, 1500);
                    p[0] = (int16_t)w;
                    p[1] = (int16_t)(r & 1 ? pick(CORNER, 2) : rr(0, 127));                 /* DTN */
                    p[2] = 0;
                    p[3] = (int16_t)(r & 2 ? pick(CORNER, 2) : rr(0, 127));                 /* NOIS */
                    p[4] = (int16_t)(r & 4 ? pick(CORNER, 2) : rr(0, 127));                 /* CUT */
                    p[5] = (int16_t)(r & 8 ? pick(CORNER, 2) : rr(0, 127));                 /* RES */
                    p[6] = (int16_t)(r & 16 ? pick(CORNER, 2) : rr(0, 127));                /* DRV */
                    p[7] = (int16_t)rr(0, 127);                                             /* KTR */
                    p[8] = (int16_t)ft;
                    ok = phrase(p, ms, pb);
                }
                snprintf(what, sizeof what, "WAVE %s %s %s: PCM and voice state as the reference", N_ANALOG_WAVE[w],
                         N_FTYPE[ft], MS[ms]);
                check(what, ok);
            }
    printf("analog_mix0: %llu blocks compared\n", (unsigned long long)ncmp);
    printf(bad ? "analog_mix0: %d FAILED\n" : "analog_mix0: all ok\n", bad);
    return bad != 0;
}
