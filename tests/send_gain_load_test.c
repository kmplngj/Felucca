/* SPDX-License-Identifier: GPL-3.0-only */
/* Real project/preset/user-preset/undo routes retain heard gains while sounding; idle restarts snap. */
#include "ui_harness.h"
#include <assert.h>

static int32_t out[2 * CTL];
static void block(void) { mix_block(out, CTL); }
static void settled(track_t *t)
{
    assert(t->send_gain[0] == t->p[P_CHOR] * 258);
    assert(t->send_gain[1] == t->p[P_DLY] * 258);
    assert(t->send_gain[2] == t->p[P_REV] * 258);
}
int main(void)
{
    ui_power_on(); track_t *t = &trk[0];
    t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 0; assert(!project_save(0));
    t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 127;
    t->p[P_REL] = 64; trk_note_on(t, 60, 100); block(); assert(t->send_valid); settled(t);
    project_load(0);
    assert(t->send_valid && t->send_gain[0] == 32766);  /* real load writes parameters, never the whole track */
    block(); settled(t); assert(t->send_gain[0] == 0);
    /* Factory and user sound loads plus undo keep heard history until the next rendered block. */
    trk_note_on(t, 64, 100); t->p[P_CHOR] = 127; block(); assert(t->send_gain[0] == 32766);
    const preset_t *preset = &ENGINES[t->engine]->presets[1];
    t->p[P_E0] = (preset->e[0] + 1) % 7;
    apply_preset_to(t, 1);
    assert(t->preset == 1 && t->p[P_E0] == preset->e[0]);
    assert(t->p[P_CHOR] == (preset->fx[1] ? preset->fx[1] - 1 : 24));
    assert(t->send_valid && t->send_gain[0] == 32766); block(); settled(t);
    int16_t saved_cho = t->p[P_CHOR], saved_wave = t->p[P_E0];
    assert(up_store(0, "SEND") == 3 && up_used(0)); /* fixture uses the documented RAM-only success code */
    int16_t old = t->send_gain[0];
    t->p[P_CHOR] = 127; t->p[P_E0] = (saved_wave + 1) % 7;
    assert(!up_load(0));
    assert(t->user == 1 && t->p[P_CHOR] == saved_cho && t->p[P_E0] == saved_wave);
    assert(t->send_gain[0] == old); block(); settled(t);
    assert(undo.trk == 1 && (undo.what & UNDO_SOUND));
    old = t->send_gain[0]; undo_swap();
    assert(t->p[P_CHOR] == 127 && t->p[P_E0] == (saved_wave + 1) % 7 && t->user == 0);
    assert(t->send_gain[0] == old); block(); settled(t);
    /* A real engine request/fade reaches the new engine without resetting queued voice ownership. */
    set_engine_of(t, ENGI_FM6); for (int i = 0; i < XF_BLOCKS + 3; i++) block();
    assert(t->engine == ENGI_FM6); if (t->send_valid) settled(t);
    /* Drain the native release, then load a project and issue a new note after its pending panic. */
    t->p[P_REL] = 0; trk_all_off(t);
    for (int i = 0; i < 512; i++) block(); assert(!t->send_valid);
    project_load(0); events_block(CTL); assert(!t->send_valid);
    t->p[P_CHOR] = 96; trk_note_on(t, 67, 100); block(); settled(t); assert(t->send_gain[0] == 24768);
    puts("send gain loads: real project/preset/user/undo/engine paths, active-history glide and drained-note restart passed");
    return 0;
}
