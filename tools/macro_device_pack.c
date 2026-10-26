/* SPDX-License-Identifier: GPL-3.0-only */
/* Offline fixture producer: compile the actual firmware serializer, project load,
 * sequencer and sound install against the existing host HAL. Never opens a device. */
#define UI_TEST_NO_MAIN 1
#include "../tests/ui_harness.h"
#include <assert.h>

static const char *const pack_files[] = {"A-legacy-poly", "B-bank-heavy", "C-mixed", "D-song"};
static const char *const pack_names[] = {"MAC LEGACY", "MAC HEAVY", "MAC MIXED", "MAC SONG"};
static const uint8_t pack_engines[4][NTRK] = {
    {14, 14, 14, 14}, {14, 14, 14, 14}, {14, 9, 12, 0}, {14, 14, 14, 14}
};
static const uint8_t pack_models[4][NTRK] = {
    {0, 1, 2, 0}, {26, 26, 26, 26}, {29, 0, 0, 0}, {0, 26, 29, 38}
};
static const chain_row_t pack_rows[] = {
    {{0, 0, 0, 0}, 8}, {{1, 2, 0, 1}, 8}, {{2, 0, 1, 2}, 8},
    {{1, 1, 1, 1}, 8}, {{CHAIN_SILENT, CHAIN_SILENT, CHAIN_SILENT, CHAIN_SILENT}, 1}
};

static void pack_setup(uint32_t slot)
{
    uint32_t k, i, j;
    chain_defaults(&chain_config);
    song.g[G_BPM] = 120;
    song.g[G_ROUTE] = 0;                         /* CH1-4 */
    song.g[G_CLOCK] = 0;                         /* internal, no clock traffic in the MIDI file */
    song.g[G_RTYPE] = 0;                         /* ROOM */
    song.sel = 0;
    for (k = 0; k < NTRK; k++) {
        track_t *t = &trk[k];
        uint32_t e = pack_engines[slot][k], model = pack_models[slot][k];
        uint32_t preset = e == 14u ? (model < 3u ? model * 2u : model + 3u) : 0u;
        track_defaults(t);
        host_preset(t, e, preset);
        track_defaults_steps(t);
        t->p[P_LEVEL] = 64;
        t->p[P_ATK] = 0; t->p[P_DEC] = 0; t->p[P_SUS] = 100; t->p[P_REL] = 25;
        t->p[P_VOICE] = V_POLY;
        t->p[P_ED_FLT] = 0;
        t->p[P_CHOR] = 20; t->p[P_DLY] = 20; t->p[P_REV] = 35;
        t->p[P_SLEN] = 16; t->p[P_SDIV] = 2; t->p[P_SSWING] = 0;
        t->p[P_SGATE] = 80; t->p[P_SQNT] = 1;
        t->p[P_AMODE] = 0;
        if (e == 14u) {
            const int16_t values[8] = {(int16_t)model, 64, 64, 0, 110, 8, 127, 0};
            memcpy(&t->p[P_E0], values, sizeof values);
        }
        /* A four-note strike / tie / rest per four steps; B one struck note
         * per step; C two-note strikes every other step. No chance or RNG. */
        for (i = 0; i < 16u; i++) {
            step_t *s = &t->step[i];
            uint32_t notes = slot == 0u ? 4u : slot == 2u ? 2u : 1u;
            if ((slot == 0u && i % 4u == 3u) || (slot == 2u && i % 2u)) continue;
            if (slot == 0u && i % 4u == 1u) { s->time = ST_TIE; continue; }
            s->time = ST_NOTE; s->n = (uint8_t)notes; s->vel = 100;
            for (j = 0; j < notes; j++)
                s->note[j] = (uint8_t)(48u + 3u * k + 2u * slot + (i / 4u) % 4u + 4u * j);
        }
    }
    if (slot == 3u) {
        chain_config.count = NELEM(pack_rows);
        memcpy(chain_config.row, pack_rows, sizeof pack_rows);
    }
}

