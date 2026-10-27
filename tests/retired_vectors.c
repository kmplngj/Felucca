/* SPDX-License-Identifier: GPL-3.0-only */
/* Reference vectors of the retired sounds (#299, part A): what today's firmware makes of DIGITAL (engine 1, four-operator
 * FM), PHYS MODEL 2 (DUST) and MODEL 4 (DRUM) and SAMPLE PERC (SET 4) in each store that can hold them. The firmware's
 * own code runs (nothing here re-implements a conversion): proj_import / proj_bound / proj_pack (projects),
 * up_bank_check / up_load (user preset records), settings_import (favourites, PER4 and PER6), fm4_apply and
 * fm4_load_preset (the load path of a DIGITAL sound), each on fixed inputs. The output is JSON on stdout, deterministic
 * (no time, no address): tests/fixtures/retired_vectors.json is its committed copy, tests/retired_vectors.py compares
 * (--check) or rewrites (--update) it, and tests/run_tests.sh fails on any difference. A change of a conversion changes
 * the vectors: that is the point; review the diff, then --update. The WebApp (Felucca-WebApp test_legacy.mjs) compares
 * its own conversions against the same file, see docs/legacy-formats.md section 4.
 *
 * Sections of the JSON (all byte strings are lower-case hex):
 *   constants    the ids the vectors use, FX_DEF, FM4_TO_FM6, DRUM_KIT_E, the sizes
 *   projects     input FUN10 / FUN8 / FUN7 image -> output FUN10 image (import, proj_bound, pack: the load path of proj_fetch);
 *                tracks (engine / preset before and after), motion_dropped (events the conversion removed)
 *   presets      a UPB1 record as stored -> the record in the RAM mirror after up_bank_check (the boot path) -> what
 *                up_load makes of it in the selected track (engine, preset, 111 values, the FM6 patch)
 *   favourites   a PER4 / PER6 settings record -> the favourites rows after settings_import; moved and dropped bits
 *   load         fm4_apply on DIGITAL values and fm4_load_preset on DIGITAL preset numbers: the track afterwards
 *   cc -w -Ibuild/gen -Ifirmware/src -o build/host/retired_vectors tests/retired_vectors.c -lm */
#include "ui_harness.h"
#include "old_pack.h"

#if FELUCCA_FM4
#error "retired_vectors converts DIGITAL: build it without FELUCCA_FM4"
#endif

/* ----------------------------------------------------------- output --- */
static void rv_hex(const void *b, uint32_t n)
{
    const uint8_t *p = b;
    uint32_t i;
    putchar('"');
    for (i = 0; i < n; i++)
        printf("%02x", p[i]);
    putchar('"');
}
static void rv_hex16(const int16_t *v, uint32_t n)     /* little-endian int16 */
{
    uint8_t b[2u * P_COUNT];
    uint32_t i;
    for (i = 0; i < n; i++) {
        b[2u * i] = (uint8_t)((uint16_t)v[i] & 255u);
        b[2u * i + 1u] = (uint8_t)((uint16_t)v[i] >> 8);
    }
    rv_hex(b, 2u * n);
}
static void rv_ints(const uint8_t *v, uint32_t n)
{
    uint32_t i;
    putchar('[');
    for (i = 0; i < n; i++)
        printf("%s%u", i ? ", " : "", (unsigned)v[i]);
    putchar(']');
}
static void rv_sep(uint32_t *n) { printf("%s\n", (*n)++ ? "," : ""); }
static void rv_die(const char *what, const char *case_name)
{
    fprintf(stderr, "retired_vectors: %s (%s)\n", what, case_name);
    exit(1);
}

/* ------------------------------------------------------------ inputs --- */
/* a track's DIGITAL values: the factory preset k as a preset load sets it (the code under test: sound_defaults and
 * fm4_preset_values), then the given overrides */
static void rv_digital_preset(int16_t *p, uint32_t k)
{
    uint32_t i;
    for (i = 0; i < P_COUNT; i++)
        p[i] = TP[i].def;
    fm4_preset_values(p, k);
}
/* DIGITAL values of algorithm alg with every field set to something other than a preset's (ratios, the master envelope,
 * FLT ENV, FDBK and the OP ENV pages: n = 0 flat, 1 shaped, 2 shaped with FDBK in the noisy range) */
