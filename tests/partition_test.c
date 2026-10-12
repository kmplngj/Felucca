/* SPDX-License-Identifier: GPL-3.0-only
 * MIDI transport partition invariance (#87, host part): one fixed event schedule rendered through the real
 * queues and parsers with a large outer partition and with irregular small ones must give the same PCM and the
 * same final state.
 *
 * Event-availability contract (what "the same" means):
 *   - The audio code consumes MIDI only at a CTL (32 sample) block start: mix_block -> events_block drains the
 *     ring. An event stamped at sample t is therefore available at logical boundary ceil(t / CTL): t = 32k-1 and
 *     t = 32k both land on block k, t = 32k+1 on block k+1. Events of one boundary keep their schedule order.
 *     fm1_ms (the stamp the external clock reads) is a function of the block index only.
 *   - Partitioning changes how the work is cut, never at which boundary an event becomes visible:
 *       render spans   blocks rendered per call into a span buffer (DMA-half-like): A 128 blocks (4096 samples),
 *                      B 1/23/37/257/19/512 blocks cycling. mix_block always gets exactly CTL samples, so a
 *                      span is a whole number of blocks; DSP is never called with an arbitrary length.
 *       USB (EP1)      events per ep1_take() packet (1..16 events, back-pressure checked): A 16, B 1/3/2/16/5/7.
 *       TRS (UART1)    bytes per uart_midi_take() (the 128-byte DMA ring bounds a take): A the whole batch,
 *                      B 1/23/37/19/1/5 bytes, so messages are split across takes; running status is used.
 *     The sizes 257 and 512 of the span table are not applicable to the byte/packet adapters (ring limits).
 *   - Out of scope: real arrival jitter. Real USB/TRS events arrive at any sample, may straddle a boundary
 *     between two bytes, and land in whichever block drains them; this test models the host side only
 *     (everything an adapter has accepted before a boundary is visible at it), not the wire timing.
 *   - Scenarios: USB (clock from USB), TRS (clock from TRS), MIX (clock and channel 1 over USB, channels 2..4 over TRS).
 *
 * Schedule: fixed table plus 40 extra controller events from a seeded xorshift32 (seeds 0x87 and three more).
 * Every render runs in a fork()ed child of a process that never touched the DSP (as regress.c), so both
 * partitions start from the identical state. Failure output names the scenario, seed and partition and the first
 * differing sample; reproduce with the printed seed: build/host/partition_test <seed> (decimal or 0x..).
 * Negative self-checks mutate the schedule (dropped note-on, reordered pedal/note-off pair, dropped pedal-up) and
 * require a different PCM hash, so a comparison that cannot see such errors fails here.
 * Not covered here: the browser emulator's transport (web/emu), which has its own harness. */
#define UI_TEST_NO_MAIN 1
#include "ui_test.c"
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

#define NB 800u                                   /* blocks rendered: 25600 samples, 0.58 s */
#define MAXEV 512u
enum { V_REF, V_DROP_ON, V_SWAP, V_DROP_PEDUP, NVAR };
enum { TAG_NONE, TAG_LATE_ON, TAG_PEDAL_DN, TAG_OFF60, TAG_PEDAL_UP };
enum { SC_USB, SC_TRS, SC_MIX, NSC };

typedef struct { uint32_t t, bnd; uint8_t st, d1, d2, src, tag; } ev_t;
static ev_t sched[MAXEV];
static uint32_t nev;

static uint32_t rng_state;
static uint32_t rnd(void) { rng_state ^= rng_state << 13; rng_state ^= rng_state >> 17; rng_state ^= rng_state << 5; return rng_state; }

static void add(uint32_t t, uint32_t st, uint32_t d1, uint32_t d2, uint32_t tag)
{
    if (nev < MAXEV) sched[nev++] = (ev_t){t, (t + CTL - 1u) / CTL, (uint8_t)st, (uint8_t)d1, (uint8_t)d2, 0, (uint8_t)tag};
}
#define AT(k, d) ((k) * CTL + (uint32_t)(d))          /* sample (k blocks) + d, d = -1 / 0 / +1 around a boundary */

