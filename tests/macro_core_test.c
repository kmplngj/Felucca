/* SPDX-License-Identifier: GPL-3.0-only */
/* Strict ASan/UBSan coverage of the selected Braids core, without running the older DSP's
 * intentional signed wraps. Interpolation is checked against wide integer arithmetic. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include <assert.h>

int main(void)
{
    uint32_t seed = 1, w, i, shape, timbre, color, note;
    for (w = 0; w < 65; w++)
        for (i = 0; i < 4096; i++) {
            uint32_t phase;
            int64_t a, d, want;
            seed = seed * 1664525u + 1013904223u;
            phase = seed >> 1;                 /* WAV LINE uses the 128-sample half of the phase space */
            a = MACRO_WAVES[w][phase >> 24];
            d = MACRO_WAVES[w][(phase >> 24) + 1] - a;
            want = a * 256 + ((d * (phase & 0xffffffu)) >> 16) - 32768;
            assert(mac_wave(MACRO_WAVES[w], phase) == want);
        }
    assert(!memcmp(MACRO_WAVES[63], MACRO_WAVES[64], 129));
    for (shape = 0; shape < MAC_NSHAPE; shape++)
        for (timbre = 0; timbre < 128; timbre += 1)
            for (color = 0; color <= 4; color++)
                for (note = 0; note < 128; note += 7) {
                    macro_osc_t s = {0};
                    uint32_t ph = 0, mp = 0, k;
                    uint32_t inc = (uint32_t)(440.0 * pow(2.0, ((int)note - 69) / 12.0) * 4294967296.0 / FS);
                    struct { int16_t before, b[CTL], after; } out = {1234, {0}, 5678};
                    s.shape = 255;
                    for (k = 0; k < 8; k++) {
                        mac_run(&s, shape, &ph, &mp, inc, inc, note * 128,
                                timbre == 127 ? 32767 : timbre * 256, color == 4 ? 32767 : color * 8192,
                                out.b, CTL);
                        assert(out.before == 1234 && out.after == 5678);
                    }
                    /* Model changes start at the preceding sample; phases continue. */
                    for (k = 0; k < MAC_NSHAPE; k++) {
                        int16_t last = s.last;
                        uint32_t next = (s.shape + 1) % MAC_NSHAPE;
                        mac_run(&s, next, &ph, &mp, inc, inc, note * 128, 32767, 32767, out.b, CTL);
                        assert(out.b[0] == last && !s.fade);
                    }
                    {   /* Invalid lengths do not write or advance state. */
                        macro_osc_t saved = s;
                        uint32_t saved_ph = ph, saved_mp = mp;
                        mac_run(&s, shape, &ph, &mp, inc, inc, note * 128, 0, 0, out.b, 0);
                        mac_run(&s, shape, &ph, &mp, inc, inc, note * 128, 0, 0, out.b, CTL + 1);
                        assert(!memcmp(&s, &saved, sizeof s) && ph == saved_ph && mp == saved_mp);
                    }
                }
    puts("macro core: wide-reference interpolation, complete scan, pitch/control corners, model transitions and bounds ok");
    return 0;
}