static void rv_digital_alg(int16_t *p, uint32_t alg, uint32_t n)
{
    uint32_t i;
    for (i = 0; i < P_COUNT; i++)
        p[i] = TP[i].def;
    p[P_E0] = (int16_t)alg;
    p[P_E1] = (int16_t)(1 + alg % 5u);
    p[P_E2] = (int16_t)(2 + alg % 7u);
    p[P_E3] = (int16_t)(3 + alg % 11u);
    p[P_E4] = (int16_t)(40 + 9u * alg);
    p[P_E5] = (int16_t)(30 + 7u * alg);
    p[P_E6] = (int16_t)(n == 2u ? 24 : n ? 6 : 0);
    p[P_ATK] = (int16_t)(alg * 3u);
    p[P_DEC] = (int16_t)(50 + alg * 5u);
    p[P_SUS] = (int16_t)(127 - alg * 11u);
    p[P_REL] = (int16_t)(30 + alg * 6u);
    p[P_ED_FLT] = (int16_t)(n ? (int)alg * 9 - 30 : 0);
    if (n)
        for (i = 0; i < 4u; i++) {
            p[P_FM1_ATK + 5u * i] = (int16_t)(5 + 11 * i + alg);
            p[P_FM1_DEC + 5u * i] = (int16_t)(40 + 7 * i);
            p[P_FM1_SUS + 5u * i] = (int16_t)(100 - 9 * i);
            p[P_FM1_REL + 5u * i] = (int16_t)(20 + 13 * i);
            p[P_FM1_LEVEL + 5u * i] = (int16_t)(110 - 5 * i);
        }
}
/* the sound a PHYS / SAMPLE track holds before conversion: common values at their defaults, E0..E7 given */
static void rv_with_e(int16_t *p, const int16_t *e)
{
    uint32_t i;
    for (i = 0; i < P_COUNT; i++)
        p[i] = TP[i].def;
    for (i = 0; i < 8u; i++)
        p[P_E0 + i] = e[i];
}

/* ---------------------------------------------------------- projects --- */
typedef struct {
    const char *name;
    uint8_t phys;                   /* the byte `phys` (0: MODEL 2 was DUST; 1: MODEL 4 was DRUM; 2 today) */
    uint8_t engine[NTRK], preset[NTRK];
    int16_t p[NTRK][P_COUNT];
    uint32_t nmotion;
    motion_event_t motion[12];
} pv_case_t;

static pv_case_t pv_new(const char *name, uint32_t phys)
{
    pv_case_t c;
    uint32_t t, i;
    memset(&c, 0, sizeof c);
    c.name = name;
    c.phys = (uint8_t)phys;
    for (t = 0; t < NTRK; t++)
        for (i = 0; i < P_COUNT; i++)
            c.p[t][i] = TP[i].def;
    return c;
}
static void pv_trk(pv_case_t *c, uint32_t t, uint32_t engine, uint32_t preset, const int16_t *p)
{
    c->engine[t] = (uint8_t)engine;
    c->preset[t] = (uint8_t)preset;
    memcpy(c->p[t], p, sizeof c->p[t]);
}
static void pv_motion(pv_case_t *c, uint32_t t, uint32_t step, uint32_t id, int value)
{
    c->motion[c->nmotion].place = (uint8_t)(t << 6 | step);
    c->motion[c->nmotion].param = (uint8_t)id;
    c->motion[c->nmotion].value = (int8_t)value;
    c->nmotion++;
}

static void pv_build(project_t *q, const pv_case_t *c)
{
    uint32_t t, i;
    memset(q, 0, sizeof *q);
    q->magic = PROJ_MAGIC;
    q->size = sizeof *q;
    for (i = 0; i < G_COUNT; i++)
        q->g[i] = 0;
    q->sel = 0;
    q->parts = NPART;
    q->phys = c->phys;
    chain_defaults(&q->chain);
    for (t = 0; t < NTRK; t++) {
        memcpy(q->t[t].p, c->p[t], sizeof q->t[t].p);
        q->t[t].engine = c->engine[t];
        q->t[t].preset = c->preset[t];
        for (i = 0; i < NSTEP; i++) {
            q->t[t].step[i].time = ST_REST;
            if (i % 8u == 0u) {                       /* a few notes, so the image is not all rests */
                q->t[t].step[i].time = ST_NOTE;
                q->t[t].step[i].n = 1;
                q->t[t].step[i].note[0] = (uint8_t)(48u + t * 4u + i / 8u);
                q->t[t].step[i].vel = (uint8_t)(90u + t);
            }
        }
        memcpy(q->fm6[t], FM6_INIT, FM6_PACKED);
    }
    memcpy(q->motion.event, c->motion, c->nmotion * sizeof c->motion[0]);
    q->motion.count = (uint8_t)c->nmotion;
    q->motion.on = 15;
    memcpy(q->name, "RETIRED", 8);
    q->sum = proj_sum(q);
}

