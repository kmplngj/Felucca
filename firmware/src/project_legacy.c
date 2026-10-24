/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The transitional legacy seam of the project codec (#300, project_codec.h): every reader of a stored project older
 * than today's, moved here unchanged from project.c. The codec calls it through one hook, proj_decode_legacy, for any
 * record proj_classify does not call CURRENT; its result then takes the same steps as a current record
 * (proj_engines_ok, the retired sounds, proj_bound: project_codec.c proj_decode). #456 stage 2b deletes this file, its
 * include at the end of project_codec.c and that one call; the identification table (project_codec.c PROJ_FORMATS)
 * stays, so the raw export still names these formats LEGACY. Fixtures: tests/project_test.c, tests/fun10_test.c,
 * tests/old_pack.h, tests/backup_test.c; docs/legacy-formats.md. */
/* Format 7 ("FUN7", written) stores P_COUNT (byte 66) and maps an older count as user presets do: FUN7 of
 * 89 parameters (before the chord keys P_CHRD / P_VOIC) loads its engine values at today's P_E0..P_E7,
 * the chord keys OFF / CLOSE, and its motion events' ids from its P_E0 on move up with them (proj_motion_ids).
 * 68 + 4 x (91 + 2 + 64 x 9) + chain + motion = 3040 of the 3372 bytes before the name: 332 spare, room for
 * 83 more track parameters (4 bytes each).
 * Format 6 ("FUN6") adds a 36-byte song chain before the checksum.
 * Format 5 ("FUN5", read only) = format 4 with the drum grid: a step is 10 bytes (step_t: its lane hits and
 * their accents after the 8 bytes it was), and each track has 40 reserved bytes (lane[8][5], written 0: room
 * for per-lane sounds of the DRUM engine). 4 ("FUN4": PROJ_NP_V4 parameters, the modulation matrix), 3
 * ("FUN3": PROJ_NP_V3, the SLICER), 2 ("FUN2") and 1 ("FUN1": PROJ_NP_V2) are read and converted, mapped by
 * count as user presets are (the first np - 8 are P_LEVEL.. in order, the last 8 P_E0..P_E7; the
 * parameters added since take their defaults: the SLICER OFF, every matrix slot OFF). Their steps get no
 * hits; on a DRUM track their notes that are a lane's note become its hits (proj_grid: the same notes and
 * velocities play, the grid shows them as its own).
 * Their engine bytes are kept: formats 1 and 2 had engines 0..7 (ANALOG .. WHEEL), and the engines
 * added since (SLICE 8, ..) were appended, no index moved.
 *
 * Track 4 was the GM drum part until 1.0 (no engine: its byte 0; its level and reverb send in the
 * globals G_DRLVL / G_DRREV, which are inert now). A project says which it has in `parts`: NPART
 * when written since, 0 before (a reserved byte, always written 0: the format and its size did not
 * change). proj_drums_to_part turns such a track 4 into a DRUM part with its default kit (the GM map, so
 * its drum steps still play drums; until 1.0.2 it was the SAMPLE engine's PERC set), keeping its steps, its
 * pattern and mix parameters (LEN DIV SWING GATE, PAN MUTE), its SLICER, and the drum level and reverb send
 * as LEVEL and REV.
 *
 * The byte `phys` (reserved, always 0, before 1.0) says what a PHYS track's MODEL means: 0 MODEL 2 was
 * DUST (dropped: it loads as MODAL bowed, eng_phys.c phys_legacy); 1 MODEL 4 was DRUM (the kit is the DRUM
 * engine since: such a track loads as DRUM, core.h drum_from_phys); 2 (PROJ_PHYS) as today. proj_phys.
 *
 * Format 8 ("FUN8", written since 1.0) = FUN7 with each track's FM6 patch (eng_fm6.c, the 128-byte packed
 * record, 4 x 128 bytes just before the name): a project is self-contained. On load an FM6 track's SLOT shows F n
 * when its patch is that factory one, else OWN (eng_fm6.c fm6_adopt; a stored 9..40, the B slots of the patch bank
 * before 1.0.3 or of 1.4.1's voice bank, is OWN too: the project has the patch).
 * It is 3584 bytes (FUN7: 3388); FUN7 is read (its tracks get the init patch). The retained cache (proj_slot,
 * .noinit) grew with it: after an update its slot 1 still starts with a FUN7 record, which is read; the other
 * slots fail their hash and come back from flash (persist_boot).
 *
 * Format 9 ("FUN9", written since 1.1) = FUN8 with 64 more bytes: the DRUM lane levels (P_LN0..P_LN7, #97) made
 * P_COUNT 99 (P_E0 91), and 68 + 4 x (99 + 2 + 576) + chain + motion = 3072 no longer fit before FUN8's patches
 * (3056). 3648 bytes, the patches at PROJ_FM6_OFF (3120): 48 spare, room for 12 more track parameters. FUN8 (3584,
 * its 91 parameters mapped by count: the lane levels 100 %) and FUN7 are read; the retained cache grew again (its
 * slot 1 still starts with the older record, read as above).
 */
#define PROJ_NP_V2 53u                         /* P_COUNT of formats 1 and 2 (P_E0 was 45) */
#define PROJ_NG_V2 27u                         /* G_COUNT of formats 1 and 2 */
#define PROJ_NP_V3 57u                         /* P_COUNT of format 3 (P_E0 was 49) */
#define PROJ_NP_V4 69u                         /* P_COUNT of format 4 (P_E0 61) */
/* Historical FUN5/6 types are frozen, independent of today's P_COUNT/step_t. */
typedef struct { uint8_t note[4], n, time, flags, vel, hit, acc; } step10_t;
typedef struct { int16_t p[69]; uint8_t engine, preset; step10_t step[NSTEP]; uint8_t lane[NLANE][5]; } proj_trk_v5_t;
typedef struct {                               /* format 5, before the song chain */
    uint32_t magic, size;
    int16_t g[G_COUNT];
    uint8_t sel, parts, phys, rsv;
    proj_trk_v5_t t[NTRK];
    uint32_t sum;
} project_v5_t;
typedef struct { uint32_t magic, size; int16_t g[G_COUNT]; uint8_t sel, parts, phys, rsv;
    proj_trk_v5_t t[NTRK]; chain_v9_t chain; uint32_t sum; } project_v6_t;
_Static_assert(sizeof(project_v5_t) == 3352u && sizeof(project_v6_t) == 3388u, "frozen formats 5 / 6 sizes");
_Static_assert(PROJ_STORE_V7 == sizeof(project_v6_t) && PROJ_STORE_V6 == sizeof(project_v6_t) &&
               PROJ_STORE_V5 == sizeof(project_v5_t), "FUN7 / FUN6 / FUN5 sizes (project_codec.c PROJ_FORMATS)");
typedef struct {                               /* a track of format 4, read only */
    int16_t p[PROJ_NP_V4];
    uint8_t engine, preset;
    step8_t step[NSTEP];
} proj_trk_v4_t;
typedef struct {                               /* format 4 (1.0 development builds), read only */
    uint32_t magic, size;
    int16_t g[G_COUNT];
    uint8_t sel, parts, phys, rsv;
    proj_trk_v4_t t[NTRK];
    uint32_t sum;
} project_v4_t;
typedef struct {                               /* a track of format 3, read only */
    int16_t p[PROJ_NP_V3];
    uint8_t engine, preset;
    step8_t step[NSTEP];
} proj_trk_v3_t;
typedef struct {                               /* format 3 (0.9 .. 1.0), read only */
    uint32_t magic, size;
    int16_t g[G_COUNT];
    uint8_t sel, parts, rsv[2];
    proj_trk_v3_t t[NTRK];
    uint32_t sum;
} project_v3_t;
typedef struct {                               /* a track of formats 1 and 2, read only */
    int16_t p[PROJ_NP_V2];
    uint8_t engine, preset;
    step8_t step[NSTEP];
} proj_trk_v2_t;
typedef struct {                               /* format 2 (until 0.9), read only */
    uint32_t magic, size;
    int16_t g[PROJ_NG_V2];
    uint8_t sel, rsv[3];
    proj_trk_v2_t t[NTRK];
    uint32_t sum;
} project_v2_t;
typedef struct {                               /* format 1 (until 0.5 beta), read only */
    uint32_t magic, size;
    int16_t g[PROJ_NG_V2];
    proj_trk_v2_t t;
    uint32_t sum;
} project_v1_t;
_Static_assert(sizeof(project_v2_t) == 2552u && sizeof(project_v1_t) == 688u && sizeof(project_v3_t) == 2584u &&
               sizeof(project_v4_t) == 2680u, "formats 1 / 2 / 3 / 4 as they were stored");
_Static_assert(PROJ_STORE_V4 == sizeof(project_v4_t) && PROJ_STORE_V3 == sizeof(project_v3_t) &&
               PROJ_STORE_V2 == sizeof(project_v2_t) && PROJ_STORE_V1 == sizeof(project_v1_t), "PROJ_FORMATS sizes");

/* G_RTYPE (id 24) was G_DRCH, the GM drum part's MIDI channel (0..16, 10 by default) until 1.0: a project of a
 * format before FUN7 may hold any channel there. FUN7 came after it was inert (always 0), so only those imports
 * set it: ROOM, the only reverb they knew */
static void proj_rtype_room(int16_t *g) { g[G_RTYPE] = 0; }

/* the globals of formats 1 and 2 (G_* unchanged since; any added later: their defaults) */
static void proj_g_from_v2(int16_t *g, const int16_t *g2)
{
    uint32_t i;
    for (i = 0; i < G_COUNT; i++)
        g[i] = i < PROJ_NG_V2 ? g2[i] : GP[i].def;
    proj_rtype_room(g);
}

/* np stored parameters, engine, preset and steps of an older track -> today's, mapped by count (see the top);
 * the steps without hits */
static void proj_trk_from(proj_trk_t *d, const int16_t *p, uint32_t np, uint8_t engine, uint8_t preset, const step8_t *step)
{
    int16_t def[P_E0];
    uint32_t k;
    for (k = 0; k < P_E0; k++)
        def[k] = TP[k].def;
    params_by_count(d->p, p, np, def);
    d->engine = engine;                         /* (indices 0..7 of formats 1 and 2 as they were) */
    d->preset = preset;
    for (k = 0; k < NSTEP; k++) {
        step_t *s = &d->step[k];
        memcpy(s->note, step[k].note, 4);
        s->n = step[k].n;
        s->time = step[k].time;
        s->flags = step[k].flags & 3u;          /* accent, slide: x1 (no RATCH then) */
        s->vel = step[k].vel;
        s->hit = s->acc = 0;
    }
}

/* the DRUM tracks of a project of before the grid: their lanes' notes as hits (see the top) */
static void proj_grid(project_t *q)
{
    uint32_t k, i;
    for (k = 0; k < NTRK; k++)
        if (q->t[k].engine == ENGI_DRUM)
            for (i = 0; i < NSTEP; i++)
                step_to_grid(&q->t[k].step[i]);
    q->sum = proj_sum(q);
}
static void proj_trk_from_v2(proj_trk_t *d, const proj_trk_v2_t *s)
{
    proj_trk_from(d, s->p, PROJ_NP_V2, s->engine, s->preset, s->step);
}

/* a project written with the GM drum part as track 4 (parts 0) -> track 4 a part (see the top);
 * project_load gives it DRUM's kit (PROJ_DEF_KEEP; the SAMPLE PERC sound until 1.0.2). Idempotent */
static void proj_drums_to_part(project_t *q)
{
    proj_trk_t *d = &q->t[NTRK - 1u];
    if (q->parts == NPART)
        return;
    d->engine = ENGI_DRUM;                      /* DRUM's first kit: independent of today's power-on drum sound */
    d->preset = PROJ_DEF_KEEP;
    d->p[P_LEVEL] = (int16_t)clamp(q->g[G_DRLVL], 0, 127);   /* the drum part's level and reverb send */
    d->p[P_REV] = (int16_t)clamp(q->g[G_DRREV], 0, 127);
    q->parts = NPART;
    q->sum = proj_sum(q);
}

/* PHYS tracks of a project written before PROJ_PHYS (see the top) -> today's: DUST as MODAL bowed, MODEL
 * DRUM as the DRUM engine (its E values moved, the preset its first). Idempotent */
static void proj_phys(project_t *q)
{
    uint32_t k;
    if (q->phys >= PROJ_PHYS)
        return;
    for (k = 0; k < NTRK; k++) {
        proj_trk_t *d = &q->t[k];
        if (d->engine != ENGI_PHYS)
            continue;
        if (!q->phys)
            phys_legacy(&d->p[P_E0]);
        if (drum_from_phys(d->engine, &d->p[P_E0])) {
            d->engine = ENGI_DRUM;
            d->preset = 0;
        }
    }
    q->phys = PROJ_PHYS;
    q->sum = proj_sum(q);
}

/* a format 4 project (n bytes in *v4) -> slot q as format 6 */
static int proj_from_v4(project_t *q, const project_v4_t *v4, int n)
{
    uint32_t i;
    if (n != (int)sizeof *v4 || v4->magic != PROJ_MAGIC_V4 || v4->size != sizeof *v4 ||
        v4->sum != proj_hash(v4, sizeof *v4 - 4u))
        return 0;
    memset(q, 0, sizeof *q);
    q->magic = PROJ_MAGIC;
    q->size = sizeof *q;
    memcpy(q->g, v4->g, sizeof q->g);
    proj_rtype_room(q->g);
    q->sel = v4->sel;
    q->parts = v4->parts;
    q->phys = v4->phys;
    for (i = 0; i < NTRK; i++)
        proj_trk_from(&q->t[i], v4->t[i].p, PROJ_NP_V4, v4->t[i].engine, v4->t[i].preset, v4->t[i].step);
    q->sum = proj_sum(q);
    proj_drums_to_part(q);
    return 1;
}

/* a format 3 project (n bytes in *v3) -> slot q as format 6 */
static int proj_from_v3(project_t *q, const project_v3_t *v3, int n)
{
    uint32_t i;
    if (n != (int)sizeof *v3 || v3->magic != PROJ_MAGIC_V3 || v3->size != sizeof *v3 ||
        v3->sum != proj_hash(v3, sizeof *v3 - 4u))
        return 0;
    memset(q, 0, sizeof *q);
    q->magic = PROJ_MAGIC;
    q->size = sizeof *q;
    memcpy(q->g, v3->g, sizeof q->g);
    proj_rtype_room(q->g);
    q->sel = v3->sel;
    q->parts = v3->parts;
    for (i = 0; i < NTRK; i++)
        proj_trk_from(&q->t[i], v3->t[i].p, PROJ_NP_V3, v3->t[i].engine, v3->t[i].preset, v3->t[i].step);
    q->sum = proj_sum(q);
    proj_drums_to_part(q);                     /* (a format 3 of firmware before 1.0: parts 0) */
    return 1;
}

/* a format 2 project (n bytes in *v2) -> slot q as format 6 */
static int proj_from_v2(project_t *q, const project_v2_t *v2, int n)
{
    uint32_t i;
    if (n != (int)sizeof *v2 || v2->magic != PROJ_MAGIC_V2 || v2->size != sizeof *v2 ||
        v2->sum != proj_hash(v2, sizeof *v2 - 4u))
        return 0;
    memset(q, 0, sizeof *q);
    q->magic = PROJ_MAGIC;
    q->size = sizeof *q;
    proj_g_from_v2(q->g, v2->g);
    q->sel = v2->sel;
    for (i = 0; i < NTRK; i++)
        proj_trk_from_v2(&q->t[i], &v2->t[i]);
    proj_drums_to_part(q);                     /* (format 2 had the drum track: parts 0) */
    return 1;
}

/* a format 1 project (n bytes in *v1) -> slot q as format 6: the instrument becomes track 1,
 * tracks 2..4 start empty (their sounds as at power-on) */
static int proj_from_v1(project_t *q, const project_v1_t *v1, int n)
{
    uint32_t i;
    if (n != (int)sizeof *v1 || v1->magic != PROJ_MAGIC_V1 || v1->size != sizeof *v1 ||
        v1->sum != proj_hash(v1, sizeof *v1 - 4u))
        return 0;
    memset(q, 0, sizeof *q);
    q->magic = PROJ_MAGIC;
    q->size = sizeof *q;
    proj_g_from_v2(q->g, v1->g);
    q->parts = NPART;                          /* (format 1 had no track 4) */
    proj_trk_from_v2(&q->t[0], &v1->t);
    for (i = 1; i < NTRK; i++) {               /* the other tracks: their defaults, no steps */
        uint32_t k;
        for (k = 0; k < P_COUNT; k++)
            q->t[i].p[k] = param_desc_of(trk_def_engine(i), k)->def;
        q->t[i].engine = (uint8_t)trk_def_engine(i);
        q->t[i].preset = PROJ_DEF_SOUND;
        for (k = 0; k < NSTEP; k++)
            q->t[i].step[k].time = ST_REST;
    }
    q->sum = proj_sum(q);
    return 1;
}

static int proj_unpack(project_t *q, const uint8_t *b, uint32_t size);
/* the init patch on every track (a project of a format before FUN8) */
static void proj_fm6_init(project_t *q)
{
    uint32_t t;
    for (t = 0; t < NTRK; t++)
        memcpy(q->fm6[t], FM6_INIT, FM6_PACKED);
    q->sum = proj_sum(q);
}
static int proj_import_old(project_t *q, const void *b, int n)
{
    if (n == (int)sizeof(project_v5_t) || n == (int)sizeof(project_v6_t)) {
        const project_v5_t *v = b;
        const project_v6_t *v6 = b;
        uint32_t bytes = n, i, k;
        chain_config_t c6;
        if (((bytes == sizeof *v && v->magic == PROJ_MAGIC_V5) ||
             (bytes == sizeof *v6 && v->magic == PROJ_MAGIC_V6 && chain_from_v9(&c6, &v6->chain))) &&
            v->size == bytes && ((const uint32_t *)b)[bytes / 4u - 1u] == proj_hash(b, bytes - 4u)) {
            memset(q, 0, sizeof *q);
            q->magic = PROJ_MAGIC; q->size = sizeof *q;
            memcpy(q->g, v->g, sizeof q->g);
            proj_rtype_room(q->g);
            q->sel = v->sel; q->parts = v->parts; q->phys = v->phys;
            for (i = 0; i < NTRK; i++) {
                int16_t def[P_COUNT];
                if (v->t[i].engine >= ENG_ID_MAX) return 0;
                for (k = 0; k < P_COUNT; k++) def[k] = param_desc_of(eng_idx(v->t[i].engine), k)->def;
                params_by_count(q->t[i].p, v->t[i].p, 69u, def);
                q->t[i].engine = v->t[i].engine; q->t[i].preset = v->t[i].preset;
                for (k = 0; k < NSTEP; k++) {
                    memcpy(&q->t[i].step[k], &v->t[i].step[k], sizeof(step10_t));
                    q->t[i].step[k].flags &= 3u;       /* (x1: no RATCH then) */
                }
            }
            if (bytes == sizeof *v6) q->chain = c6; else chain_defaults(&q->chain);
            q->sum = proj_sum(q); proj_drums_to_part(q); proj_phys(q);
            return 1;
        }
    }
    if (proj_from_v4(q, (const project_v4_t *)b, n) || proj_from_v3(q, (const project_v3_t *)b, n) ||
        proj_from_v2(q, (const project_v2_t *)b, n) || proj_from_v1(q, (const project_v1_t *)b, n)) {
        proj_phys(q);                          /* (formats 1..3 had no PHYS track: only the byte) */
        proj_grid(q);                          /* (after it: a PHYS DRUM track is DRUM now) */
        return 1;
    }
    return 0;
}

/* the motion of a FUN7 / FUN8 written with np parameters (np < P_COUNT: a FUN7 of 89 before the chord keys, every
 * FUN8 of 91 before the DRUM lane levels) -> today's ids: an event names a parameter id, and the ids from that
 * store's P_E0 (np - 8) on moved up with P_E0, as its values did (params_by_count); the ones below kept theirs. A
 * lock's bit 7 (MOTION_LOCK) stays: the id moves under it (a FUN8 / FUN7 of a 1.1 development build may hold
 * locks). 0: an id that store could not have named (np or more) */
static int proj_motion_ids(motion_store_t *m, uint32_t np)
{
    uint32_t i;
    for (i = 0; i < m->count && i < MOTION_MAX; i++) {
        uint32_t id = MOTION_ID(&m->event[i]);
        if (id >= np) return 0;
        if (np < P_COUNT && id >= np - 8u)
            m->event[i].param = (uint8_t)((m->event[i].param & MOTION_LOCK) | (id + P_COUNT - np));
    }
    return 1;
}
/* the motion block of a FUN7 / FUN8 / FUN9 (PROJ_MOTION_V9 bytes at b: count, on, 2 reserved, 64 x (place, id, i16
 * value LE)) -> m: its records as they are (values -64..127, as motion_valid wanted then), the rest 0. 0: not one */
static int proj_motion_v9(motion_store_t *m, const uint8_t *b)
{
    uint32_t i;
    memset(m, 0, sizeof *m);
    if (b[0] > 64u)
        return 0;
    m->count = b[0];
    m->on = b[1];
    for (i = 0; i < m->count; i++) {
        const uint8_t *e = b + 4u + 4u * i;
        int32_t v = (int16_t)(e[2] | e[3] << 8);
        if (v < -64 || v > 127)
            return 0;
        m->event[i].place = e[0];
        m->event[i].param = e[1];
        m->event[i].value = (int8_t)v;
    }
    return 1;
}
/* a stored FUN10 (st = PROJ_STORE_SIZE), FUN9 (PROJ_STORE_V9: 64 motion records of 4 bytes, no nudges), FUN8
 * (PROJ_STORE_V8: FUN9 with its tail 64 bytes shorter) or FUN7 (PROJ_STORE_V7: no patches, the init one) */
static int proj_unpack(project_t *q, const uint8_t *b, uint32_t st)
{
    uint32_t pos, t, i, magic, size, sum, np = b[66], v7 = st == PROJ_STORE_V7, v10 = st == PROJ_STORE_SIZE;
    uint32_t name_off = st - 4u - PROJ_NAME_LEN, end = v7 ? name_off : name_off - NTRK * FM6_PACKED;
    uint32_t mot = v10 ? sizeof q->motion : PROJ_MOTION_V9, chn = v10 ? sizeof q->chain : sizeof(chain_v9_t);
    memcpy(&magic, b, 4); memcpy(&size, b + 4, 4); memcpy(&sum, b + st - 4u, 4);
    if (magic != (v7 ? PROJ_MAGIC_V7 : st == PROJ_STORE_V8 ? PROJ_MAGIC_V8 : st == PROJ_STORE_V9 ? PROJ_MAGIC_V9 : PROJ_MAGIC) ||
        size != st || sum != proj_hash(b, st - 4u) ||
        np < 8u || np > P_COUNT || 68u + NTRK * (np + 2u + NSTEP * 9u) + chn + mot > end)
        return 0;
    memset(q, 0, sizeof *q); q->magic = PROJ_MAGIC; q->size = sizeof *q;
    memcpy(q->g, b + 8, sizeof q->g); q->sel = b[62]; q->parts = b[63]; q->phys = b[64];
    if (v7 && (q->g[G_RTYPE] < 0 || q->g[G_RTYPE] > 1))   /* a FUN7 may still hold the old drum channel there */
        proj_rtype_room(q->g);
    pos = proj_unpack_tracks(q, b, np, v10);            /* (project_codec.c: the tracks, as FUN10's) */
    if (!pos) return 0;
    if (v10)                                            /* (FUN10: sections, a slot per track; before: rows) */
        memcpy(&q->chain, b + pos, sizeof q->chain);
    else {
        chain_v9_t c9;
        memcpy(&c9, b + pos, sizeof c9);
        if (!chain_from_v9(&q->chain, &c9)) return 0;
    }
    pos += chn;
    if (v10)
        memcpy(&q->motion, b + pos, sizeof q->motion);
    else if (!proj_motion_v9(&q->motion, b + pos))
        return 0;
    if (!proj_motion_ids(&q->motion, np) || !chain_valid(&q->chain) || !motion_valid(&q->motion)) return 0;
    if (v10)
        proj_unpack_tail(q, b);                         /* (project_codec.c: MIDI, patches, name, hash, as FUN10's) */
    else {                                              /* (FUN9..FUN7 have no MIDI IN TRACK) */
        for (t = 0; t < NTRK; t++) {
            if (v7)
                memcpy(q->fm6[t], FM6_INIT, FM6_PACKED);
            else
                for (i = 0; i < FM6_PACKED; i++)
                    q->fm6[t][i] = b[end + t * FM6_PACKED + i] & 0x7Fu;
        }
        {
            char n[PROJ_NAME_LEN + 1u];
            memcpy(q->name, n, proj_name_get(n, b + name_off));
        }
        q->sum = proj_sum(q);
    }
    proj_drums_to_part(q); proj_phys(q);
    return 1;
}

/* the hook: n bytes of a stored project of any older format -> q as today's, not bounded; 0 = not one. A FUN10 too
 * (proj_classify did not call it CURRENT: fewer parameters, the pre-1.0 header bytes, or no project at all), and the
 * retained .noinit slot holding an older, shorter record (its own size word) */
int proj_decode_legacy(project_t *q, const void *b, int n)
{
    if (n == PROJ_STORE_SIZE && ((const uint32_t *)b)[0] == PROJ_MAGIC)
        return proj_unpack(q, b, PROJ_STORE_SIZE);
    if (n == PROJ_STORE_SIZE && ((const uint32_t *)b)[1] >= 8u && ((const uint32_t *)b)[1] < PROJ_STORE_SIZE)
        n = (int)((const uint32_t *)b)[1];      /* a retained slot holding an older, shorter record: its own size
                                                 * (every format checks its magic and hash) */
    if (n == (int)PROJ_STORE_V9 && ((const uint32_t *)b)[0] == PROJ_MAGIC_V9)
        return proj_unpack(q, b, PROJ_STORE_V9);
    if (n == (int)PROJ_STORE_V8 && ((const uint32_t *)b)[0] == PROJ_MAGIC_V8)
        return proj_unpack(q, b, PROJ_STORE_V8);
    if (n == (int)PROJ_STORE_V7 && ((const uint32_t *)b)[0] == PROJ_MAGIC_V7)
        return proj_unpack(q, b, PROJ_STORE_V7);
    if (n == (int)sizeof *q && proj_ok((const project_t *)b)) {
        memcpy(q, b, sizeof *q);
        proj_drums_to_part(q);
        proj_phys(q);
        return 1;
    }
    if (!proj_import_old(q, b, n))
        return 0;
    proj_fm6_init(q);
    return 1;
}
