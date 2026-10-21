/* SPDX-License-Identifier: GPL-3.0-only */
/* Fresh process per capture: the real sound installer, events, voices, stereo
 * mixer, buses and master. Python owns metrics/artifacts; no DSP substitution. */
#ifndef FELUCCA_CPU2
#define FELUCCA_CPU2 1
#endif
#if FELUCCA_CPU2
#include "c1_host.h"
static uint32_t transition_frame, transition_calls, transition_refused, transition_affected;
static int transition_fallback;
static int transition_run(void (*fn)(uint32_t), uint32_t arg)
{
    transition_calls++;
    if (transition_fallback && transition_frame >= 16384u) {
        transition_refused++;
        return 0;                   /* worker refuses before touching any part */
    }
    if (transition_frame >= 16384u && transition_frame < 18432u && (arg & 7u) == 7u)
        transition_affected++;
    return c1h_run(fn, arg);
}
#undef C1_RUN
#define C1_RUN(fn, arg) transition_run(fn, arg)
#endif
#define main hostsim_main
#include "hostsim.c"
#undef main

#define TRANSITION_AT 16384u
#define TRANSITION_FRAMES 49152u
#define TRANSITION_CASES 16u
static int transition_attack_reference;

static void transition_sine(track_t *t, uint32_t preset)
{
    host_preset(t, 0u, preset);
    t->p[P_E4] = 127;
    t->p[P_E5] = t->p[P_E6] = t->p[P_ED_FLT] = 0;
    t->p[P_ATK] = 20;
    t->p[P_DEC] = t->p[P_SUS] = 127;
    t->p[P_REL] = 100;
    t->p[P_VOICE] = V_POLY;
    t->p[P_LEVEL] = 90;
    t->p[P_DIST] = t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 0;
}

static void transition_setup(uint32_t id)
{
    uint32_t p, k;
    host_tracks_init();
    for (p = 0; p < NPART; p++)
        transition_sine(&trk[p], id == 14u ? 0u : 5u);
    if (id == 3u) {
        /* Fill the shared budget, then steal from another part at the event. */
        for (k = 0; k < NVOICE; k++)
            trk_note_on(&trk[0], 24u + 3u * k, 80);
    } else if (id == 11u) {
        song.g[G_RTYPE] = 2;       /* HALL: asymmetric stereo wet output */
        song.g[G_DTIME] = 11;      /* shortest delay, echoes inside capture */
        song.g[G_DFDBK] = 60;
        for (p = 0; p < NPART; p++) {
            trk[p].p[P_PAN] = (int16_t)(p * 36) - 54;
            trk[p].p[P_CHOR] = 60;
            trk[p].p[P_DLY] = 70;
            trk[p].p[P_REV] = 90;
            trk_note_on(&trk[p], 36u + p * 7u, 80);
        }
    } else if (id == 15u) {
        /* Independent channel references: loud left, near-zero right. */
        trk[0].p[P_PAN] = -64;
        trk[1].p[P_PAN] = 63;
        trk[1].p[P_LEVEL] = 1;
        trk_note_on(&trk[0], 48, 100);
        trk_note_on(&trk[1], 55, 100);
    } else if (id != 12u) {
        if (id == 13u)
            trk[0].p[P_LEVEL] = 1;
        trk_note_on(&trk[0], id == 14u ? 96u : 48u, 100);
        if (id < 3u)
            trk_note_on(&trk[0], 55, 90);
    }
    if (id == 6u || id == 7u)
        trk[0].p[P_ITYPE] = IT_SOFT;
    if (id == 9u) {
        trk[0].p[P_CHOR] = 100;
        song.g[G_CDEPTH] = 0;
    }
}

static void transition_event(uint32_t id, uint32_t f)
{
    track_t *t = &trk[0];
    if (f == TRANSITION_AT - 2048u) {
        if (id == 2u)
            trk_all_off(t);                     /* keep the actual release tail */
        if (id == 11u) {
            trk_all_off(&trk[0]);
            trk_all_off(&trk[3]);               /* held and released parts together */
        }
    }
    if (f == TRANSITION_AT) {
        switch (id) {
        case 0:
            sound_load_factory(t, 0u, 1, SND_PANIC | SND_EDIT_DEF);
            break;
        case 1: case 2:
            sound_load_factory(t, ENGI_FM6, 0, SND_EDIT_DEF | (id == 1u ? SND_PANIC : 0u));
            break;
        case 3:
            trk_note_on(&trk[1], 48, 100);
            trk_note_on(&trk[2], 55, 100);
            break;
        case 4: perf_press(PF_M1, 1); break;
        case 5: t->p[P_DIST] = 100; break;
        case 6: t->p[P_ITYPE] = IT_PHASER; break;
        case 7: t->p[P_IMIX] = 0; break;
        case 8: t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 127; break;
        case 9: song.g[G_CDEPTH] = 127; break;
        case 11:
            trk[1].p[P_ITYPE] = IT_SOFT;
            trk[2].p[P_CHOR] = 127;
            trk[2].p[P_REV] = 10;
            song.g[G_CDEPTH] = 127;
            break;
        case 12: case 13:
            t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 127;
            song.g[G_CDEPTH] = 127;
            break;
        case 14:
            t->p[P_ATK] = 0;
            trk_note_on(t, 103, 100);            /* intentional sharp musical attack */
            break;
        case 15: trk[1].p[P_ITYPE] = IT_SOFT; break;
        }
    }
    if (id == 10u && f >= TRANSITION_AT && f < TRANSITION_AT + 1024u && f % 64u == 0u) {
        t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = (f / 64u & 1u) ? 0 : 127;
        song.g[G_CDEPTH] = (f / 64u & 1u) ? 127 : 0;
    }
    if (id == 4u && f == TRANSITION_AT + 1024u)
        perf_press(PF_M1, 0);
    if ((id == 1u || id == 2u) && f == TRANSITION_AT + 32u)
        trk_note_on(t, 60, 90);                  /* queued while engine fades */
}

