/* SPDX-License-Identifier: GPL-3.0-only */
/* MIDI sync (#281): Song Position Pointer then Continue, through the real USB/TRS queues, external clock, sequencer
 * and SONG. A located run must match a reference run that played from Start to the same position: every track's
 * step, its samples into it and its loop count, the SONG's section and repeat, then the same steps afterwards. */
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

int main(void)
{
    int bad = patterns_test(1) + patterns_test(2) + boundary_test() + transport_rules_test() + song_test(1) + song_test(2) +
              song_rules_test();
    printf("%s\n", bad ? "MIDI SYNC TEST FAILED" : "MIDI sync tests passed");
    return bad != 0;
}
