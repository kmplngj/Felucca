/* SPDX-License-Identifier: GPL-3.0-only */
#include "ui_harness.h"

static void midi_test_reset(void)
{
    ui_power_on();
    memset(midi_ch, 0, sizeof midi_ch); memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners); memset(midi_bend_q8, 0, sizeof midi_bend_q8);
    memset(midi_bend_target, 0, sizeof midi_bend_target); memset(&midi_clock, 0, sizeof midi_clock);
    memset(&um, 0, sizeof um); memset(midi_in_source, 0, sizeof midi_in_source);
    mi_r = mi_w = 0; midi_in_overflow = 0; midi_beat_samples = 0;
    fm1_in.notes = kb_prev = 0; fm1_ms = 0; song.sel = 0;
    memset(song.mch, 0, sizeof song.mch); song.g[G_ROUTE] = 0; midi_seen = 0; memset(midi_lit_ms, 0, sizeof midi_lit_ms);
    events_block(CTL);
}
static void queued(uint32_t st, uint32_t d1, uint32_t d2, uint32_t source)
{
    midi_enqueue((st >= 0xF8u ? 0xFu : st >> 4) | st << 8 | d1 << 16 | d2 << 24, source);
    events_block(CTL);
}
static int gate_note(const track_t *t, uint32_t note)
{
    for (uint32_t i = 0; i < NVOICE; i++) if (t->v[i].active && t->v[i].gate && t->v[i].note == note) return 1;
    return 0;
}


