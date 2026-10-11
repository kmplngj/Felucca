/* SPDX-License-Identifier: MIT
 * Copyright 2012 Emilie Gillet.
 * C adaptation for Felucca, 2026. See LICENSES/MIT-Braids.txt. */
/* Selected Braids oscillators: digital_oscillator.cc RenderWaveLine / RenderFeedbackFm,
 * analog_oscillator.cc RenderSineFold / RenderTriangleFold, macro_oscillator.cc RenderSineTriangle.
 * Source: pichenettes/eurorack, 08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4.
 * Integer interpolation follows stmlib. Signed products are bounded or split explicitly;
 * phase modulation wraps as uint32_t instead of shifting a negative signed sample.
 * The caller supplies 44.1 kHz phase increments, so no 96 kHz Braids tuning tables are used.
 * Two subsamples are averaged for WAV LINE and FOLD, as in Braids. This reduces aliasing;
 * it is not a claim that these nonlinear/wavetable oscillators are band limited. */
#include "felucca_macro.h"

enum { MAC_WAVE, MAC_FOLD, MAC_FBFM, MAC_NSHAPE };
typedef struct {
    uint32_t inc;
    int32_t timbre, color, scan;
    int32_t fm_sample, last, correction;
    uint8_t shape, fade;
} macro_osc_t;

static inline int32_t mac_mix(int32_t a, int32_t b, uint32_t balance)
{
    /* Each term's nonnegative weight sums to 65535; Q15 inputs fit int32_t. */
    return (a * (int32_t)(65535u - balance) + b * (int32_t)balance) >> 16;
}

static inline int32_t mac_sine(uint32_t phase)
{
    uint32_t i = phase >> 24;
    int32_t a = MACRO_SINE[i], d = MACRO_SINE[i + 1u] - a;
    return a + mulq16(d, (phase >> 8) & 65535u);
}

static inline int32_t mac_wave(const uint8_t *w, uint32_t phase)
{
    uint32_t i = phase >> 24;
    int32_t a = w[i], d = w[i + 1u] - a;
    int32_t hi = d * (int32_t)((phase >> 8) & 65535u);
    /* Exact (d * fraction24) >> 16 without its possible signed 32-bit overflow. */
    int32_t lo = (hi & 255) * 256 + d * (int32_t)(phase & 255u);
    return a * 256 + (hi >> 8) + (lo >> 16) - 32768;
}

static inline int32_t mac_cross(const uint8_t *a, const uint8_t *b, uint32_t phase, uint32_t balance)
{
    int32_t x = mac_wave(a, phase), y = mac_wave(b, phase);
    return x + mulq16(y - x, balance);
}

static inline int32_t mac_folder(const int16_t *w, int32_t x)
{
    uint32_t u = (uint32_t)(x + 32768), i = u >> 8;
    int32_t a = w[i];
    return a + ((w[i + 1u] - a) * (int32_t)(u & 255u) >> 8);
}

/* WAVE: TIMBRE traverses the complete original WAV LINE sequence. COLOR progresses from
 * stepped samples to smooth samples, then smooth waves, then increasingly coarse samples.
 * The scan's 1/4 smoothing is time-adjusted from Braids' 24 samples at 96 kHz to 32 at FS:
 * coefficient 0.5667 (~three original blocks); previous-wave crossfade still spans one block. */
static __attribute__((noinline)) void mac_waveline(macro_osc_t *s, uint32_t *phase, uint32_t inc,
                                                   int32_t timbre, int32_t color, int16_t *out, uint32_t n)
{
    int32_t target = timbre * 2;
    uint32_t ph = *phase, i, scan, smooth, rough = 0, step = 32768u / n;
    uint32_t balance = (uint32_t)(color & 8191) * 8u;
    const uint8_t *w0, *w1, *w2;
    s->scan += mulq16(target - s->scan, 37139u);
    scan = (uint32_t)s->scan;
    w0 = MACRO_WAVES[(uint32_t)s->timbre >> 9];
    w1 = MACRO_WAVES[scan >> 10];
    w2 = MACRO_WAVES[(scan >> 10) + 1u];
    smooth = (scan << 6) & 65535u;
    for (i = 0; i < n; i++) {
        int32_t sample = 0;
        uint32_t k;
        for (k = 0; k < 2u; k++) {
            uint32_t p = ph >> 1;
            int32_t a, b;
            if (color < 8192) {
                a = mac_cross(w0, w1, p & 0xfe000000u, rough);
                b = mac_cross(w0, w1, p, rough);
            } else if (color < 16384) {
                a = mac_cross(w0, w1, p, rough);
                b = mac_cross(w1, w2, p, smooth);
            } else if (color < 24576) {
                a = mac_cross(w1, w2, p, smooth);
                b = mac_cross(w1, w2, p & 0xfe000000u, smooth);
            } else {
                a = mac_cross(w1, w2, p & 0xfe000000u, smooth);
                b = mac_cross(w1, w2, p & 0xf8000000u, smooth);
            }
            sample += mac_mix(a, b, balance);
            ph += inc >> 1;
            rough += step;
        }
        out[i] = (int16_t)(sample >> 1);
    }
    s->timbre = s->scan >> 1;
    *phase = ph;
}

