/* SPDX-License-Identifier: GPL-3.0-only
 * #796: actual external queues, UART, captured owners, chords and ARP. */
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
    midi_key_reset(); events_block(CTL);
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
    /* BSS defaults before any explicit reset. */
    for (uint32_t t = 0; t < NTRK; t++)
        ok &= midi_key_range_get(t, 0) == 0 && midi_key_range_get(t, 1) == 127;
    int bad = check("key ranges boot full without a reset call", ok);
    reset();
    ok = midi_key_range_set(0, 0, 60) && midi_key_range_set(0, 1, 60);
    ok &= !midi_key_range_set(0, 0, 61) && !midi_key_range_set(0, 1, 59);
    ok &= !midi_key_range_set(NTRK, 0, 0) && !midi_key_range_set(0, 2, 60) &&
          !midi_key_range_set(0, 1, 128) && !midi_key_range_set(0, 0, (uint32_t)-1);
    ok &= midi_key_range_get(0, 0) == 60 && midi_key_range_get(0, 1) == 60 &&
          midi_key_range_get(NTRK, 0) == -1 && midi_key_range_get(0, 2) == -1;
    ok &= midi_key_mask(15, 128) == 0 && midi_key_mask(0, 60) == 0;
    bad += check("single-note ranges work; invalid/reversed setters reject without mutation", ok);
    midi_key_reset();
    bad += check("explicit key reset restores all four inclusive full ranges", midi_key_mask(15, 0) == 15 && midi_key_mask(15, 127) == 15);
    return bad;
}
static int sweep_test(void)
{
    int bad = 0;
    for (uint32_t source = 1; source <= 2; source++) {
        for (uint32_t mode = 0; mode < 3; mode++) {
            int ok = 1;
            reset();
            if (mode) {
                midi_key_range_set(0, 1, mode == 1 ? 59 : 64);
                midi_key_range_set(1, 0, mode == 1 ? 60 : 55);
            }
            for (uint32_t n = 0; n < 128; n++) {
                uint32_t want = !mode ? 3u : mode == 1 ? (n < 60 ? 1u : 2u) :
                                (n <= 64 ? 1u : 0u) | (n >= 55 ? 2u : 0u);
                send(0x90, n, 100, source);
                ok &= midi_notes[0][n] == want && midi_owners[0] == !!(want & 1u) &&
                      midi_owners[1] == !!(want & 2u) && key_gate(0, n) == !!(want & 1u) && key_gate(1, n) == !!(want & 2u);
                send(0x90, n, 0, source);
                ok &= !midi_notes[0][n] && !midi_owners[0] && !midi_owners[1] && !key_gate(0, n) && !key_gate(1, n);
            }
            bad += check(source == 1 ? "USB every pitch 0..127: default/split/overlap attacks and velocity-zero releases" :
                                      "TRS queue every pitch 0..127: default/split/overlap attacks and velocity-zero releases", ok);
        }
    }
    return bad;
}
static int ownership_test(void)
{
    int bad = 0, ok;
    reset();
    send(0x90, 60, 100, 1);
    midi_key_range_set(0, 1, 59); midi_key_range_set(1, 0, 61);
    ok = midi_notes[0][60] == 3 && key_gate(0, 60) && key_gate(1, 60);
    send(0x80, 60, 0, 2);
    ok &= !midi_notes[0][60] && !key_gate(0, 60) && !key_gate(1, 60);
    bad += check("range edits retain held owners; cross-transport note-off releases original layer", ok);
    reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
    midi_key_range_set(0, 1, 59); midi_key_range_set(1, 0, 61);
    ok = midi_notes[0][60] == 0x33;
    send(0xB0, 64, 0, 2);
    ok &= !midi_notes[0][60] && !midi_owners[0] && !midi_owners[1] && !key_gate(0, 60) && !key_gate(1, 60);
    bad += check("pedal-up releases captured owners after both ranges exclude the note", ok);
    reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
    midi_key_range_set(0, 1, 59); send(0x90, 60, 90, 1);
    ok = midi_notes[0][60] == 2 && !midi_owners[0] && midi_owners[1] == 1 && !key_gate(0, 60);
    midi_key_range_set(1, 0, 61); send(0x90, 60, 90, 1);
    ok &= !midi_notes[0][60] && !midi_owners[1] && !key_gate(1, 60);
    bad += check("retrigger replaces old pedal owners even when new zones reject all destinations", ok);
    reset(); song.g[G_ROUTE] = 1; events_block(CTL);
    send(0x94, 60, 100, 1); send(0x95, 60, 100, 2);
    midi_key_range_set(0, 1, 59); song.sel = 1;
    send(0x84, 60, 0, 1);
    ok = midi_owners[0] == 1 && key_gate(0, 60);
    send(0x95, 60, 0, 2);
    ok &= !midi_owners[0] && !key_gate(0, 60);
    bad += check("independent channels keep captured owners across zone and selection edits", ok);
    reset(); send(0x90, 60, 100, 1); midi_key_range_set(0, 1, 59);
    sound_load_factory(&trk[0], 0, 0, SND_PANIC); events_block(CTL);
    ok = midi_notes[0][60] == 2 && !midi_owners[0] && midi_key_range_get(0, 1) == 59;
    send(0x80, 60, 0, 1);
    ok &= !midi_notes[0][60] && !midi_owners[1];
    bad += check("sound install panic forgets only its owner and preserves session ranges", ok);
    for (uint32_t cc = 120; cc <= 123; cc++) {
        if (cc == 122) continue;
        reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
        midi_key_range_set(0, 1, 59); midi_key_range_set(1, 0, 61);
        send(0xB0, cc, 0, 1); send(0xB0, 64, 0, 1);
        bad += check("CC120/121/123 clean excluded held owners without resetting ranges", !midi_notes[0][60] &&
                     !midi_owners[0] && !midi_owners[1] && midi_key_range_get(0, 1) == 59);
    }
    reset(); send(0x90, 60, 100, 1); midi_key_range_set(0, 1, 59);
    for (uint32_t i = 0; i <= MQ; i++)
        midi_enqueue(0x09u | 0x90u << 8 | 70u << 16 | 100u << 24, 1);
    events_block(CTL);
    bad += check("input overflow forgets excluded owners while retaining zone setup", !midi_owners[0] && !midi_owners[1] &&
                 !midi_notes[0][60] && !key_gate(0, 60) && midi_key_range_get(0, 1) == 59);
    return bad;
}
static int expansion_test(void)
{
    int bad = 0, ok;
    for (uint32_t arp = 0; arp <= 1; arp++) {
        reset(); midi_key_range_set(0, 0, 60); midi_key_range_set(0, 1, 60);
        midi_key_range_set(1, 0, 64); midi_key_range_set(1, 1, 67);
        trk[0].p[P_CHRD] = CH_MAJ; trk[0].p[P_AMODE] = (int16_t)arp;
        trk[0].p[P_TRANS] = 12;
        send(0x90, 60, 100, 1);
        ok = midi_notes[0][60] == 1 && mchord_of(0, 60, 1) && !midi_owners[1];
        ok &= arp ? trk[0].nheld == 3 && trk[0].held[0] == 60 && trk[0].held[1] == 64 && trk[0].held[2] == 67 :
                    key_gate(0, 60) && key_gate(0, 64) && key_gate(0, 67);
        midi_key_range_set(0, 1, 61); midi_key_range_set(0, 0, 61);
        trk[0].p[P_CHRD] = CH_OFF;
        send(0x80, 60, 0, 1);
        ok &= !midi_notes[0][60] && !trk[0].nheld && !trk[0].arp_phys && !key_gate(0, 60) && !key_gate(0, 64) && !key_gate(0, 67);
        send(0x90, 60, 100, 1); ok &= !midi_notes[0][60] && !trk[0].nheld;
        bad += check(arp ? "ARP uses admitted source chord; range/chord edits release all original tones" :
                          "CHRD filters source before expansion; TRN retains existing external-note behavior", ok);
    }
    reset(); midi_key_range_set(0, 1, 0);
    fm1_in.notes = 1u << 7; events_block(CTL);
    ok = key_gate(0, kb_note[7]) && !midi_owners[0];
    fm1_in.notes = 0; events_block(CTL);
    step_t step = {{60}, 1, ST_NOTE, 0, 100};
    seq_step(&trk[0], &step, 0, FS / 8, 0);
    ok &= key_gate(0, 60) && !midi_owners[0]; seq_release(&trk[0]);
    bad += check("panel keys and sequencer bypass external-input zones", ok);
    reset(); midi_key_range_set(0, 1, 59); midi_key_range_set(1, 0, 60);
    um_byte(0x90); um_byte(59); um_byte(100); events_block(CTL);
    ok = midi_notes[0][59] == 1;
    um_byte(59); um_byte(0); um_byte(60); um_byte(100); events_block(CTL);
    ok &= !midi_notes[0][59] && midi_notes[0][60] == 2;
    um_byte(60); um_byte(0); events_block(CTL);
    bad += check("TRS UART running status crosses exact split boundaries and releases", ok && !midi_owners[0] && !midi_owners[1]);
    return bad;
}
static int routing_test(void)
{
    int bad = 0, ok;
    reset();
    menu_put(MI_TCH2, MCH_OMNI); menu_put(MI_TCH3, MCH_OFF); events_block(CTL);
    midi_key_range_set(0, 1, 59);
    send(0x90, 60, 100, 1);
    ok = !midi_notes[0][60]; /* An exact assignment rejected by a zone is not an OMNI fallback. */
    send(0x92, 60, 100, 1);
    ok &= midi_notes[2][60] == 2 && !midi_owners[2];
    send(0x82, 60, 0, 1);
    bad += check("zones preserve exact-channel priority, first OMNI fallback and OFF semantics", ok && !midi_owners[1]);
    reset(); send(0x90, 60, 100, 1); send(0xB0, 64, 127, 1); send(0x80, 60, 0, 1);
    midi_key_range_set(0, 1, 59);
    menu_put(MI_TCH2, 1); events_block(CTL);
    ok = midi_notes[0][60] == 0x11 && !midi_owners[1] && gated(&trk[0], 60);
    send(0xB0, 64, 0, 1);
    bad += check("route removal cleans one layer while excluded remaining owners follow pedal-up", ok && !midi_owners[0]);
    reset(); midi_key_range_set(0, 1, 59); send(0x90, 55, 100, 1);
    midi_key_reset();
    ok = midi_notes[0][55] == 3 && midi_key_range_get(0, 1) == 127;
    send(0x80, 55, 0, 1);
    bad += check("key reset restores configuration without dropping existing release ownership", ok && !midi_owners[0] && !midi_owners[1]);
    return bad;
}
int main(void)
{
    int bad = bounds_test(); /* Check BSS boot defaults before any reset/test edits. */
    bad += sweep_test() + ownership_test() + expansion_test() + routing_test();
    printf("%s\n", bad ? "MIDI KEY RANGE TEST FAILED" : "MIDI key range integration tests passed");
    return bad != 0;
}
