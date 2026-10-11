/* SPDX-License-Identifier: GPL-3.0-only */
/* MACRO: selected Braids oscillators, with Felucca's envelopes, modulation, LP filter and drive.
 * Core/table attribution: macro_dsp.c, assets/braids/, LICENSES/MIT-Braids.txt. */
#include "macro_dsp.c"

typedef struct {
    macro_osc_t osc;
    int32_t ic1, ic2;
} macro_note_t;
ENG_MEM_FITS("MACRO", sizeof(macro_note_t) * NVOICE);

static macro_note_t *macro_note(track_t *t, voice_t *v)
{
    return (macro_note_t *)ENG_MEM((uint32_t)(t - trk)) + (uint32_t)(v - t->v);
}

static void macro_note_on(track_t *t, voice_t *v)
{
    macro_note_t *s = macro_note(t, v);
    if (!v->env_out) {                     /* voice_start sets this to 0 for a note from silence */
        memset(s, 0, sizeof *s);
        s->osc.shape = 255u;
        v->ph[0] = v->ph[1] = 0;
    }                                     /* a sounding retrigger retains phases, feedback and filter */
}

/* Q7 pitch, including COLOR's fractional semitone. Reuse Felucca's 44.1 kHz tuning;
 * interpolate its 1/16-semitone table instead of clamping the fractional modulator pitch away. */
static uint32_t macro_inc_q7(int32_t pitch, int32_t fine)
{
    uint32_t shifts = 0, p, a;
    while (pitch < 0) {                   /* COLOR reaches at most 64 semitones below note 0: six shifts */
        pitch += 12 * 128;
        shifts++;
    }
    p = (uint32_t)clamp(pitch, 0, 2047 * 8);
    a = pitch_inc((int32_t)(p >> 3));
    uint32_t b = pitch_inc((int32_t)((p >> 3) + (p < 2047u * 8u)));
    uint32_t inc = (a + (((b - a) * (p & 7u)) >> 3)) >> shifts;
    return inc + (uint32_t)((int32_t)(inc >> 12) * fine);
}

static void macro_render(track_t *t, voice_t *v, int32_t *out, uint32_t n, const vmod_t *m)
{
    macro_note_t *s = macro_note(t, v);
    const int16_t *p = t->p;
    uint32_t shape = (uint32_t)p[P_E0] % MAC_NSHAPE, i;
    int32_t timbre = clamp((p[P_E1] == 127 ? 32767 : p[P_E1] * 256) + m->shape - (64 << 8), 0, 32767);
    int32_t color = p[P_E2] == 127 ? 32767 : p[P_E2] * 256;
    int32_t pitch = clamp(m->pitch16 + p[P_E3] * 16, 0, 2047);
    uint32_t inc = cents_inc(pitch, p[P_E7], m->fine);
    uint32_t mod_inc = macro_inc_q7(pitch * 8 + ((color - 16384) >> 1), m->fine + p[P_E7] * 2367 / 1000);
    int32_t cut = clamp(p[P_E4] * 256 + m->cutoff, 0, 127 << 8), drive = 32768 + p[P_E6] * 768;
    int16_t b[CTL];
    tsvf_t flt;
    if (n > CTL)
        n = CTL;
    mac_run(&s->osc, shape, &v->ph[0], &v->ph[1], inc, mod_inc, pitch * 8, timbre, color, b, n);
    tsvf_coef(&flt, cut, p[P_E5]);
    for (i = 0; i < n; i++) {
        int32_t x = b[i];
        if (p[P_E6])
            x = softclip((x * drive) >> 15);
        x = tsvf_lp(&flt, x >> 1, &s->ic1, &s->ic2);
        out[i] += voice_amp(soft_knee(x * 2, 24000), m, i);
    }
}

static const char *const N_MACRO_SHAPE[] = {"WAVE", "FOLD", "FBFM"};
static const preset_t MACRO_PRESETS[] = {
    /* SHAPE TIMBRE COLOR TUNE CUT RES DRIVE FINE; envelope; filter envelope; mono */
    {"WAVE SCAN", {MAC_WAVE, 40, 64, 0, 110, 8, 0, 0}, {10, 65, 100, 45}, 0, 0, FX(0, 20, 20, 35), PAT(5)},
    {"WAVE BASS", {MAC_WAVE, 80, 32, -12, 60, 30, 8, 0}, {0, 55, 75, 20}, 24, 1, FX(0, 0, 15, 0), PAT(2)},
    {"FOLD LEAD", {MAC_FOLD, 80, 32, 0, 100, 12, 0, 0}, {0, 60, 100, 35}, 0, 1, FX(0, 15, 30, 20), PAT(4)},
    {"FOLD PAD", {MAC_FOLD, 45, 96, 0, 78, 15, 0, 4}, {65, 80, 105, 80}, 0, 0, FX(0, 40, 25, 55), PAT(5)},
    {"FBFM BELL", {MAC_FBFM, 50, 76, 0, 115, 5, 0, 0}, {0, 85, 0, 70}, 0, 0, FX(0, 0, 25, 45), PAT(7)},
    {"FBFM BASS", {MAC_FBFM, 72, 64, -12, 65, 15, 5, 0}, {0, 50, 75, 25}, 18, 1, FX(0, 0, 10, 0), PAT(2)},
};

static const engine_t ENG_MACRO = {
    .name = "MACRO",
    .page_title = {"OSC", "TONE"},
    .edit = {
        {"SHAPE", F_ENUM, 0, MAC_NSHAPE - 1, MAC_WAVE, N_MACRO_SHAPE, 0},
        {"TIMBRE", F_PCT, 0, 127, 64, 0, 0},
        {"COLOR", F_PCT, 0, 127, 64, 0, 0},
        {"TUNE", F_SEMI, -24, 24, 0, 0, 0},
        {"CUT", F_CUTOFF, 0, 127, 110, 0, 0},
        {"RES", F_PCT, 0, 127, 8, 0, 0},
        {"DRIVE", F_PCT, 0, 127, 0, 0, 0},
        {"FINE", F_INT, -50, 50, 0, 0, "ct"},
    },
    .presets = MACRO_PRESETS,
    .npresets = NELEM(MACRO_PRESETS),
    .note_on = macro_note_on,
    .render = macro_render,
    .knob = {P_E1, P_E2, P_E4, P_E0},
    .mem = sizeof(macro_note_t) * NVOICE,
};