static void build(uint32_t variant, uint32_t scen, uint32_t seed)
{
    uint32_t i, k, j;
    static const uint8_t vals[5] = {0, 40, 40, 90, 127};
    nev = 0; rng_state = seed ? seed : 1u;
    add(AT(2, -1), 0xFA, 0, 0, 0);                                      /* Start */
    add(AT(10, -1), 0x90, 60, 100, 0); add(AT(10, 0), 0x90, 64, 90, 0); add(AT(10, 1), 0x90, 67, 80, 0);   /* before / on / after */
    add(AT(30, 0), 0xE0, 127, 127, 0); add(AT(31, 0), 0xE0, 127, 127, 0);       /* bend, then the same value again */
    add(AT(60, 0), 0xE0, 0, 64, 0); add(AT(60, 0), 0xE0, 0, 64, 0); add(AT(61, 0), 0xE0, 0, 64, 0);
    add(AT(40, 0), 0xB0, 1, 87, 0); add(AT(41, 0), 0xB0, 1, 87, 0); add(AT(42, 0), 0xB0, 1, 87, 0); add(AT(44, 0), 0xB0, 1, 20, 0);
    add(AT(45, 0), 0xB0, 11, 100, 0); add(AT(46, 0), 0xB0, 11, 100, 0); add(AT(47, 0), 0xB0, 7, 90, 0); add(AT(48, 0), 0xB0, 7, 90, 0);
    add(AT(50, 0), 0x91, 55, 100, 0); add(AT(150, 0), 0x81, 55, 0, 0);          /* channel 2 */
    add(AT(100, -1), 0x80, 64, 0, 0); add(AT(100, 0), 0x80, 67, 0, 0);
    /* several ordered events at one boundary (block 200): pedal down BEFORE the note-off holds note 60 */
    if (variant == V_SWAP) { add(AT(200, -5), 0x80, 60, 0, TAG_OFF60); add(AT(200, -4), 0xB0, 64, 127, TAG_PEDAL_DN); }
    else { add(AT(200, -5), 0xB0, 64, 127, TAG_PEDAL_DN); add(AT(200, -4), 0x80, 60, 0, TAG_OFF60); }
    add(AT(200, -3), 0x91, 57, 100, 0); add(AT(200, -2), 0xB0, 1, 64, 0); add(AT(200, -1), 0xE0, 0, 80, 0);
    add(AT(200, 0), 0x81, 57, 0, 0);
    if (variant != V_DROP_PEDUP) add(AT(300, 0), 0xB0, 64, 0, TAG_PEDAL_UP);    /* the sustain release */
    add(AT(320, 0), 0x93, 36, 100, 0); add(AT(330, 0), 0x93, 38, 100, 0); add(AT(340, 0), 0x93, 42, 90, 0);
    add(AT(520, -1), 0xFC, 0, 0, 0); add(AT(560, 0), 0xFB, 0, 0, 0);            /* Stop, Continue */
    add(AT(640, -3), 0x90, 65, 100, 0); add(AT(640, -2), 0xFC, 0, 0, 0);        /* Start right after Stop, with notes */
    add(AT(640, -1), 0xFA, 0, 0, 0); add(AT(640, 0), 0x80, 65, 0, 0);
    if (variant != V_DROP_ON) add(AT(700, -1), 0x90, 72, 100, TAG_LATE_ON);     /* held to the end */
    for (i = 0; i < 40u; i++) {                                                 /* seeded controllers, around boundaries */
        uint32_t r = rnd(), ch = r & 1u, kind = (r >> 1) % 4u, v = vals[(r >> 8) % 5u];
        k = 5u + (r >> 12) % 775u; j = (r >> 24) % 3u;
        add(AT(k, 0) + j - 1u, kind == 3u ? 0xE0u | ch : 0xB0u | ch, kind == 0u ? 1u : kind == 1u ? 11u : kind == 2u ? 7u : v, v, 0);
    }
    for (i = 0; 7u + 918u * i < NB * CTL; i++) add(7u + 918u * i, 0xF8, 0, 0, 0);    /* 24 ppqn at ~120 BPM */
    for (i = 1; i < nev; i++) {                                                 /* stable sort by boundary */
        ev_t e = sched[i]; j = i;
        while (j && sched[j - 1].bnd > e.bnd) { sched[j] = sched[j - 1]; j--; }
        sched[j] = e;
    }
    for (i = 0; i < nev; i++) {
        uint32_t ch = sched[i].st >= 0xF8u ? 0u : sched[i].st & 15u;
        sched[i].src = scen == SC_USB ? 1u : scen == SC_TRS ? 2u : (sched[i].st < 0xF8u && ch != 0u) ? 2u : 1u;
    }
}

