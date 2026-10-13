/* SPDX-License-Identifier: GPL-3.0-only */
/* #87: exercise the actual browser adapter, not a second DSP scheduler.
 * Run partition_test.mjs for the availability/representation contract. This
 * translation unit is built both natively and as a standalone test Wasm. */
#include "felucca_web.c"

typedef char partition_cadence[(CTL == 32 && HALF_FRAMES == 128 && FS == 44100) ? 1 : -1];
#define PART_FRAMES 40960u
#define PART_MAX_EVENTS 128u
static float part_pcm[PART_FRAMES * 2u];
static uint32_t part_state[4096], part_nstate;
static uint32_t part_observations[PART_MAX_EVENTS * 4u], part_nobservations;
/* Four checkpoints: pedal-held note, released note, stopped, restarted. */
static uint32_t part_checks[4u * 8u];
static uint32_t part_error;
typedef char partition_state_capacity[(8u + NTRK * (7u + 16u + P_COUNT + 4u + 4u * NVOICE) +
                                      16u * (9u + NTRK + 128u) <= 4096u) ? 1 : -1];
typedef struct { uint32_t frame, status, d1, d2, tag; } part_event_t;
static part_event_t part_events[PART_MAX_EVENTS];
static uint32_t part_nevents;
enum { PART_MIDI, PART_BUTTON = 1, PART_DROP_ON = 2, PART_PEDAL_DOWN = 3,
       PART_NOTE_OFF = 4, PART_PEDAL_UP = 5 };
enum { PART_REF, PART_MISSING_ON, PART_REORDER, PART_MISSING_UP, PART_LATE_ON, PART_NO_REPEATS };

static void part_add(uint32_t frame, uint32_t status, uint32_t d1, uint32_t d2, uint32_t tag)
{
    if (part_nevents == PART_MAX_EVENTS) { part_error++; return; }
    part_events[part_nevents++] = (part_event_t){frame, status, d1, d2, tag};
}
static void part_schedule(uint32_t seed, uint32_t variant)
{
    uint32_t i, j, r = seed ? seed : 1u;
    part_add(31, 0x90, 60, 100, PART_MIDI);
    part_add(32, 0x90, 64, 90, PART_MIDI);
    part_add(33, 0x90, 67, 80, PART_MIDI);
    part_add(127, 0xE0, 127, 127, PART_MIDI);
    part_add(128, 0xB0, 1, 87, PART_MIDI);
    part_add(129, 0xE0, 0, 64, PART_MIDI);
    if (variant != PART_NO_REPEATS) {
        part_add(512, 0xB0, 1, 87, PART_MIDI);   /* unchanged controller value */
        part_add(513, 0xB0, 1, 87, PART_MIDI);
    }
    part_add(1024, 0x80, 64, 0, PART_MIDI);
    part_add(1024, 0x80, 67, 0, PART_MIDI);
    if (variant == PART_REORDER) {
        part_add(2048, 0x80, 60, 0, PART_NOTE_OFF);
        part_add(2048, 0xB0, 64, 127, PART_PEDAL_DOWN);
    } else {
        part_add(2048, 0xB0, 64, 127, PART_PEDAL_DOWN);
        part_add(2048, 0x80, 60, 0, PART_NOTE_OFF);
    }
    part_add(2048, 0xB0, 11, 100, PART_MIDI);
    part_add(2048, 0xB0, 7, 90, PART_MIDI);
    part_add(4096, 1u << B_PLAY, 0, 0, PART_BUTTON);
    part_add(7168, 0, 0, 0, PART_BUTTON);          /* held >24 ms, as the worklet */
    if (variant != PART_MISSING_UP) part_add(8192, 0xB0, 64, 0, PART_PEDAL_UP);
    part_add(24576, 1u << B_PLAY, 0, 0, PART_BUTTON);
    part_add(27648, 0, 0, 0, PART_BUTTON);
    part_add(32768, 1u << B_PLAY, 0, 0, PART_BUTTON);
    part_add(35840, 0, 0, 0, PART_BUTTON);
    if (variant != PART_MISSING_ON)
        part_add(variant == PART_LATE_ON ? 38912 : 38400, 0x90, 72, 100, PART_DROP_ON);
    /* Stable seeded controller schedule; it uses no sample assets or wall time. */
    for (i = 0; i < 24u; i++) {
        r ^= r << 13; r ^= r >> 17; r ^= r << 5;
        part_add(14000u + (r % 9000u), 0xB0, i & 1u ? 1u : 11u, (r >> 16) & 127u, PART_MIDI);
    }
    for (i = 1; i < part_nevents; i++) {
        part_event_t e = part_events[i]; j = i;
        while (j && part_events[j - 1].frame > e.frame) { part_events[j] = part_events[j - 1]; j--; }
        part_events[j] = e;                       /* equal timestamps retain file order */
    }
}

