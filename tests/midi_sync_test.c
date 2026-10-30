/* SPDX-License-Identifier: GPL-3.0-only */
/* MIDI sync. #281: Song Position Pointer then Continue, through the real USB/TRS queues, external clock, sequencer
 * and SONG. A located run must match a reference run that played from Start to the same position: every track's
 * step, its samples into it and its loop count, the SONG's section and repeat, then the same steps afterwards.
 * #280: CLOCK OUT, the USB out ring read as a host would: pulses, transport bytes, the reserved slots. */
#include "ui_harness.h"

#define PULSE_MS(i) (10u + (uint32_t)(((uint64_t)(i) * 125u) / 6u))   /* 120 BPM: 24 pulses a quarter */

static uint32_t sync_src;                          /* 1 USB, 2 TRS */
static uint32_t sync_pulse;                        /* the master's pulses sent since its Start */

static void sync_byte3(uint32_t st, uint32_t d1, uint32_t d2)
{
    if (sync_src == 2u) {
        um_byte(st); um_byte(d1); um_byte(d2);
    } else {
        midi_in_event(0x3u | st << 8 | d1 << 16 | d2 << 24);
    }
}
static void sync_rt(uint32_t status, uint32_t ms)
{
    fm1_ms = ms;
    if (sync_src == 2u) um_byte(status);
    else midi_in_event(0xFu | status << 8);
    events_block(CTL);
}
static void sync_spp(uint32_t beats)
{
    sync_byte3(0xF2u, beats & 0x7Fu, beats >> 7 & 0x7Fu);
    events_block(CTL);
}
static void sync_pulses(uint32_t n)                /* the master's next n clocks, in time */
{
    while (n--) {
        sync_rt(0xF8u, PULSE_MS(sync_pulse));
        sync_pulse++;
    }
}
static const int16_t SYNC_LEN[NTRK] = {16, 17, 7, 5}, SYNC_DIV[NTRK] = {2, 3, 1, 0}, SYNC_SW[NTRK] = {0, 0, 30, 0};
static void sync_tracks(void)
{
    for (uint32_t k = 0; k < NTRK; k++) {
        track_t *t = &trk[k];
        t->p[P_SLEN] = SYNC_LEN[k]; t->p[P_SDIV] = SYNC_DIV[k]; t->p[P_SSWING] = SYNC_SW[k];
        t->p[P_SGATE] = 64; t->p[P_SQNT] = 1;
        for (uint32_t i = 0; i < NSTEP; i++) t->step[i] = (step_t){{(uint8_t)(40 + i)}, 1, ST_NOTE, 0, 100};
    }
}
static void sync_setup(uint32_t source)
{
    ui_power_on();
    memset(&midi_clock, 0, sizeof midi_clock); memset(&um, 0, sizeof um); memset(midi_in_source, 0, sizeof midi_in_source);
    mi_r = mi_w = 0; midi_in_overflow = 0; midi_beat_samples = 0; fm1_ms = 0;
    sync_src = source; sync_pulse = 0;
    song.g[G_CLOCK] = (int16_t)source; song.g[G_BPM] = 120; song.g[G_SWING] = 0;
    events_block(CTL);
    for (uint32_t k = 0; k < NTRK; k++) {
        set_engine_of(&trk[k], 0); apply_preset_to(&trk[k], 0); trk[k].engine = trk[k].eng_req;
    }
    sync_tracks();
}

typedef struct {
    uint16_t idx[NTRK];
    uint32_t pos[NTRK];
    uint8_t cond[NTRK], row, remaining, song, playing;
    uint32_t clk_step, beat_n;
} sync_state_t;
static sync_state_t sync_state(void)
{
    sync_state_t s;
    memset(&s, 0, sizeof s);
    for (uint32_t k = 0; k < NTRK; k++) {
        s.idx[k] = trk[k].seq_idx; s.pos[k] = trk[k].seq_pos; s.cond[k] = trk[k].cond_loop;
    }
    s.song = chain.running; s.row = chain.running ? chain.row : 0; s.remaining = chain.running ? chain.remaining : 0;
    s.playing = song.playing; s.clk_step = clk_step; s.beat_n = beat_n;
    return s;
}
static int sync_same(const sync_state_t *a, const sync_state_t *b)
{
    int ok = a->song == b->song && a->row == b->row && a->remaining == b->remaining && a->playing == b->playing &&
             a->clk_step == b->clk_step && a->beat_n == b->beat_n;
    for (uint32_t k = 0; k < NTRK; k++) {
        int32_t d = (int32_t)(a->pos[k] - b->pos[k]);
        ok &= a->idx[k] == b->idx[k] && a->cond[k] == b->cond[k] && d >= -2 && d <= 2;   /* (sample rounding) */
    }
    return ok;
}
static void sync_print(const char *what, const sync_state_t *s)
{
    printf("  %s: song %u row %u rem %u play %u clk %u beat %u |", what, s->song, s->row, s->remaining, s->playing,
           s->clk_step, s->beat_n);
    for (uint32_t k = 0; k < NTRK; k++) printf(" T%u %u/%u c%u", k + 1u, s->idx[k], s->pos[k], s->cond[k]);
    printf("\n");
}