/* ------------------------------------------------------------ results --- */
typedef struct {
    uint64_t pcm_hash, state_hash;
    int32_t peak; uint64_t e_early, e_late;
    uint32_t ring_ok, playing, gates, late72;
    int32_t pcm[NB * 2u * CTL];
} res_t;

static uint64_t h64(uint64_t h, uint32_t v) { for (int i = 0; i < 4; i++) { h ^= (v >> (8 * i)) & 0xFFu; h *= 0x100000001B3ull; } return h; }
static uint64_t h64_mem(uint64_t h, const void *p, size_t n)
{
    const uint8_t *b = p;
    while (n--) { h ^= *b++; h *= 0x100000001B3ull; }
    return h;
}

static void state_reset(void)                    /* as midi_control_test.c */
{
    ui_power_on();
    memset(midi_ch, 0, sizeof midi_ch); memset(midi_notes, 0, sizeof midi_notes);
    memset(midi_owners, 0, sizeof midi_owners); memset(midi_bend_q8, 0, sizeof midi_bend_q8);
    memset(midi_bend_target, 0, sizeof midi_bend_target); memset(&midi_clock, 0, sizeof midi_clock);
    memset(&um, 0, sizeof um); memset(midi_in_source, 0, sizeof midi_in_source);
    mi_r = mi_w = 0; midi_in_overflow = 0; midi_beat_samples = 0;
    fm1_in.notes = kb_prev = 0; fm1_ms = 0; song.sel = 0;
    events_block(CTL);
}

/* ---------------------------------------------------------- adapters --- */
static const uint32_t SPAN_A[1] = {128}, SPAN_B[6] = {1, 23, 37, 257, 19, 512};
static const uint32_t USB_A[1] = {16}, USB_B[6] = {1, 3, 2, 16, 5, 7};
static const uint32_t TRS_A[1] = {128}, TRS_B[6] = {1, 23, 37, 19, 1, 5};
typedef struct { const uint32_t *span, *usb, *trs; uint32_t n; } part_t;
static const part_t PART_A = {SPAN_A, USB_A, TRS_A, 1}, PART_B = {SPAN_B, USB_B, TRS_B, 6};
static uint32_t usb_i, trs_i, bad_adapter;

/* the events of one boundary that arrive over USB: one 4-byte packet each, ep1_take() with `chunk` events at a time */
static void feed_usb(const ev_t *e, uint32_t n, const part_t *p)
{
    uint8_t buf[64]; uint32_t i = 0;
    while (i < n) {
        uint32_t m = p->usb[usb_i++ % p->n], k;
        if (m > n - i) m = n - i;
        for (k = 0; k < m; k++, i++) {
            uint32_t pk = e[i].st >= 0xF8u ? (0xFu | (uint32_t)e[i].st << 8) :
                          ((uint32_t)e[i].st >> 4) | (uint32_t)e[i].st << 8 | (uint32_t)e[i].d1 << 16 | (uint32_t)e[i].d2 << 24;
            memcpy(buf + 4u * k, &pk, 4);                           /* (little-endian host, as usb.c reads it) */
        }
        if (!ep1_take(buf, 4u * m)) bad_adapter++;                  /* back-pressure must not hit this schedule */
    }
}
/* TRS: the same events as MIDI bytes with running status, taken from the UART ring `chunk` bytes at a time */
static void feed_trs(const ev_t *e, uint32_t n, const part_t *p)
{
    uint8_t bytes[128]; uint32_t nb = 0, i, run = 0, pos = 0;
    for (i = 0; i < n; i++) {
        if (e[i].st >= 0xF8u) { bytes[nb++] = e[i].st; continue; }                 /* realtime keeps running status */
        if (e[i].st != run) { bytes[nb++] = e[i].st; run = e[i].st; }
        bytes[nb++] = e[i].d1;
        if ((e[i].st & 0xE0u) != 0xC0u) bytes[nb++] = e[i].d2;
    }
    while (pos < nb) {
        uint32_t m = p->trs[trs_i++ % p->n], k;
        if (m > nb - pos) m = nb - pos;
        for (k = 0; k < m; k++) um_ring[(um.rd + um.pend + k) & (UM_RING - 1u)] = bytes[pos + k];
        uart_midi_take(m); pos += m;
    }
}