/* Hash semantic state after every joined mixer block. Omit CPU2-only caches,
 * addresses and struct padding; this is a voice/control oracle, not a full DSP
 * state snapshot. The complete stereo PCM is compared separately. */
static uint64_t transition_state = UINT64_C(14695981039346656037);
static void transition_hash(uint32_t value)
{
    transition_state ^= value;
    transition_state *= UINT64_C(1099511628211);
}
static void transition_take_state(void)
{
    uint32_t p, i;
    for (p = 0; p < NPART; p++) {
        track_t *t = &trk[p];
        for (i = 0; i < P_COUNT; i++) transition_hash((uint16_t)t->p[i]);
        transition_hash(t->engine); transition_hash(t->eng_req);
        transition_hash(t->lfo_ph); transition_hash((uint32_t)t->lfo_val);
        transition_hash(t->xf_on); transition_hash(t->xf); transition_hash(t->xp_n);
        transition_hash(t->send_valid);
        for (i = 0; i < 3u; i++) transition_hash((uint16_t)t->send_gain[i]);
        for (i = 0; i < NVOICE; i++) {
            voice_t *v = &t->v[i];
            transition_hash(v->active); transition_hash(v->gate);
            transition_hash(v->note); transition_hash(v->stage);
            transition_hash((uint32_t)v->env); transition_hash(v->age);
        }
    }
}

int main(int argc, char **argv)
{
    uint32_t id, n, f, group, kills, pre_active = 0, pre_released = 0, queued = 0;
    FILE *pcm;
    if (argc != 5 && argc != 6)
        return 2;
    id = (uint32_t)atoi(argv[1]);
    n = (uint32_t)atoi(argv[2]);
    if (id >= TRANSITION_CASES || (n != HALF_FRAMES && n != CTL))
        return 2;
    if (strcmp(argv[3], "off") && strcmp(argv[3], "on") && strcmp(argv[3], "fallback"))
        return 2;
    if (argc == 6 && strcmp(argv[5], "attack"))
        return 2;
    if (!eng_ok(0u) || !eng_ok(ENGI_FM6)) {
        fprintf(stderr, "audio transitions require native ANALOG and FM6 fixture engines\n");
        return 2;
    }
#if FELUCCA_CPU2
    c1h_off = !strcmp(argv[3], "off");
    transition_fallback = !strcmp(argv[3], "fallback");
#else
    if (strcmp(argv[3], "off"))
        return 2;
#endif
    pcm = fopen(argv[4], "wb");
    if (!pcm)
        return 2;
    transition_attack_reference = argc == 6 && !strcmp(argv[5], "attack");
    transition_setup(transition_attack_reference ? 12u : id);
    if (transition_attack_reference)
        host_preset(&trk[0], ENGI_FM6, 0);
    kills = voice_kills;
    /* Native audio.c groups four CTL blocks into a DMA half. The two
     * callers expose those supported boundaries without shortening fades. */
    for (group = 0; group < TRANSITION_FRAMES; group += n)
    for (f = group; f < group + n; f += CTL) {
        int32_t out[2 * CTL];
#if FELUCCA_CPU2
        transition_frame = f;
#endif
        if (f == TRANSITION_AT) {
            uint32_t i;
            for (i = 0; i < NVOICE; i++) {
                pre_active += trk[0].v[i].active != 0;
                pre_released += trk[0].v[i].active && !trk[0].v[i].gate;
            }
        }
        if (transition_attack_reference) {
            if (f == TRANSITION_AT)
                trk_note_on(&trk[0], 60, 90);
        } else
            transition_event(id, f);
#ifdef AUDIO_TRANSITION_UBSAN_PROBE
        if (f == TRANSITION_AT) {
            volatile int32_t maximum = INT32_MAX;
            volatile int32_t overflow = maximum + 1;
            (void)overflow;                    /* prove capture rejects real UB */
        }
#endif
        mix_block(out, CTL);
        if (f == TRANSITION_AT + 1024u) {
            uint32_t i;
            for (i = 0; i < NVOICE; i++)
                queued += trk[0].v[i].active && trk[0].v[i].gate && trk[0].v[i].note == 60u;
        }
        transition_take_state();
        if (fwrite(out, sizeof *out, 2u * CTL, pcm) != 2u * CTL)
            return 2;
    }
    if (fclose(pcm))
        return 2;
    printf("{\"profile\":\"%s\",\"pre_active\":%u,\"pre_released\":%u,\"queued\":%u,\"frames\":%u,\"engine\":%u,\"kills\":%u,\"voices\":%u,\"cpu2\":%u",
           FELUCCA_PROFILE_NAME,
           pre_active, pre_released, queued, TRANSITION_FRAMES, trk[0].engine, voice_kills - kills, busy_now(), FELUCCA_CPU2);
#if FELUCCA_CPU2
    printf(",\"calls\":%u,\"taken\":%u,\"refused\":%u,\"affected\":%u", transition_calls, c1h_taken, transition_refused, transition_affected);
#else
    printf(",\"calls\":0,\"taken\":0,\"refused\":0,\"affected\":0");
#endif
    printf(",\"state\":\"%016llx\"}\n", (unsigned long long)transition_state);
    return 0;
}