/* sync_state() after `after` more pulses, from Start, at the master position `beats` (sixteenths) */
static void sync_reference(uint32_t beats, uint32_t after, sync_state_t *at, sync_state_t *later)
{
    sync_rt(0xFAu, PULSE_MS(0));
    sync_pulses(beats * 6u + 1u);
    *at = sync_state();
    sync_pulses(after);
    *later = sync_state();
}
/* the master stops (now), locates to `beats` and continues there (its clock resumes at that pulse) */
static void sync_locate(uint32_t beats, uint32_t after, sync_state_t *at, sync_state_t *later)
{
    sync_rt(0xFCu, fm1_ms + 1u);
    sync_spp(beats);
    sync_pulse = beats * 6u;
    sync_rt(0xFBu, PULSE_MS(sync_pulse) - 1u);
    sync_pulses(1);
    *at = sync_state();
    sync_pulses(after);
    *later = sync_state();
}

static int patterns_test(uint32_t source)
{
    static const uint32_t beats[] = {0, 1, 3, 5, 14, 37, 100, 341, 1000};
    int bad = 0, ok = 1;
    for (uint32_t i = 0; i < sizeof beats / sizeof beats[0]; i++) {
        sync_state_t ra, rb, la, lb;
        sync_setup(source);
        sync_reference(beats[i], 77, &ra, &rb);
        sync_setup(source);
        sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(50);           /* somewhere else first */
        sync_locate(beats[i], 77, &la, &lb);
        if (!sync_same(&ra, &la) || !sync_same(&rb, &lb)) {
            printf("  position %u:\n", beats[i]);
            sync_print("reference", &ra); sync_print("located  ", &la);
            sync_print("ref later", &rb); sync_print("loc later", &lb);
            ok = 0;
        }
    }
    bad += check(source == 1u ? "USB SPP + Continue: polymetric, swung, conditions as from Start"
                              : "TRS SPP + Continue: polymetric, swung, conditions as from Start", ok);
    return bad;
}

/* a step starting exactly on the position sounds; a step that started before it does not */
static int voice_on(const track_t *t, uint32_t note)
{
    for (uint32_t i = 0; i < NVOICE; i++) if (t->v[i].active && t->v[i].gate && t->v[i].note == note) return 1;
    return 0;
}
static int boundary_test(void)
{
    int bad = 0;
    sync_setup(1);
    sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(10); sync_rt(0xFCu, 300);
    sync_spp(9);                                    /* T1 (1/16) step 10 starts; T4 (1/4) is a quarter into step 3 */
    sync_rt(0xFBu, 400);
    bad += check("SPP on a step: it plays on Continue; a step begun before stays silent",
                 song.playing && voice_on(&trk[0], 49) && trk[0].seq_idx == 9u && !voice_on(&trk[3], 42) &&
                 trk[3].seq_idx == 2u && !trk[3].seq_n);
    return bad;
}

