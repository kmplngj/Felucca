/* SPDX-License-Identifier: GPL-3.0-only */
/* MACRO: the full Braids model bank, with Felucca's envelopes, modulation, LP filter and drive.
 * Core/table attribution: macro_dsp.c, assets/braids/, LICENSES/MIT-Braids.txt. */
#include "felucca_braids.h"
#include "macro_dsp.c"

typedef struct {
    macro_osc_t osc;
    int32_t ic1, ic2;
} macro_note_t;
typedef struct {
    macro_note_t note[NVOICE];
    braids_MacroOscillator full;
    uint8_t full_shape, full_init;
} macro_part_t;
ENG_MEM_FITS("MACRO", sizeof(macro_part_t));
_Static_assert(sizeof(braids_MacroOscillator) % 4u == 0u, "MACRO reset uses whole words");
typedef uint32_t macro_clear_word_t __attribute__((may_alias));

static macro_part_t *macro_part(track_t *t)
{
    return (macro_part_t *)ENG_MEM_OF(t, ENGI_MACRO, trk_index(t));
}

static uint8_t macro_poly(const track_t *t)
{
    return (uint32_t)t->p[P_E0] % MAC_NSHAPE < 3u ? 0u : 1u;
}

static macro_note_t *macro_note(track_t *t, voice_t *v)
{
    return &macro_part(t)->note[voice_index(t, v)];
}