/* FOLD: TIMBRE is the folding gain, COLOR blends the folded sine and triangle. Pitch
 * attenuation follows Braids to reduce high-note aliasing. One shared phase is sufficient
 * here: the two original oscillators have the same pitch, sync and initial phase. */
static __attribute__((noinline)) void mac_fold(macro_osc_t *s, uint32_t *phase, uint32_t inc,
                                               int32_t pitch_q7, int32_t timbre, int32_t color,
                                               int16_t *out, uint32_t n)
{
    uint32_t ph = *phase, i, current_inc = s->inc, step = 32767u / n;
    int32_t dinc = inc >= current_inc ? (int32_t)(inc - current_inc) / (int32_t)n
                                     : -((int32_t)(current_inc - inc) / (int32_t)n);
    int32_t as = clamp(32767 - 6 * (pitch_q7 - 92 * 128), 0, 32767);
    int32_t at = clamp(32767 - 7 * (pitch_q7 - 80 * 128), 0, 32767);
    int32_t t0 = s->timbre, dt = timbre - t0, c0 = s->color, dc = color - c0;
    for (i = 0; i < n; i++) {
        uint32_t f = (i + 1u) * step, k;
        int32_t t = t0 + ((dt * (int32_t)f) >> 15);
        int32_t c = c0 + ((dc * (int32_t)f) >> 15);
        int32_t gs = 2048 + (((t * as) >> 15) * 30720 >> 15);
        int32_t gt = 2048 + (((t * at) >> 15) * 30720 >> 15);
        int32_t sum = 0;
        current_inc += (uint32_t)dinc;
        for (k = 0; k < 2u; k++) {
            int32_t x, y;
            uint16_t tri;
            ph += current_inc >> 1;
            x = mac_folder(MACRO_SINE_FOLD, (mac_sine(ph) * gs) >> 15);
            tri = (uint16_t)(ph >> 16);
            y = (int16_t)((uint16_t)((tri << 1) ^ (tri & 32768u ? 65535u : 0u)) + 32768u);
            y = mac_folder(MACRO_TRIANGLE_FOLD, (y * gt) >> 15);
            sum += mac_mix(x, y, (uint32_t)c * 2u);
        }
        out[i] = (int16_t)(sum >> 1);
    }
    s->inc = inc;
    s->timbre = timbre;
    s->color = color;
    *phase = ph;
}

/* FBFM: TIMBRE is modulation depth; COLOR shifts the modulator's pitch +/-64 semitones.
 * The previous carrier sample phase-modulates the modulator: Braids' feedback topology. */
static __attribute__((noinline)) void mac_fbfm(macro_osc_t *s, uint32_t *phase, uint32_t *mod_phase,
                                               uint32_t inc, uint32_t mod_inc, int32_t pitch_q7,
                                               int32_t timbre, int32_t color, int16_t *out, uint32_t n)
{
    uint32_t ph = *phase, mp = *mod_phase, i, step = 32767u / n;
    int32_t previous = s->fm_sample, t0 = s->timbre, dt = timbre - t0;
    int32_t attenuation = clamp(32767 - (pitch_q7 - 72 * 128 + ((color - 16384) >> 1)) * 4, 0, 32767);
    for (i = 0; i < n; i++) {
        uint32_t f = (i + 1u) * step;
        int32_t t = t0 + ((dt * (int32_t)f) >> 15), depth = (t * attenuation) >> 15;
        uint32_t pm;
        ph += inc;
        mp += mod_inc;
        pm = (uint32_t)previous * 16384u;
        pm = (uint32_t)(mac_sine(mp + pm) * depth) * 2u;
        previous = mac_sine(ph + pm);
        out[i] = (int16_t)previous;
    }
    s->fm_sample = previous;
    s->timbre = timbre;
    *phase = ph;
    *mod_phase = mp;
}

static void mac_run(macro_osc_t *s, uint32_t shape, uint32_t *phase, uint32_t *mod_phase,
                    uint32_t inc, uint32_t mod_inc, int32_t pitch_q7, int32_t timbre, int32_t color,
                    int16_t *out, uint32_t n)
{
    uint32_t i;
    int changed = s->shape < MAC_NSHAPE && s->shape != shape;
    if (!n || n > CTL)
        return;
    if (s->shape != shape) {
        s->timbre = timbre;
        s->color = color;
        s->scan = timbre * 2;
        s->inc = inc;
        s->fm_sample = 0;
        s->shape = (uint8_t)shape;
        s->fade = changed ? CTL : 0u;
    }
    if (shape == MAC_WAVE)
        mac_waveline(s, phase, inc, timbre, color, out, n);
    else if (shape == MAC_FOLD)
        mac_fold(s, phase, inc, pitch_q7, timbre, color, out, n);
    else
        mac_fbfm(s, phase, mod_phase, inc, mod_inc, pitch_q7, timbre, color, out, n);
    if (changed)
        s->correction = s->last - out[0];
    for (i = 0; i < n; i++) {
        int32_t x = out[i];
        if (s->fade) {
            x += (s->correction * s->fade) >> CTL_LOG2;
            s->fade--;
        }
        x = clamp(x, -32768, 32767);
        out[i] = (int16_t)x;
        s->last = x;
    }
}