static int transport_rules_test(void)
{
    int bad = 0;
    sync_state_t ra, rb, la, lb;
    /* SPP while playing: ignored (no locate now, none on a later Continue) */
    sync_setup(1);
    sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(30);
    ra = sync_state(); sync_spp(200); la = sync_state();
    bad += check("SPP while playing is ignored", sync_same(&ra, &la) && !midi_clock.spp_set);
    /* Start after an SPP: from zero */
    sync_rt(0xFCu, fm1_ms + 1u); sync_spp(37); sync_pulse = 0;
    sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(1); la = sync_state();
    sync_setup(1); sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(1); ra = sync_state();
    bad += check("Start after an SPP starts from zero", sync_same(&ra, &la));
    /* the other source's SPP is ignored; Continue without SPP keeps the stopped step (as before #281) */
    sync_setup(1); sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(40); sync_rt(0xFCu, fm1_ms + 1u);
    ra = sync_state();
    sync_src = 2; sync_spp(100); sync_src = 1;
    sync_rt(0xFBu, fm1_ms + 5u); la = sync_state();
    bad += check("TRS SPP ignored with USB clock; plain Continue resumes in place",
                 !midi_clock.spp_set && la.playing && la.idx[0] == ra.idx[0] && la.pos[0] == ra.pos[0]);
    /* a truncated F2 (a status inside) does not locate */
    sync_setup(2); sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(40); sync_rt(0xFCu, fm1_ms + 1u);
    ra = sync_state();
    um_byte(0xF2); um_byte(0x05); um_byte(0xB0); um_byte(7); um_byte(100); events_block(CTL);
    sync_rt(0xFBu, fm1_ms + 5u); la = sync_state();
    bad += check("truncated TRS F2 does not locate", la.idx[0] == ra.idx[0] && la.pos[0] == ra.pos[0]);
    (void)rb; (void)lb;
    return bad;
}

/* SONG: slot 0 (LEN 16 1/16) twice, slot 1 (T1 LEN 12, T2 silent, T3 LEN 6 1/8) 3 times, all silent once: 84 x 1/16 */
static void song_setup(uint32_t source)
{
    sync_setup(source);
    for (uint32_t k = 0; k < NTRK; k++) { trk[k].p[P_SLEN] = 16; trk[k].p[P_SDIV] = 2; trk[k].p[P_SSWING] = 0; }
    project_save(0);
    trk[0].p[P_SLEN] = 12; trk[2].p[P_SLEN] = 6; trk[2].p[P_SDIV] = 1;
    project_save(1);
    sync_tracks();                                  /* (the editable timing differs: the song must own it) */
    chain_config.count = 3;
    chain_config.row[0] = (chain_row_t){{0, 0, 0, 0}, 2};
    chain_config.row[1] = (chain_row_t){{1, CHAIN_SILENT, 1, 1}, 3};
    chain_config.row[2] = (chain_row_t){{CHAIN_SILENT, CHAIN_SILENT, CHAIN_SILENT, CHAIN_SILENT}, 1};
}
static void song_reference(uint32_t beats, uint32_t after, sync_state_t *at, sync_state_t *later)
{
    chain_prepare(); fm1_ms = PULSE_MS(0); events_block(CTL);   /* SONG PLAY (the panel): its Start, waiting */
    sync_pulses(beats * 6u + 1u);
    *at = sync_state();
    sync_pulses(after);
    *later = sync_state();
}
static int song_test(uint32_t source)
{
    static const uint32_t beats[] = {0, 5, 16, 31, 32, 33, 44, 56, 67, 68, 70, 83};
    int bad = 0, ok = 1;
    for (uint32_t i = 0; i < sizeof beats / sizeof beats[0]; i++) {
        sync_state_t ra, rb, la, lb;
        song_setup(source);
        song_reference(beats[i], 5, &ra, &rb);
        song_setup(source);
        song_reference(20, 0, &la, &lb);            /* the song plays; the master stops it, locates, continues */
        sync_locate(beats[i], 5, &la, &lb);
        if (!sync_same(&ra, &la) || !sync_same(&rb, &lb) || !ra.song) {
            printf("  song position %u:\n", beats[i]);
            sync_print("reference", &ra); sync_print("located  ", &la);
            sync_print("ref later", &rb); sync_print("loc later", &lb);
            ok = 0;
        }
    }
    bad += check(source == 1u ? "USB SPP + Continue: SONG section, repeat, silent lanes as from Start"
                              : "TRS SPP + Continue: SONG section, repeat, silent lanes as from Start", ok);
    return bad;
}
static int song_rules_test(void)
{
    int bad = 0;
    sync_state_t ra, rb, la, lb;
    /* past the end: stays stopped, the song kept; a locate back plays it */
    song_setup(1); song_reference(20, 0, &la, &lb);
    sync_locate(84, 6, &la, &lb);
    bad += check("SONG: SPP past its end stays stopped, timing restored",
                 !song.playing && !chain.running && midi_clock.song && trk[2].p[P_SLEN] == SYNC_LEN[2] &&
                 trk[2].p[P_SDIV] == SYNC_DIV[2]);
    sync_locate(40, 6, &la, &lb);
    bad += check("SONG: then a locate back into it plays its section", la.playing && la.song && la.row == 1u);
    /* plain Continue (no SPP) resumes the song where the master stopped it */
    song_setup(1); song_reference(50, 0, &ra, &rb);
    sync_rt(0xFCu, fm1_ms + 1u);
    sync_rt(0xFBu, PULSE_MS(sync_pulse) - 1u); sync_pulses(13); la = sync_state();
    song_setup(1); song_reference(52, 0, &ra, &rb);
    bad += check("SONG: Continue without SPP resumes it where it stopped", sync_same(&ra, &la));
    /* Start after a song the master stopped: the song from its first section */
    song_setup(1); song_reference(40, 0, &la, &lb);
    sync_rt(0xFCu, fm1_ms + 1u); sync_pulse = 0;
    sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(7); la = sync_state();
    song_setup(1); song_reference(1, 0, &ra, &rb);
    bad += check("SONG: Start after the master's Stop plays it from section 1", sync_same(&ra, &la) && la.song);
    /* the panel's PLAY / STOP ends it: Continue then plays the patterns */
    song_setup(1); song_reference(40, 0, &la, &lb);
    sync_rt(0xFCu, fm1_ms + 1u);
    transport_req = 2; events_block(CTL);
    sync_spp(8); sync_rt(0xFBu, fm1_ms + 1u);
    bad += check("SONG: after the panel's STOP, SPP + Continue locates the patterns", song.playing && !chain.running &&
                 trk[0].p[P_SLEN] == SYNC_LEN[0] && trk[0].seq_idx == 8u);
    /* a song that reached its end: the master's Start plays it again */
    song_setup(1); song_reference(90, 0, &la, &lb);
    bad += check("SONG: at its end it stops (as before)", !song.playing && !chain.running && midi_clock.song);
    sync_rt(0xFCu, fm1_ms + 1u); sync_pulse = 0; sync_rt(0xFAu, PULSE_MS(0)); sync_pulses(1);
    bad += check("SONG: the master's next Start plays it again", song.playing && chain.running && chain.row == 0u);
    chain_defaults(&chain_config); memset(proj_slot, 0, sizeof proj_slot);
    return bad;
}