static int rv_ev_has(const motion_store_t *m, const motion_event_t *e)
{
    uint32_t i;
    for (i = 0; i < m->count && i < MOTION_MAX; i++)
        if (!memcmp(&m->event[i], e, sizeof *e))
            return 1;
    return 0;
}

static uint32_t pv_n;
static void pv_emit(const pv_case_t *c, const char *format, uint32_t np, const char *retired)
{
    static project_store_t in10, out10;
    static uint8_t old[PROJ_STORE_V9];
    project_t q, post;
    const uint8_t *in;
    uint32_t inlen, t, i, nd = 0;
    /* Each historical format for one case of each retired sound; the rest in FUN10 only (file size). */
    if (strcmp(format, "FUN10") && strcmp(c->name, "digital presets 0-3") && !strstr(c->name, "ALG 5-6") &&
        !strstr(c->name, "phys byte 0") && !strstr(c->name, "phys byte 1") && !strstr(c->name, "PERC"))
        return;
    pv_build(&q, c);
    if (!strcmp(format, "FUN10")) {
        if (!proj_pack(&in10, &q))
            rv_die("proj_pack of the input", c->name);
        in = in10.raw;
        inlen = sizeof in10;
    } else {
        uint32_t magic = !strcmp(format, "FUN8") ? OLD_FUN8 : OLD_FUN7;
        memset(old, 0, sizeof old);
        inlen = old_pack(old, &q, magic, np);
        if (!inlen)
            rv_die("old_pack of the input", c->name);
        in = old;
    }
    if (!proj_import(&post, in, (int)inlen))          /* the load path: + proj_fm4, proj_perc */
        rv_die("proj_import", c->name);
    proj_bound(&post);                                /* (proj_fetch, project_load, autosave_boot, ed_bk_commit) */
    if (!proj_pack(&out10, &post))
        rv_die("proj_pack of the output", c->name);
    rv_sep(&pv_n);
    printf("    {\"name\": \"%s\", \"format\": \"%s\", \"np\": %u, \"retired\": \"%s\", \"phys_byte\": %u,\n",
           c->name, format, np, retired, (unsigned)c->phys);
    printf("     \"tracks\": [");
    for (t = 0; t < NTRK; t++)
        printf("%s{\"engine_in\": %u, \"preset_in\": %u, \"engine_out\": %u, \"preset_out\": %u}", t ? ", " : "",
               (unsigned)q.t[t].engine, (unsigned)q.t[t].preset, (unsigned)post.t[t].engine,
               (unsigned)post.t[t].preset);
    printf("],\n     \"motion_dropped\": [");
    /* q is the input before any migration; proj_import_any already changes PHYS identities.
     * Its motion uses current IDs, as the legacy serializer/reader map them by stored count. */
    for (i = 0; i < q.motion.count && i < MOTION_MAX; i++)
        if (!rv_ev_has(&post.motion, &q.motion.event[i])) {
            const motion_event_t *e = &q.motion.event[i];
            printf("%s{\"track\": %u, \"step\": %u, \"param\": %u, \"lock\": %u, \"value\": %d}", nd++ ? ", " : "",
                   (unsigned)(e->place >> 6), (unsigned)(e->place & 63u), (unsigned)MOTION_ID(e),
                   (unsigned)((e->param & MOTION_LOCK) != 0), (int)e->value);
        }
    printf("],\n     \"input\": ");
    rv_hex(in, inlen);
    printf(",\n     \"output\": ");
    rv_hex(out10.raw, sizeof out10);
    printf("}");
}