/* ----------------------------------------------------------- the render --- */
static void render(res_t *r, uint32_t scen, uint32_t variant, uint32_t seed, const part_t *p)
{
    static int32_t span[512u * 2u * CTL];
    uint32_t b = 0, si = 0, ev = 0, i, t, v;
    uint64_t h = 0xCBF29CE484222325ull;
    state_reset();
    song.master_q12 = 4096;                                  /* (as host_tracks_init: ui_power_on leaves MASTER at 0) */
    song.g[G_CLOCK] = (int16_t)(scen == SC_TRS ? 2 : 1);
    trk[2].p[P_SLEN] = 16; trk[2].p[P_SDIV] = 2;
    for (i = 0; i < 16u; i++) trk[2].step[i] = (step_t){{(uint8_t)(48 + 3 * i)}, 1, ST_NOTE, 0, 100};
    events_block(CTL);
    build(variant, scen, seed);
    while (b < NB) {
        uint32_t nbk = p->span[si++ % p->n], k;
        if (nbk > NB - b) nbk = NB - b;
        for (k = 0; k < nbk; k++, b++) {                     /* one CTL block: events due at this boundary, then the render */
            uint32_t first = ev, usbn = 0, trsn = 0;
            ev_t u[64], tr[64];
            fm1_ms = (uint32_t)((uint64_t)b * CTL * 1000u / FS);
            while (ev < nev && sched[ev].bnd <= b) ev++;
            /* the batch keeps its order; each adapter gets its own events in order (USB then TRS: the adapters
             * are separate producers, they cannot interleave inside one boundary on the host) */
            for (i = first; i < ev; i++) {
                if (sched[i].src == 1u) u[usbn++] = sched[i]; else tr[trsn++] = sched[i];
            }
            if (usbn) feed_usb(u, usbn, p);
            if (trsn) feed_trs(tr, trsn, p);
            mix_block(span + 2u * CTL * k, CTL);
        }
        memcpy(r->pcm + 2u * CTL * (b - nbk), span, sizeof(int32_t) * 2u * CTL * nbk);
    }
    for (i = 0; i < NB * 2u * CTL; i++) {
        int32_t s = r->pcm[i], a = s < 0 ? -s : s;
        if (a > r->peak) r->peak = a;
        if (i / (2u * CTL) >= 2u && i / (2u * CTL) < 200u) r->e_early += (uint64_t)((int64_t)s * s);
        if (i / (2u * CTL) >= NB - 100u) r->e_late += (uint64_t)((int64_t)s * s);
        h = h64(h, (uint32_t)s);
    }
    r->pcm_hash = h;
    h = 0xCBF29CE484222325ull;
    for (t = 0; t < NTRK; t++) {
        const track_t *tk = &trk[t];
        h = h64(h, tk->nheld); h = h64(h, (uint32_t)tk->mw); h = h64(h, (uint32_t)tk->ex_off); h = h64(h, (uint32_t)tk->at);
        h = h64(h, (uint32_t)tk->p[P_LEVEL]); h = h64(h, tk->seq_idx); h = h64(h, tk->seq_pos); h = h64(h, tk->seq_n);
        h = h64(h, (uint32_t)midi_bend_q8[t]); h = h64(h, (uint32_t)midi_bend_target[t]); h = h64(h, midi_owners[t]);
        for (v = 0; v < NVOICE; v++) {
            h = h64(h, tk->v[v].active); h = h64(h, tk->v[v].gate); h = h64(h, tk->v[v].note); h = h64(h, tk->v[v].stage);
            r->gates += tk->v[v].active && tk->v[v].gate;
            r->late72 |= tk->v[v].active && tk->v[v].gate && tk->v[v].note == 72u;   /* the late note-on, held to the end */
        }
    }
    h = h64_mem(h, midi_notes, sizeof midi_notes); h = h64_mem(h, midi_ch, sizeof midi_ch);
    h = h64_mem(h, &midi_clock, sizeof midi_clock);
    h = h64(h, song.playing); h = h64(h, (uint32_t)song.tick);
    r->state_hash = h;
    r->playing = song.playing;
    r->ring_ok = mi_r == mi_w && !midi_in_overflow && !um.drops && !um.pend && !bad_adapter;
}

