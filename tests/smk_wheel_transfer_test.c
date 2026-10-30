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
#if BOARD_SMK37
static void channel_event(uint32_t status, uint32_t channel, uint32_t d1, uint32_t d2)
{
    midi_enqueue((status >> 4) | (status | channel) << 8 | d1 << 16 | d2 << 24, 1);
}
static int expression_ownership(void)
{
    /* Note-ons do not own expression: stationary physical bend must survive
     * notes in this block and the next, including another heard SEL channel. */
    channel_event(0x90, 0, 60, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 99 && mo_w == mo_r);
    events_block(CTL); CHECK(midi_bend_target[0] == 256 && mo_w == mo_r);
    song.g[G_ROUTE] = ROUTE_SEL; events_block(CTL);
    channel_event(0x90, 5, 62, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 99 && mo_w == mo_r);
    /* The latest explicit MIDI bend/CC1 wins even when a different channel's
     * note arrives later in the same queue, or on a later unchanged block. */
    channel_event(0x90, 0, 63, 100);
    channel_event(0xE0, 5, 0, 32); channel_event(0xB0, 5, 1, 31);
    channel_event(0x90, 5, 64, 100); channel_event(0x90, 0, 65, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == -256 && trk[0].mw == 31 && mo_w == mo_r);
    channel_event(0x90, 2, 67, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == -256 && trk[0].mw == 31 && mo_w == mo_r);
    smk_bend14 = 4097; channel_event(0x90, 5, 68, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 31); drain();
    channel_event(0x90, 5, 69, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && mo_w == mo_r);
    /* RPN0 changes the authoritative source's range, not its raw bend. */
    channel_event(0xB0, 0, 101, 0); channel_event(0xB0, 0, 100, 0);
    channel_event(0xB0, 0, 6, 12); channel_event(0xB0, 0, 38, 50); events_block(CTL);
    CHECK(midi_bend_target[0] == 1600 && mo_w == mo_r);
    channel_event(0xB0, 5, 101, 0); channel_event(0xB0, 5, 100, 0);
    channel_event(0xB0, 5, 6, 4); channel_event(0x90, 5, 71, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == 1600 && mo_w == mo_r);
    channel_event(0xE0, 5, 0, 32); events_block(CTL);
    CHECK(midi_bend_target[0] == -512 && mo_w == mo_r);
    channel_event(0xB0, 0, 6, 1); channel_event(0x90, 0, 72, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == -512 && mo_w == mo_r);
    /* Explicit Reset Controllers takes authority; later notes cannot restore
     * the stationary physical wheel or another channel's remembered bend. */
    channel_event(0xB0, 5, 121, 0); channel_event(0x90, 0, 74, 100); events_block(CTL);
    CHECK(midi_bend_target[0] == 0 && trk[0].mw == 0 && mo_w == mo_r);
    events_block(CTL); CHECK(midi_bend_target[0] == 0 && trk[0].mw == 0 && mo_w == mo_r);
    /* Return controller/channel state to the starting point for route/handoff
     * cases below, with only physical movement restoring physical authority. */
    channel_event(0xB0, 0, 6, 2); channel_event(0xB0, 0, 38, 0);
    channel_event(0xB0, 0, 121, 0); events_block(CTL);
    smk_bend14 = 4096; smk_modw = 100; events_block(CTL); drain();
    smk_modw = 99; events_block(CTL); drain();
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 99);
    channel_event(0xB0, 0, 123, 0); channel_event(0xB0, 5, 123, 0); channel_event(0xB0, 2, 123, 0);
    events_block(CTL); CHECK(mo_w == mo_r);
    return 0;
}
#endif
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
    CHECK(!expression_ownership());
    /* SEL -> CH1-4 and TRACK revalidation retain output channel1, but routing
     * cleanup rebuilds the internal bend from incoming MIDI channel state. */
    song.g[G_ROUTE] = ROUTE_SEL; events_block(CTL); CHECK(mo_w == mo_r);
    song.g[G_ROUTE] = 0; events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 99);
    CHECK(mo_w-mo_r == 2 && controllers(0, 0, 4096, 99)); drain();
    events_block(CTL); CHECK(mo_w == mo_r && midi_bend_target[0] == 256);
    song.g[G_ROUTE] = ROUTE_TRACK; mch_set(0, 0); events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && mo_w-mo_r == 2 && controllers(0, 0, 4096, 99)); drain();
    mch_set(1, 5); midi_route = MIDI_ROUTE_AGAIN; events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && mo_w-mo_r == 2 && controllers(0, 0, 4096, 99)); drain();
    events_block(CTL); CHECK(mo_w == mo_r);
    /* MIDI arriving later in the very same cleanup block still wins; an idle
     * wheel must not take precedence again on the following unchanged block. */
    midi_route = MIDI_ROUTE_AGAIN;
    midi_enqueue(0x0Eu | 0xE0u << 8 | 80u << 24, 1);  /* bend+2048: +128 Q8 at default range */
    midi_enqueue(0x0Bu | 0xB0u << 8 | 1u << 16 | 31u << 24, 1);
    events_block(CTL);
    CHECK(midi_bend_target[0] == 128 && trk[0].mw == 31);
    CHECK(mo_w-mo_r == 2 && controllers(0, 0, 4096, 99)); drain();
    events_block(CTL); CHECK(mo_w == mo_r && midi_bend_target[0] == 128 && trk[0].mw == 31);
    smk_bend14 = 4097; events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 31 && mo_w-mo_r == 1);
    CHECK(midi_out_q[mo_r % MQ] == (0x0Eu | 0xE0u << 8 | 1u << 16 | 96u << 24)); drain();
    smk_modw = 100; events_block(CTL);
    CHECK(midi_bend_target[0] == 256 && trk[0].mw == 100 && mo_w-mo_r == 1);
    CHECK(midi_out_q[mo_r % MQ] == (0x0Bu | 0xB0u << 8 | 1u << 16 | 100u << 24)); drain();
    smk_bend14 = 4096; smk_modw = 99; events_block(CTL); drain();
    /* Return to the default route before the existing channel-handoff cases. */
    song.g[G_ROUTE] = 0; events_block(CTL); drain();
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
    /* TRACK input uses its first matching track, but a later matching track
     * can own the physical output bend. Its source's RPN range still applies. */
    mch_set(1, 9); song.sel = 1; events_block(CTL); drain();
    CHECK(midi_bend_target[0] == 0 && midi_bend_target[1] == -512);
    channel_event(0xB0, 9, 101, 0); channel_event(0xB0, 9, 100, 0);
    channel_event(0xB0, 9, 6, 12); events_block(CTL);
    CHECK(midi_bend_target[1] == -3072 && midi_bend_target[0] == 0 && mo_w == mo_r);
    channel_event(0x90, 9, 60, 100); channel_event(0xE0, 9, 0, 80); events_block(CTL);
    CHECK(midi_bend_target[0] == 768 && midi_bend_target[1] == -3072 && mo_w == mo_r);
    channel_event(0xB0, 9, 6, 2); events_block(CTL);
    CHECK(midi_bend_target[0] == 128 && midi_bend_target[1] == -512 && mo_w == mo_r);
    channel_event(0x80, 9, 60, 0); events_block(CTL);
    song.sel = 0; events_block(CTL); drain();
    CHECK(midi_bend_target[1] == 0 && midi_bend_target[0] == -512);
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
