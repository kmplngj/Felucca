/* SPDX-License-Identifier: GPL-3.0-only */
/* All physical note IDs through the production keyboard mapper, note/MIDI paths,
 * sound loading and renderer. The separate input_test covers matrix/debounce;
 * this fixture does not model GPIO timing or replace FM-1 qualification. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include <assert.h>

static uint32_t gates(const track_t *t)
{
    uint32_t i, n = 0;
    for (i = 0; i < NVOICE; i++) n += t->v[i].gate != 0;
    return n;
}

static uint32_t render_blocks(track_t *t, uint32_t count)
{
    int32_t out[CTL];
    uint32_t i, audible = 0;
    while (count--) {
        engine_block(t);
        track_render(t, out, CTL);
        for (i = 0; i < CTL; i++) audible |= out[i] != 0;
    }
    return audible;
}

static void load_sound(track_t *t, uint32_t engine, uint32_t preset, uint32_t quant)
{
    host_preset_req(t, engine, preset);
    render_blocks(t, XF_BLOCKS + 2u);
    assert(t->engine == engine && t->p[P_QUANT] == (int16_t)quant);
    assert(t->p[P_SCALE] == 1 && t->p[P_ROOT] == 0 && t->p[P_TRANS] == 0);
    t->p[P_ATK] = t->p[P_REL] = 0;
    t->p[P_SUS] = 127;
    t->p[P_VOICE] = V_POLY;
}

static void press_release(track_t *t, uint32_t key, uint32_t quant)
{
    /* Fixed C major oracle, independent of kb_map/key_black. F3 .. G5. */
    static const uint8_t black[12] = {0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0};
    uint32_t note = 53u + key, silent = quant == QN_WHITE && black[note % 12u];
    mo_w = mo_r = 0;
    assert(!gates(t) && !kb_prev && !fm1_in.notes);
    fm1_in.notes = 1u << key;
    keyboard_block();
    if (silent) {
        assert(kb_note[key] == KB_SILENT && !gates(t) && !mo_w);
    } else {
        uint32_t i, found = 0;
        if (quant == QN_SNAP && black[note % 12u]) note--;
        assert(kb_note[key] != KB_SILENT && gates(t) == 1u && mo_w == 1u);
        if (quant != QN_WHITE) assert(kb_note[key] == note);
        for (i = 0; i < NVOICE; i++)
            found |= t->v[i].gate && t->v[i].note == kb_note[key];
        assert(found && ((midi_out_q[0] >> 8) & 255u) == 0x90u);
        assert(((midi_out_q[0] >> 16) & 127u) == kb_note[key]);
    }
    {
        uint32_t audible = render_blocks(t, 8);
        /* Tonal fixtures provide an audio oracle too. Other Braids models
         * have their own excitation/delay semantics, covered by braids_test. */
        if (!silent && (t->engine == ENGI_FM6 || t->p[P_E0] <= 3)) assert(audible);
    }
    fm1_in.notes = 0;
    keyboard_block();
    assert(!gates(t) && !kb_layer);
    assert(mo_w == (silent ? 0u : 2u));
    if (!silent) {
        assert(((midi_out_q[1] >> 8) & 255u) == 0x80u);
        assert(((midi_out_q[1] >> 16) & 127u) == kb_note[key]);
    }
    render_blocks(t, 8);
}

static void held_switch(track_t *t, uint32_t key, uint32_t engine, uint32_t preset, uint32_t quant)
{
    uint32_t silent, note;
    mo_w = mo_r = 0;
    fm1_in.notes = 1u << key;
    keyboard_block();
    silent = kb_note[key] == KB_SILENT;
    note = kb_note[key];
    assert(gates(t) == !silent && mo_w == !silent);
    render_blocks(t, 8);
    load_sound(t, engine, preset, quant);
    /* Existing sound-install policy fades the old sound; a held physical
     * key is not a new press. Its release must still close its MIDI note. */
    assert(!gates(t) && !t->xp_n);
    fm1_in.notes = 0;
    keyboard_block();
    assert(!gates(t) && !kb_layer && mo_w == (silent ? 0u : 2u));
    if (!silent) assert(((midi_out_q[1] >> 16) & 127u) == note);
    press_release(t, key, quant);
}

int main(void)
{
    track_t *t = &trk[0];
    uint32_t quant, shape, key, count = 0;
    memset(trk, 0, sizeof trk);
    memset(&song, 0, sizeof song);
    host_tracks_init();
    usb.config = 1;
    t->p[P_SCALE] = 1; /* C major */
    for (quant = QN_OFF; quant <= QN_WHITE; quant++) {
        t->p[P_QUANT] = (int16_t)quant;
        for (shape = 0; shape < MAC_NSHAPE; shape++) {
            uint32_t preset = shape < 3u ? shape * 2u : shape + 3u;
            /* Change engines for every model; keep QNT as the panel's loads do. */
            load_sound(t, ENGI_FM6, 0, quant);
            for (key = 0; key < 27u; key++) press_release(t, key, quant), count++;
            load_sound(t, ENGI_MACRO, preset, quant);
            assert(t->p[P_E0] == (int16_t)shape);
            for (key = 0; key < 27u; key++) press_release(t, key, quant), count++;
            for (key = 0; key < 27u; key++) {
                held_switch(t, key, ENGI_FM6, 0, quant);
                held_switch(t, key, ENGI_MACRO, preset, quant);
                count += 4;
            }
        }
    }
    /* A track left on WHITE recovers all raised keys immediately on OFF,
     * without an engine change, reload or restart. */
    t->p[P_QUANT] = QN_OFF;
    for (key = 0; key < 27u; key++) press_release(t, key, QN_OFF), count++;
    printf("macro keyboard: %u presses/releases; all 27 keys, all 48 models and FM6, OFF/SNAP/WHITE, held-key engine switches, preserved QNT and OFF recovery ok\n", count);
    return 0;
}
