/* SPDX-License-Identifier: GPL-3.0-only
 * CC67 through the production MIDI queue, routing, ownership and note input. */
#include "ui_harness.h"

static void soft_reset(void)
{
    ui_power_on();
    memset(midi_ch, 0, sizeof midi_ch);
    memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners);
    memset(mchord, 0, sizeof mchord);
    mi_r = mi_w = 0; midi_in_overflow = 0;
    fm1_in.notes = kb_prev = 0; song.sel = 0;
    song.g[G_ROUTE] = 0; memset(song.mch, 0, sizeof song.mch);
    events_block(CTL);
    for (uint32_t i = 0; i < NPART; i++) {
        host_preset(&trk[i], 0, 0);
        trk[i].p[P_VOICE] = V_POLY;
        trk[i].p[P_SCALE] = trk[i].p[P_QUANT] = trk[i].p[P_TRANS] = 0;
        trk[i].p[P_AMODE] = 0;
        for (uint32_t j = 0; j < 4; j++) trk[i].p[P_M1AMT + 3u * j] = 0;
    }
}
static void soft_event(uint32_t st, uint32_t d1, uint32_t d2, uint32_t source)
{
    midi_enqueue((st >> 4) | st << 8 | d1 << 16 | d2 << 24, source);
    events_block(CTL);
}
static const voice_t *soft_voice(uint32_t track, uint32_t note)
{
    for (uint32_t i = 0; i < NVOICE; i++) {
        const voice_t *v = &trk[track].v[i];
        if (v->active && v->gate && v->note == note) return v;
    }
    return NULL;
}
static uint32_t soft_vel(uint32_t track, uint32_t note)
{
    const voice_t *v = soft_voice(track, note);
    return v ? v->vel : 0;
}
static int soft_mapping_test(void)
{
    int bad = 0, ok = 1;
    soft_reset();
    for (uint32_t pedal = 0; pedal < 128; pedal++) {
        soft_event(0xB0, 67, pedal, 1);
        soft_event(0xB0, 67, pedal, 2);       /* repeated switch, shared USB/TRS state */
        uint32_t previous = 0;
        for (uint32_t vel = 0; vel < 128; vel++) {
            soft_event(0x90, 60, vel, 2);
            uint32_t actual = soft_vel(0, 60);
            uint32_t want = pedal < 64 ? vel : (vel + 1u) / 2u;
            ok &= actual == want && actual >= previous && actual <= 127u;
            ok &= !!midi_notes[0][60] == !!vel;
            previous = actual;
            soft_event(0x80, 60, 0, 1);
        }
    }
    bad += check("CC67: all 128 switch values x 128 velocities, zero release, monotonic bounded mapping, repeated USB/TRS CC", ok);
    bad += check("CC67 is reserved from MIDI Learn", !ml_free_cc(67));
    trk[0].p[P_M1SRC] = MS_VEL;
    trk[0].p[P_M1DST] = MD_VEL;
    trk[0].p[P_M1AMT] = -32;
    soft_event(0xB0, 67, 127, 1);
    soft_event(0x90, 62, 127, 1);
    bad += check("soft scaling precedes existing matrix velocity response exactly once", soft_vel(0, 62) == 32);
    return bad;
}
static int soft_lifecycle_test(void)
{
    int bad = 0;
    soft_reset();
    soft_event(0x90, 60, 101, 1);
    const voice_t *held = soft_voice(0, 60);
    uint32_t age = held ? held->age : 0;
    soft_event(0xB0, 67, 64, 2);
    bad += check("soft switch keeps existing held note velocity and identity", held && held == soft_voice(0, 60) && held->vel == 101 && held->age == age);
    soft_event(0x90, 62, 101, 1);
    soft_event(0x91, 64, 101, 2);
    bad += check("new notes soften once; other channel stays normal", soft_vel(0, 62) == 51 && soft_vel(1, 64) == 101);
    soft_event(0xB0, 64, 127, 1);
    soft_event(0x90, 62, 0, 2);
    soft_event(0xB0, 67, 0, 2);
    bad += check("velocity zero releases into independent sustain; soft off leaves held voice", soft_vel(0, 62) == 51 && midi_notes[0][62] == 0x11u);
    soft_event(0xB0, 64, 0, 1);
    bad += check("sustain release releases soft note", !soft_voice(0, 62) && !midi_notes[0][62]);
    soft_event(0xB0, 67, 127, 1);
    soft_event(0x90, 60, 127, 1);
    bad += check("repeated pitch replaces owner with softened attack", soft_vel(0, 60) == 64 && midi_owners[0] == 1);
    soft_event(0xB0, 123, 0, 1);
    soft_event(0x90, 60, 127, 1);
    bad += check("CC123 releases notes and keeps soft switch", soft_vel(0, 60) == 64 && midi_owners[0] == 1);
    soft_event(0xB0, 120, 0, 1);
    soft_event(0x90, 60, 127, 1);
    bad += check("CC120 kills notes and keeps soft switch", soft_vel(0, 60) == 64 && midi_owners[0] == 1);
    panic_req |= 1; events_block(CTL);
    soft_event(0x90, 60, 127, 1);
    bad += check("sound/preset panic forgets owners and keeps soft switch", soft_vel(0, 60) == 64 && midi_owners[0] == 1);
    soft_event(0xB0, 121, 0, 2);
    soft_event(0x90, 62, 127, 1);
    bad += check("CC121 resets soft without changing held velocity", soft_vel(0, 60) == 64 && soft_vel(0, 62) == 127);
    soft_event(0xB0, 67, 127, 1);
    midi_in_overflow = 1; events_block(CTL);
    soft_event(0x90, 60, 127, 1);
    bad += check("lost input clears soft and held ownership", soft_vel(0, 60) == 127 && midi_owners[0] == 1 && !midi_notes[0][62]);
    soft_event(0xB0, 67, 127, 1);
    song.g[G_ROUTE] = ROUTE_SEL; events_block(CTL);
    song.sel = 1;
    soft_event(0x90, 65, 127, 1);
    bad += check("still-heard channel retains soft across route/selected track changes", soft_vel(1, 65) == 64);
    song.g[G_ROUTE] = 2; events_block(CTL);
    song.g[G_ROUTE] = 0; events_block(CTL);
    soft_event(0x90, 67, 127, 1);
    bad += check("excluding channel through route clears its soft switch", soft_vel(0, 67) == 127);
    soft_event(0xB0, 67, 127, 1);
    midi_soft_reset();
    soft_event(0x90, 69, 127, 1);
    bad += check("project reset helper clears switch without altering held voices", soft_vel(0, 69) == 127 && soft_vel(0, 67) == 127);
    return bad;
}
static int soft_layer_test(void)
{
    int bad = 0;
    soft_reset(); song.g[G_ROUTE] = ROUTE_TRACK;
    mch_set(0, 0); mch_set(1, 0);
    mch_set(2, MCH_OFF); mch_set(3, MCH_OFF);
    events_block(CTL);
    soft_event(0xB0, 67, 127, 1);
    soft_event(0x90, 60, 127, 2);
    bad += check("shared channel layer destinations get identical once-scaled velocity", soft_vel(0, 60) == 64 && soft_vel(1, 60) == 64 && midi_notes[0][60] == 3);
    soft_event(0xB0, 67, 0, 2);
    soft_event(0x90, 60, 0, 1);
    bad += check("layer note-on zero releases all captured owners after controller edit", !midi_notes[0][60] && !soft_voice(0, 60) && !soft_voice(1, 60));
    return bad;
}
int main(void)
{
    int bad = soft_mapping_test() + soft_lifecycle_test() + soft_layer_test();
    return bad ? 1 : 0;
}