static void rv_projects(void)
{
    pv_case_t c;
    int16_t p[P_COUNT], e[8];
    uint32_t k, t, fmt;
    pv_n = 0;
    printf("  \"projects\": [");
    for (fmt = 0; fmt < 3u; fmt++) {          /* FUN10, FUN8 (1.0.x), FUN7 (before FM6 patches) */
        const char *f = fmt == 0u ? "FUN10" : fmt == 1u ? "FUN8" : "FUN7";
        uint32_t np = fmt ? 91u : P_COUNT;
        /* DIGITAL: the factory presets, then every algorithm with shaped OP ENV and the noisy feedback */
        for (k = 0; k < 2u; k++) {
            c = pv_new(k ? "digital presets 4-7" : "digital presets 0-3", PROJ_PHYS);
            for (t = 0; t < NTRK; t++) {
                rv_digital_preset(p, k * 4u + t);
                pv_trk(&c, t, ENGI_DIGITAL, k * 4u + t, p);
            }
            pv_motion(&c, 0, 3, P_E0 + 2u, 20);                  /* EDIT value: dropped */
            pv_motion(&c, 0, 5, P_FM1_DEC + 5u, 40);             /* OP ENV: dropped */
            pv_motion(&c, 0, 6, P_REV, 30);                      /* not an EDIT value: kept */
            pv_motion(&c, 1, 3, (P_E0 + 4u) | MOTION_LOCK, 50);  /* a parameter lock on EDIT: dropped */
            pv_motion(&c, 1, 9, P_PAN, -20);
            pv_motion(&c, 2, 1, P_FM4_LEVEL, 60);                /* the last OP ENV id: dropped */
            pv_motion(&c, 3, 2, P_ED_FLT, 10);                   /* below P_E0 and not OP ENV: kept */
            pv_emit(&c, f, np, "DIGITAL");
        }
        for (k = 0; k < 4u; k++) {
            static const char *const NM[4] = {"digital ALG 1-2 (flat OP ENV, shaped, FDBK)", "digital ALG 3-4 (shaped OP ENV)",
                                              "digital ALG 5-6 (shaped, noisy FDBK)", "digital ALG 7-8 (shaped, noisy FDBK)"};
            c = pv_new(NM[k], PROJ_PHYS);
            for (t = 0; t < NTRK; t++) {
                rv_digital_alg(p, k * 2u + (t & 1u), k == 0u ? t >> 1 : k == 1u ? 1u : 2u);
                pv_trk(&c, t, ENGI_DIGITAL, t == 3u ? PROJ_DEF_KEEP : t, p);
            }
            pv_emit(&c, f, np, "DIGITAL");
        }
        /* PHYS: the byte `phys` says what MODEL 2 and MODEL 4 mean */
        for (k = 0; k < 3u; k++) {
            static const char *const NM[3] = {"phys byte 0 (before 1.0: MODEL 2 DUST, MODEL 4 DRUM)",
                                              "phys byte 1 (MODEL 4 DRUM)", "phys byte 2 (today: unchanged)"};
            c = pv_new(NM[k], k);
            e[0] = 2; e[1] = 60; e[2] = 61; e[3] = 62; e[4] = 63; e[5] = 64; e[6] = 65; e[7] = 66;
            rv_with_e(p, e); pv_trk(&c, 0, ENGI_PHYS, 3, p);                 /* MODEL 2 */
            e[0] = 4; e[6] = 100; e[7] = 127;
            rv_with_e(p, e); pv_trk(&c, 1, ENGI_PHYS, 0, p);                 /* MODEL 4, KICK round, PERC top */
            e[0] = 4; e[6] = 10; e[7] = 40;
            rv_with_e(p, e); pv_trk(&c, 2, ENGI_PHYS, 2, p);                 /* MODEL 4, KICK punch, PERC 40 */
            e[0] = 1; e[6] = 0; e[7] = 0;
            rv_with_e(p, e); pv_trk(&c, 3, ENGI_PHYS, 1, p);                 /* MODEL 1: a sound that stays */
            pv_motion(&c, 1, 3, P_E0 + 1u, 30);                          /* (PHYS MODEL 4 keeps its motion) */
            pv_emit(&c, f, np, "PHYS");
        }
        /* SAMPLE PERC */
        c = pv_new("sample set 4 PERC", PROJ_PHYS);
        e[0] = 4; e[1] = 11; e[2] = 12; e[3] = 13; e[4] = 14; e[5] = 15; e[6] = 16; e[7] = 17;
        rv_with_e(p, e); pv_trk(&c, 0, ENGI_SAMPLE, 0, p);
        e[0] = 3;
        rv_with_e(p, e); pv_trk(&c, 1, ENGI_SAMPLE, 3, p);                  /* SET 3: stays */
        e[0] = 4;
        rv_with_e(p, e); pv_trk(&c, 2, ENGI_SAMPLE, PROJ_DEF_KEEP, p);      /* kept preset byte (old drum part) */
        rv_with_e(p, e); pv_trk(&c, 3, ENGI_SAMPLE, 5, p);
        pv_motion(&c, 0, 2, P_E0, 3);                                    /* EDIT value of a PERC track: dropped */
        pv_motion(&c, 0, 4, P_E0 + 7u, 9);                               /* dropped */
        pv_motion(&c, 0, 6, P_REL, 12);        /* common value: kept */
        pv_motion(&c, 1, 2, P_E0, 2);                                    /* SET 3: kept */
        pv_motion(&c, 2, 5, P_E0 + 3u, 22);                              /* dropped */
        pv_emit(&c, f, np, "SAMPLE PERC");
    }
    printf("\n  ],\n");
}