/* ---- #280: CLOCK OUT. The out ring drained as the host would, each packet with the samples played when queued */
static uint32_t out_pkt[8192], out_at[8192], out_n, out_samples;
static void out_drain(void)
{
    while (mo_r != mo_w) {
        if (out_n < 8192u) { out_pkt[out_n] = midi_out_q[mo_r % MQ]; out_at[out_n++] = out_samples; }
        mo_r++;
    }
}
static void out_reset(void) { mo_r = mo_w; out_n = 0; out_samples = 0; midi_out_drops = midi_rt_drops = 0; }
static void out_block(void)
{
    events_block(CTL);
    out_samples += CTL;
    out_drain();
}
static uint32_t out_count(uint32_t status, uint32_t from)
{
    uint32_t c = 0;
    for (uint32_t i = from; i < out_n; i++) c += out_pkt[i] == (0xFu | status << 8);
    return c;
}
static void out_setup(uint32_t mode, uint32_t bpm)
{
    sync_setup(1);
    song.g[G_CLOCK] = 0; song.g[G_BPM] = (int16_t)bpm; events_block(CTL);
    usb.config = 1;
    menu_put(MI_CLKOUT, mode);
    out_reset();
}
/* blocks of play from PLAY: each 1/16 of T1 (LEN 16, 1/16) starts in the block of its first pulse and holds 6; pulse k
 * leaves within a block of k * beat / 24 samples (plus the whole-sample 1/16's truncation) */
