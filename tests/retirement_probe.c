/* SPDX-License-Identifier: GPL-3.0-only */
/* Native engines and real MIDI ownership; launched once per scenario. */
#define main retirement_hostsim_main
#include "hostsim.c"
#undef main

static FILE *rv_pcm;
static uint32_t rv_frame;
static void rv_render(uint32_t frames)
{
    uint32_t i;
    for (i = 0; i < frames; i += CTL) {
        int32_t out[2 * CTL];
        fm1_ms = (uint32_t)((uint64_t)rv_frame * 1000u / FS);
        mix_block(out, CTL);
        if (fwrite(out, sizeof out, 1, rv_pcm) != 1) exit(2);
        rv_frame += CTL;
    }
}
static void rv_state(const char *label, uint32_t note)
{
    track_t *t = &trk[0];
    uint32_t i, active = 0, inactive = 0;
    for (i = 0; i < NVOICE; i++) {
        if (t->v[i].active && t->v[i].gate) active |= 1u << i;
        if (!t->v[i].active && t->v[i].gate) inactive |= 1u << i;
    }
    printf("{\"label\":\"%s\",\"frame\":%u,\"engine\":%u,\"note\":%u,"
           "\"logical_midi_held\":%u,\"midi_owners\":%u,\"active_gate_mask\":%u,"
           "\"inactive_gate_mask\":%u,\"phase\":%u,\"fade\":%d,\"voices\":[",
           label, rv_frame, t->eng_req, note, !!midi_note_held(t, note), midi_owners[0],
           active, inactive, t->lfo_ph, t->lfo_fade);
    for (i = 0; i < NVOICE; i++)
        printf("%s{\"active\":%u,\"gate\":%u,\"stage\":%u,\"env\":%d,\"note\":%u,\"logical_midi_held\":%u}",
               i ? "," : "", t->v[i].active, t->v[i].gate, t->v[i].stage, t->v[i].env, t->v[i].note,
               !!midi_note_held(t, t->v[i].note));
    printf("]}\n");
}
int main(int argc, char **argv)
{
    uint32_t e, found = 0, first = 60, second = 64, release_first, same, change, gap;
    track_t *t = &trk[0];
    if (argc != 4) return 2;
    release_first = !strcmp(argv[2], "released");
    same = !strcmp(argv[2], "same_pitch");
    change = !strcmp(argv[2], "engine_change");
    gap = !strcmp(argv[2], "zone_gap");
    if (!release_first && !same && !change && !gap && strcmp(argv[2], "held")) return 2;
    for (e = 0; e < NENGINES; e++)
        if (eng_ok(e) && !strcmp(ENGINES[e]->name, argv[1])) { found = 1; break; }
    if (!found || !(rv_pcm = fopen(argv[3], "wb"))) return 2;
    host_tracks_init();
    rng_state = 0x309u;
    host_preset(t, e, !strcmp(argv[1], "LOFI") ? 4u : 0u); /* STEP LEAD exercises lofi_amp */
    t->p[P_VOICE] = V_POLY;
    t->p[P_LTRIG] = 0;                         /* NOTE */
    t->p[P_LPHASE] = 23;
    t->p[P_LRATE] = 100;
    t->p[P_LD_PIT] = 48;                      /* legal -64..63 range; expose a phase change */
    t->p[P_ATK] = 0; t->p[P_DEC] = 127; t->p[P_SUS] = 127; t->p[P_REL] = 12;
    t->p[P_DIST] = t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 0;
    if (!strcmp(argv[1], "SAMPLE") || !strcmp(argv[1], "GRAIN")) {
        if (!SMP_ZONES[0].n || smp_set_missing(0)) return 3; /* forbid fallback-sine evidence */
        t->p[P_E0] = 0;
    }
    if (!strcmp(argv[1], "SAMPLE")) t->p[P_E3] = 0; /* no loop */
    if (!strcmp(argv[1], "SLICE")) {
        if (!SLC_BREAK.len) return 3;
        t->p[P_E0] = 0; t->p[P_E4] = SLC_ONE;
    }
    if (gap) {
        if (strcmp(argv[1], "GRAIN")) return 2;
        /* Synthetic user-slot key map, real exported factory ADPCM and no IO.
         * This exercises native GRAIN's intentional unmatched-key silence. */
        usr_nz[0] = 1; usr_zone[0][0] = SMP_ZONES[0];
        usr_zone[0][0].lo = usr_zone[0][0].hi = 64;
        t->p[P_E0] = SMP_NSETS;
    }
    for (e = 0; e < P_COUNT; e++) {
        const param_desc_t *d = track_desc(t, e);
        if (t->p[e] < d->min || t->p[e] > d->max) {
            fprintf(stderr, "retirement: parameter %u=%d outside %d..%d\n",
                    e, t->p[e], d->min, d->max);
            return 4;
        }
    }
    midi_note_event(0, first, 100);
    rv_state("first_on", first);
    rv_render(2u * FS);
    rv_state("before_action", first);
    if (release_first) {
        midi_note_event(0, first, 0);
        rv_render(FS / 10u);
        rv_state("first_released", first);
    }
    if (change) {
        host_preset_req(t, 0, 5);              /* real fade/engine_block path */
        rv_render(FS / 10u);
        rv_state("after_engine_change", first);
        t->p[P_LTRIG] = 0;
    }
    if (same) second = first;                 /* MIDI repeated press releases its old owner */
    rv_state("before_second", first);
    midi_note_event(0, second, 100);
    rv_state("second_on", second);
    rv_render(FS);
    midi_note_event(0, first, 0);
    midi_note_event(0, second, 0);
    rv_state("all_released", first);
    rv_render(FS / 2u);
    fclose(rv_pcm);
    return 0;
}
