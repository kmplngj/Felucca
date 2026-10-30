/* SPDX-License-Identifier: GPL-3.0-only */
/* Actual audio-block event consumer and USB-MIDI output queue, without hardware. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s (MIDI packets %u)\n", __LINE__, #x, mo_w-mo_r); return 1; } } while (0)
static int controllers(uint32_t at, uint32_t channel, int32_t bend, uint32_t mod)
{
    uint32_t a = midi_out_q[(mo_r + at) % MQ], b = midi_out_q[(mo_r + at + 1) % MQ];
    uint32_t u = (uint32_t)(bend + 8192);
    return a == (0x0Eu | (0xE0u | channel) << 8 | (u & 127u) << 16 | (u >> 7) << 24) &&
           b == (0x0Bu | (0xB0u | channel) << 8 | 1u << 16 | mod << 24);
}
static void drain(void) { mo_r = mo_w; }
int main(void)
{
    uint32_t i;
    memset(&song, 0, sizeof song); memset(trk, 0, sizeof trk);
    for (i = 0; i < G_COUNT; i++) song.g[i] = GP[i].def;
    host_tracks_init();
    usb.config = 1; mo_w = mo_r = mi_w = mi_r = 0;
#if BOARD_SMK37
    smk_bend14 = 4096; smk_modw = 99; events_block(CTL);
    CHECK(mo_w-mo_r == 2 && controllers(0, 0, 4096, 99)); drain();
    song.sel = 1; events_block(CTL);
    CHECK(mo_w-mo_r == 4 && controllers(0, 0, 0, 0) && controllers(2, 1, 4096, 99));
    CHECK(midi_bend_target[0] == 0 && trk[0].mw == 0 && midi_bend_target[1] == 256 && trk[1].mw == 99);
    drain(); events_block(CTL); CHECK(mo_w == mo_r);    /* no repeated neutral/value traffic */
    smk_bend14 = 0; smk_modw = 0; events_block(CTL);
    CHECK(mo_w-mo_r == 2 && controllers(0, 1, 0, 0)); drain();
    song.sel = 2; events_block(CTL);
    CHECK(mo_w-mo_r == 4 && controllers(0, 1, 0, 0) && controllers(2, 2, 0, 0)); drain();
    /* Rerouting the selected track must release its old output channel too. */
    song.g[G_ROUTE] = ROUTE_TRACK; mch_set(2, 12); smk_bend14 = -8192; smk_modw = 127; events_block(CTL);
    CHECK(mo_w-mo_r == 4 && controllers(0, 2, 0, 0) && controllers(2, 12, -8192, 127)); drain();
    /* Reassigning the old track does not change which receiver channel it left bent. */
    mch_set(2, 4); mch_set(3, 9); song.sel = 3; events_block(CTL);
    CHECK(mo_w-mo_r == 4 && controllers(0, 12, 0, 0) && controllers(2, 9, -8192, 127));
    CHECK(midi_bend_target[2] == 0 && trk[2].mw == 0 && midi_bend_target[3] == -512 && trk[3].mw == 127); drain();
    /* A shared output channel stays controlled; never insert a neutral glitch. */
    mch_set(0, 9); song.sel = 0; events_block(CTL);
    CHECK(mo_w-mo_r == 2 && controllers(0, 9, -8192, 127));
    CHECK(midi_bend_target[3] == 0 && trk[3].mw == 0 && midi_bend_target[0] == -512 && trk[0].mw == 127); drain();
    smk_bend14 = 0; smk_modw = 0; events_block(CTL);
    CHECK(mo_w-mo_r == 2 && controllers(0, 9, 0, 0));
    puts("SMK wheel handoff releases old receiver channel and preserves new/shared channel controllers");
#else
    midi_bend_target[0] = 512; trk[0].mw = 99;
    song.sel = 1; events_block(CTL);
    CHECK(mo_w == mo_r && midi_bend_target[0] == 512 && trk[0].mw == 99);
    song.g[G_ROUTE] = ROUTE_TRACK; mch_set(1, 12); events_block(CTL);
    CHECK(mo_w == mo_r);
    puts("FM1 selection and routing have no SMK wheel output");
#endif
    return 0;
}