static void pack_write(const char *dir, uint32_t slot)
{
    char path[4096];
    project_t decoded;
    project_store_t again;
    assert(!project_save_as(slot, pack_names[slot]));
    assert(proj_import(&decoded, &proj_slot[slot], sizeof proj_slot[slot]));
    assert(proj_pack(&again, &decoded));
    assert(!memcmp(&again, &proj_slot[slot], sizeof again));
    assert(!memcmp(decoded.name, pack_names[slot], strlen(pack_names[slot])));
    for (uint32_t k = 0; k < NTRK; k++) {
        assert(decoded.t[k].engine == pack_engines[slot][k]);
        assert(decoded.t[k].p[P_SLEN] == 16 && decoded.t[k].p[P_SDIV] == 2);
        if (decoded.t[k].engine == 14u) assert(decoded.t[k].p[P_E0] == pack_models[slot][k]);
    }
    assert(snprintf(path, sizeof path, "%s/%s.fun10", dir, pack_files[slot]) < (int)sizeof path);
    FILE *f = fopen(path, "wb");
    assert(f);
    assert(fwrite(&proj_slot[slot], 1, sizeof proj_slot[slot], f) == sizeof proj_slot[slot]);
    assert(!fclose(f));
}

static void pack_song_check(void)
{
    uint32_t seen = 0, blocks = 0;
    project_load(3);
    assert(chain_prepare() == 0);
    while (blocks < 110000u && (blocks == 0u || chain.running)) {
        events_block(32);
        if (chain.running) {
            uint32_t row = chain.row;
            assert(row < NELEM(pack_rows));
            seen |= 1u << row;
            assert(!memcmp(chain.lane, pack_rows[row].slot, sizeof chain.lane));
            for (uint32_t k = 0; k < NTRK; k++) {
                uint32_t src = pack_rows[row].slot[k];
                assert(trk[k].eng_req == 14u);       /* sections retain D's sounds */
                assert(trk[k].p[P_E0] == pack_models[3][k]);
                if (src < 4u)
                    assert(!memcmp(seq_steps(&trk[k]), chain.source[src].step[k], sizeof trk[k].step));
                else assert(!trk[k].seq_n);
            }
        }
        blocks++;
    }
    assert(seen == (1u << NELEM(pack_rows)) - 1u && !chain.running && !song.playing);
    /* Integer tempo periods round each step; allow less than one control block
     * per step across the 32 pattern loops plus the final silent bar. */
    assert(blocks * 32u > 66u * FS - 1024u && blocks * 32u < 66u * FS + 1024u);
    printf("song: all five sections, lane sources, retained D sounds, silent ending and STOP: %u blocks\n", blocks);
}

static void pack_transition_check(void)
{
    int32_t out[CTL * 2];
    static const uint8_t order[] = {0, 2, 1, 2, 3, 0};
    for (uint32_t i = 0; i < NELEM(order); i++) {
        uint32_t slot = order[i];
        project_load(slot);
        for (uint32_t b = 0; b < XF_BLOCKS + 2u; b++) mix_block(out, CTL);
        for (uint32_t k = 0; k < NTRK; k++) {
            assert(trk[k].engine == pack_engines[slot][k]);
            trk_note_on(&trk[k], 60u + k, 100);
        }
        for (uint32_t b = 0; b < 64u; b++) mix_block(out, CTL);
    }
    for (uint32_t k = 0; k < NTRK; k++) trk_all_off(&trk[k]);
    puts("transitions: A/C/B/C/D/A project loads, shared arenas, live-note rendering OK");
}