static uint32_t part_gate(uint32_t note)
{
    uint32_t i, n = 0;
    for (i = 0; i < NVOICE; i++)
        n += trk[0].v[i].active && trk[0].v[i].gate && trk[0].v[i].note == note;
    return n;
}
static void part_checkpoint(uint32_t index)
{
    uint32_t *p = part_checks + 8u * index;
    p[0] = midi_ch[0].pedal; p[1] = midi_notes[0][60]; p[2] = midi_notes[0][72];
    p[3] = part_gate(60); p[4] = part_gate(72); p[5] = song.playing;
    p[6] = midi_owners[0]; p[7] = mi_w - mi_r;
}
static void part_put(uint32_t v) { part_state[part_nstate++] = v; }
static void part_snapshot(void)
{
    uint32_t t, i;
    part_put(ring_r); part_put(ring_w); part_put(web_samples_due); part_put(fm1_ms);
    part_put(song.playing); part_put(song.tick); part_put(mi_w - mi_r); part_put(midi_in_overflow);
    for (t = 0; t < NTRK; t++) {
        const track_t *p = &trk[t];
        part_put(midi_owners[t]); part_put(midi_bend_q8[t]); part_put(midi_bend_target[t]);
        part_put(p->mw); part_put(p->ex_off); part_put(p->at); part_put(p->nheld);
        for (i = 0; i < p->nheld; i++) part_put(p->held[i]);
        for (i = 0; i < P_COUNT; i++) part_put(p->p[i]);
        part_put(p->seq_pos); part_put(p->seq_idx); part_put(p->seq_n); part_put(p->seq_off);
        for (i = 0; i < NVOICE; i++) {
            part_put(p->v[i].active); part_put(p->v[i].gate); part_put(p->v[i].note); part_put(p->v[i].stage);
        }
    }
    for (t = 0; t < 16u; t++) {
        const midi_channel_t *c = &midi_ch[t];
        part_put(c->bend); part_put(c->wheel); part_put(c->pedal); part_put(c->targets);
        part_put(c->ready); part_put(c->semis); part_put(c->cents); part_put(c->rpn_msb); part_put(c->rpn_lsb);
        for (i = 0; i < NTRK; i++) part_put(c->owned[i]);
        for (i = 0; i < 128u; i++) part_put(midi_notes[t][i]);
    }
}

/* Drain arbitrary outer lengths through web_render; it alone drives web_ms
 * and the real 128-frame DMA ISR, whose DSP calls remain exactly CTL=32. */
EXPORT uint32_t web_partition_run(uint32_t seed, uint32_t partition, uint32_t variant)
{
    static const uint32_t sizes[6] = {1, 23, 37, 257, 19, 512};
    static const uint32_t checkpoints[4] = {4096, 12288, 28672, PART_FRAMES};
    uint32_t frame = 0, pi = 0, ei = 0, ci = 0, i;
    rng_state = seed ? seed : 1u;
    web_nor_erase(); web_boot();
    /* Splash complete, audio ring empty, same seed/presets in each fresh runtime. */
    for (i = 0; i < 172u; i++) web_render(128);
    song.g[G_CLOCK] = 0; song.g[G_ROUTE] = 0; song.sel = 0;
    host_preset(&trk[0], 0, 1);                 /* ANALOG POLY, no sample dependency */
    trk[0].p[P_ATK] = 0; trk[0].p[P_SUS] = 127; trk[0].p[P_REL] = 20;
    host_preset(&trk[2], 0, 5);
    for (i = 0; i < 16u; i++) {
        uint8_t n = (uint8_t)(48u + i % 5u);
        put_step(&trk[2], i, 1, &n, ST_NOTE, 0);
    }
    part_schedule(seed, variant);
    while (frame < PART_FRAMES) {
        uint32_t end = ei < part_nevents ? part_events[ei].frame : PART_FRAMES;
        if (ci < 4u && checkpoints[ci] < end) end = checkpoints[ci];
        while (frame < end) {
            uint32_t n = partition == 0u ? 1024u : partition == 1u ? sizes[pi++ % 6u] : 128u;
            if (n > end - frame) n = end - frame;
            web_render(n);
            for (i = 0; i < n; i++) {
                part_pcm[2u * (frame + i)] = out_l[i];
                part_pcm[2u * (frame + i) + 1u] = out_r[i];
            }
            frame += n;
        }
        if (ci < 4u && checkpoints[ci] == frame) part_checkpoint(ci++);
        while (ei < part_nevents && part_events[ei].frame == frame) {
            const part_event_t *e = &part_events[ei++];
            part_observations[part_nobservations++] = frame;
            part_observations[part_nobservations++] = ring_w;
            part_observations[part_nobservations++] = ring_r;
            part_observations[part_nobservations++] = fm1_ms;
            if (e->tag == PART_BUTTON) web_buttons(e->status);
            else if (!web_midi(e->status, e->d1, e->d2)) part_error++;
        }
    }
    part_snapshot();
    return part_error;
}
EXPORT float *web_partition_pcm(void) { return part_pcm; }
EXPORT uint32_t web_partition_frames(void) { return PART_FRAMES; }
EXPORT uint32_t *web_partition_state(void) { return part_state; }
EXPORT uint32_t web_partition_nstate(void) { return part_nstate; }
EXPORT uint32_t *web_partition_observations(void) { return part_observations; }
EXPORT uint32_t web_partition_nobservations(void) { return part_nobservations; }
EXPORT uint32_t *web_partition_checks(void) { return part_checks; }

#ifndef __EMSCRIPTEN__
int main(int argc, char **argv)
{
    uint32_t header[4], seed, partition, variant;
    if (argc != 4) return 2;
    seed = (uint32_t)strtoul(argv[1], 0, 0); partition = (uint32_t)strtoul(argv[2], 0, 0);
    variant = (uint32_t)strtoul(argv[3], 0, 0);
    if (partition > 2u || variant > PART_NO_REPEATS || web_partition_run(seed, partition, variant)) return 2;
    header[0] = 0x87321280u; header[1] = PART_FRAMES; header[2] = part_nstate; header[3] = part_nobservations;
    if (fwrite(header, sizeof header, 1, stdout) != 1 ||
        fwrite(part_pcm, sizeof part_pcm, 1, stdout) != 1 ||
        fwrite(part_state, sizeof(uint32_t), part_nstate, stdout) != part_nstate ||
        fwrite(part_observations, sizeof(uint32_t), part_nobservations, stdout) != part_nobservations ||
        fwrite(part_checks, sizeof part_checks, 1, stdout) != 1) return 2;
    return fflush(stdout) == 0 ? 0 : 2;
}
#endif
