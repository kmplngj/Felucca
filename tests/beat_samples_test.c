/* SPDX-License-Identifier: GPL-3.0-only */
/* Exercise the production tempo helper before initialization and over every
 * stored int16 value. Descriptor-invalid values use the declared default;
 * valid values and measured external-clock precedence remain exact. */
#define main hostsim_main
#include "hostsim.c"
#undef main

int main(void)
{
    uint32_t bad = 0, fallback = (uint32_t)FS * 60u / (uint32_t)GP[G_BPM].def;
    if (beat_samples() != fallback) bad++;
    for (int32_t bpm = INT16_MIN; bpm <= INT16_MAX; bpm++) {
        uint32_t expected = bpm < GP[G_BPM].min || bpm > GP[G_BPM].max
                          ? fallback : (uint32_t)FS * 60u / (uint32_t)bpm;
        song.g[G_BPM] = (int16_t)bpm;
        midi_beat_samples = 22051u;
        song.g[G_CLOCK] = 0;
        if (beat_samples() != expected) bad++;
        song.g[G_CLOCK] = 1;
        if (beat_samples() != 22051u) bad++;
        midi_beat_samples = 0;
        if (beat_samples() != expected) bad++;
    }
    printf("beat_samples: zero-initialized state and 65536 BPM values, internal/unmeasured/measured external: %s\n", bad ? "FAIL" : "PASS");
    return bad != 0;
}