/* ------------------------------------------------------- user presets --- */
static void rv_rec_set(up_rec_t *r, uint32_t ver, uint32_t engine, const char *name, const int16_t *v, uint32_t np)
{
    uint32_t i;
    memset(r, 0, sizeof *r);
    r->used = UP_USED;
    r->ver = (uint8_t)ver;
    r->engine = (uint8_t)engine;
    r->np = (uint8_t)np;
    for (i = 0; name[i] && i < 12u; i++)
        r->name[i] = name[i];
    for (i = 0; i < np; i++)
        up_set_value(r, i, v[i]);
    for (i = 0; i < 16u; i++) {
        r->note[i] = (uint8_t)(i % 4u ? 0u : 48u + i);
        r->flags[i] = (uint8_t)(i % 8u ? 0u : 1u);
    }
}

typedef struct { const char *name, *retired; up_rec_t rec; } uv_case_t;
static uv_case_t uv[16];
static uint32_t uv_n;
static void uv_add(const char *name, const char *retired, uint32_t ver, uint32_t engine, const int16_t *v, uint32_t np)
{
    if (uv_n >= 16u)
        rv_die("too many preset cases for one bank", name);
    uv[uv_n].name = name;
    uv[uv_n].retired = retired;
    rv_rec_set(&uv[uv_n].rec, ver, engine, "VECTOR", v, np);
    uv[uv_n].rec.name[6] = (char)('A' + uv_n);
    uv_n++;
}

static void rv_track_state(const char *indent)
{
    track_t *t = TSEL;
    uint32_t tr = trk_index(t) % NTRK;
    printf("%s\"engine\": %u, \"preset\": %u, \"p\": ", indent, (unsigned)t->eng_req, (unsigned)t->preset);
    rv_hex16(t->p, P_COUNT);
    printf(", \"fm6_patch\": ");
    if (t->eng_req == ENGI_FM6)
        rv_hex(fm6_patch[tr], FP_SIZE + 1u);
    else
        printf("null");
}

static void rv_presets(void)
{
    static up_bank_t stored, migrated;
    static char dn[8][24];
    int16_t p[P_COUNT], e[8];
    uint32_t k, i, n = 0;
    uv_n = 0;
    for (k = 0; k < 8u; k++) {                           /* DIGITAL: a record keeps it as stored; every load converts */
        rv_digital_preset(p, k);
        snprintf(dn[k], sizeof dn[k], "DIGITAL preset %u", (unsigned)k);
        uv_add(dn[k], "DIGITAL", UP_VER, ENGI_DIGITAL, p, P_COUNT);
    }
    rv_digital_alg(p, 4, 2);
    uv_add("DIGITAL ALG 5, shaped OP ENV, noisy FDBK", "DIGITAL", UP_VER_GRID, ENGI_DIGITAL, p, P_COUNT);
    e[0] = 4; e[1] = 60; e[2] = 61; e[3] = 62; e[4] = 63; e[5] = 64; e[6] = 100; e[7] = 127;
    rv_with_e(p, e);
    uv_add("PHYS MODEL 4, KICK round, PERC top", "PHYS MODEL 4", UP_VER, ENGI_PHYS, p, P_COUNT);
    e[6] = 10; e[7] = 40;
    rv_with_e(p, e);
    uv_add("PHYS MODEL 4, KICK punch, PERC 40", "PHYS MODEL 4", UP_VER, ENGI_PHYS, p, P_COUNT);
    e[0] = 2;
    rv_with_e(p, e);
    uv_add("PHYS MODEL 2 (version 4: stays)", "PHYS MODEL 2", UP_VER, ENGI_PHYS, p, P_COUNT);
    e[0] = 4; e[1] = 11; e[2] = 12; e[3] = 13; e[4] = 14; e[5] = 15; e[6] = 16; e[7] = 17;
    rv_with_e(p, e);
    uv_add("SAMPLE set 4 PERC", "SAMPLE PERC", UP_VER, ENGI_SAMPLE, p, P_COUNT);
    e[0] = 3;
    rv_with_e(p, e);
    uv_add("SAMPLE set 3 (stays)", "SAMPLE PERC", UP_VER, ENGI_SAMPLE, p, P_COUNT);
    {   /* version 1: 16-bit values, 53 parameters (P_E0 = 45); PHYS MODEL 2 meant DUST */
        int16_t v[53];
        for (i = 0; i < 45u; i++)
            v[i] = (int16_t)(i % 7u);
        for (i = 0; i < 8u; i++)
            v[45u + i] = (int16_t)(2 + (i ? 20 + 3 * i : 0));
        uv_add("version 1 PHYS MODEL 2 = DUST", "PHYS MODEL 2", 1, ENGI_PHYS, v, 53);
    }
    memset(&stored, 0, sizeof stored);
    stored.magic = UP_BANK_MAGIC;
    stored.rsize = sizeof(up_rec_t);
    stored.nslot = UP_PER_BANK;
    for (k = 0; k < uv_n; k++)
        stored.r[k] = uv[k].rec;
    memcpy(&up_bank[0], &stored, sizeof stored);
    up_bank_check(0, (int)sizeof stored);                        /* the boot path: migrate the RAM mirror */
    memcpy(&migrated, &up_bank[0], sizeof migrated);
    printf("  \"presets\": [");
    for (k = 0; k < uv_n; k++) {
        const up_rec_t *r = &migrated.r[k];
        ui_power_on();
        memcpy(&up_bank[0], &migrated, sizeof migrated);
        track_select(0);
        if (up_load(k))
            rv_die("up_load", uv[k].name);
        rv_sep(&n);
        printf("    {\"name\": \"%s\", \"retired\": \"%s\", \"slot\": %u, \"ver\": %u, \"engine_in\": %u, \"engine_out\": %u,\n",
               uv[k].name, uv[k].retired, (unsigned)k, (unsigned)uv[k].rec.ver, (unsigned)uv[k].rec.engine,
               (unsigned)r->engine);
        printf("     \"input\": ");
        rv_hex(&uv[k].rec, sizeof uv[k].rec);
        printf(",\n     \"record_out\": ");
        rv_hex(r, sizeof *r);
        printf(",\n     \"loaded\": {");
        rv_track_state("");
        printf("}}");
    }
    printf("\n  ],\n");
}