static res_t *run_child(uint32_t scen, uint32_t variant, uint32_t seed, const part_t *p)
{
    res_t *r = mmap(0, sizeof *r, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    pid_t pid = fork();
    if (pid == 0) { render(r, scen, variant, seed, p); _exit(0); }
    int st = 0; waitpid(pid, &st, 0);
    if (!WIFEXITED(st) || WEXITSTATUS(st)) { printf("partition: render child failed (status %d)\n", st); r->ring_ok = 0; r->peak = -1; }
    return r;
}

static const char *const SCN[NSC] = {"USB", "TRS", "MIX"};
int main(int argc, char **argv)
{
    static const uint32_t seeds[4] = {0x87u, 1u, 2u, 3u};
    uint32_t sd, sc, v, nseed = 4, only = 0; int bad = 0;
    if (argc > 1) { only = (uint32_t)strtoul(argv[1], 0, 0); nseed = 1; }
    for (sd = 0; sd < nseed; sd++) {
        uint32_t seed = only ? only : seeds[sd];
        for (sc = 0; sc < NSC; sc++) {
            res_t *a = run_child(sc, V_REF, seed, &PART_A), *b = run_child(sc, V_REF, seed, &PART_B);
            char what[160]; uint32_t i, first = ~0u;
            for (i = 0; i < NB * 2u * CTL; i++) if (a->pcm[i] != b->pcm[i]) { first = i; break; }
            snprintf(what, sizeof what, "%s seed 0x%x: PCM identical, 4096-sample spans vs 1/23/37/257/19/512 blocks (hash %016llx)", SCN[sc], seed, (unsigned long long)a->pcm_hash);
            bad += check(what, first == ~0u && a->pcm_hash == b->pcm_hash);
            if (first != ~0u) printf("    first difference: sample %u (block %u, frame %u), A=%d B=%d; reproduce: partition_test 0x%x\n", first, first / (2u * CTL), first / 2u, a->pcm[first], b->pcm[first], seed);
            snprintf(what, sizeof what, "%s seed 0x%x: final gates, ownership, sustain, bend, controllers, transport identical", SCN[sc], seed);
            bad += check(what, a->state_hash == b->state_hash && a->playing == b->playing && a->gates == b->gates);
            snprintf(what, sizeof what, "%s seed 0x%x: audible (peak %d), early and late energy nonzero, rings drained without drops", SCN[sc], seed, a->peak);
            bad += check(what, a->peak > 500 && a->e_early > 0 && a->e_late > 0 && a->ring_ok && b->ring_ok && b->peak > 500);
            bad += check("  transport running and the late note still held at the end", a->playing && a->late72 && b->late72);
            if (sd == 0) {                                     /* negative self-checks: the comparison must see these */
                static const char *const VN[NVAR] = {"", "dropped note-on", "reordered pedal-down / note-off", "dropped pedal-up (note kept after release)"};
                for (v = V_DROP_ON; v < NVAR; v++) {
                    res_t *m = run_child(sc, v, seed, &PART_A);
                    snprintf(what, sizeof what, "  negative: %s %s changes the PCM hash", SCN[sc], VN[v]);
                    bad += check(what, m->ring_ok && m->peak > 500 && m->pcm_hash != a->pcm_hash);
                    if (v == V_DROP_PEDUP) bad += check("  negative: the retained note shows in the final state", m->state_hash != a->state_hash);
                    munmap(m, sizeof *m);
                }
            }
            munmap(a, sizeof *a); munmap(b, sizeof *b);
        }
    }
    printf("%s\n", bad ? "MIDI PARTITION INVARIANCE TEST FAILED" : "MIDI partition invariance tests passed"); return bad != 0;
}
