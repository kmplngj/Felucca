/* SPDX-License-Identifier: GPL-3.0-only
 * CC65/68 through the production MIDI queue, ownership and voice paths. */
#include "ui_harness.h"

static void reset(void)
{
    ui_power_on();
    memset(midi_ch, 0, sizeof midi_ch);
    memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners);
    memset(midi_glide_switch, 0, sizeof midi_glide_switch);
    memset(midi_legato_switch, 0, sizeof midi_legato_switch);
    memset(mchord, 0, sizeof mchord);
    mi_r = mi_w = midi_in_overflow = 0;
    song.sel = 0; song.g[G_ROUTE] = 0;
    fm1_in.notes = kb_prev = 0;
    events_block(CTL);
    trk[0].p[P_VOICE] = V_MONO;
    trk[0].p[P_GLIDE] = 70;
}
static void send(uint32_t st, uint32_t d1, uint32_t d2)
{
    midi_enqueue((st >> 4) | st << 8 | d1 << 16 | d2 << 24, 1);
    events_block(CTL);
}
static int threshold_test(void)
{
    int bad = 0; reset(); track_t *t = &trk[0];
    bad += check("untouched authored MONO and glide remain exact", trk_vmode(t) == V_MONO && trk_glide(t) == 70);
    t->p[P_VOICE] = V_LEGATO;
    bad += check("untouched authored LEGATO remains exact", trk_vmode(t) == V_LEGATO);
    for (uint32_t k = 0; k < 4; k++) {
        const uint8_t value[] = {0, 63, 64, 127};
        send(0xB0, 65, value[k]); send(0xB0, 68, value[k]);
        bad += check("65/68 standard threshold and authored values preserved",
                     trk_glide(t) == (k < 2 ? 0 : 70) && trk_vmode(t) == (k < 2 ? V_MONO : V_LEGATO) &&
                     t->p[P_GLIDE] == 70 && t->p[P_VOICE] == V_LEGATO);
    }
    send(0xB0, 65, 0); send(0xB0, 5, 127);
    bad += check("CC5 remembers maximum mapped time while CC65 is OFF", t->p[P_GLIDE] == 127 && !trk_glide(t));
    send(0xB0, 65, 64); send(0xB0, 65, 127);
    bad += check("CC65 ON/repeated ON restores requested time", trk_glide(t) == 127);
    send(0xB0, 5, 0);
    bad += check("zero CC5 means no portamento even when CC65 ON", !trk_glide(t));
    t->p[P_VOICE] = V_POLY;
    bad += check("CC68 never converts POLY", trk_vmode(t) == V_POLY);
    t->p[P_VOICE] = V_UNISON;
    bad += check("CC68 never converts UNISON", trk_vmode(t) == V_UNISON);
    send(0xB3, 68, 127);
    bad += check("CC68 never converts drums/one-shot", trk_vmode(&trk[3]) == V_POLY);
    bad += check("new fixed switches are unavailable for MIDI LEARN", !ml_free_cc(65) && !ml_free_cc(68));
    return bad;
}
static int phrase_test(void)
{
    int bad = 0; reset(); track_t *t = &trk[0]; voice_t *v = &t->v[0];
    send(0xB0, 68, 0); send(0xB0, 65, 0);
    send(0x90, 60, 100); uint32_t age = v->age;
    send(0x90, 64, 100);
    bad += check("normal overlap retriggers and OFF moves pitch immediately", v->age > age && v->note == 64 && v->pitch_cur == 64 * 16 && t->nmono == 2);
    send(0x80, 60, 0);
    bad += check("release older first leaves current mono note", v->gate && v->note == 64 && t->nmono == 1);
    send(0x80, 64, 0);
    bad += check("release final key empties stack", !v->gate && !t->nmono);
    send(0x90, 60, 100); age = v->age;
    v->stage = 2; v->env = 12345;
    send(0xB0, 68, 127); send(0xB0, 65, 127); send(0x90, 64, 100);
    bad += check("legato overlap preserves envelope and glides", v->age == age && v->stage == 2 && v->env == 12345 && v->pitch_cur == 60 * 16 && v->pitch16 == 64 * 16);
    int32_t out[CTL]; track_render(t, out, CTL);
    bad += check("real renderer advances portamento toward E4", v->pitch_cur > 60 * 16 && v->pitch_cur < 64 * 16);
    send(0xB0, 65, 63);
    bad += check("OFF during held glide lands without envelope retrigger", v->pitch_cur == v->pitch16 && v->age == age && t->nmono == 2);
    send(0x80, 64, 0);
    bad += check("release newest first returns to older note", v->gate && v->note == 60 && t->nmono == 1);
    send(0xB0, 64, 127); send(0x80, 60, 0); send(0xB0, 68, 0);
    bad += check("toggle during sustain preserves captured stack/owner", v->gate && t->nmono == 1 && midi_notes[0][60] == 0x11);
    send(0xB0, 121, 0);
    bad += check("CC121 turns both switches OFF, preserves time, releases sustain", !v->gate && !t->nmono && !trk_glide(t) && trk_vmode(t) == V_MONO && t->p[P_GLIDE] == 70);
    return bad;
}
static int cleanup_test(void)
{
    int bad = 0; reset(); track_t *t = &trk[0];
    song.g[G_ROUTE] = ROUTE_TRACK; mch_set(0, 0); mch_set(1, 0);
    mch_set(2, 2); mch_set(3, 3);
    events_block(CTL);
    trk[1].p[P_VOICE] = V_MONO; trk[1].p[P_GLIDE] = 80;
    send(0xB0, 65, 0); send(0xB0, 68, 127); send(0x90, 60, 100);
    bad += check("layer applies both switches independently", !trk_glide(t) && !trk_glide(&trk[1]) && trk_vmode(t) == V_LEGATO && trk_vmode(&trk[1]) == V_LEGATO);
    panic_req |= 1u; events_block(CTL);
    send(0x90, 62, 100);
    bad += check("sound/panic discards old switches only for affected part", trk_glide(t) == 70 && trk_vmode(t) == V_MONO && !trk_glide(&trk[1]) && trk_vmode(&trk[1]) == V_LEGATO);
    send(0xB0, 65, 0); send(0xB0, 68, 127); send(0xB0, 120, 0);
    bad += check("CC120 clears owners and overlays without editing patch", !midi_owners[0] && !midi_owners[1] && !t->nmono && trk_glide(t) == 70 && trk_vmode(t) == V_MONO);
    send(0xB0, 65, 0); send(0xB0, 68, 127); send(0x90, 60, 100);
    mch_set(0, 4); midi_route = MIDI_ROUTE_AGAIN; events_block(CTL);
    bad += check("route reassignment releases former destination and its overlays", !midi_owners[0] && !t->nmono && trk_glide(t) == 70 && trk_vmode(t) == V_MONO && trk_vmode(&trk[1]) == V_LEGATO);
    for (uint32_t k = 0; k <= MQ; k++) midi_enqueue(0x09u | 0x90u << 8 | 67u << 16 | 100u << 24, 1);
    events_block(CTL);
    bad += check("input loss returns every part to authored behavior", !midi_owners[1] && !trk[1].nmono && trk_glide(&trk[1]) == 80 && trk_vmode(&trk[1]) == V_MONO);
    return bad;
}
static int allocation_test(void)
{
    int bad = 0;
    for (uint32_t mode = V_POLY; mode <= V_UNISON; mode++) {
        if (mode != V_POLY && mode != V_UNISON) continue;
        for (uint32_t on = 0; on < 2; on++) {
            reset(); track_t *t = &trk[0];
            t->p[P_VOICE] = (int16_t)mode;
            t->v[0].pitch_cur = 60 * 16;
            send(0xB0, 65, on ? 127 : 0); send(0xB0, 68, 127);
            if (mode == V_UNISON) {
                send(0x90, 60, 100); send(0x90, 64, 100);
            } else send(0x90, 64, 100);
            bad += check("CC65 uses existing POLY/UNISON pitch paths without CC68 allocation changes",
                         trk_vmode(t) == mode && t->v[0].pitch16 == 64 * 16 &&
                         t->v[0].pitch_cur == (on ? 60 * 16 : 64 * 16));
            send(0x80, 60, 0); send(0x80, 64, 0);
            bad += check("POLY/UNISON final release empties mono stack and owners", !t->nmono && !midi_owners[0]);
        }
    }
    return bad;
}
static int install_test(void)
{
    int bad = 0; reset(); track_t *t = &trk[0];
    send(0xB0, 65, 0); send(0xB0, 68, 127); send(0x90, 60, 100);
    int16_t p[P_COUNT]; memcpy(p, t->p, sizeof p);
    p[P_GLIDE] = 17; p[P_VOICE] = V_MONO;
    sound_install(t, t->eng_req, t->preset, p, 0, SND_ALL | SND_PANIC);
    events_block(CTL); send(0x90, 64, 100);
    bad += check("real sound install never reinstalls stale time/mode", trk_glide(t) == 17 && trk_vmode(t) == V_MONO && t->nmono == 1);
    send(0x90, 64, 100); send(0x90, 64, 100); send(0x80, 64, 0);
    bad += check("repeated notes under switches leave no stuck stack or owners", !t->nmono && !midi_owners[0] && !t->v[0].gate);
    midi_enqueue(0xBu | 0xB0u << 8 | 68u << 16 | 127u << 24, 2);
    events_block(CTL);
    bad += check("TRS and USB share channel switch state", trk_vmode(t) == V_LEGATO && midi_ch[0].legato_switch == 2);
    send(0xB0, 68, 0);
    bad += check("USB resets the same TRS switch", trk_vmode(t) == V_MONO && midi_ch[0].legato_switch == 1);
    return bad;
}
int main(void)
{
    int bad = threshold_test() + phrase_test() + cleanup_test() + allocation_test() + install_test();
    printf("MIDI glide/legato: %s (%d failures)\n", bad ? "FAIL" : "PASS", bad);
    return bad != 0;
}
