/* SPDX-License-Identifier: GPL-3.0-only */
/* Full-bank bounds, independent parts, live transitions, persisted model IDs and
 * repeated real-mixer cost. Separate from the original three-model goldens. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include <assert.h>
#ifdef __APPLE__
#include <libproc.h>
#include <sys/resource.h>
#endif

static uint64_t bank_instructions(void)
{
#ifdef __APPLE__
    struct rusage_info_v4 r;
    if (!proc_pid_rusage(getpid(), RUSAGE_INFO_V4, (rusage_info_t *)&r)) return r.ri_instructions;
#endif
    return 0;
}
static void bank_setup(uint32_t model, uint32_t timbre, uint32_t color, uint32_t note)
{
    memset(trk, 0, sizeof trk);
    memset(eng_mem_owner, 0, sizeof eng_mem_owner);
    host_tracks_init();
    host_preset(&trk[0], ENGI_MACRO, 0);
    trk[0].p[P_E0] = model;
    trk[0].p[P_E1] = timbre;
    trk[0].p[P_E2] = color;
    trk[0].p[P_ATK] = trk[0].p[P_REL] = trk[0].p[P_ED_FLT] = 0;
    trk[0].p[P_SUS] = 127;
    trk[0].p[P_VOICE] = V_POLY;
    trk[0].p[P_CHOR] = trk[0].p[P_DLY] = trk[0].p[P_REV] = 0;
    trk_note_on(&trk[0], note, 100);
}
static uint64_t bank_hash(uint32_t frames)
{
    int32_t out[CTL];
    uint64_t h = 0xcbf29ce484222325ull;
    uint32_t i, k;
    for (i = 0; i < frames; i += CTL) {
        track_render(&trk[0], out, CTL);
        for (k = 0; k < CTL; k++) {
            assert(out[k] >= -2 * VOICE_FS && out[k] <= 2 * VOICE_FS);
            h = (h ^ (uint32_t)out[k]) * 0x100000001b3ull;
        }
    }
    return h;
}
static double bank_cost(uint32_t model, uint32_t timbre, uint32_t color, uint32_t parts)
{
    uint32_t k, blocks = FS / CTL;
    uint64_t start = 0, end;
    int32_t out[2 * CTL];
    bank_setup(model, timbre, color, 60);
    trk[0].p[P_E6] = 127;
    trk[0].p[P_CHOR] = 20; trk[0].p[P_DLY] = 20; trk[0].p[P_REV] = 35;
    if (!parts) trk[0].v[0].active = trk[0].v[0].gate = 0;
    for (k = 1; k < parts; k++) {
        host_preset(&trk[k], ENGI_MACRO, 0);
        memcpy(trk[k].p, trk[0].p, sizeof trk[k].p);
        trk_note_on(&trk[k], 60, 100);
    }
    for (k = 0; k < blocks / 2 + blocks; k++) {
        if (k == blocks / 2) start = bank_instructions();
        mix_block(out, CTL);
    }
    end = bank_instructions();
    return start ? (double)(end - start) / (blocks * CTL) : 0;
}

static void bank_noise_separation(void)
{
    int32_t samples[NPART][CTL * 8], repeat[CTL * 8];
    uint32_t p, q, b;
    bank_setup(41, 64, 64, 60);                 /* NOISE: identical parts must not share a stream */
    for (p = 1; p < NPART; p++) {
        host_preset(&trk[p], ENGI_MACRO, 44);
        memcpy(trk[p].p, trk[0].p, sizeof trk[p].p);
        trk_note_on(&trk[p], 60, 100);
    }
    for (b = 0; b < 8u; b++)
        for (p = 0; p < NPART; p++)
            track_render(&trk[p], samples[p] + b * CTL, CTL);
    for (p = 0; p < NPART; p++)
        for (q = 0; q < p; q++)
            assert(memcmp(samples[p], samples[q], sizeof samples[p]));
    bank_setup(41, 64, 64, 60);
    for (b = 0; b < 8u; b++) track_render(&trk[0], repeat + b * CTL, CTL);
    assert(!memcmp(samples[0], repeat, sizeof repeat));
    puts("braids: identical NOISE parts have distinct streams; part-zero reset stays deterministic");
}
int main(void)
{
    uint32_t model, corner, i;
    int32_t out[CTL];
    static uint8_t saved[sizeof(macro_part_t)];
    printf("braids: core %zu B, wrapper %zu B/part, arena %u B/part, 48 models\n",
           sizeof(braids_MacroOscillator), sizeof(macro_part_t), ENG_MEM_PART);
    assert(MAC_NSHAPE == 48 && ENG_MACRO.npresets == 51);
    bank_noise_separation();
    for (model = 3; model < MAC_NSHAPE; model++) {
        uint64_t hash, repeat;
        bank_setup(model, 64, 64, 60); hash = bank_hash(8192);
        bank_setup(model, 64, 64, 60); repeat = bank_hash(8192);
        assert(hash == repeat);
        assert(hash != 0);
        memcpy(saved, macro_part(&trk[0]), sizeof saved);
        host_preset(&trk[1], ENGI_MACRO, model + 3);
        trk_note_on(&trk[1], 72, 110);
        for (i = 0; i < 32; i++) track_render(&trk[1], out, CTL);
        assert(!memcmp(saved, macro_part(&trk[0]), sizeof saved));
        trk_note_on(&trk[0], 72, 100);
        bank_hash(2048);
        assert(trk[0].v[0].active && trk[0].v[0].note == 72);
        trk_note_off(&trk[0], 72);
        bank_hash(FS / 4);
        assert(!trk[0].v[0].active);
        for (corner = 0; corner < 16; corner++) {
            bank_setup(model, corner & 1 ? 127 : 0, corner & 2 ? 127 : 0, corner & 4 ? 127 : 0);
            trk[0].p[P_E7] = corner & 8 ? 50 : -50;
            bank_hash(2048);
        }
        bank_setup(MAC_WAVE, 64, 64, 60);
        for (i = 0; i < 8; i++) trk_note_on(&trk[0], 48 + i * 3, 100);
        bank_hash(128);
        trk[0].p[P_E0] = model;
        bank_hash(128);
        for (i = 1; i < NVOICE; i++) assert(!trk[0].v[i].active);
        assert(trk_nvoice(&trk[0]) == 1);
        trk[0].p[P_E0] = MAC_WAVE;
        bank_hash(128);
        assert(trk_nvoice(&trk[0]) == NVOICE);
        printf("braids: %-12s id %2u upstream %2u hash %016llx bounds/reset/parts/transitions ok\n",
               N_MACRO_SHAPE[model], model, MACRO_UPSTREAM[model], (unsigned long long)hash);
    }
    if (!getenv("NOCOST")) {
        static const uint8_t values[] = {0, 64, 127};
        uint32_t heavy = 0, ht = 0, hc = 0;
        double maximum = 0;
        printf("braids: CPU idle %.1f instr/frame\n", bank_cost(3, 64, 64, 0));
        for (model = 3; model < MAC_NSHAPE; model++) {
            double worst = 0;
            uint32_t t, c, wt = 0, wc = 0;
            for (t = 0; t < 3; t++) for (c = 0; c < 3; c++) {
                double cost = bank_cost(model, values[t], values[c], 1);
                if (cost > worst) worst = cost, wt = values[t], wc = values[c];
            }
            printf("braids: CPU %-12s %.1f instr/frame, 1 voice (TIMBRE %u COLOR %u)\n", N_MACRO_SHAPE[model], worst, wt, wc);
            if (worst > maximum) maximum = worst, heavy = model, ht = wt, hc = wc;
        }
        if (maximum)
            printf("braids: CPU four parts %-12s %.1f instr/frame (TIMBRE %u COLOR %u)\n",
                   N_MACRO_SHAPE[heavy], bank_cost(heavy, ht, hc, 4), ht, hc);
        else
            puts("braids: CPU skipped (host instruction counter unavailable)");
    }
    puts("braids: full bank passed");
    return 0;
}
