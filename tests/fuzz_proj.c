/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Fuzz harness of the project record codec alone (firmware/src/project_codec.h, #300): no ui.c, panel.c, gfx.c or
 * menu_items.c, only tests/hostsim.c and project.c's codec part (-DPROJ_HOST). Random valid projects (every field in
 * its range), written by proj_encode or as FUN9 / FUN8 / FUN7 (tests/old_pack.h), then mutated: bytes, the magic
 * (FUN1..FUN9, FUNA), the length (each stored format's, a retained 3840-byte slot, any), the hash recomputed or not.
 * Every input goes through proj_classify and proj_decode; what decodes must hold:
 *   - proj_decode = the reader's own output (proj_import) followed by proj_bound: the one fixed order;
 *   - a CURRENT record decodes the same through proj_decode_current; anything else is refused by it;
 *   - the result is inside every field and range (param_fit is the identity on it, the steps' fields bounded), its
 *     engines in the id space, its hash right;
 *   - proj_encode stores it, and decoding that again gives the same project: the encode -> decode fixed point;
 *   - proj_accepts_length is exactly the stored lengths of FUN10, FUN9, FUN8 and FUN7 / FUN6.
 * run_tests.sh runs it under ASan / UBSan with a fixed seed.   fuzz_proj [ITERATIONS [SEED]] */
#define main hostsim_main
#include "hostsim.c"
#undef main
#define PROJ_HOST 1
#include "../firmware/src/project.c"
#include "old_pack.h"

static uint32_t rs = 0x2545F491u;
static uint32_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 17; rs ^= rs << 5; return rs; }
static int32_t rnd_in(int32_t lo, int32_t hi) { return lo + (int32_t)(rnd() % (uint32_t)(hi - lo + 1)); }
static uint32_t fails;
static void need(int ok, const char *what, uint32_t it)
{
    if (!ok && fails++ < 20u)
        printf("fuzz_proj: iteration %u: %s\n", it, what);
}

/* a project with every field in its range, as a capture could hold it */
static void random_project(project_t *a)
{
    uint32_t t, i, n;
    memset(a, 0, sizeof *a);
    a->magic = PROJ_MAGIC; a->size = sizeof *a;
    for (i = 0; i < G_COUNT; i++)
        a->g[i] = (int16_t)(rnd() & 3u ? GP[i].def : rnd_in(GP[i].min, GP[i].max));
    a->sel = (uint8_t)(rnd() % NTRK); a->parts = NPART; a->phys = PROJ_PHYS;
    chain_defaults(&a->chain);
    if (rnd() & 1u) {
        a->chain.count = (uint8_t)(1u + rnd() % CHAIN_ROWS);
        for (i = 0; i < a->chain.count; i++) {
            uint32_t s = rnd() % 4u;                           /* (one slot a row, so FUN9..FUN7 can hold it) */
            for (t = 0; t < NTRK; t++) a->chain.row[i].slot[t] = (uint8_t)s;
            a->chain.row[i].repeat = (uint8_t)(1u + rnd() % 16u);
        }
    }
    for (t = 0; t < NTRK; t++) {
        proj_trk_t *d = &a->t[t];
        d->engine = (uint8_t)(rnd() % 4u ? trk_def_engine(t) : rnd() % ENG_ID_MAX);
        d->preset = (uint8_t)(rnd() % 8u ? rnd() % 16u : 0xFEu + rnd() % 2u);
        for (i = 0; i < P_COUNT; i++) {
            const param_desc_t *p = param_desc_of(eng_idx(d->engine), i);
            int32_t lo = p->min < -64 ? -64 : p->min, hi = p->max > 127 ? 127 : p->max;
            d->p[i] = (int16_t)(rnd() & 1u ? p->def : rnd_in(lo, hi));
        }
        for (i = 0; i < NSTEP; i++) {
            step_t *s = &d->step[i];
            uint32_t j;
            s->time = (uint8_t)(rnd() % 3u);
            s->n = (uint8_t)(rnd() % 5u);
            for (j = 0; j < 4u; j++) s->note[j] = (uint8_t)(rnd() & 127u);
            s->flags = (uint8_t)(rnd() & 3u);
            s->vel = (uint8_t)(rnd() & 127u);
            s->hit = (uint8_t)rnd(); s->acc = (uint8_t)(rnd() & s->hit);
            s->probability = (uint8_t)(rnd() % (COND_FIRST + NCOND));
            step_set_ratchet(s, 1u + rnd() % 4u);
            step_set_nudge(s, rnd_in(-8, 7));
        }
        for (i = 0; i < FM6_PACKED; i++) a->fm6[t][i] = (uint8_t)(rnd() & 127u);
        a->mch[t] = (uint8_t)(rnd() % MCH_N);
    }
    for (i = n = 0; i < 64u; i++) {                            /* motion: valid ids, a place/id pair once */
        uint32_t id = rnd() % P_COUNT, place = rnd() & 255u, k, dup = 0;
        if (!motion_param(id)) continue;
        for (k = 0; k < n; k++)
            dup |= a->motion.event[k].place == place && MOTION_ID(&a->motion.event[k]) == id;
        if (dup) continue;
        a->motion.event[n].place = (uint8_t)place;
        a->motion.event[n].param = (uint8_t)(id | (rnd() % 4u ? 0u : MOTION_LOCK));
        a->motion.event[n].value = (int8_t)rnd_in(-64, 127);
        n++;
    }
    a->motion.count = (uint8_t)n;
    a->motion.on = (uint8_t)(rnd() & 15u);
    for (i = 0; i < PROJ_NAME_LEN && rnd() % 6u; i++) a->name[i] = (char)('A' + rnd() % 26u);
    a->sum = proj_sum(a);
}

/* q is inside every field and range proj_bound keeps */
static int bounded(const project_t *q)
{
    uint32_t t, i;
    if (!proj_ok(q) || !proj_engines_ok(q)) return 0;
    for (t = 0; t < NTRK; t++)
        for (i = 0; i < P_COUNT; i++) {
            const step_t *s = &q->t[t].step[i < NSTEP ? i : 0];
            if (param_fit(param_desc_of(eng_idx(q->t[t].engine), i), q->t[t].p[i]) != q->t[t].p[i]) return 0;
            if (i < NSTEP && (s->n > 4u || s->time > ST_REST || (s->flags & ~(3u | SF_RATCH | SF_NUDGE)) ||
                              s->vel > 127u || (s->acc & ~s->hit) || s->probability >= COND_FIRST + NCOND))
                return 0;
            if (i < NSTEP && (s->note[0] > 127u || s->note[1] > 127u || s->note[2] > 127u || s->note[3] > 127u)) return 0;
        }
    return 1;
}

int main(int argc, char **argv)
{
    static project_t a, c, d, e;
    static union { uint32_t align; uint8_t raw[4096]; project_store_t st; } in;
    static project_store_t st2;
    static const uint32_t LEN[11] = {3840u, 3648u, 3584u, 3388u, 3352u, 2680u, 2584u, 2552u, 688u, 3839u, 3841u};
    uint32_t iters = argc > 1 ? (uint32_t)atoi(argv[1]) : 20000u, i, j, k, n, decoded = 0, current = 0;
    if (argc > 2) rs = (uint32_t)atoi(argv[2]) | 1u;
    for (n = 0; n < 4000u; n++)
        need(proj_accepts_length(n) == (n == 3840u || n == 3648u || n == 3584u || n == 3388u), "proj_accepts_length", n);
    for (i = 0; i < iters; i++) {
        uint32_t mode = rnd() % 8u, fix;
        memset(in.raw, 0, sizeof in.raw);
        random_project(&a);
        if (mode == 0) {                                        /* random bytes under a format's magic */
            for (j = 0; j < PROJ_STORE_SIZE; j++) in.raw[j] = (uint8_t)rnd();
            k = 0x46554E31u + rnd() % 10u;                      /* "FUN1".."FUN9", ":" */
            if (k == 0x46554E3Au) k = PROJ_MAGIC;
            memcpy(in.raw, &k, 4);
            n = LEN[rnd() % 11u];
            memcpy(in.raw + 4, &n, 4);
        } else if (mode <= 2) {                                 /* FUN9 / FUN8 / FUN7 as 1.1 / 1.0 wrote them */
            static const uint32_t M[3] = {OLD_FUN9, OLD_FUN8, OLD_FUN7};
            uint32_t m = M[rnd() % 3u], np = m == OLD_FUN7 && (rnd() & 1u) ? 89u : m == OLD_FUN9 ? 99u : 91u;
            a.motion.count = a.motion.count > 64u ? 64u : a.motion.count;
            n = old_pack(in.raw, &a, m, np);
            if (!n) continue;
        } else {
            if (!proj_encode(&in.st, &a)) { need(0, "a valid project encodes", i); continue; }
            n = PROJ_STORE_SIZE;
        }
        k = rnd() % 4u ? 1u + rnd() % 24u : 0u;                /* mutations (none: the record as written) */
        for (j = 0; j < k; j++) {
            uint32_t off = rnd() % 4u == 0 ? rnd() % 200u : rnd() % PROJ_STORE_SIZE;
            in.raw[off] = (uint8_t)(rnd() % 4u == 0 ? 0xFF : rnd() % 4u == 0 ? 0x7F : rnd());
        }
        if (rnd() % 8u == 0) n = rnd() % 8u ? LEN[rnd() % 11u] : rnd() % (PROJ_STORE_SIZE + 64u);
        fix = rnd() % 2u || !k;                                 /* a valid hash: attacker-controlled flash */
        if (fix && n >= 8u && n <= PROJ_STORE_SIZE) {
            uint32_t sum = proj_hash(in.raw, n - 4u);
            memcpy(in.raw + n - 4u, &sum, 4);
        }
        {
            uint32_t cl = proj_classify(in.raw, n);
            int ok = proj_decode(&c, in.raw, (int)n), ok2 = proj_import(&d, in.raw, (int)n);
            need(cl <= PROJ_DAMAGED, "classification in range", i);
            need(ok == ok2, "proj_decode accepts what the reader accepts", i);
            if (ok2) { proj_bound(&d); need(!memcmp(&c, &d, sizeof c), "proj_decode = reader + proj_bound", i); }
            need(proj_decode_current(&e, in.raw, (int)n) == (ok && cl == PROJ_CURRENT), "proj_decode_current: CURRENT only", i);
            if (ok && cl == PROJ_CURRENT) need(!memcmp(&c, &e, sizeof c), "proj_decode_current = proj_decode", i);
            if (cl == PROJ_CURRENT) current++;
            if (!ok) continue;
            decoded++;
            need(bounded(&c), "decoded: every field and value inside its range", i);
            need(proj_encode(&st2, &c), "decoded: proj_encode stores it", i);
            need(proj_classify(&st2, sizeof st2) == PROJ_CURRENT, "encoded: CURRENT", i);
            need(proj_decode(&d, &st2, sizeof st2) && !memcmp(&c, &d, sizeof c), "encode -> decode: the same project", i);
        }
    }
    printf("fuzz_proj %s: %u iterations, %u decoded (%u CURRENT), %u failures\n", fails ? "FAILED" : "ok", iters, decoded,
           current, fails);
    return fails != 0;
}