/* --------------------------------------------------------- favourites --- */
typedef struct { uint8_t row; uint8_t bits[32]; } fv_row_t;
static void fv_rows_out(const uint8_t rows[][32], uint32_t nrows)
{
    uint32_t r, n = 0;
    static const uint8_t ZERO[32];
    putchar('{');
    for (r = 0; r < nrows; r++)
        if (memcmp(rows[r], ZERO, 32)) {
            printf("%s\"%u\": ", n++ ? ", " : "", (unsigned)r);
            rv_hex(rows[r], 32);
        }
    putchar('}');
}
static uint32_t fv_n;
static void fv_emit(const char *name, const char *retired, int per6, const uint8_t in_rows[FAV_ROWS][32])
{
    static persist_rec_t rec;
    static uint8_t in_copy[FAV_ROWS][32];
    uint32_t r, k, n = 0;
    int len, res;
    memset(&rec, 0, sizeof rec);
    rec.magic = per6 ? PERSIST_MAGIC_EXT : PERSIST_MAGIC;
    rec.palette = 0;
    rec.panel = PANEL_DEFAULT;
    for (r = 0; r < PERSIST_ROWS_V4; r++)
        memcpy(rec.favorites.factory[r], in_rows[r], 32);
    if (per6) {
        rec.x.ver = PERSIST_EXT_VER;
        rec.x.rows = FAV_ROWS;
        rec.x.ml_n = rec.x.dev_n = 32;
        for (r = 0; r < FAV_ROWS; r++)
            memcpy(rec.x.fav[r], in_rows[r], 32);
        len = (int)(sizeof(persist_t) + PERSIST_EXT_HDR + FAV_ROWS * 32u);
    } else {
        len = (int)sizeof(persist_t);
    }
    memcpy(in_copy, in_rows, sizeof in_copy);
    ui_power_on();
    res = settings_import((persist_t *)(void *)&rec, len);
    if (res != 1)
        rv_die("settings_import", name);
    rv_sep(&fv_n);
    printf("    {\"name\": \"%s\", \"retired\": \"%s\", \"format\": \"%s\",\n     \"rows_in\": ", name, retired,
           per6 ? "PER6" : "PER4");
    fv_rows_out(in_copy, per6 ? FAV_ROWS : PERSIST_ROWS_V4);
    printf(",\n     \"rows_out\": ");
    fv_rows_out(favorites.factory, FAV_ROWS);
    /* moved: DIGITAL preset k (row 1) -> FM6 preset FM4_TO_FM6[k]; SAMPLE PERC (row 4, bit 4) -> DRUM preset 0.
     * dropped: row 1's bits past the 8 factory presets (no sound to carry them to) */
    printf(",\n     \"moved\": [");
    for (k = 0; k < FM4_NPRESETS; k++)
        if ((in_copy[ENGI_DIGITAL][0] >> k) & 1u)
            printf("%s{\"from_row\": %u, \"from_bit\": %u, \"to_row\": %u, \"to_bit\": %u}", n++ ? ", " : "",
                   (unsigned)ENGI_DIGITAL, (unsigned)k, (unsigned)ENGI_FM6, (unsigned)FM4_TO_FM6[k]);
    if ((in_copy[ENGI_SAMPLE][0] >> SMP_SET_PERC) & 1u)
        printf("%s{\"from_row\": %u, \"from_bit\": %u, \"to_row\": %u, \"to_bit\": 0}", n++ ? ", " : "",
               (unsigned)ENGI_SAMPLE, (unsigned)SMP_SET_PERC, (unsigned)ENGI_DRUM);
    printf("],\n     \"dropped\": [");
    n = 0;
    for (k = FM4_NPRESETS; k < 256u; k++)
        if ((in_copy[ENGI_DIGITAL][k / 8u] >> (k % 8u)) & 1u)
            printf("%s{\"row\": %u, \"bit\": %u}", n++ ? ", " : "", (unsigned)ENGI_DIGITAL, (unsigned)k);
    printf("]}");
}

