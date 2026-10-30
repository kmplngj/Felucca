/* SPDX-License-Identifier: GPL-3.0-only
 * #797: actual external queues, UART, captured owners, chords and ARP. */
#include "ui_harness.h"

static void reset(void)
{
    ui_power_on();
    memset(midi_ch, 0, sizeof midi_ch); memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners); memset(midi_bend_q8, 0, sizeof midi_bend_q8);
    memset(midi_bend_target, 0, sizeof midi_bend_target); memset(&midi_clock, 0, sizeof midi_clock);
    memset(&um, 0, sizeof um); memset(midi_in_source, 0, sizeof midi_in_source);
    mi_r = mi_w = 0; midi_in_overflow = 0; midi_beat_samples = 0;
    fm1_in.notes = kb_prev = 0; fm1_ms = 0; song.sel = 0;
    memset(song.mch, 0, sizeof song.mch); song.g[G_ROUTE] = ROUTE_TRACK;
    midi_key_reset(); midi_velocity_reset(); events_block(CTL);
    menu_put(MI_TCH2, 0); events_block(CTL);
    trk[0].p[P_VOICE] = trk[1].p[P_VOICE] = V_POLY;
}
static void send(uint32_t st, uint32_t note, uint32_t vel, uint32_t source)
{
    midi_enqueue((st >> 4) | st << 8 | note << 16 | vel << 24, source);
    events_block(CTL);
}
static int key_gate(uint32_t track, uint32_t note)
{
    for (uint32_t i = 0; i < NVOICE; i++)
        if (trk[track].v[i].active && trk[track].v[i].gate && trk[track].v[i].note == note)
            return 1;
    return 0;
}
static int bounds_test(void)
{
    int ok = 1;
    for (uint32_t t = 0; t < NTRK; t++)
        ok &= midi_velocity_range_get(t, 0) == 1 && midi_velocity_range_get(t, 1) == 127;
    int bad = check("velocity BSS defaults admit all positive velocities", ok);
    reset();
    ok = midi_velocity_range_set(0, 0, 64) && midi_velocity_range_set(0, 1, 64);
    ok &= !midi_velocity_range_set(0, 0, 65) && !midi_velocity_range_set(0, 1, 63);
    ok &= !midi_velocity_range_set(NTRK, 0, 1) && !midi_velocity_range_set(0, 2, 64) &&
          !midi_velocity_range_set(0, 0, 0) && !midi_velocity_range_set(0, 1, 128) &&
          !midi_velocity_range_set(0, 0, (uint32_t)-1);
    ok &= midi_velocity_range_get(0, 0) == 64 && midi_velocity_range_get(0, 1) == 64 &&
          midi_velocity_range_get(NTRK, 0) == -1 && midi_velocity_range_get(0, 2) == -1;
    for (uint32_t v = 0; v < 128; v++)
        ok &= midi_velocity_mask(1, v) == (v == 64 ? 1u : 0u);
    ok &= !midi_velocity_mask(15, 128) && !midi_velocity_mask(0, 64);
    bad += check("single-value velocity zone and invalid/reversed updates preserve bounds", ok);
    midi_velocity_reset();
    bad += check("velocity reset restores 1..127 and zero never enters any zone",
                 !midi_velocity_mask(15, 0) && midi_velocity_mask(15, 1) == 15 && midi_velocity_mask(15, 127) == 15);
    return bad;
}
static int sweep_test(void)
{
    int bad = 0;
    for (uint32_t source = 1; source <= 2; source++) {
        for (uint32_t mode = 0; mode < 4; mode++) {
            int ok = 1;
            reset();
            if (mode) {
                midi_velocity_range_set(0, 1, mode == 1 ? 79 : mode == 2 ? 95 : 80);
                midi_velocity_range_set(1, 0, mode == 1 ? 80 : mode == 2 ? 64 : 80);
            }
            for (uint32_t v = 0; v < 128; v++) {
                uint32_t want = !v ? 0u : !mode ? 3u : mode == 1 ? (v < 80 ? 1u : 2u) :
                    (v <= (mode == 2 ? 95u : 80u) ? 1u : 0u) | (v >= (mode == 2 ? 64u : 80u) ? 2u : 0u);
                send(0x90, 60, v, source);
                ok &= midi_notes[0][60] == want && midi_owners[0] == !!(want & 1u) && midi_owners[1] == !!(want & 2u) &&
                      key_gate(0, 60) == !!(want & 1u) && key_gate(1, 60) == !!(want & 2u);
                send(0x90, 60, 0, source);
                ok &= !midi_notes[0][60] && !midi_owners[0] && !midi_owners[1] && !key_gate(0, 60) && !key_gate(1, 60);
            }
            bad += check(source == 1 ? "USB all velocities: default/split/overlap/shared boundary and zero release" :
                                      "TRS all velocities: default/split/overlap/shared boundary and zero release", ok);
        }
    }
    reset();
    midi_key_range_set(0, 1, 63); midi_key_range_set(1, 0, 60);
    midi_velocity_range_set(0, 1, 95); midi_velocity_range_set(1, 0, 64);
    int ok = 1;
    for (uint32_t n = 0; n < 128; n++)
        for (uint32_t v = 0; v < 128; v++) {
            uint32_t want = (v && n <= 63 && v <= 95 ? 1u : 0u) | (v >= 64 && n >= 60 ? 2u : 0u);
            send(0x90, n, v, 1);
            ok &= midi_notes[0][n] == want && key_gate(0, n) == !!(want & 1u) && key_gate(1, n) == !!(want & 2u);
            send(0x80, n, 127, 1); /* release velocity cannot select a destination */
            ok &= !midi_notes[0][n] && !midi_owners[0] && !midi_owners[1];
        }
    bad += check("all 16384 source pitch/velocity pairs compose key and velocity masks", ok);
    return bad;
}
static int ownership_test(void)
{
    int bad = 0, ok;
    reset();
    send(0x90, 60, 100, 1);
    midi_velocity_range_set(0, 1, 79); midi_velocity_range_set(1, 0, 101);
    ok = midi_notes[0][60] == 3 && key_gate(0, 60) && key_gate(1, 60);
    send(0x80, 60, 0, 2);
    ok &= !midi_notes[0][60] && !key_gate(0, 60) && !key_gate(1, 60);
    bad += check("range edits retain held owners; cross-transport note-off releases original layer", ok);
    reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
    midi_velocity_range_set(0, 1, 79); midi_velocity_range_set(1, 0, 101);
    ok = midi_notes[0][60] == 0x33;
    send(0xB0, 64, 0, 2);
    ok &= !midi_notes[0][60] && !midi_owners[0] && !midi_owners[1] && !key_gate(0, 60) && !key_gate(1, 60);
    bad += check("pedal-up releases captured owners after both ranges exclude the note", ok);
    reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
    midi_velocity_range_set(0, 1, 79); send(0x90, 60, 90, 1);
    ok = midi_notes[0][60] == 2 && !midi_owners[0] && midi_owners[1] == 1 && !key_gate(0, 60);
    midi_velocity_range_set(1, 0, 111); send(0x90, 60, 90, 1);
    ok &= !midi_notes[0][60] && !midi_owners[1] && !key_gate(1, 60);
    bad += check("retrigger replaces old pedal owners even when new zones reject all destinations", ok);
    reset(); song.g[G_ROUTE] = 1; events_block(CTL);
    send(0x94, 60, 100, 1); send(0x95, 60, 100, 2);
    midi_velocity_range_set(0, 1, 79); song.sel = 1;
    send(0x84, 60, 0, 1);
    ok = midi_owners[0] == 1 && key_gate(0, 60);
    send(0x95, 60, 0, 2);
    ok &= !midi_owners[0] && !key_gate(0, 60);
    bad += check("independent channels keep captured owners across zone and selection edits", ok);
    reset(); send(0x90, 60, 100, 1); midi_velocity_range_set(0, 1, 79);
    sound_load_factory(&trk[0], 0, 0, SND_PANIC); events_block(CTL);
    ok = midi_notes[0][60] == 2 && !midi_owners[0] && midi_velocity_range_get(0, 1) == 79;
    send(0x80, 60, 0, 1);
    ok &= !midi_notes[0][60] && !midi_owners[1];
    bad += check("sound install panic forgets only its owner and preserves session ranges", ok);
    for (uint32_t cc = 120; cc <= 123; cc++) {
        if (cc == 122) continue;
        reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
        midi_velocity_range_set(0, 1, 79); midi_velocity_range_set(1, 0, 101);
        send(0xB0, cc, 0, 1); send(0xB0, 64, 0, 1);
        bad += check("CC120/121/123 clean excluded held owners without resetting ranges", !midi_notes[0][60] &&
                     !midi_owners[0] && !midi_owners[1] && midi_velocity_range_get(0, 1) == 79);
    }
    reset(); send(0x90, 60, 100, 1); midi_velocity_range_set(0, 1, 79);
    for (uint32_t i = 0; i <= MQ; i++)
        midi_enqueue(0x09u | 0x90u << 8 | 70u << 16 | 100u << 24, 1);
    events_block(CTL);
    bad += check("input overflow forgets excluded owners while retaining zone setup", !midi_owners[0] && !midi_owners[1] &&
                 !midi_notes[0][60] && !key_gate(0, 60) && midi_velocity_range_get(0, 1) == 79);
    return bad;
}
static int expansion_test(void)
{
    int bad = 0, ok;
    for (uint32_t arp = 0; arp <= 1; arp++) {
        reset(); midi_velocity_range_set(0, 1, 79); midi_velocity_range_set(1, 0, 80);
        trk[0].p[P_CHRD] = CH_MAJ; trk[0].p[P_AMODE] = (int16_t)arp;
        send(0x90, 60, 79, 1);
        ok = midi_notes[0][60] == 1 && mchord_of(0, 60, 1) && !midi_owners[1];
        ok &= arp ? trk[0].nheld == 3 : key_gate(0, 60) && key_gate(0, 64) && key_gate(0, 67);
        midi_velocity_range_set(0, 1, 50); trk[0].p[P_CHRD] = CH_OFF;
        send(0x80, 60, 127, 1);
        ok &= !midi_notes[0][60] && !trk[0].nheld && !trk[0].arp_phys && !key_gate(0, 60) && !key_gate(0, 64) && !key_gate(0, 67);
        bad += check("velocity selects source before CHRD/ARP; zone edits keep captured chord release", ok);
    }
    reset(); midi_velocity_range_set(0, 0, 127); midi_velocity_range_set(0, 1, 127);
    fm1_in.notes = 1u << 7; events_block(CTL);
    ok = key_gate(0, kb_note[7]) && !midi_owners[0];
    fm1_in.notes = 0; events_block(CTL);
    step_t step = {{60}, 1, ST_NOTE, 0, 100};
    seq_step(&trk[0], &step, 0, FS / 8, 0);
    ok &= key_gate(0, 60) && !midi_owners[0]; seq_release(&trk[0]);
    bad += check("panel and sequencer velocities bypass external zones", ok);
    reset(); midi_velocity_range_set(0, 1, 79); midi_velocity_range_set(1, 0, 80);
    um_byte(0x90); um_byte(60); um_byte(79); events_block(CTL);
    ok = midi_notes[0][60] == 1;
    um_byte(60); um_byte(80); events_block(CTL);
    ok &= midi_notes[0][60] == 2 && !key_gate(0, 60);
    um_byte(60); um_byte(0); events_block(CTL);
    bad += check("TRS UART running status retriggers into a new velocity owner and releases", ok && !midi_owners[0] && !midi_owners[1]);
    reset(); send(0x90, 60, 100, 1); midi_velocity_range_set(0, 1, 79);
    midi_velocity_reset();
    ok = midi_notes[0][60] == 3 && midi_velocity_range_get(0, 1) == 127;
    send(0x80, 60, 0, 1);
    bad += check("velocity configuration reset retains captured release ownership", ok && !midi_owners[0] && !midi_owners[1]);
    reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
    midi_velocity_range_set(0, 1, 79);
    menu_put(MI_TCH2, 1); events_block(CTL);
    ok = midi_notes[0][60] == 0x11 && !midi_owners[1] && key_gate(0, 60);
    send(0xB0, 64, 0, 1);
    bad += check("route edit removes one layer; excluded old velocity owner still follows pedal-up", ok && !midi_owners[0]);
    reset(); menu_put(MI_TCH2, MCH_OMNI); menu_put(MI_TCH3, MCH_OFF); events_block(CTL);
    midi_velocity_range_set(0, 1, 79);
    send(0x90, 60, 100, 1); ok = !midi_notes[0][60];
    send(0x92, 60, 100, 1); ok &= midi_notes[2][60] == 2 && !midi_owners[2];
    send(0x82, 60, 0, 1);
    bad += check("velocity rejection preserves exact-channel priority and first OMNI/OFF semantics", ok && !midi_owners[1]);
    return bad;
}
int main(void)
{
    int bad = bounds_test();
    bad += sweep_test() + ownership_test() + expansion_test();
    printf("%s\n", bad ? "MIDI VELOCITY RANGE TEST FAILED" : "MIDI velocity range integration tests passed");
    return bad != 0;
}