static int out_run(uint32_t blocks, const uint32_t *bpm_at, const uint32_t *bpm, uint32_t changes)
{
    uint32_t prev = 0, steps = 0, k = 0, c = 0, beat = (uint32_t)FS * 60u / (uint32_t)song.g[G_BPM];
    int ok = 1, fixed = changes == 0u;
    transport_req = 1;
    for (uint32_t b = 0; b < blocks; b++) {
        uint32_t n0 = out_n;
        if (c < changes && b == bpm_at[c]) song.g[G_BPM] = (int16_t)bpm[c++];
        out_block();
        if (!b) prev = trk[0].seq_idx;
        else if (trk[0].seq_idx != prev) {
            steps += (uint32_t)(trk[0].seq_idx - prev) & 15u;   /* (a faster tempo may skip steps: LEN 16) */
            prev = trk[0].seq_idx;
            /* (a tempo change may land well into the step: its pulses due by then too) */
            if ((out_count(0xF8u, 0) - 1u) / 6u != steps || !out_count(0xF8u, n0) || (fixed && out_count(0xF8u, 0) != 6u * steps + 1u)) {
                if (ok) printf("  step %u at block %u: %u pulses\n", steps, b, out_count(0xF8u, 0));
                ok = 0;
            }
        }
        for (uint32_t i = n0; fixed && i < out_n; i++)
            if (out_pkt[i] == 0xF80Fu) {
                int32_t ideal = (int32_t)((uint64_t)k * beat / 24u), d = (int32_t)out_at[i] - (int32_t)CTL - ideal;
                if (!(d >= -(int32_t)(k / 6u + 2u) && d < (int32_t)CTL)) { if (ok) printf("  pulse %u at %u ideal %d\n", k, out_at[i], ideal); ok = 0; }
                k++;
            }
    }
    ok &= steps > 0u;
    return ok;
}
static int clock_out_test(void)
{
    static const uint32_t bpms[] = {40, 97, 120, 177, 240};
    int bad = 0, ok = 1;
    uint32_t n0, i;
    for (i = 0; i < sizeof bpms / sizeof bpms[0]; i++) {
        uint32_t beat = (uint32_t)FS * 60u / bpms[i], blocks = 8u * beat / CTL, want, n;
        out_setup(1, bpms[i]);
        int ph = out_run(blocks, 0, 0, 0);
        n = out_count(0xF8u, 0);
        want = (uint32_t)((uint64_t)blocks * CTL * 24u / beat) + 1u;   /* (8 quarters) */
        if (n + 1u < want || n > want + 1u || !ph) {
            printf("  %u BPM: %u pulses, want %u, phase %d\n", bpms[i], n, want, ph);
            ok = 0;
        }
        ok &= !out_count(0xFAu, 0) && !out_count(0xFCu, 0);
    }
    bad += check("CLOCK OUT CLOCK: 24 PPQN at 40..240 BPM with the 1/16 steps, no transport bytes", ok);
    {
        static const uint32_t at[] = {700, 1500, 2200}, to[] = {61, 233, 140};
        out_setup(1, 120); trk[1].p[P_SSWING] = 40;   /* (T2 swings; T1, the reference, does not) */
        bad += check("CLOCK OUT: tempo changes while playing keep 6 pulses each 1/16 step (swing ignored)",
                     out_run(3000, at, to, 3) && trk[0].p[P_SDIV] == 2);
        song.g[G_SWING] = 0;
    }
    /* CLOCK+TRANS: Start first, then the pulses; Stop; a restart is Stop, Start; OFF sends nothing */
    out_setup(2, 120);
    transport_req = 1; out_block();
    ok = out_n >= 2u && out_pkt[0] == 0xFA0Fu && out_pkt[1] == 0xF80Fu;
    for (i = 0; i < 200u; i++) out_block();
    transport_req = 2; out_block();
    ok &= out_pkt[out_n - 1u] == 0xFC0Fu && out_count(0xFAu, 0) == 1u && out_count(0xFCu, 0) == 1u;
    n0 = out_n;
    for (i = 0; i < 200u; i++) out_block();
    ok &= out_n == n0;
    bad += check("CLOCK OUT CLOCK+TRANS: Start before the first pulse, Stop, then nothing", ok);
    transport_req = 1; out_block(); for (i = 0; i < 100u; i++) out_block();
    n0 = out_n; transport_req = 3; out_block();
    bad += check("CLOCK OUT CLOCK+TRANS: GLO + PLAY restart sends Stop, Start, a pulse",
                 out_n >= n0 + 3u && out_pkt[n0] == 0xFC0Fu && out_pkt[n0 + 1u] == 0xFA0Fu && out_pkt[n0 + 2u] == 0xF80Fu);
    out_setup(0, 120);
    transport_req = 1; for (i = 0; i < 400u; i++) out_block();
    key_on(0, TSEL); out_block();
    bad += check("CLOCK OUT OFF: no realtime bytes (the keys' notes still go out)", out_n == 1u && (out_pkt[0] & 0xFFu) == 0x09u);
    /* switched on while playing: from the next PLAY; switched OFF: a Stop ends it */
    menu_put(MI_CLKOUT, 2); out_reset();
    for (i = 0; i < 400u; i++) out_block();
    ok = out_n == 0u;
    transport_req = 2; out_block(); transport_req = 1; for (i = 0; i < 100u; i++) out_block();
    ok &= out_pkt[0] == 0xFA0Fu;
    menu_put(MI_CLKOUT, 0); n0 = out_n; out_block();
    ok &= out_n == n0 + 1u && out_pkt[n0] == 0xFC0Fu;
    bad += check("CLOCK OUT: on while playing waits for PLAY; OFF while playing sends Stop", ok);
    /* following an external clock: nothing out (no THRU) */
    out_setup(2, 120);
    song.g[G_CLOCK] = 1; events_block(CTL); out_reset();
    sync_rt(0xFAu, PULSE_MS(0)); sync_pulse = 1;
    for (i = 0; i < 200u; i++) { sync_pulses(1); out_drain(); }
    bad += check("CLOCK OUT: nothing while following USB clock", song.playing && out_n == 0u);
    usb.config = 0;
    return bad;
}
static int clock_out_ring_test(void)
{
    int bad = 0, ok;
    uint32_t i, rt = 0;
    out_setup(1, 120);
    transport_req = 1; out_block(); out_reset();
    for (i = 0; i < 100u; i++) midi_out_event(0x09u | 0x90u << 8 | 60u << 16 | 100u << 24);
    ok = mo_w - mo_r == MQ - MQ_RT_ROOM && midi_out_drops == 100u - (MQ - MQ_RT_ROOM);
    for (i = 0; i < 600u && mo_w - mo_r < MQ; i++) events_block(CTL);
    for (i = mo_r; i != mo_w; i++) rt += midi_out_q[i % MQ] == 0xF80Fu;
    ok &= rt == MQ_RT_ROOM;
    for (i = 0; i < 300u; i++) events_block(CTL);
    ok &= midi_rt_drops > 0u;                          /* (no host draining: counted) */
    bad += check("CLOCK OUT: a key burst leaves the clock its 8 slots; overflows counted", ok);
    out_setup(0, 120);
    for (i = 0; i < 100u; i++) midi_out_event(0x09u | 0x90u << 8 | 60u << 16 | 100u << 24);
    bad += check("CLOCK OUT OFF: the keys have the whole ring, as before", mo_w - mo_r == MQ);
    mo_r = mo_w; usb.config = 0;
    return bad;
}
/* SONG with CLOCK+TRANS: the pulses run on across its sections; its end sends Stop */
static int clock_out_song_test(void)
{
    int bad = 0;
    song_setup(1);
    song.g[G_CLOCK] = 0; events_block(CTL);
    usb.config = 1; menu_put(MI_CLKOUT, 2); out_reset();
    chain_prepare();
    for (uint32_t b = 0; b < 40000u && (chain.running || chain.armed || !out_n); b++) out_block();
    out_block();
    bad += check("CLOCK OUT: a SONG's sections keep the pulses (84 x 1/16: 504), its end sends Stop",
                 out_n && out_pkt[0] == 0xFA0Fu && out_pkt[out_n - 1u] == 0xFC0Fu && out_count(0xF8u, 0) == 84u * 6u &&
                 out_count(0xFAu, 0) == 1u && out_count(0xFCu, 0) == 1u);
    if (out_count(0xF8u, 0) != 84u * 6u) printf("  song pulses %u\n", out_count(0xF8u, 0));
    usb.config = 0; chain_defaults(&chain_config); memset(proj_slot, 0, sizeof proj_slot);
    return bad;
}

int main(void)
{
    int bad = patterns_test(1) + patterns_test(2) + boundary_test() + transport_rules_test() + song_test(1) + song_test(2) +
              song_rules_test() + clock_out_test() + clock_out_ring_test() + clock_out_song_test();
    printf("%s\n", bad ? "MIDI SYNC TEST FAILED" : "MIDI sync tests passed");
    return bad != 0;
}