static void rv_favourites(void)
{
    static uint8_t rows[FAV_ROWS][32];
    uint32_t k, per6;
    fv_n = 0;
    printf("  \"favourites\": [");
    for (per6 = 0; per6 < 2u; per6++) {
        const char *f = per6 ? " (PER6)" : " (PER4)";
        static char nm[16][64];
        uint32_t ni = 0;
        for (k = 0; k < FM4_NPRESETS; k++) {                       /* each DIGITAL preset starred alone */
            memset(rows, 0, sizeof rows);
            rows[ENGI_DIGITAL][0] = (uint8_t)(1u << k);
            snprintf(nm[ni], sizeof nm[ni], "DIGITAL preset %u starred%s", (unsigned)k, f);
            fv_emit(nm[ni++], "DIGITAL", (int)per6, rows);
        }
        memset(rows, 0, sizeof rows);
        rows[ENGI_DIGITAL][0] = 0xFF;
        rows[ENGI_FM6][0] = 0x81;                                  /* FM6 stars already there stay */
        rows[ENGI_FM6][1] = 0x10;
        snprintf(nm[ni], sizeof nm[ni], "all 8 DIGITAL presets + FM6 stars%s", f);
        fv_emit(nm[ni++], "DIGITAL", (int)per6, rows);
        memset(rows, 0, sizeof rows);
        rows[ENGI_DIGITAL][0] = 0x05;
        rows[ENGI_DIGITAL][1] = 0x03;                              /* presets 8, 9: no DIGITAL sound: dropped */
        rows[ENGI_DIGITAL][31] = 0x80;                             /* 255 */
        snprintf(nm[ni], sizeof nm[ni], "DIGITAL bits past the 8 presets%s", f);
        fv_emit(nm[ni++], "DIGITAL", (int)per6, rows);
        memset(rows, 0, sizeof rows);
        rows[ENGI_SAMPLE][0] = 1u << SMP_SET_PERC;
        snprintf(nm[ni], sizeof nm[ni], "SAMPLE PERC starred alone%s", f);
        fv_emit(nm[ni++], "SAMPLE PERC", (int)per6, rows);
        memset(rows, 0, sizeof rows);
        rows[ENGI_SAMPLE][0] = (uint8_t)(1u << SMP_SET_PERC | 0x07u);
        rows[ENGI_DRUM][0] = 0x02;
        snprintf(nm[ni], sizeof nm[ni], "SAMPLE PERC + sets 0-2, DRUM preset 1 starred%s", f);
        fv_emit(nm[ni++], "SAMPLE PERC", (int)per6, rows);
        memset(rows, 0, sizeof rows);
        rows[ENGI_SAMPLE][0] = (uint8_t)(1u << 5);                 /* USR1: not retired */
        rows[ENGI_DRUM][0] = 0x01;
        snprintf(nm[ni], sizeof nm[ni], "SAMPLE USR1 + DRUM preset 0 (nothing retired)%s", f);
        fv_emit(nm[ni++], "none", (int)per6, rows);
        memset(rows, 0, sizeof rows);
        rows[ENGI_DIGITAL][0] = 0x03;
        rows[ENGI_SAMPLE][0] = (uint8_t)(1u << SMP_SET_PERC);
        rows[ENGI_DRUM][0] = 0x01;                                 /* DRUM preset 0 already starred: merged */
        snprintf(nm[ni], sizeof nm[ni], "DIGITAL 0-1 and SAMPLE PERC together, DRUM 0 starred%s", f);
        fv_emit(nm[ni++], "DIGITAL + SAMPLE PERC", (int)per6, rows);
    }
    printf("\n  ],\n");
}

