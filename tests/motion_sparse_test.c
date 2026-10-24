/* SPDX-License-Identifier: GPL-3.0-only */
/* Real source differential driver. Observation adapters exist only in build/. */
#define UI_TEST_NO_MAIN 1
#include MOTION_TEST_UI
_Static_assert(P_COUNT == 111u && MOTION_MAX == 128u, "review pinned sparse-mask boundary fixtures");

static FILE *sparse_pcm, *sparse_trace, *sparse_state;
static uint32_t sparse_case, sparse_time, sparse_records, sparse_pcm_words, sparse_snapshots;
static uint32_t sparse_writes[6], sparse_words[8192], sparse_nwords;
static void sparse_need(int ok, const char *why)
{
    if (!ok) { fprintf(stderr, "SPARSE oracle: %s (case=%u time=%u)\n", why, sparse_case, sparse_time); exit(1); }
}
static void sparse_event(uint32_t kind, track_t *t, uint32_t id, int32_t value)
{
    uint32_t record[8] = {sparse_case, sparse_time, kind, trk_index(t), id, (uint32_t)value, t->seq_idx, t->seq_pos};
    if (!sparse_trace) return;                 /* ordinary fixture initialization precedes observation */
    sparse_need(fwrite(record, sizeof record, 1, sparse_trace) == 1, "write ordered event");
    sparse_records++; sparse_writes[kind]++;
}
static int16_t sparse_write(uint32_t kind, track_t *t, uint32_t id, int16_t value)
{
    sparse_need(id < P_COUNT, "unused tail bit reached parameter write");
    sparse_event(kind, t, id, value);
    return value;
}
static void sparse_note(uint32_t kind, track_t *t, uint32_t note, uint32_t velocity)
{
    sparse_event(kind, t, note, (int32_t)velocity);
}
static void sparse_put(uint32_t v)
{
    sparse_need(sparse_nwords < NELEM(sparse_words), "bounded state snapshot");
    sparse_words[sparse_nwords++] = v;
}
static void sparse_store(const motion_store_t *m)
{
    sparse_put(m->count); sparse_put(m->on);
    for (uint32_t i = 0; i < m->count; i++) {
        sparse_put(m->event[i].place); sparse_put(m->event[i].param); sparse_put((uint32_t)(int32_t)m->event[i].value);
    }
}
static void sparse_snapshot(uint32_t boundary)
{
    sparse_nwords = 0;
    sparse_put(sparse_case); sparse_put(sparse_time); sparse_put(boundary);
    sparse_put(motion_base_valid); sparse_put(rng_state); sparse_put(vage);
    sparse_put(song.playing); sparse_put(song.tick); sparse_put(song.rec); sparse_put(transport_req);
    sparse_put(chain.running); sparse_put(chain.armed); sparse_put(chain.row); sparse_put(chain.remaining);
    sparse_put(chain.clk); sparse_put(chain.carry);
    sparse_put(midi_clock.pos); sparse_put(midi_clock.rendered); sparse_put(midi_clock.last_ms);
    for (uint32_t k = 0; k < NTRK; k++) {
        const track_t *t = &trk[k];
        for (uint32_t id = 0; id < P_COUNT; id++) sparse_put((uint32_t)(int32_t)t->p[id]);
        for (uint32_t id = 0; id < P_COUNT; id++) sparse_put((uint32_t)(int32_t)motion_base[k][id]);
        for (uint32_t w = 0; w < (P_COUNT + 31u) / 32u; w++) {
            sparse_put(motion_active[k][w]); sparse_put(motion_locked[k][w]);
        }
        sparse_put(t->seq_pos); sparse_put(t->seq_idx); sparse_put(t->seq_n); sparse_put(t->seq_off);
        sparse_put(t->seq_hold); sparse_put(t->slide_glide); sparse_put(t->rat_left); sparse_put(t->seq_active);
        for (uint32_t i = 0; i < NELEM(t->seq_notes); i++) sparse_put(t->seq_notes[i]);
        sparse_put(t->rskip_idx); sparse_put(t->rskip_n);
        for (uint32_t i = 0; i < NELEM(t->rskip); i++) sparse_put(t->rskip[i]);
        sparse_put(t->nd_late); sparse_put(t->nd_early); sparse_put(t->nd_fired); sparse_put(t->cond_loop);
        sparse_put(t->rh_n); sparse_put(t->rh_start); sparse_put(t->rh_ties); sparse_put(t->rh_last);
        for (uint32_t i = 0; i < NELEM(t->rh_note); i++) sparse_put(t->rh_note[i]);
        sparse_put(t->arp_pos); sparse_put(t->arp_idx); sparse_put(t->arp_off); sparse_put(t->arp_note);
        sparse_put(t->nheld); sparse_put(t->mono_note); sparse_put(t->rr);
        sparse_put(t->eng_req); sparse_put(t->xf_on); sparse_put(t->xf);
        sparse_put(chain.lane[k]); sparse_put(midi_seq_grid[k].remainder);
        for (uint32_t i = 0; i < NVOICE; i++) {
            sparse_put(t->v[i].active); sparse_put(t->v[i].gate); sparse_put(t->v[i].note); sparse_put(t->v[i].age);
        }
    }
    sparse_store(&motion);
    for (uint32_t s = 0; s < 4u; s++) sparse_store(&chain.source[s].motion);
    sparse_need(fwrite(&sparse_nwords, sizeof sparse_nwords, 1, sparse_state) == 1 &&
                fwrite(sparse_words, sizeof sparse_words[0], sparse_nwords, sparse_state) == sparse_nwords,
                "write explicit state (no struct padding)");
    sparse_snapshots++;
}
static void sparse_reset(uint32_t seed)
{
    ui_power_on();
    rng_state = seed; fm1_ms = 1000; sparse_time = 0;
    memset(motion_base, 0, sizeof motion_base);
    memset(&chain, 0, sizeof chain); chain_defaults(&chain_config);
    memset(&midi_clock, 0, sizeof midi_clock);
    for (uint32_t k = 0; k < NTRK; k++) {
        set_engine_of(&trk[k], 0); apply_preset_to(&trk[k], 1);
        memcpy(motion_base[k], trk[k].p, sizeof trk[k].p);
    }
}
static uint32_t sparse_bits(uint32_t pattern, uint32_t w)
{
    static const uint32_t edges[] = {0, 1, 31, 32, 63, 64, 95, 96, 110};
    uint32_t v = 0;
    if (pattern == 1u) return w == 0u ? 2u : 0u;
    if (pattern == 3u || pattern == 5u) return ~0u;
    if (pattern == 4u) return w == (P_COUNT - 1u) / 32u ? 0x80008000u : 0u;
    if (pattern == 2u)
        for (uint32_t i = 0; i < NELEM(edges); i++) if (edges[i] / 32u == w) v |= 1u << (edges[i] % 32u);
    return v;
}
static void sparse_walks(uint32_t seed)
{
    for (uint32_t k = 0; k < NTRK; k++) for (uint32_t pattern = 0; pattern < 6u; pattern++) {
        motion_store_t alternate = {0};
        sparse_reset(seed); sparse_case = 100u + k * 10u + pattern;
        motion_base_valid = (uint8_t)(1u << k);
        for (uint32_t id = 0; id < P_COUNT; id++) trk[k].p[id] ^= 1;
        for (uint32_t w = 0; w < (P_COUNT + 31u) / 32u; w++) {
            uint32_t bits = sparse_bits(pattern, w);
            if (pattern == 3u && w == (P_COUNT - 1u) / 32u) bits &= 0x7FFFu;
            motion_active[k][w] = motion_locked[k][w] = bits;
        }
        sparse_snapshot(1); motion_restore(&trk[k]); sparse_snapshot(2);
        for (uint32_t w = 0; w < (P_COUNT + 31u) / 32u; w++)
            motion_locked[k][w] = sparse_bits(pattern, w);
        alternate.count = 4; alternate.on = (uint8_t)(1u << k);
        alternate.event[0] = (motion_event_t){(uint8_t)(k << 6 | 3u), P_REV, 71};
        alternate.event[1] = (motion_event_t){(uint8_t)(k << 6 | 1u), P_REV, 15};
        alternate.event[2] = (motion_event_t){(uint8_t)(k << 6 | 2u), P_REV | MOTION_LOCK, 90};
        alternate.event[3] = (motion_event_t){(uint8_t)(k << 6 | 3u), P_E7, 9};
        sparse_snapshot(3); motion_unlock(&trk[k], 4, &alternate); sparse_snapshot(4);
    }
}
static void sparse_records_setup(uint32_t density)
{
    static const uint8_t ids[8] = {P_LEVEL, P_ATK, P_DEC, P_SUS, P_FM1_ATK, P_FM4_LEVEL, P_SPRD, P_E7};
    for (uint32_t k = 0; k < NTRK; k++) {
        track_t *t = &trk[k];
        motion_clear(t); track_defaults_steps(t);
        t->p[P_SLEN] = 4; t->p[P_SDIV] = 3; t->p[P_SSWING] = 60; t->p[P_SQNT] = (int16_t)(k & 1u);
        t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 0;
        for (uint32_t s = 0; s < 4u; s++) {
            t->step[s] = (step_t){{(uint8_t)(48 + 3u * k + s)}, 1, ST_NOTE, 0, 100};
            if (s == 1u) { step_set_chance(&t->step[s], 50); step_set_nudge(&t->step[s], 2); }
            if (s == 2u) step_set_ratchet(&t->step[s], 3);
            if (s == 3u) step_set_nudge(&t->step[s], -2);
        }
        if (!density) continue;
        uint32_t n = density == 1u ? (k ? 0u : 1u) : density == 3u ? 32u : 8u;
        for (uint32_t i = 0; i < n; i++) {
            uint32_t id = ids[i / 4u + (density == 3u ? 0u : 6u)], s = i % 4u;
            const param_desc_t *d = param_desc_of(eng_idx(t->eng_req), id);
            int16_t v = (int16_t)param_fit(d, d->min + (int32_t)(i + k + 1u) % (d->max - d->min + 1));
            sparse_need(!motion_put(t, s, id, v, i & 1u ? MOTION_LOCK : 0u), "install bounded records");
        }
    }
}
static void sparse_edits(uint32_t block)
{
    track_t *t = &trk[0];
    if (block == 40u || block == 41u) {
        song.sel = 0; song.rec = 1; t->p[P_PAN] = (int16_t)(block - 60u);
        (void)motion_capture(t, P_PAN, t->p[P_PAN]); song.rec = 0;
    } else if (block == 70u) {
        uint32_t i = (uint32_t)motion_find(t, 0, P_SPRD);
        sparse_need(i < motion.count && !motion_move(t, i, 3, P_GLIDE, 21), "same-count move");
    } else if (block == 90u || block == 91u) {
        int32_t i = motion_find(t, 3, P_GLIDE); sparse_need(i >= 0, "record for kind toggle");
        sparse_need(!motion_put(t, 3, P_GLIDE, motion.event[i].value, block == 90u ? MOTION_LOCK : 0u), "same-count kind toggle");
    } else if (block == 110u) motion_delete_event(t, 3, P_GLIDE);
    else if (block == 130u) (void)motion_clear_locks(t, NSTEP);
    else if (block == 160u) { tl_undo_take(t); tl_shift(t, 4, 1); }
    else if (block == 161u || block == 162u) undo_swap();
    else if (block == 200u) (void)tl_double(t, 4);
    else if (block == 201u) (void)tl_half(t, 8);
    else if (block == 240u) set_engine_of(t, ENGI_FM6);
    else if (block == 241u) undo_swap();
    else if (block == 280u) {
        project_t p; project_capture(&p); sparse_need(!project_restore_runtime(&p), "project/current-backup restore seam");
        seq_start();
    } else if (block == 320u) {
        motion_store_t copy; motion_snapshot_track(t, &copy);
        sparse_need(!motion_replace_track(t, &copy), "track copy/replace");
    } else if (block == 360u) motion_set_enabled(t, 0);
    else if (block == 361u) motion_set_enabled(t, 1);
    else if (block == 400u) motion_clear(&trk[3]);
}
static void sparse_play(uint32_t seed, uint32_t scenario)
{
    sparse_reset(seed); sparse_case = scenario;
    song.g[G_BPM] = 240;
    sparse_records_setup(scenario == 3u ? 3u : scenario < 3u ? scenario : 2u);
    sparse_need(scenario != 3u || motion.count == MOTION_MAX, "dense scenario fills the complete record pool");
    if (scenario == 4u) {
        for (uint32_t s = 0; s < 4u; s++) {
            sparse_need(!motion_set_event(&trk[0], 0, P_PAN, (int16_t)(10u * s)), "song same-count source value");
            project_save(s);
        }
        chain_config.count = 4;
        for (uint32_t r = 0; r < 4u; r++) {
            chain_config.row[r].repeat = 1;
            for (uint32_t k = 0; k < NTRK; k++) chain_config.row[r].slot[k] = (uint8_t)((r + k) % 4u);
        }
        chain_config.row[2].slot[2] = CHAIN_SILENT;
        sparse_need(!chain_prepare(), "prepare all four const playback stores");
    }
    if (scenario == 6u) song.g[G_CLOCK] = 1;
    transport_req = 1; sparse_snapshot(10);
    for (uint32_t block = 0; block < 512u; block++) {
        int32_t pcm[CTL * 2u];
        sparse_time = block * CTL; fm1_ms = 1000u + sparse_time * 1000u / FS;
        if (scenario == 5u) sparse_edits(block);
        if (scenario == 6u && !(block % 14u)) midi_clock_pulse(fm1_ms);
        if (block == 440u) seq_stop();
        if (block == 448u) {
            if (scenario == 6u) midi_clock_transport(0xFBu, fm1_ms); else seq_start();
        }
        if (block == 470u) {
            if (scenario == 6u) midi_clock_transport(0xFAu, fm1_ms); else { seq_stop(); seq_start(); }
        }
        mix_block(pcm, CTL);
        sparse_need(fwrite(pcm, sizeof pcm, 1, sparse_pcm) == 1, "write every PCM word");
        sparse_pcm_words += NELEM(pcm); sparse_snapshot(11);
    }
    seq_stop(); sparse_snapshot(12);
}
static FILE *sparse_open(const char *prefix, const char *suffix)
{
    char path[1024];
    sparse_need(snprintf(path, sizeof path, "%s.%s", prefix, suffix) < (int)sizeof path, "bounded output path");
    FILE *f = fopen(path, "wb"); sparse_need(f != 0, "open output"); return f;
}
int main(int argc, char **argv)
{
    if (argc < 3 || argc > 4) return 2;
    uint32_t seed = (uint32_t)strtoul(argv[2], 0, 0);
    int walks_only = argc == 4 && !strcmp(argv[3], "--walks-only");
    if (argc == 4 && !walks_only) return 2;
    sparse_pcm = sparse_open(argv[1], "pcm"); sparse_trace = sparse_open(argv[1], "events"); sparse_state = sparse_open(argv[1], "state");
    sparse_walks(seed);
    if (!walks_only) for (uint32_t scenario = 0; scenario < 7u; scenario++) sparse_play(seed, scenario);
    sparse_need(sparse_writes[1] && sparse_writes[2], "both changed functions observed");
    if (!walks_only) sparse_need(sparse_writes[3] && sparse_writes[4] && sparse_writes[5] && sparse_pcm_words, "actual motion/note/PCM coverage");
    sparse_need(!fclose(sparse_pcm) && !fclose(sparse_trace) && !fclose(sparse_state), "close outputs");
    printf("{\"pcm_words\":%u,\"events\":%u,\"snapshots\":%u,\"restore\":%u,\"unlock\":%u,\"step\":%u,\"on\":%u,\"off\":%u}\n",
           sparse_pcm_words, sparse_records, sparse_snapshots, sparse_writes[1], sparse_writes[2], sparse_writes[3], sparse_writes[4], sparse_writes[5]);
    return 0;
}
