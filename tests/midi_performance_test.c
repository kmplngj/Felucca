/* SPDX-License-Identifier: GPL-3.0-only */
/* Cross-feature tests use the real MIDI queue, project restore and note owners. */
#define MIDI_CONTROL_NO_MAIN
#include "midi_control_test.c"

static void perf_reset(void)
{
    midi_test_reset();
    midi_session_reset();
    song.g[G_ROUTE] = ROUTE_TRACK;
    mch_set(1, 0);
    midi_route = MIDI_ROUTE_AGAIN;
    events_block(CTL);
}
static void config(uint32_t address, uint32_t value)
{
    queued(0xB0, 99, address >> 7, 1);
    queued(0xB0, 98, address & 127u, 1);
    queued(0xB0, 6, value, 1);
}
static int played_velocity(uint32_t part, uint32_t note)
{
    uint32_t i;
    for (i = 0; i < NVOICE; i++)
        if (trk[part].v[i].active && trk[part].v[i].gate && trk[part].v[i].note == note)
            return trk[part].v[i].vel;
    return -1;
}
int main(void)
{
    int bad = 0, ok;
    static project_t saved;
    perf_reset();
    config(0x3001, 59); config(0x3010, 60);
    config(0x3003, 79); config(0x3012, 80);
    queued(0xB0, 67, 127, 1);
    queued(0x90, 60, 100, 1);
    bad += check("raw100 selects hard zone before soft scaling to50", midi_notes[0][60] == 2u &&
                 !midi_owners[0] && midi_owners[1] == 1 && played_velocity(1, 60) == 50);
    config(0x3010, 70);                         /* later edit cannot hide the original release */
    queued(0x90, 60, 0, 1);
    bad += check("velocity-zero releases captured zone after bounds change", !midi_notes[0][60] && !midi_owners[1]);
    queued(0x90, 59, 64, 2);
    bad += check("USB-configured key/velocity zones apply to raw TRS input", midi_notes[0][59] == 1u && played_velocity(0, 59) == 32);
    queued(0x80, 59, 0, 2);
    config(0x3001, 20); config(0x3000, 21);
    bad += check("reversed range write is rejected through actual NRPN", midi_key_range_get(0, 0) == 0 && midi_key_range_get(0, 1) == 20);

    perf_reset();
    config(0x3100, 20); config(0x3101, 0); config(0x3102, 1);
    queued(0x90, 60, 100, 1); queued(0xB0, 20, 0, 1);
    ok = trk[0].p[P_LEVEL] == 112 && trk[1].p[P_LEVEL] == 0;
    queued(0xB0, 20, 127, 2);
    ok &= trk[0].p[P_LEVEL] == 0 && trk[1].p[P_LEVEL] == 112;
    config(0x3100, 65);
    ok &= midi_mix_config_get(0) == 20;
    queued(0xB0, 7, 100, 1);
    ok &= trk[0].p[P_LEVEL] == 100 && trk[1].p[P_LEVEL] == 100;
    queued(0xB0, 101, 0, 1); queued(0xB0, 100, 1, 1); queued(0xB0, 6, 96, 1); queued(0xB0, 38, 0, 1);
    ok &= midi_ch[0].fine14 == 12288;
    queued(0xB0, 121, 0, 1);
    ok &= midi_ch[0].fine14 == 12288 && midi_mix_config_get(0) == 20;
    queued(0x80, 60, 0, 1);
    ok &= !midi_owners[0] && !midi_owners[1];
    bad += check("mix binding, fixed controls and registered tuning coexist", ok);

    perf_reset();
    project_capture(&saved);
    config(0x3001, 59); config(0x3012, 80); config(0x3100, 20);
    queued(0xB0, 67, 127, 1); queued(0xB0, 32, 1, 1); pc(0, 0);
    queued(0xB0, 101, 0, 1); queued(0xB0, 100, 2, 1); queued(0xB0, 6, 76, 1);
    ok = !project_restore_runtime(&saved);
    ok &= midi_key_range_get(0, 1) == 127 && midi_velocity_range_get(1, 0) == 1 && !midi_mix_config_get(0);
    ok &= !midi_ch[0].soft && !midi_ch[0].bank_lsb && !ui.mpc[0] && !ui.mpc[1];
    ok &= midi_ch[0].coarse == 12 && midi_ch[0].rpn_msb == 127 && midi_ch[0].rpn_lsb == 127;
    queued(0xB0, 6, 70, 1);
    ok &= midi_ch[0].coarse == 12;                /* selector cancelled, registered value retained */
    bad += check("project restore resets session setup and pending recalls, keeps tuning but cancels data entry", ok);
    printf("MIDI performance integration: %s\n", bad ? "FAILED" : "PASS");
    return bad != 0;
}