/* ------------------------------------------------------------ load path --- */
static void rv_load_path(void)
{
    int16_t p[P_COUNT];
    uint32_t k, n = 0;
    printf("  \"load\": [");
    for (k = 0; k < 8u; k++) {                      /* a stored DIGITAL preset number (fm4_load_preset) */
        ui_power_on();
        track_select(0);
        fm4_load_preset(TSEL, k);
        rv_sep(&n);
        printf("    {\"via\": \"fm4_load_preset\", \"name\": \"DIGITAL preset %u\", \"input\": {\"preset\": %u},\n     \"track\": {",
               (unsigned)k, (unsigned)k);
        rv_track_state("");
        printf("}}");
    }
    for (k = 0; k < 8u; k++) {                      /* DIGITAL values (fm4_apply: up_load, project_restore, set_engine) */
        rv_digital_alg(p, k, k < 4u ? 0u : k < 6u ? 1u : 2u);
        ui_power_on();
        track_select(0);
        rv_sep(&n);
        printf("    {\"via\": \"fm4_apply\", \"name\": \"DIGITAL ALG %u values\", \"input\": {\"p\": ", (unsigned)(k + 1u));
        rv_hex16(p, P_COUNT);
        printf("},\n     \"track\": {");
        fm4_apply(TSEL, p, 0);
        rv_track_state("");
        printf("}, \"p_after_convert\": ");
        rv_hex16(p, P_COUNT);
        printf("}");
    }
    printf("\n  ]\n");
}

int main(void)
{
    ui_power_on();
    printf("{\n  \"schema\": 1,\n");
    printf("  \"about\": \"Retired-sound reference vectors (#299): generated by tests/retired_vectors.c from the firmware's own conversion code; "
           "bytes are hex, int16 values little-endian. Regenerate: python3 tests/retired_vectors.py --update\",\n");
    printf("  \"constants\": {\"P_COUNT\": %u, \"P_E0\": %u, \"P_FM1_ATK\": %u, \"P_FM4_LEVEL\": %u, \"P_ED_FLT\": %u, "
           "\"FP_SIZE\": %u, \"PROJ_STORE_SIZE\": %u, \"UP_REC_SIZE\": %u, \"ENGI_DIGITAL\": %u, \"ENGI_SAMPLE\": %u, "
           "\"ENGI_FM6\": %u, \"ENGI_PHYS\": %u, \"ENGI_DRUM\": %u, \"SMP_SET_PERC\": %u, \"PROJ_PHYS\": %u, "
           "\"PROJ_DEF_KEEP\": %u, \"FX_DEF\": ",
           (unsigned)P_COUNT, (unsigned)P_E0, (unsigned)P_FM1_ATK, (unsigned)P_FM4_LEVEL, (unsigned)P_ED_FLT,
           (unsigned)FP_SIZE, (unsigned)PROJ_STORE_SIZE, (unsigned)sizeof(up_rec_t), (unsigned)ENGI_DIGITAL,
           (unsigned)ENGI_SAMPLE, (unsigned)ENGI_FM6, (unsigned)ENGI_PHYS, (unsigned)ENGI_DRUM, (unsigned)SMP_SET_PERC,
           (unsigned)PROJ_PHYS, (unsigned)PROJ_DEF_KEEP);
    rv_ints(FX_DEF, 4);
    printf(", \"FM4_TO_FM6\": ");
    rv_ints(FM4_TO_FM6, FM4_NPRESETS);
    printf(", \"DRUM_KIT_E\": ");
    {
        static const int16_t KIT[8] = DRUM_KIT_E;
        uint8_t b[8];
        uint32_t i;
        for (i = 0; i < 8u; i++)
            b[i] = (uint8_t)KIT[i];
        rv_ints(b, 8);
    }
    printf("},\n");
    rv_projects();
    rv_presets();
    rv_favourites();
    rv_load_path();
    printf("}\n");
    return 0;
}