static void select_nrpn(uint32_t ch, uint32_t source, uint32_t msb, uint32_t lsb)
{
    queued(0xB0u | ch, 99, msb, source);
    queued(0xB0u | ch, 98, lsb, source);
}
static int32_t expected_cc(track_t *t, uint32_t id, uint32_t value)
{
    const param_desc_t *d = param_desc_of(eng_idx(t->eng_req), id);
    return d->min + ((int32_t)value * (d->max - d->min) + 63) / 127;
}
static int nrpn_registry_test(void)
{
    int bad = 0;
    midi_test_reset(); midi_nrpn_reset();
    for (uint32_t msb = 0; msb < 128; msb++)
        for (uint32_t lsb = 0; lsb < 128; lsb++) {
            uint32_t expected = P_COUNT;
#define EXPECT_COMMON(at, id, name) if (!msb && lsb == at) expected = id;
            MIDI_NRPN_COMMON(EXPECT_COMMON)
#undef EXPECT_COMMON
#define EXPECT_ENGINE(at, id, name) if (msb == 1 && lsb == at) expected = id;
            MIDI_NRPN_ENGINE(EXPECT_ENGINE)
#undef EXPECT_ENGINE
            if (midi_nrpn_id(msb, lsb) != expected) return check("entire 14-bit registry preserves all assigned and reserved addresses", 0);
        }
    bad += check("entire 14-bit registry preserves all assigned and reserved addresses", 1);
#define APPLY_COMMON(at, id, name) \
    select_nrpn(0, 1, 0, at); \
    for (uint32_t v = 0; v < 3; v++) { \
        uint32_t value = v == 0 ? 0 : v == 1 ? 64 : 127; \
        queued(0xB0, 6, value, 1); \
        bad += check("common registry entry applies real native descriptor", trk[0].p[id] == expected_cc(&trk[0], id, value)); \
    }
    MIDI_NRPN_COMMON(APPLY_COMMON)
#undef APPLY_COMMON
    return bad;
}
static int nrpn_sources_test(void)
{
    int bad = 0;
    midi_test_reset(); midi_nrpn_reset(); song.g[G_ROUTE] = ROUTE_SEL;
    for (uint32_t ch = 0; ch < 16; ch++) {
        select_nrpn(ch, 1, 0, 0); select_nrpn(ch, 2, 0, 39);
        queued(0xB0u | ch, 6, ch, 1);
        bad += check("each USB channel keeps its level selector", trk[0].p[P_LEVEL] == (int32_t)ch);
        queued(0xB0u | ch, 6, 127 - ch, 2);
        bad += check("each TRS channel keeps its pan selector", trk[0].p[P_PAN] == 63 - (int32_t)ch);
    }
    for (uint32_t ch = 0; ch < 16; ch++) {
        queued(0xB0u | ch, 6, 100, 1); queued(0xB0u | ch, 6, 64, 2);
        bad += check("interleaved source selectors survive other channels", trk[0].p[P_LEVEL] == 100 && trk[0].p[P_PAN] == 0);
    }
    midi_nrpn_reset(); trk[0].p[P_LEVEL] = 77;
    queued(0xB0, 99, 0, 1); queued(0xB0, 6, 0, 1);
    bad += check("partial selector does not dispatch", trk[0].p[P_LEVEL] == 77);
    queued(0xB0, 98, 0, 2); queued(0xB0, 6, 0, 2);
    bad += check("halves from different sources do not combine", trk[0].p[P_LEVEL] == 77);
    queued(0xB0, 98, 0, 1);
    bad += check("completing selection does not dispatch stale data", trk[0].p[P_LEVEL] == 77);
    queued(0xB0, 38, 0, 1); queued(0xB0, 96, 0, 1); queued(0xB0, 97, 0, 1);
    bad += check("NRPN ignores LSB and increment/decrement", trk[0].p[P_LEVEL] == 77);
    select_nrpn(0, 1, 127, 127); queued(0xB0, 6, 0, 1);
    bad += check("null selector cancels", trk[0].p[P_LEVEL] == 77);
    select_nrpn(0, 1, 0, 8); queued(0xB0, 6, 0, 1);
    bad += check("retired common hole remains ignored", trk[0].p[P_LEVEL] == 77);
    select_nrpn(0, 1, 2, 0); queued(0xB0, 6, 0, 1);
    bad += check("unknown bank remains ignored", trk[0].p[P_LEVEL] == 77);
    return bad;
}
static int nrpn_routing_test(void)
{
    int bad = 0;
    midi_test_reset(); midi_nrpn_reset();
    song.g[G_ROUTE] = ROUTE_TRACK; mch_set(0, 0); mch_set(1, 0); mch_set(2, 1); mch_set(3, 2);
    select_nrpn(0, 1, 0, 39);
    for (uint32_t v = 0; v < 3; v++) {
        uint32_t value = v == 0 ? 0 : v == 1 ? 64 : 127;
        queued(0xB0, 6, value, 1);
        bad += check("all routed layer destinations use native PAN bounds", trk[0].p[P_PAN] == expected_cc(&trk[0], P_PAN, value) && trk[1].p[P_PAN] == trk[0].p[P_PAN]);
    }
    select_nrpn(0, 1, 1, 0);
    for (uint32_t eng = 0; eng < NENGINES; eng++) {
        trk[0].eng_req = (uint8_t)eng;
        for (uint32_t k = 0; k < 8; k++) {
            select_nrpn(0, 1, 1, k);
            const param_desc_t *d = param_desc_of(eng_idx(eng), P_E0 + k);
            for (uint32_t v = 0; v < 3; v++) {
                uint32_t value = v == 0 ? 0 : v == 1 ? 64 : 127;
                trk[0].p[P_E0 + k] = 23;
                queued(0xB0, 6, value, 1);
                bad += check("engine slots follow current native descriptor including absent slots", trk[0].p[P_E0 + k] == (eng_ok(eng) && d->max > d->min ? expected_cc(&trk[0], P_E0 + k, value) : 23));
            }
        }
    }
    trk[0].eng_req = 255; trk[0].p[P_E0] = 23; select_nrpn(0, 1, 1, 0); queued(0xB0, 6, 127, 1);
    bad += check("unknown engine is silent descriptor and cannot redirect to another engine", trk[0].p[P_E0] == 23);
    return bad;
}
static int nrpn_motion_test(void)
{
    int bad = 0;
    midi_test_reset(); midi_nrpn_reset();
    track_t *t = &trk[0]; t->p[P_REV] = 23; song.rec = 1;
    seq_start(); seq_tick(t, CTL);
    select_nrpn(0, 1, 0, 36); queued(0xB0, 6, 92, 1);
    bad += check("NRPN uses real motion capture and preserves patch base", motion.count == 1u && motion.event[0].value == 92 && motion_base_value(t, P_REV) == 23);
    seq_stop();
    bad += check("recorded NRPN restores original base on stop", t->p[P_REV] == 23);
    return bad;
}
static int nrpn_reset_priority_test(void)
{
    int bad = 0;
    midi_test_reset(); midi_nrpn_reset();
    select_nrpn(0, 1, 0, 0); select_nrpn(0, 2, 0, 39);
    queued(0xB0, 101, 0, 2); queued(0xB0, 100, 0, 2); queued(0xB0, 6, 12, 1);
    bad += check("shared RPN supersedes both source NRPN selectors", midi_ch[0].semis == 12 && !midi_nrpn[0][0].seen && !midi_nrpn[1][0].seen);
    select_nrpn(0, 1, 0, 0); queued(0xB0, 6, 90, 1);
    bad += check("NRPN cancels RPN without changing bend sensitivity", midi_ch[0].semis == 12 && trk[0].p[P_LEVEL] == 90);
    queued(0xB0, 7, 80, 2);
    bad += check("fixed CC retains priority while NRPN selected", trk[0].p[P_LEVEL] == 80);
    uint32_t e = 7u | ((P_PAN + 1u) << 9); ml_tab[0] = (uint8_t)e; ml_tab[1] = (uint8_t)(e >> 8);
    queued(0xB0, 7, 127, 1); queued(0xB0, 6, 92, 1);
    bad += check("learned CC priority preserved and NRPN consumes no learn slots", trk[0].p[P_PAN] == 63 && trk[0].p[P_LEVEL] == 92 && ml_tab[0] == (uint8_t)e && ml_tab[1] == (uint8_t)(e >> 8));
    queued(0xB0, 121, 0, 2); queued(0xB0, 6, 0, 1);
    bad += check("CC121 cancels both sources", trk[0].p[P_LEVEL] == 92);
    select_nrpn(0, 1, 0, 0); midi_in_overflow = 1; events_block(CTL); queued(0xB0, 6, 0, 1);
    bad += check("overflow invalidates all selectors before recovery", trk[0].p[P_LEVEL] == 92 && !midi_nrpn[0][0].seen);
    select_nrpn(0, 1, 0, 0); song.g[G_ROUTE] = 2; events_block(CTL); song.g[G_ROUTE] = 0; events_block(CTL); queued(0xB0, 6, 0, 1);
    bad += check("unheard channel route transition invalidates selector", trk[0].p[P_LEVEL] == 92);
    return bad;
}
static void public_map(void)
{
    puts("| Address | Parameter | Native bounds |\n| --- | --- | --- |");
#define MAP_ROW(lsb, id, name) printf("| 0:%u | %s | %d..%d |\n", (unsigned)(lsb), name, TP[id].min, TP[id].max);
    MIDI_NRPN_COMMON(MAP_ROW)
#undef MAP_ROW
    puts("| 1:0..7 | Current engine E1..E8 | Current native engine descriptor |");
}
int main(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "--map")) { public_map(); return 0; }
    int bad = nrpn_registry_test() + nrpn_sources_test() + nrpn_routing_test() + nrpn_motion_test() + nrpn_reset_priority_test();
    printf("NRPN: %s (%d failures)\n", bad ? "FAIL" : "PASS", bad);
    return !!bad;
}
