/* SPDX-License-Identifier: GPL-3.0-only */
/* MACRO through the real engine/mixer: tuning, control response, independence, retriggers,
 * eight-voice corner loads, release and repeatable host instruction measurements. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#ifdef __APPLE__
#include <libproc.h>
#include <sys/resource.h>
#endif
static int bad;
static void check(const char *what, int ok)
{
    printf("macro: %-76s %s\n", what, ok ? "ok" : "FAIL");
    bad += !ok;
}
static void setup(uint32_t shape, uint32_t timbre, uint32_t color)
{
    memset(trk, 0, sizeof trk);
    memset(eng_mem_owner, 0, sizeof eng_mem_owner);
    host_tracks_init();
    host_preset(&trk[0], ENGI_MACRO, 0);
    trk[0].p[P_E0] = shape; trk[0].p[P_E1] = timbre; trk[0].p[P_E2] = color;
    trk[0].p[P_E4] = 127; trk[0].p[P_E5] = 0;
    trk[0].p[P_ATK] = trk[0].p[P_REL] = trk[0].p[P_ED_FLT] = 0;
    trk[0].p[P_SUS] = 127; trk[0].p[P_VOICE] = V_POLY;
    trk[0].p[P_CHOR] = trk[0].p[P_DLY] = trk[0].p[P_REV] = 0;
}
static uint64_t capture(uint32_t note, int32_t *samples)
{
    uint64_t hash = 0xcbf29ce484222325ull;
    int32_t b[CTL];
    uint32_t i, k;
    trk_note_on(&trk[0], note, 100);
    for (i = 0; i < FS / 10 / CTL; i++) track_render(&trk[0], b, CTL);
    for (i = 0; i < 8192; i += CTL) {
        track_render(&trk[0], b, CTL);
        for (k = 0; k < CTL; k++) {
            if (samples) samples[i + k] = b[k];
            hash ^= (uint32_t)b[k]; hash *= 0x100000001B3ull;
        }
    }
    return hash;
}
static void tuning_and_controls(void)
{
    static int32_t y[8192];
    uint32_t shape, note;
    for (shape = MAC_FOLD; shape <= MAC_FBFM; shape++)
        for (note = 45; note <= 81; note += 12) {
            uint32_t i, crossings = 0;
            char msg[128];
            double want = 440.0 * pow(2.0, ((int)note - 69) / 12.0), hz;
            setup(shape, 0, 0);
            capture(note, y);
            for (i = 1; i < 8192; i++) crossings += y[i - 1] <= 0 && y[i] > 0;
            hz = crossings * (double)FS / 8192;
            snprintf(msg, sizeof msg, "%s note %u: %.2f Hz (want %.2f)", N_MACRO_SHAPE[shape], note, hz, want);
            check(msg, fabs(hz - want) < FS / 8192.0 + want * 0.002);
        }
    for (shape = 0; shape < 3u; shape++) {
        uint64_t a, b, c, d;
        setup(shape, 20, 32); a = capture(60, 0);
        setup(shape, 100, 32); b = capture(60, 0);
        setup(shape, 100, 96); c = capture(60, 0);
        setup(shape, 20, 32); d = capture(60, 0);
        check("TIMBRE and COLOR change each model; notes from silence repeat exactly", a != b && b != c && a == d);
    }
}
static void lifecycle(void)
{
    int32_t b[CTL];
    uint32_t shape, i;
    for (shape = 0; shape < 3u; shape++) {
        setup(shape, 100, 80);
        trk_note_on(&trk[0], 60, 100);
        for (i = 0; i < 100; i++) track_render(&trk[0], b, CTL);
        voice_t *v = 0;
        for (i = 0; i < NVOICE; i++) if (trk[0].v[i].active) { v = &trk[0].v[i]; break; }
        macro_note_t saved = *macro_note(&trk[0], v);
        uint32_t ph = v->ph[0], mp = v->ph[1];
        trk_note_on(&trk[0], 60, 100);
        check("sounding retrigger retains phase, feedback and filter state",
              v->ph[0] == ph && v->ph[1] == mp && !memcmp(&saved, macro_note(&trk[0], v), sizeof saved));
        host_preset(&trk[1], ENGI_MACRO, 2);
        trk_note_on(&trk[1], 72, 110);
        for (i = 0; i < 100; i++) track_render(&trk[1], b, CTL);
        check("another part owns independent oscillator/filter state",
              !memcmp(&saved, macro_note(&trk[0], v), sizeof saved));
        trk_note_off(&trk[0], 60);
        for (i = 0; i < FS * 4 / CTL; i++) track_render(&trk[0], b, CTL);
        int silent = 1;
        for (i = 0; i < CTL; i++) silent &= !b[i];
        for (i = 0; i < NVOICE; i++) silent &= !trk[0].v[i].active;
        check("note-off frees every voice and ends in exact silence", silent);
    }
}
static void corners(void)
{
    uint32_t shape, k, i, j;
    int32_t b[CTL], peak = 0;
    for (shape = 0; shape < 3u; shape++)
        for (k = 0; k < 32; k++) {
            setup(shape, k & 1 ? 127 : 0, k & 2 ? 127 : 0);
            trk[0].p[P_E4] = k & 4 ? 127 : 0;
            trk[0].p[P_E5] = k & 8 ? 127 : 0;
            trk[0].p[P_E6] = k & 16 ? 127 : 0;
            trk[0].p[P_LEVEL] = 127;
            for (i = 0; i < 8; i++) trk_note_on(&trk[0], 12 + i * 16, 127);
            for (i = 0; i < FS / 4 / CTL; i++) {
                track_render(&trk[0], b, CTL);
                for (j = 0; j < CTL; j++) if (abs(b[j]) > peak) peak = abs(b[j]);
            }
        }
    printf("macro: eight-voice corner sum peak %d, bound %d\n", peak, 8 * 2 * VOICE_FS);
    check("all models remain bounded at TIMBRE/COLOR/filter/resonance/drive corners", peak < 8 * 2 * VOICE_FS);
}
static uint64_t instr_now(void)
{
#ifdef __APPLE__
    struct rusage_info_v4 r;
    if (!proc_pid_rusage(getpid(), RUSAGE_INFO_V4, (rusage_info_t *)&r)) return r.ri_instructions;
#endif
    return 0;
}
static double cost(uint32_t shape, uint32_t timbre, uint32_t color, uint32_t notes, int mixed)
{
    int32_t out[2 * CTL];
    uint32_t i, k, nb = FS / CTL;
    static const uint8_t chord[8] = {48, 52, 55, 59, 60, 64, 67, 71};
    uint64_t begin = 0;
    setup(shape, timbre, color);
    /* Same sends/filter envelope as the factory WAVE SCAN workload. */
    trk[0].p[P_E4] = 110; trk[0].p[P_E5] = 8;
    trk[0].p[P_E6] = 127;                   /* include the optional drive path in the corner CPU workload */
    trk[0].p[P_CHOR] = 20; trk[0].p[P_DLY] = 20; trk[0].p[P_REV] = 35;
    for (i = 0; i < notes; i++) trk_note_on(&trk[0], chord[i], 100);
    if (mixed) {
        host_preset(&trk[1], ENGI_PHYS, 7); host_preset(&trk[2], ENGI_FM6, 4);
        trk[1].p[P_SUS] = trk[2].p[P_SUS] = 127;
        for (i = 0; i < 2; i++) {
            trk_note_on(&trk[1], chord[i] + 12, 100);
            trk_note_on(&trk[2], chord[i] + 24, 100);
        }
    }
    for (k = 0; k < nb / 2 + nb; k++) {
        if (k == nb / 2) begin = instr_now();
        mix_block(out, CTL);
    }
    return begin ? (double)(instr_now() - begin) / (nb * CTL) : 0;
}
static void costs(void)
{
    uint32_t shape, notes, color;
    double idle = cost(0, 0, 0, 0, 0), worst = 0;
    if (!idle) { puts("macro: SKIP host instructions (no proc_pid_rusage counter)"); return; }
    printf("macro: CPU host instructions per 44.1 kHz frame (0.5 s warm, 1 s counted), idle %.1f\n", idle);
    for (shape = 0; shape < 3u; shape++)
        for (notes = 1; notes <= 8; notes *= 2) {
            double high = 0;
            uint32_t worst_color = 0;
            for (color = 0; color <= 127; color += 1) {
                /* Exhaust the COLOR branches/endpoints; TIMBRE's endpoints do not change loop count. */
                if (color != 0 && color != 31 && color != 32 && color != 63 && color != 64 && color != 95 && color != 96 && color != 127) continue;
                double c = cost(shape, 127, color, notes, 0);
                if (c > high) high = c, worst_color = color;
            }
            printf("macro: CPU %-4s %u voices: %.1f total, %.1f net/voice, COLOR %u\n",
                   N_MACRO_SHAPE[shape], notes, high, (high - idle) / notes, worst_color);
            if (high > worst) worst = high;
        }
    printf("macro: CPU mixed 4 WAVE + 2 PHYS + 2 FM6: %.1f total\n", cost(0, 127, 32, 4, 1));
    check("MACRO corner load stays within the recorded 2600 host-instruction budget", worst < 2600);
}
int main(void)
{
    check("MACRO is ID 14 in every FM4/SLICE configuration; disabled slots stay reserved",
          NENGINES == FELUCCA_PROFILE_NSLOTS + FELUCCA_ENG_TEST14 && ENGI_MACRO == 14 && ENGINES[ENGI_MACRO] == &ENG_MACRO &&
          eng_ok(ENGI_MACRO) && eng_rank(ENGI_MACRO) < NENG_SHOWN &&
          eng_ok(ENGI_SLICE) == !!FELUCCA_SLICE && eng_ok(ENGI_DIGITAL) == !!FELUCCA_FM4);
    printf("macro: state %zu B/voice, %u B/part, arena %u B/part\n", sizeof(macro_note_t), ENG_MACRO.mem, ENG_MEM_PART);
    tuning_and_controls(); lifecycle(); corners();
    if (!getenv("NOCOST")) costs();
    return bad != 0;
}
