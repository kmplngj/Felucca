/* SPDX-License-Identifier: GPL-3.0-only */
/* Queued outer-key events and central/pad note bits through production events,
 * mapping, chord/ARP ownership, voice gates and USB-MIDI output. */
#include <stdint.h>
static int32_t ext_event = -1;
static int32_t take_ext_event(void) { int32_t e = ext_event; ext_event = -1; return e; }
#define HOST_SMK_EXTKEY_TAKE() take_ext_event()
#define BOARD_SMK37 1
#define main hostsim_main
#include "hostsim.c"
#undef main
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static uint32_t gates(uint32_t track, uint32_t note)
{
    uint32_t i, n = 0;
    for (i = 0; i < NVOICE; i++)
        n += trk[track].v[i].active && trk[track].v[i].gate && trk[track].v[i].note == note;
    return n;
}
static int held(uint32_t track, uint32_t note, uint32_t arp)
{
    uint32_t i;
    if (!arp) return gates(track, note) == 1u;
    for (i = 0; i < trk[track].nheld; i++) if (trk[track].held[i] == note) return 1;
    return 0;
}
static uint32_t output(uint32_t status, uint32_t note)
{
    uint32_t i, n = 0;
    for (i = mo_r; i < mo_w; i++) {
        uint32_t p = midi_out_q[i % MQ];
        n += ((p >> 8) & 0xFFu) == status && ((p >> 16) & 0x7Fu) == note;
    }
    return n;
}
static void reset(uint32_t arp, uint32_t chord)
{
    uint32_t i;
    memset(trk, 0, sizeof trk); memset(&song, 0, sizeof song);
    memset(&fm1_in, 0, sizeof fm1_in);
    memset(kb_chn, 0, sizeof kb_chn); memset(ext_note, 0, sizeof ext_note);
    memset(midi_ch, 0, sizeof midi_ch); memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners); memset(mchord, 0, sizeof mchord);
    kb_prev = kb_boot_hold = kb_asleep = kb_lock = 0; kb_mask = 0;
    mi_r = mi_w = mo_r = mo_w = 0; midi_route = 0; usb.config = 1;
    panic_req = transport_req = cin_left = 0; ext_event = -1;
    host_tracks_init();
    for (i = 0; i < NTRK; i++) {
        host_preset(&trk[i], ENGI_FM6, 0);
        trk[i].p[P_SCALE] = 1; trk[i].p[P_ROOT] = trk[i].p[P_TRANS] = 0;
        trk[i].p[P_QUANT] = QN_SNAP; trk[i].p[P_CHRD] = chord ? CH_MAJ : CH_OFF;
        trk[i].p[P_AMODE] = (int16_t)arp;
        trk[i].p[P_AHOLD] = 0; trk[i].p[P_VOICE] = V_POLY;
    }
}
static void central(uint32_t down)
{
    fm1_in.key_vel[31] = 91;
    fm1_in.notes = down ? 1u << 26 : 0u;           /* physical G5, central key27 or a pad note */
    events_block(CTL);
}
static void outer(uint32_t key, uint32_t down)
{
    ext_event = (int32_t)(key << 8 | (down ? 103u : 0u));
    events_block(CTL);
}
static void external_note(uint32_t note, uint32_t down)
{
    midi_enqueue((down ? 0x09u | 0x90u << 8 | 100u << 24 : 0x08u | 0x80u << 8) | note << 16, 1);
    events_block(CTL);
}
static void external(uint32_t down) { external_note(79, down); }
static void pedal(uint32_t down)
{
    midi_enqueue(0x0Bu | 0xB0u << 8 | 64u << 16 | (down ? 127u << 24 : 0u), 1);
    events_block(CTL);
}
static void cc(uint32_t channel, uint32_t control)
{
    midi_enqueue(0x0Bu | (0xB0u | channel) << 8 | control << 16, 1);
    events_block(CTL);
}
static void all_notes_off_test(void)
{
    static const uint8_t keys[10] = {0,1,2,3,4,32,33,34,35,36};
    uint32_t arp, k, note, use_pedal;
    for (arp = 0; arp < 2u; arp++) {
        for (k = 0; k < 10u; k++) {
            reset(arp, 0); outer(keys[k], 1);
            note = ext_note[keys[k]] - 1u;
            REQUIRE(held(0, note, arp));
            cc(0, 123);
            REQUIRE(held(0, note, arp) && ext_note[keys[k]] == note + 1u);
            REQUIRE(!arp || (trk[0].arp_phys == 1u && trk[0].nheld == 1u));
            REQUIRE(!output(0x80, note));
            outer(keys[k], 0);
            REQUIRE(!held(0, note, arp) && !trk[0].nheld && !trk[0].arp_phys);
            REQUIRE(output(0x80, note) == 1u);
        }
        for (use_pedal = 0; use_pedal < 2u; use_pedal++) {
            reset(arp, 0); outer(32, 1); external(1); external_note(72, 1);
            if (use_pedal) pedal(1);
            cc(0, 123);
            REQUIRE(held(0, 79, arp));
            REQUIRE(!!midi_owners[0] == !!use_pedal);
            external(0);                              /* later MIDI note-off must preserve the local owner */
            if (use_pedal) pedal(0);
            REQUIRE(held(0, 79, arp) && !held(0, 72, arp) && !midi_owners[0]);
            REQUIRE(!arp || (trk[0].arp_phys == 1u && trk[0].nheld == 1u));
            outer(32, 0);
            REQUIRE(!held(0, 79, arp) && !trk[0].nheld && !trk[0].arp_phys);
        }
        reset(arp, 0); outer(32, 1); song.sel = 1;
        /* Track2 has sequenced/unowned sound; an outer owner on T1 must not
         * block CC123's normal cleanup of another addressed track. */
        input_on(&trk[1], 60, 100); cc(1, 123);
        REQUIRE(!held(1, 60, arp) && !trk[1].nheld && !trk[1].arp_phys);
        REQUIRE(held(0, 79, arp));
        midi_enqueue(0x09u | 0x91u << 8 | 62u << 16 | 100u << 24, 1); events_block(CTL);
        cc(0, 123);
        REQUIRE(held(0, 79, arp) && held(1, 62, arp));
        outer(32, 0); REQUIRE(!held(0, 79, arp) && held(1, 62, arp));
        cc(1, 123); REQUIRE(!held(1, 62, arp));
        reset(arp, 0); outer(32, 1); cc(0, 120);
        REQUIRE(!held(0, 79, arp) && !trk[0].nheld && !trk[0].arp_phys);
        outer(32, 0);                              /* CC120 remains an unconditional panic */
    }
}
int main(void)
{
    uint32_t arp, chord, first, up;
    for (arp = 0; arp < 2u; arp++) for (chord = 0; chord < 2u; chord++)
        for (first = 0; first < 2u; first++) for (up = 0; up < 2u; up++) {
            reset(arp, chord);
            REQUIRE(kb_map(&trk[0], 26) == 79u && kb_map(&trk[0], 27) == 79u);
            if (first) outer(32, 1); else central(1);
            if (first) central(1); else outer(32, 1);
            REQUIRE(held(0, 79, arp) && output(0x90, 79) == 1u && !output(0x80, 79));
            REQUIRE(!arp || trk[0].arp_phys == (chord ? 3u : 1u));
            if (up) outer(32, 0); else central(0);
            REQUIRE(held(0, 79, arp) && !output(0x80, 79));
            if (up) central(0); else outer(32, 0);
            REQUIRE(!held(0, 79, arp) && output(0x80, 79) == 1u);
            REQUIRE(!trk[0].nheld && !trk[0].arp_phys);
        }
    for (arp = 0; arp < 2u; arp++) for (first = 0; first < 2u; first++) for (up = 0; up < 2u; up++) {
        reset(arp, 0);
        if (first) external(1); else outer(32, 1);
        if (first) outer(32, 1); else external(1);
        REQUIRE(held(0, 79, arp) && (!arp || trk[0].arp_phys == 1u));
        if (up) outer(32, 0); else external(0);
        REQUIRE(held(0, 79, arp));
        if (up) external(0); else outer(32, 0);
        REQUIRE(!held(0, 79, arp) && !trk[0].arp_phys);
        REQUIRE(output(0x90, 79) == 1u && output(0x80, 79) == 1u);
    }
    /* The new outer source shares internal MIDI/ARP ownership without changing
     * the existing FM-1 central-key/MIDI asymmetry characterized by #307. Its
     * own MIDI OUT press/release remains one pair even when MIDI IN came first. */
    for (arp = 0; arp < 2u; arp++) for (first = 0; first < 2u; first++) for (up = 0; up < 2u; up++) {
        reset(arp, 0);
        if (!first) outer(32, 1);
        trk[0].p[P_CHRD] = CH_MAJ; external_note(72, 1); trk[0].p[P_CHRD] = CH_OFF;
        if (first) outer(32, 1);
        REQUIRE(held(0, 79, arp) && (!arp || trk[0].arp_phys == 3u));
        if (up) outer(32, 0); else external_note(72, 0);
        REQUIRE(held(0, 79, arp));
        if (up) external_note(72, 0); else outer(32, 0);
        REQUIRE(!held(0, 79, arp) && !trk[0].nheld && !trk[0].arp_phys);
        REQUIRE(output(0x90, 79) == 1u && output(0x80, 79) == 1u);
    }
    for (arp = 0; arp < 2u; arp++) for (first = 0; first < 2u; first++) {
        reset(arp, 0);
        if (!first) outer(32, 1);
        external(1); pedal(1); external(0);
        if (first) outer(32, 1);
        REQUIRE(held(0, 79, arp) && (!arp || trk[0].arp_phys == 1u));
        outer(32, 0); REQUIRE(held(0, 79, arp));
        pedal(0); REQUIRE(!held(0, 79, arp) && !trk[0].arp_phys);
    }
    reset(0, 0); central(1); song.sel = 1; outer(32, 1);
    REQUIRE(gates(0, 79) == 1u && gates(1, 79) == 1u);
    song.sel = 2; outer(32, 0); REQUIRE(gates(0, 79) == 1u && !gates(1, 79));
    central(0); REQUIRE(!gates(0, 79));
    for (up = 0; up < 2u; up++) {
        reset(0, 0); trk[0].p[P_TRANS] = 96;
        outer(32, 1); outer(33, 1);
        REQUIRE(gates(0, 127) == 1u && output(0x90, 127) == 1u);
        outer(up ? 33 : 32, 0); REQUIRE(gates(0, 127) == 1u && !output(0x80, 127));
        outer(up ? 32 : 33, 0); REQUIRE(!gates(0, 127) && output(0x80, 127) == 1u);
    }
    all_notes_off_test();
    puts("SMK central/pad/outer/MIDI shared-note ownership and release orders passed");
    return 0;
}
