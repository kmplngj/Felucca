/* SPDX-License-Identifier: GPL-3.0-only */
/* Compiled by insert_lpk_test.py against lookup and original-formula sources.
 * Each 256-block episode sweeps every cutoff, alternates clamped endpoints,
 * fades MIX out/in, drains a silent tail, resets/restarts and switches OFF.
 * The next episode switches type while wet; each of the five callers runs.
 * Compare bytes, including the entire zero-initialized ins_t and ins_run after
 * every block: a hidden filter-state change must not escape a PCM-only check.
 * The stream is native host data, compared only within one compiler/flags run. */
#define main hostsim_main
#include INSERT_LPK_HOSTSIM
#undef main

static void emit(const void *p, size_t n)
{
    if (fwrite(p, 1, n, stdout) != n)
        exit(2);
}

int main(int argc, char **argv)
{
    uint32_t tracks = argc > 1 ? (uint32_t)atoi(argv[1]) : 1u;
    uint32_t block, ti, i, seed = 0x12345678u, active[IT_N] = {0};
    if (tracks != 1u && tracks != NTRK)
        return 2;
    memset(trk, 0, sizeof trk);
    memset(ins, 0, sizeof ins);
    for (block = 0; block < 2048u; block++) {
        uint32_t phase = block % 256u;
        uint32_t n = block % 7u ? CTL : 1u + block % CTL;
        for (ti = 0; ti < tracks; ti++) {
            track_t *t = &trk[ti];
            int32_t b[CTL];
            uint32_t ty = IT_SOFT + (block / 256u + ti) % 5u;
            int32_t cutoff = phase < 128u ? (int32_t)phase : (phase & 1u ? -1 : 128);
            t->p[P_ITYPE] = (int16_t)(phase >= 224u && phase < 240u ? IT_OFF : ty);
            t->p[P_IA] = (int16_t)((block * 17u + ti * 19u) & 127u);
            t->p[P_IB] = (int16_t)(ty == IT_CRUSH ? block & 127u : cutoff);
            t->p[P_IC] = (int16_t)(ty == IT_CRUSH ? cutoff : 100);
            t->p[P_IMIX] = (int16_t)(phase >= 160u && phase < 176u ? 0u :
                                    phase >= 176u && phase < 192u ? 63u : 127u);
            if (phase == 208u)
                ins_rest(t);  /* explicit reset/retrigger while active */
            for (i = 0; i < n; i++) {
                seed ^= seed << 13;
                seed ^= seed >> 17;
                seed ^= seed << 5;
                b[i] = phase >= 192u ? 0 : (int32_t)(seed & 65535u) - 32768;
            }
            track_insert(t, b, n);
            if (ins[ti].w && ins[ti].type < IT_N)
                active[ins[ti].type]++;
            emit(b, sizeof *b * n);
            emit(&ins[ti], sizeof ins[ti]);
            emit(&t->ins_run, sizeof t->ins_run);
        }
    }
    for (i = IT_SOFT; i <= IT_CRUSH; i++)
        if (!active[i])
            return 3;
    return ferror(stdout) ? 2 : 0;
}