static void macro_note_on(track_t *t, voice_t *v)
{
    macro_note_t *s = macro_note(t, v);
    if (!v->env_out) {                     /* voice_start sets this to 0 for a note from silence */
        memset(s, 0, sizeof *s);
        s->osc.shape = 255u;
        v->ph[0] = v->ph[1] = 0;
    }                                     /* a sounding retrigger retains phases, feedback and filter */
    if ((uint32_t)t->p[P_E0] % MAC_NSHAPE >= 3u && macro_part(t)->full_init)
        braids_MacroOscillator_Strike(&macro_part(t)->full);
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

static const char *const N_MACRO_SHAPE[] = {"WAVE", "FOLD", "FBFM", "CSAW", "MORPH", "SAW SQUARE", "BUZZ", "SQUARE SUB", "SAW SUB", "SQUARE SYNC", "SAW SYNC", "TRIPLE SAW", "TRIPLE SQR", "TRIPLE TRI", "TRIPLE SINE", "RING", "SWARM", "SAW COMB", "TOY", "ZLPF", "ZPKF", "ZBPF", "ZHPF", "VOSIM", "VOWEL", "VOWEL FOF", "HARMONICS", "FM", "CHAOTIC FM", "PLUCKED", "BOWED", "BLOWN", "FLUTE", "BELL", "METAL DRUM", "KICK", "CYMBAL", "SNARE", "WAVETABLE", "WAVE MAP", "WAVE CHORD", "NOISE", "TWIN PEAKS", "CLOCK NOISE", "CLOUD", "PARTICLES", "QPSK", "QUESTION"};
static const uint8_t MACRO_UPSTREAM[MAC_NSHAPE] = {39, 3, 26, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 44, 45, 46, 47};
static const char *const MACRO_LABEL[MAC_NSHAPE][2] = {
    {"SCAN", "TEXTURE"},
    {"FOLD", "BLEND"},
    {"DEPTH", "MOD PIT"},
    {"NOTCH", "DEPTH"},
    {"WAVE", "CHAR"},
    {"WIDTH", "BLEND"},
    {"HARM", "DETUNE"},
    {"WIDTH", "SUB LV"},
    {"WIDTH", "SUB LV"},
    {"SYNC", "BAL"},
    {"SYNC", "BAL"},
    {"PITCH 2", "PITCH 3"},
    {"PITCH 2", "PITCH 3"},
    {"PITCH 2", "PITCH 3"},
    {"PITCH 2", "PITCH 3"},
    {"PITCH 2", "PITCH 3"},
    {"DETUNE", "HIPASS"},
    {"COMB", "FBACK"},
    {"CLOCK", "GLITCH"},
    {"CUTOFF", "WAVE"},
    {"CUTOFF", "WAVE"},
    {"CUTOFF", "WAVE"},
    {"CUTOFF", "WAVE"},
    {"FORM1", "FORM2"},
    {"VOWEL", "FORMNT"},
    {"VOWEL", "FORMNT"},
    {"CENTER", "SPREAD"},
    {"DEPTH", "RATIO"},
    {"DEPTH", "RATIO"},
    {"DAMP", "POSIT"},
    {"FRICT", "POSIT"},
    {"PRESS", "GEOM"},
    {"PRESS", "GEOM"},
    {"DAMP", "INHARM"},
    {"DAMP", "BRIGHT"},
    {"DECAY", "TONE"},
    {"BAND", "NOISE"},
    {"TONE", "SNAPPY"},
    {"SCAN", "BANK"},
    {"X SCAN", "Y SCAN"},
    {"SCAN", "CHORD"},
    {"RES", "LP / HP"},
    {"RES", "SPACING"},
    {"PERIOD", "QUANT"},
    {"DENSE", "SPREAD"},
    {"DENSE", "SPREAD"},
    {"RATE", "DATA"},
    {"CLOCK", "CHAR"},
};

/* The added bank retains Braids' internal delays and plucked-string voices in
 * one slot per part. The original three models still have independent eight-voice
 * state. Model changes retire extra voices with the existing one-block fade. */
static void macro_block(track_t *t)
{
    uint32_t i, shape = (uint32_t)t->p[P_E0] % MAC_NSHAPE;
    macro_part_t *part = macro_part(t);
    if (shape < 3u) {
        part->full_shape = 255u;
        return;
    }
    if (!t->v[0].active)
        for (i = 1; i < NVOICE; i++)
            if (t->v[i].active && t->v[i].stage != 4u) {
                t->v[0] = t->v[i];
                part->note[0] = part->note[i];
                t->v[i].active = t->v[i].gate = 0;
                break;
            }
    for (i = 1; i < NVOICE; i++)
        if (t->v[i].active) {
            t->v[i].gate = 0;
            t->v[i].stage = 4;
        }
    if (!part->full_init || part->full_shape != shape) {
        /* eng_mem_claim already zeroes the first use. Later model changes clear
         * aligned words, keeping the large delay reset bounded in the audio path. */
        if (part->full_init) {
            macro_clear_word_t *words = (macro_clear_word_t *)&part->full;
            for (i = 0; i < sizeof part->full / 4u; i++) words[i] = 0;
        }
        /* Independent deterministic streams, including after model resets.
         * Part zero retains the source/reference seed and existing goldens. */
        part->full.digital_oscillator_.rng_ = 0x21u + 0x9e3779b9u * trk_index(t);
        braids_MacroOscillator_Init(&part->full);
        part->full.shape_ = (braids_MacroOscillatorShape)MACRO_UPSTREAM[shape];
        part->full_shape = (uint8_t)shape;
        part->full_init = 1;
    }
}

static void macro_full_run(track_t *t, voice_t *v, int32_t pitch, int32_t timbre,
                           int32_t color, const vmod_t *m, int16_t *b, uint32_t n)
{
    macro_part_t *part = macro_part(t);
    macro_osc_t *old = &macro_note(t, v)->osc;
    uint32_t shape = (uint32_t)t->p[P_E0] % MAC_NSHAPE, i, offset;
    int changed = old->shape < MAC_NSHAPE && old->shape != shape;
    int16_t raw[2 * CTL];
    uint8_t sync[24] = {0};
    int32_t fine_pitch = t->p[P_E7] * 128 / 100 + m->fine * 709 / 1310;
    braids_MacroOscillator_set_pitch(&part->full, (int16_t)clamp(pitch * 8 + fine_pitch, 0, 16383));
    braids_MacroOscillator_set_parameters(&part->full, (int16_t)timbre, (int16_t)color);
    for (offset = 0; offset < 2u * n; offset += 24u) {
        uint32_t count = 2u * n - offset;
        if (count > 24u) count = 24u;
        braids_MacroOscillator_Render(&part->full, sync, raw + offset, count);
    }
    for (i = 0; i < n; i++) {
        int32_t x = ((int32_t)raw[2u * i] + raw[2u * i + 1u]) >> 1;
        if (!i && changed) {
            old->correction = old->last - x;
            old->fade = CTL;
        }
        if (old->fade) {
            x += old->correction * old->fade / CTL;
            old->fade--;
        }
        b[i] = (int16_t)clamp(x, -32768, 32767);
        old->last = b[i];
    }
    old->shape = (uint8_t)shape;
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
    if (shape >= 3u && v == &t->v[0])
        macro_full_run(t, v, pitch, timbre, color, m, b, n);
    else {
        uint32_t old_shape = shape < 3u ? shape : s->osc.shape % 3u;
        mac_run(&s->osc, old_shape, &v->ph[0], &v->ph[1], inc, mod_inc, pitch * 8, timbre, color, b, n);
    }
    tsvf_coef(&flt, cut, p[P_E5]);
    for (i = 0; i < n; i++) {
        int32_t x = b[i];
        if (p[P_E6])
            x = softclip((x * drive) >> 15);
        x = tsvf_lp(&flt, x >> 1, &s->ic1, &s->ic2);
        out[i] += voice_amp(soft_knee(x * 2, 24000), m, i);
    }
}

static const preset_t MACRO_PRESETS[] = {
    /* SHAPE TIMBRE COLOR TUNE CUT RES DRIVE FINE; envelope; filter envelope; mono */
    {"WAVE SCAN", {MAC_WAVE, 40, 64, 0, 110, 8, 0, 0}, {10, 65, 100, 45}, 0, 0, FX(0, 20, 20, 35), PAT(5)},
    {"WAVE BASS", {MAC_WAVE, 80, 32, -12, 60, 30, 8, 0}, {0, 55, 75, 20}, 24, 1, FX(0, 0, 15, 0), PAT(2)},
    {"FOLD LEAD", {MAC_FOLD, 80, 32, 0, 100, 12, 0, 0}, {0, 60, 100, 35}, 0, 1, FX(0, 15, 30, 20), PAT(4)},
    {"FOLD PAD", {MAC_FOLD, 45, 96, 0, 78, 15, 0, 4}, {65, 80, 105, 80}, 0, 0, FX(0, 40, 25, 55), PAT(5)},
    {"FBFM BELL", {MAC_FBFM, 50, 76, 0, 115, 5, 0, 0}, {0, 85, 0, 70}, 0, 0, FX(0, 0, 25, 45), PAT(7)},
    {"FBFM BASS", {MAC_FBFM, 72, 64, -12, 65, 15, 5, 0}, {0, 50, 75, 25}, 18, 1, FX(0, 0, 10, 0), PAT(2)},
    {"CSAW", {3, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"MORPH", {4, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SAW SQUARE", {5, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"BUZZ", {6, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SQUARE SUB", {7, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SAW SUB", {8, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SQUARE SYNC", {9, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SAW SYNC", {10, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"TRIPLE SAW", {11, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"TRIPLE SQR", {12, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"TRIPLE TRI", {13, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"TRIPLE SINE", {14, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"RING", {15, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SWARM", {16, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SAW COMB", {17, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"TOY", {18, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"ZLPF", {19, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"ZPKF", {20, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"ZBPF", {21, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"ZHPF", {22, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"VOSIM", {23, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"VOWEL", {24, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"VOWEL FOF", {25, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"HARMONICS", {26, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"FM", {27, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"CHAOTIC FM", {28, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"PLUCKED", {29, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 0, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"BOWED", {30, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"BLOWN", {31, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"FLUTE", {32, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"BELL", {33, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 0, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"METAL DRUM", {34, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 0, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"KICK", {35, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 0, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"CYMBAL", {36, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"SNARE", {37, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 0, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"WAVETABLE", {38, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"WAVE MAP", {39, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"WAVE CHORD", {40, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"NOISE", {41, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"TWIN PEAKS", {42, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"CLOCK NOISE", {43, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"CLOUD", {44, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"PARTICLES", {45, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"QPSK", {46, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
    {"QUESTION", {47, 64, 64, 0, 110, 8, 0, 0}, {0, 85, 100, 45}, 0, 0, FX(0, 10, 15, 25), PAT(5)},
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
    .block = macro_block,
    .knob = {P_E1, P_E2, P_E4, P_E0},
    .mem = sizeof(macro_part_t),
};
