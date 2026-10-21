/* SPDX-License-Identifier: GPL-3.0-only */
/* MACRO's new arena/voice policy, using the production Sound install, allocator,
 * engine fade and renderer. Existing union PCM oracles remain unchanged. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include <assert.h>

static void reset_world(void)
{
    memset(trk, 0, sizeof trk);
    memset(eng_mem, 0, sizeof eng_mem);
    memset(eng_mem_owner, 0, sizeof eng_mem_owner);
    memset(midi_bend_q8, 0, sizeof midi_bend_q8);
    memset(midi_bend_target, 0, sizeof midi_bend_target);
    host_tracks_init();
}

static void tick(track_t *t, uint32_t blocks)
{
    int32_t out[CTL];
    while (blocks--) {
        engine_block(t);
        track_render(t, out, CTL);
    }
}

static uint32_t active(const track_t *t)
{
    uint32_t i, n = 0;
    for (i = 0; i < NVOICE; i++) n += t->v[i].active != 0;
    return n;
}

static void plain_envelope(track_t *t)
{
    t->p[P_ATK] = t->p[P_REL] = t->p[P_ED_FLT] = 0;
    t->p[P_SUS] = 127;
    t->p[P_VOICE] = V_POLY;
    t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 0;
}

static void load_macro(track_t *t, uint32_t shape, int request)
{
    uint32_t preset = shape < 3u ? shape * 2u : shape + 3u;
    if (request) host_preset_req(t, ENGI_MACRO, preset);
    else host_preset(t, ENGI_MACRO, preset);
    plain_envelope(t);
}

static uint64_t note_hash(track_t *t)
{
    int32_t out[CTL];
    uint64_t h = 0xcbf29ce484222325ull;
    uint32_t i, k;
    trk_note_on(t, 60, 100);
    for (i = 0; i < 64u; i++) {
        engine_block(t);
        track_render(t, out, CTL);
        for (k = 0; k < CTL; k++)
            h = (h ^ (uint32_t)out[k]) * 0x100000001b3ull;
    }
    return h;
}

/* The new sound must not claim/reset the arena until the old voices finish their
 * fade. A note arriving in that interval must start with the new owner. */
static void finish_switch(track_t *t, uint32_t old, uint32_t want, uint32_t note)
{
    uint32_t p = (uint32_t)(t - trk), i;
    assert(active(t));
    trk_note_on(t, note, 110);
    assert(t->xp_n == 1u && t->engine == old);
    assert(eng_mem_owner[p] == old + 1u);
    for (i = 0; i < XF_BLOCKS; i++) {
        tick(t, 1);
        assert(t->engine == old && eng_mem_owner[p] == old + 1u);
    }
    tick(t, 1);
    assert(t->engine == want && eng_mem_owner[p] == want + 1u);
    assert(!t->xf_on && !t->xp_n && active(t));
    for (i = 0; i < NVOICE; i++)
        if (t->v[i].active) assert(t->v[i].note == note);
    trk_note_off(t, note);
}