static int pack_verify_files(const char *dir)
{
    char path[4096];
    for (uint32_t slot = 0; slot < 4u; slot++) {
        project_t decoded;
        project_store_t again;
        if (snprintf(path, sizeof path, "%s/%s.fun10", dir, pack_files[slot]) >= (int)sizeof path) return 1;
        FILE *f = fopen(path, "rb");
        if (!f) return 1;
        size_t n = fread(&proj_slot[slot], 1, sizeof proj_slot[slot], f);
        int end = fgetc(f), error = ferror(f);
        fclose(f);
        if (n != sizeof proj_slot[slot] || end != EOF || error ||
            !proj_import(&decoded, &proj_slot[slot], sizeof proj_slot[slot]) ||
            !proj_pack(&again, &decoded) || memcmp(&again, &proj_slot[slot], sizeof again)) return 1;
    }
    return 0;
}

static void pack_metadata(const char *dir)
{
    char path[4096];
    assert(snprintf(path, sizeof path, "%s/firmware-projects.json", dir) < (int)sizeof path);
    FILE *f = fopen(path, "w");
    assert(f);
    fprintf(f, "{\"global_descriptors\":[");
    for (uint32_t i = 0; i < G_COUNT; i++)
        fprintf(f, "%s{\"id\":%u,\"label\":\"%s\"}", i ? "," : "", i, GP[i].label);
    fprintf(f, "],\"projects\":[");
    for (uint32_t slot = 0; slot < 4u; slot++) {
        project_t p;
        assert(proj_import(&p, &proj_slot[slot], sizeof proj_slot[slot]));
        fprintf(f, "%s{\"slot\":%u,\"stem\":\"%s\",\"name\":\"%s\",\"globals\":[", slot ? "," : "", slot, pack_files[slot], pack_names[slot]);
        for (uint32_t i = 0; i < G_COUNT; i++) fprintf(f, "%s%d", i ? "," : "", p.g[i]);
        fprintf(f, "],\"tracks\":[");
        for (uint32_t k = 0; k < NTRK; k++) {
            proj_trk_t *t = &p.t[k];
            fprintf(f, "%s{\"engine_id\":%u,\"preset\":%u,\"model\":\"%s\",\"parameters\":[", k ? "," : "", t->engine, t->preset, t->engine == 14u ? N_MACRO_SHAPE[t->p[P_E0]] : "");
            for (uint32_t i = 0; i < P_COUNT; i++) fprintf(f, "%s%d", i ? "," : "", t->p[i]);
            fprintf(f, "]}");
        }
        fprintf(f, "],\"sections\":[");
        for (uint32_t i = 0; i < p.chain.count; i++) {
            chain_row_t *r = &p.chain.row[i];
            fprintf(f, "%s{\"slots\":[%u,%u,%u,%u],\"repeat\":%u}", i ? "," : "", r->slot[0], r->slot[1], r->slot[2], r->slot[3], r->repeat);
        }
        fprintf(f, "]}");
    }
    fprintf(f, "],\"parameter_ids\":{\"level\":%u,\"attack\":%u,\"decay\":%u,\"sustain\":%u,\"release\":%u,\"chorus\":%u,\"delay\":%u,\"reverb\":%u,\"engine_first\":%u},\"parameter_count\":%u}\n",
        P_LEVEL, P_ATK, P_DEC, P_SUS, P_REL, P_CHOR, P_DLY, P_REV, P_E0, P_COUNT);
    assert(!fclose(f));
}

int main(int argc, char **argv)
{
    assert(eng_ok(14) && NTRK == 4);
    ui_power_on();
    if (argc == 3 && !strcmp(argv[1], "--verify")) {
        if (pack_verify_files(argv[2])) { fputs("invalid device pack project\n", stderr); return 1; }
        pack_transition_check();
        pack_song_check();
        return 0;
    }
    assert(argc == 2);
    for (uint32_t slot = 0; slot < 4u; slot++) { pack_setup(slot); pack_write(argv[1], slot); }
    pack_metadata(argv[1]);
    pack_transition_check();
    pack_song_check();
    puts("MACRO device pack: four real FUN10 saves/imports, byte-identical round trips, song playback OK");
    return 0;
}
