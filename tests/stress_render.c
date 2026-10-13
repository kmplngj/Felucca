/* SPDX-License-Identifier: GPL-3.0-only */
/* Host-only mix_block replay. The Python runner generates the bounded schedule
 * from JSON; each invocation starts with fresh static firmware state. */
#define main hostsim_main
#include "hostsim.c"
#undef main

enum { EV_PRESET, EV_PARAM, EV_GLOBAL, EV_ON, EV_OFF };
typedef struct { uint32_t frame, op, part, a, b; } stress_event_t;
typedef struct {
    const char *name;
    uint32_t frames, seed, count;
    const stress_event_t *events;
} stress_scenario_t;
#include "stress_schedule.h"

int main(int argc, char **argv)
{
    uint32_t frame, next = 0, i, p, max_voices = 0, peak = 0, tail_peak = 0;
    uint64_t render_ns = 0;
    char *end;
    unsigned long index;
    FILE *raw, *wav;
    const stress_scenario_t *s;
    if (argc != 4)
        return 2;
    index = strtoul(argv[1], &end, 10);
    if (!*argv[1] || *end || index >= sizeof STRESS_SCENARIOS / sizeof STRESS_SCENARIOS[0])
        return 2;
    s = &STRESS_SCENARIOS[index];
    if (!(raw = fopen(argv[2], "wb")))
        return 2;
    if (!(wav = fopen(argv[3], "wb"))) {
        fclose(raw);
        return 2;
    }
    host_tracks_init();
    rng_state = s->seed;
    /* Every part has a known factory sound; JSON overrides are ordered events. */
    for (p = 0; p < NPART; p++) {
        host_preset(&trk[p], 0, 5);             /* ANALOG SINE KEY */
        trk[p].p[P_VOICE] = V_POLY;
        trk[p].p[P_CHOR] = trk[p].p[P_DLY] = trk[p].p[P_REV] = 0;
        trk[p].p[P_REL] = 24;
    }
    wav_hdr(wav, s->frames);
    for (frame = 0; frame < s->frames; frame += CTL) {
        int32_t out[2 * CTL];
        uint32_t voices = 0;
        uint64_t start;
        fm1_ms = (uint32_t)((uint64_t)frame * 1000u / FS);
        while (next < s->count && s->events[next].frame == frame) {
            const stress_event_t *e = &s->events[next++];
            track_t *t = &trk[e->part];
            if (e->op == EV_PRESET) {
                if (e->a >= NENGINES || e->b >= ENGINES[e->a]->npresets) {
                    fprintf(stderr, "stress: invalid engine/preset %u/%u at frame %u\n", e->a, e->b, frame);
                    return 2;                 /* never let host_preset_req wrap a preset */
                }
                host_preset_req(t, e->a, e->b);
            } else if (e->op == EV_PARAM) {
                const param_desc_t *d = track_desc(t, e->a);
                if ((int32_t)e->b < d->min || (int32_t)e->b > d->max) {
                    fprintf(stderr, "stress: track parameter %u=%u outside %d..%d at frame %u\n",
                            e->a, e->b, d->min, d->max, frame);
                    return 2;
                }
                t->p[e->a] = (int16_t)e->b;
            } else if (e->op == EV_GLOBAL) {
                if ((int32_t)e->b < GP[e->a].min || (int32_t)e->b > GP[e->a].max) {
                    fprintf(stderr, "stress: global parameter %u=%u outside %d..%d at frame %u\n",
                            e->a, e->b, GP[e->a].min, GP[e->a].max, frame);
                    return 2;
                }
                song.g[e->a] = (int16_t)e->b;
            } else if (e->op == EV_ON)
                input_on(t, e->a, e->b);
            else
                input_off(t, e->a);
        }
        start = now_ns();
        mix_block(out, CTL);
        render_ns += now_ns() - start;         /* mix only; excludes files/events/checks */
        if (fwrite(out, sizeof out, 1, raw) != 1)
            return 2;
        for (i = 0; i < 2u * CTL; i++) {
            int64_t x = out[i], a = x < 0 ? -x : x;
            if (a > 32767)
                return 1;                     /* before 16-bit WAV saturation */
            if ((uint32_t)a > peak)
                peak = (uint32_t)a;
            if (frame >= s->frames - FS / CTL * CTL / 4u && (uint32_t)a > tail_peak)
                tail_peak = (uint32_t)a;
        }
        for (i = 0; i < CTL; i++)
            wav_put(wav, out[2u * i], out[2u * i + 1u]);
        for (p = 0; p < NPART; p++)
            for (i = 0; i < NVOICE; i++)
                voices += trk[p].v[i].active && trk[p].v[i].stage != 4u;
        if (voices > max_voices)
            max_voices = voices;
        if (voices > NVOICE)
            return 1;
    }
    {
        int raw_error = fclose(raw), wav_error = fclose(wav);
        if (raw_error || wav_error || next != s->count)
            return 2;
    }
    printf("{\"frames\":%u,\"peak\":%u,\"tail_peak\":%u,\"max_voices\":%u,"
           "\"voice_starts\":%u,\"rng\":%u,\"playing\":%u,\"parts\":[",
           s->frames, peak, tail_peak, max_voices, vage, rng_state, song.playing);
    for (p = 0; p < NPART; p++) {
        uint32_t active = 0, gated = 0;
        for (i = 0; i < NVOICE; i++) {
            active += trk[p].v[i].active != 0;
            gated += trk[p].v[i].active && trk[p].v[i].gate;
        }
        printf("%s{\"engine\":%u,\"requested\":%u,\"active\":%u,\"gated\":%u,\"held\":%u,\"fading\":%u}",
               p ? "," : "", trk[p].engine, trk[p].eng_req, active, gated, trk[p].nheld, trk[p].xf_on);
    }
    printf("],\"render_ns\":%llu}\n", (unsigned long long)render_ns);
    return 0;
}