static void switch_pairs(void)
{
    /* Include the string/delay models as well as each original polyphonic core. */
    static const uint8_t models[] = {MAC_WAVE, MAC_FOLD, MAC_FBFM, 3, 29, 30, 31, 32, 33, 35, 38, 42, 47};
    uint32_t e, shape, model, donors = 0, count = 0;
    track_t *t = &trk[0], *other = &trk[2];
    static uint8_t saved[sizeof(macro_part_t)];
    for (e = 0; e < NENGINES; e++) {
        if (e == ENGI_MACRO || !eng_ok(e) || !eng_of(e)->mem) continue;
        donors++;
        for (model = 0; model < NELEM(models); model++) {
            shape = models[model];
            uint64_t clean, reclaimed;
            uint32_t donor_note = e == ENGI_DRUM ? 36u : 60u;
            reset_world();
            load_macro(t, shape, 0);
            tick(t, XF_BLOCKS + 2u);
            clean = note_hash(t);

            /* A separate part keeps its full-bank oscillator while part 0's arena
             * changes owners. Snapshot before those switches, render it afterward. */
            load_macro(other, 38, 0);
            trk_note_on(other, 72, 100);
            tick(other, 16);
            memcpy(saved, macro_part(other), sizeof saved);
            host_preset_req(t, e, 0);
            plain_envelope(t);
            finish_switch(t, ENGI_MACRO, e, donor_note);
            assert(!memcmp(saved, macro_part(other), sizeof saved));
            assert(eng_mem_owner[2] == ENGI_MACRO + 1u);
            tick(other, 1);
            trk_note_off(other, 72);
            tick(other, FS / CTL);
            assert(!active(other));

            /* Render the donor, then return silently so onset can be compared to
             * a clean MACRO claim. The donor's smaller state leaves dirty tail
             * bytes; MACRO must zero all of its own state on reclaim. */
            trk_note_on(t, donor_note, 100);
            tick(t, 32);
            load_macro(t, shape, 1);
            finish_switch(t, e, ENGI_MACRO, 60);
            tick(t, FS / CTL);
            assert(!active(t));
            /* Exercise a second dirty donor claim, with no queued new note. */
            host_preset_req(t, e, 0);
            tick(t, XF_BLOCKS + 2u);
            assert(t->engine == e);
            load_macro(t, shape, 1);
            tick(t, XF_BLOCKS + 2u);
            assert(!active(t) && t->engine == ENGI_MACRO);
            reclaimed = note_hash(t);
            assert(clean == reclaimed);
            trk_note_off(t, 60);
            tick(t, FS / CTL);
            assert(!active(t));
            count++;
        }
    }
    assert(donors >= 4u && count == donors * NELEM(models)); /* SLICE may be disabled. */
    printf("macro switch: %u memory-engine/model pairs, both directions, queued notes, fresh reset and part isolation ok\n", count);
}

static void model_caps(void)
{
    track_t *t = &trk[0];
    uint32_t shape, i;
    int32_t out[CTL];
    for (shape = 3; shape < MAC_NSHAPE; shape++) {
        reset_world();
        load_macro(t, MAC_WAVE, 0);
        for (i = 0; i < NVOICE; i++) trk_note_on(t, 48u + i, 100);
        tick(t, 8);
        assert(active(t) == NVOICE && trk_nvoice(t) == NVOICE);
        t->p[P_E0] = (int16_t)shape;
        tick(t, 2);
        assert(active(t) == 1u && t->v[0].active && trk_nvoice(t) == 1u);
        trk_note_on(t, 80, 100);
        tick(t, 2);
        assert(active(t) == 1u && t->v[0].note == 80);
        t->p[P_E0] = MAC_WAVE;
        tick(t, 2);
        for (i = 0; i < NVOICE - 1u; i++) trk_note_on(t, 60u + i, 100);
        tick(t, 2);
        assert(active(t) == NVOICE && trk_nvoice(t) == NVOICE);
        for (i = 0; i < 128u; i++) trk_note_off(t, i);
        tick(t, FS / CTL);
        track_render(t, out, CTL);
        assert(!active(t));
        for (i = 0; i < CTL; i++) assert(!out[i]);
    }
    puts("macro switch: all 45 full-bank models, 8 -> 1 -> 8 voices, replacement and exact-silence release ok");
}

#if FELUCCA_ARENA_CHECK
static uint32_t failures, failure_why;
static void expected_failure(uint32_t why, const track_t *t, uint32_t want)
{
    (void)t;
    assert(want == ENGI_MACRO);
    failures++;
    failure_why = why;
}
static void checked_access(void)
{
    track_t *t = &trk[0];
    reset_world();
    load_macro(t, MAC_WAVE, 0);
    eng_arena_fail = expected_failure;
    eng_mem_owner[0] = ENGI_PHYS + 1u;
    assert((void *)macro_part(t) == (void *)eng_arena_scratch);
    assert(failures == 1u && failure_why == ARENA_BAD_OWNER);
    t->engine = ENGI_PHYS;
    assert((void *)macro_part(t) == (void *)eng_arena_scratch);
    assert(failures == 2u && failure_why == ARENA_BAD_ENGINE);
    eng_arena_fail = eng_arena_trap;
    puts("macro switch: checked accessor rejects wrong rendered engine and wrong arena owner");
}
#endif
int main(void)
{
#if FELUCCA_ARENA_CHECK
    checked_access();
#endif
    switch_pairs();
    model_caps();
    return 0;
}
