/* SPDX-License-Identifier: GPL-3.0-only
 * Session pair-mix: real MIDI queue, UART parser, level edits and motion. */
#include "ui_harness.h"

static void mix_reset_fixture(void)
{
    ui_power_on();
    midi_mix_reset();
    memset(midi_ch, 0, sizeof midi_ch);
    memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners);
    memset(&um, 0, sizeof um);
    memset(midi_in_source, 0, sizeof midi_in_source);
    memset(settings_ml, 0, sizeof settings_ml);
    mi_r = mi_w = 0; midi_in_overflow = 0;
    fm1_in.notes = kb_prev = 0; song.sel = 0;
    memset(song.mch, 0, sizeof song.mch);
    song.g[G_ROUTE] = 0;
    events_block(CTL);
}
static void mix_queue(uint32_t status, uint32_t a, uint32_t b)
{
    midi_enqueue((status >> 4) | status << 8 | a << 16 | b << 24, 1);
    events_block(CTL);
}
static int mix_config_test(void)
{
    int bad = 0, ok = 1;
    mix_reset_fixture();
    int16_t a = trk[0].p[P_LEVEL], b = trk[1].p[P_LEVEL];
    mix_queue(0xB0, 20, 127);
    bad += check("mix defaults inactive; receiving CC20 leaves native levels exact",
                 !midi_mix_config_get(0) && midi_mix_config_get(1) == 0 && midi_mix_config_get(2) == 1 &&
                 trk[0].p[P_LEVEL] == a && trk[1].p[P_LEVEL] == b);
    const uint8_t reserved[] = {1, 5, 6, 7, 10, 11, 32, 38, 64, 65, 67, 68, 71, 72, 73, 74, 75,
                                91, 93, 94, 96, 97, 98, 99, 100, 101, 120, 121, 123, 127};
    ok &= midi_mix_config_set(0, 20);
    for (uint32_t i = 0; i < NELEM(reserved); i++)
        ok &= !midi_mix_config_set(0, reserved[i]) && midi_mix_config_get(0) == 20;
    ok &= !midi_mix_config_set(0, 128) && !midi_mix_config_set(1, 4) && !midi_mix_config_set(2, 128) &&
          !midi_mix_config_set(3, 0) && !midi_mix_config_set(1, 1) && !midi_mix_config_set(2, 0);
    bad += check("reserved/fixed CC and invalid/identical pair updates are rejected atomically", ok);
    bad += check("reversed pair can be configured through a spare part",
                 midi_mix_config_set(2, 2) && midi_mix_config_set(1, 1) && midi_mix_config_set(2, 0));
    mix_queue(0xB0, 20, 0);
    bad += check("reversed pair endpoint isolates the selected A", trk[1].p[P_LEVEL] == 112 && !trk[0].p[P_LEVEL]);
    midi_mix_config_set(0, 0);
    mix_queue(0xB0, 20, 127);
    bad += check("disabling stops edits without restoring levels", trk[1].p[P_LEVEL] == 112 && !trk[0].p[P_LEVEL]);
    midi_mix_reset();
    bad += check("session reset restores default assignment without touching sound", !midi_mix_config_get(0) &&
                 midi_mix_config_get(1) == 0 && midi_mix_config_get(2) == 1 && trk[1].p[P_LEVEL] == 112 && !trk[0].p[P_LEVEL]);
    return bad;
}
static int mix_sweep_test(void)
{
    int bad = 0, ok = 1;
    mix_reset_fixture(); midi_mix_config_set(0, 20);
    int16_t before[NPART][P_COUNT];
    for (uint32_t i = 0; i < NPART; i++) memcpy(before[i], trk[i].p, sizeof before[i]);
    uint32_t prev_a = 4096, prev_b = 0;
    for (uint32_t pos = 0; pos < 128u; pos++) {
        mix_queue(0xB0, 20, pos);
        uint32_t ga = LEVEL_Q12[trk[0].p[P_LEVEL]], gb = LEVEL_Q12[trk[1].p[P_LEVEL]];
        ok &= ga <= prev_a && gb >= prev_b && ga <= 4096u && gb <= 4096u;
        prev_a = ga; prev_b = gb;
        /* Exhaustive independent nearest-gain oracle: every representable native
         * level must be at least as far from the ideal complementary amplitudes. */
        for (uint32_t k = 0; k < 128u; k++) {
            int32_t want_a = (4096u * (127u - pos) + 63u) / 127u;
            int32_t want_b = (4096u * pos + 63u) / 127u;
            int32_t da = (int32_t)ga - want_a, db = (int32_t)gb - want_b;
            int32_t ka = (int32_t)LEVEL_Q12[k] - want_a, kb = (int32_t)LEVEL_Q12[k] - want_b;
            ok &= abs(da) <= abs(ka) && abs(db) <= abs(kb);
        }
        for (uint32_t i = 0; i < NPART; i++)
            for (uint32_t p = 0; p < P_COUNT; p++)
                if (i > 1u || p != P_LEVEL) ok &= trk[i].p[p] == before[i][p];
    }
    bad += check("all 128 real queued positions are monotonic nearest gains, with only the pair LEVEL edited", ok);
    bad += check("127 isolates B at unity", !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112);
    mix_queue(0xB0, 20, 0);
    bad += check("0 isolates A at unity", trk[0].p[P_LEVEL] == 112 && !trk[1].p[P_LEVEL]);
    mix_queue(0xB0, 20, 63);
    bad += check("position63 quantizes both halves to LEVEL100, -6dB each", trk[0].p[P_LEVEL] == 100 && trk[1].p[P_LEVEL] == 100);
    mix_queue(0xB0, 20, 64);
    bad += check("position64 has the same documented native midpoint quantization", trk[0].p[P_LEVEL] == 100 && trk[1].p[P_LEVEL] == 100);
    return bad;
}
static int mix_priority_test(void)
{
    int bad = 0;
    mix_reset_fixture(); midi_mix_config_set(0, 20);
    mix_queue(0xB9, 20, 127);
    bad += check("unheard channel cannot operate absolute pair", trk[0].p[P_LEVEL] != 0);
    mix_queue(0xB2, 20, 127);
    bad += check("a heard channel can operate the explicit pair outside its note destination",
                 !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112);
    mix_queue(0xB0, 7, 91);
    bad += check("CC7 wins until the next mix event", trk[0].p[P_LEVEL] == 91 && trk[1].p[P_LEVEL] == 112);
    mix_queue(0xB0, 20, 0);
    bad += check("next mix event replaces manual CC7 level", trk[0].p[P_LEVEL] == 112 && !trk[1].p[P_LEVEL]);
    ml_learn(20, 2, P_LEVEL);
    mix_queue(0xB0, 20, 63);
    bad += check("learned CC takes precedence over pair", trk[2].p[P_LEVEL] == 63 && trk[0].p[P_LEVEL] == 112 && !trk[1].p[P_LEVEL]);
    ml_drop(20, NTRK, P_COUNT); ml_arm = 1;
    mix_queue(0xB0, 20, 127);
    bad += check("learning capture consumes the CC before mix", ml_heard == 21 && trk[0].p[P_LEVEL] == 112 && !trk[1].p[P_LEVEL]);
    ml_arm = ml_heard = 0;
    um_byte(0xB0); um_byte(20); um_byte(127); events_block(CTL);
    bad += check("TRS parser reaches the same shared mix assignment", !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112);
    um_byte(20); um_byte(0); events_block(CTL);
    bad += check("TRS running status reaches both pair edits", trk[0].p[P_LEVEL] == 112 && !trk[1].p[P_LEVEL]);
    return bad;
}
static int mix_motion_test(void)
{
    int bad = 0;
    mix_reset_fixture(); midi_mix_config_set(0, 20);
    trk[0].p[P_LEVEL] = 82; trk[1].p[P_LEVEL] = 83;
    song.rec = 1; seq_start(); events_block(CTL);
    mix_queue(0xB0, 20, 127);
    bad += check("mix records selected armed part through native motion_capture; other part becomes base",
                 motion.count == 1 && motion.event[0].param == P_LEVEL && motion.event[0].value == 0 &&
                 !(motion.event[0].place >> 6) && !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112);
    seq_stop(); events_block(CTL);
    bad += check("stop uses native motion restore only for captured part", trk[0].p[P_LEVEL] == 82 && trk[1].p[P_LEVEL] == 112);
    song.rec = 0; motion_clear(&trk[0]);
    motion_set_event(&trk[0], 0, P_LEVEL, 27);
    seq_start(); events_block(CTL);
    bad += check("existing motion event can override mix level", trk[0].p[P_LEVEL] == 27);
    mix_queue(0xB0, 20, 0);
    bad += check("live mix replaces playing motion until its next event", trk[0].p[P_LEVEL] == 112);
    seq_stop(); events_block(CTL);
    bad += check("unarmed mix becomes native motion base", trk[0].p[P_LEVEL] == 112);
    return bad;
}
static int mix_lifecycle_test(void)
{
    int bad = 0;
    mix_reset_fixture(); midi_mix_config_set(0, 20);
    mix_queue(0x90, 60, 100); mix_queue(0xB0, 64, 127); mix_queue(0x80, 60, 0);
    for (uint32_t i = 0; i < 128; i++) mix_queue(0xB0, 20, i);
    bad += check("sweeps retain held-note ownership", midi_notes[0][60] == 0x11u && midi_owners[0] == 1);
    mix_queue(0xB0, 64, 0);
    bad += check("pedal release still releases after sweep", !midi_notes[0][60] && !midi_owners[0]);
    set_engine_of(&trk[0], ENGI_FM6);
    mix_queue(0xB0, 20, 0);
    bad += check("engine changes retain absolute part targets, no cached engine pointer", trk[0].p[P_LEVEL] == 112 && !trk[1].p[P_LEVEL]);
    trk[1].eng_req = trk[1].engine = 255;
    mix_queue(0xB0, 20, 127);
    bad += check("absent engine safely receives native level edit, no sound fallback", !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112 && eng_of(trk[1].eng_req) == &ENG_NONE);
    mix_queue(0xB0, 121, 0);
    bad += check("CC121 preserves deliberate sound-level edits and mix assignment", !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112 && midi_mix_config_get(0) == 20);
    for (uint32_t i = 0; i <= MQ; i++)
        midi_enqueue(0x09u | 0x90u << 8 | 60u << 16 | 100u << 24, 1);
    events_block(CTL);
    bad += check("input overflow discards ownership without replaying or restoring mix", !midi_in_overflow && !midi_owners[0] &&
                 !trk[0].p[P_LEVEL] && trk[1].p[P_LEVEL] == 112 && midi_mix_config_get(0) == 20);
    return bad;
}
static int mix_audio_test(void)
{
    int bad = 0, ok = 1;
    mix_reset_fixture(); midi_mix_config_set(0, 20);
    set_engine_of(&trk[0], 0); set_engine_of(&trk[1], 0);
    song.g[G_ROUTE] = ROUTE_TRACK;
    menu_put(MI_TCH2, 0); events_block(CTL);
    for (uint32_t k = 0; k < 2u; k++) {
        trk[k].p[P_REV] = trk[k].p[P_DLY] = trk[k].p[P_CHOR] = 0;
        trk[k].p[P_SPRD] = trk[k].p[P_DIST] = trk[k].p[P_ITYPE] = 0;
    }
    mix_queue(0x90, 60, 100);
    bad += check("same-channel layer owns both notes before audible sweep", midi_notes[0][60] == 3u);
    for (uint32_t pos = 0; pos < 128u; pos++) {
        mix_queue(0xB0, 20, pos);
        for (uint32_t k = 0; k < 2u; k++) {
            uint64_t energy = 0;
            for (uint32_t block = 0; block < 12u; block++) {
                memset(mix_l, 0, sizeof mix_l); memset(mix_r, 0, sizeof mix_r);
                mix_part(&trk[k], CTL SM_ARG(&mx[0]));
                for (uint32_t n = 0; n < CTL; n++) {
                    ok &= mix_l[n] > -0x1000000 && mix_l[n] < 0x1000000;
                    energy += (uint64_t)abs(mix_l[n]) + (uint64_t)abs(mix_r[n]);
                }
            }
            ok &= ((k == 0 && pos == 127) || (k == 1 && pos == 0)) ? energy == 0 : energy > 0;
        }
    }
    bad += check("real voice/mixer sweep has bounded PCM, both contributions, exact dry silence at muted endpoints", ok);
    mix_queue(0xB0, 64, 127); mix_queue(0x80, 60, 0);
    mix_queue(0xB0, 20, 0); mix_queue(0xB0, 20, 127); mix_queue(0xB0, 64, 0);
    bad += check("same-channel layered pedal release cleans both owners after fast sweep", !midi_notes[0][60] && !midi_owners[0] && !midi_owners[1]);
    return bad;
}
int main(void)
{
    int bad = mix_config_test() + mix_sweep_test() + mix_priority_test() + mix_motion_test() + mix_lifecycle_test() + mix_audio_test();
    printf("%s\n", bad ? "MIDI MIX TEST FAILED" : "MIDI pair mix tests passed");
    return bad != 0;
}
