/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The project record codec (#300; interface and contract: project_codec.h). Stored bytes -> project_t (proj_decode) and
 * back (proj_encode); slots, flash, autosave timing and the runtime (capture / restore) stay in project.c. The readers
 * of older formats are behind one hook in project_legacy.c, included at the end.
 *
 * Format 10 ("FUNA", written since 1.2; FUN10 in the docs) = FUN9 laid out the same way, 3840 bytes (a whole storage
 * object, storage.c ST_PAYLOAD_MAX), for four changes made together:
 *   - P_COUNT 104 (P_E0 96): LFO 2's SYNC TRIG POL, QUANTIZE and SPREAD (P_LSYNC .. P_SPRD) before the engine
 *     values. SPREAD (#148) came before FUN10's release, into the spare bytes below: a FUN10 of a 1.2 build before
 *     it holds 103 (byte 66) and loads by count (SPREAD 0, its engine values and their motion moved up by one);
 *   - 128 motion records (core.h MOTION_MAX, 64 before), 3 bytes each (place, id, the value as an int8_t: the values
 *     were always -64..127): the block is 4 + 384 = 388 bytes (FUN9's 260 held 64 of 4 bytes);
 *   - each step's NUDGE (core.h step_nudge, -8..+7) in bit 7 of its four note bytes (bit j in note j), bits every
 *     earlier format wrote 0: the step stays 9 bytes;
 *   - the song's sections (core.h chain_row_t): a slot per track (A..D or "-") and the repeats, 5 bytes a row: the
 *     chain is 4 + 16 x 5 = 84 bytes (FUN6..FUN9: 36, rows {slot, repeat}, chain_v9_t; they load as sections with the
 *     four tracks on the row's slot, song_chain.c chain_from_v9: the same song).
 * 68 + 4 x (104 + 2 + 576) + chain + motion = 3268; the patches at PROJ_FM6_OFF (3312): 44 spare, room for 11 more
 * track parameters. 1.5 took seven of them (no format change, FUN10 as it was): the INSERT (P_ITYPE .. P_IMIX, 96..100),
 * ANALOG's filter TYPE (P_FTYPE, 101) and ENV SYNC (P_ESYNC, 102), before the engine values (P_COUNT 111, P_E0 103; 16
 * spare, room for 4). A FUN10 of 1.2 .. 1.4 (104) loads by count: the INSERT OFF, TYPE LP, ENV SYNC OFF (as they
 * played), its engine values and their motion moved up by seven.
 * Firmware 1.2 .. 1.4 refuses a FUN10 of more parameters than its own (np > P_COUNT): a 1.5 project shows EMPTY there. FUN9 / FUN8 / FUN7 load as before (their 64 records of 4 bytes read by proj_motion_v9, every
 * step's nudge 0: the timing they always had; parameters mapped by count, the four new ones at their defaults:
 * SYNC OFF, TRIG NOTE, POL BI, QUANTIZE ON, SPREAD 0, which play as before 1.2), and so do FUN6..FUN1. Firmware before 1.2
 * refuses a FUN10 everywhere (its size and magic are no format it knows): a slot holding one shows EMPTY there (the
 * flash copy stays until that slot is saved over), a backup PUT of one is refused (rc 1), the retained RAM copy of
 * one fails its checks.
 *
 * Parameter locks (1.1, core.h MOTION_LOCK) are motion records with bit 7 of their id byte set (P_COUNT 99 < 128:
 * the bit is free): no byte moved for them, and every project before 1.1 has none. FUN9 holds them. A FUN8 / FUN7
 * record of a 1.1 development build may hold some: on load their ids move to today's positions as the others do,
 * the lock bit kept (proj_motion_ids). Firmware before 1.1 refuses a project that holds a lock (an id out of its
 * range), as with RATCH below; FUN9 it refuses anyway (a newer format).
 *
 * A step's RATCH (core.h SF_RATCH, the hits - 1, 0..3) is in bit 7 of its velocity byte (bit 0) and of its chance
 * byte (bit 1) of FUN7 / FUN8: bits every firmware before wrote 0, so every older project loads with its steps x1,
 * and no format or size changed. Firmware before RATCH refuses a project that holds a ratchet (those bytes out
 * of their range), as it would a newer format. FUN6..FUN1 have none (x1).
 *
 * DIGITAL (engine 1) was retired in 1.0 (fm4_convert.c): a track of it, in any format, loads as FM6 with the
 * patch converted from its values as the track's own (proj_fm4, on every import; the stored record keeps what it
 * holds until saved again). Its motion events on the EDIT or OP ENV values are dropped.
 *
 * SAMPLE's SET 4, PERC (the GM drum kit), was retired after 1.0.2: a SAMPLE track that selects it, in any
 * format, loads as the DRUM engine with its default kit (core.h drum_from_perc: the same GM key map, its steps
 * as they are, the rest of its sound kept; proj_perc, on every import as proj_fm4). Its motion events on the
 * EDIT values are dropped (SAMPLE's meanings, not DRUM's).
 *
 * Built on the host without the UI (tests/project_test.c, tests/fuzz_proj.c: -DPROJ_HOST, core.h, params.c (TP),
 * engines.c, song_chain.c, motion.c through tests/hostsim.c). */
#include "project_codec.h"
#define PROJ_MAGIC_V9 0x46554E39u              /* "FUN9": FUN8, 64 bytes longer (the DRUM lane levels, 99 parameters) */
#define PROJ_MAGIC_V8 0x46554E38u              /* "FUN8": FUN7 + the tracks' FM6 patches */
#define PROJ_MAGIC_V7 0x46554E37u              /* "FUN7": serialized (byte params, packed steps), chain, motion */
#define PROJ_MAGIC_V6 0x46554E36u              /* FUN6: 69 parameters, drum grid, chain */
#define PROJ_MAGIC_V5 0x46554E35u              /* "FUN5": the grid, without the chain; read only */
#define PROJ_MAGIC_V4 0x46554E34u              /* "FUN4": four tracks, PROJ_NP_V4 parameters, 8-byte steps; read only */
#define PROJ_MAGIC_V3 0x46554E33u              /* "FUN3": four tracks, PROJ_NP_V3 parameters; read only */
#define PROJ_MAGIC_V2 0x46554E32u              /* "FUN2": four tracks, PROJ_NP_V2 parameters; read only */
#define PROJ_MAGIC_V1 0x46554E31u              /* "FUN1": one instrument; loads into track 1 */
#define PROJ_STORE_V9 3648u                    /* FUN9 */
#define PROJ_MOTION_V9 260u                    /* the motion block of FUN7..FUN9: 64 x (place, id, i16 value) */
#define PROJ_STORE_V8 3584u                    /* FUN8 */
#define PROJ_STORE_V7 3388u                    /* FUN7 */
#define PROJ_STORE_V6 3388u                    /* FUN6 (project_legacy.c project_v6_t) */
#define PROJ_STORE_V5 3352u                    /* FUN5 */
#define PROJ_STORE_V4 2680u                    /* FUN4 */
#define PROJ_STORE_V3 2584u                    /* FUN3 */
#define PROJ_STORE_V2 2552u                    /* FUN2 */
#define PROJ_STORE_V1 688u                     /* FUN1 */
/* Serialized FUN7 keeps the retained cache's exact extent. Params are biased
 * bytes, steps pack n/time/flags. Reserved tail is zero and covered by hash.
 * The tail's last 12 bytes (PROJ_NAME_OFF, just before the hash) are the project's name since 1.0:
 * ASCII 32..126 (upper case), 0-padded, all 0 = no name ("PROJECT A"). Firmware before wrote them 0 and
 * never reads them, so every FUN7 file stays valid both ways; FUN6..FUN1 imports get no name.
 * FUN8: the same, 3584 bytes, the four packed FM6 patches at PROJ_FM6_OFF (before the name); 16 bytes of the
 * reserved tail were left for parameters added later. FUN9: the same, 3648 bytes (see the top). */
/* 1.5.5 (#202): MIDI IN TRACK, the last 3 of FUN10's 16 spare bytes (just before the patches: the parameters a later
 * version adds grow from the other end, 13 bytes, 3 more track parameters). 24 bits LE: bits 5k..5k+4 track k's channel
 * as song.mch holds it (0..15 its distance up from channel k + 1, 16 OMNI, 17 OFF; 18..31 read as 0), bit 23 set: MIDI IN
 * is TRACK. Then the globals' G_ROUTE holds the block TRACK falls back to (proj_route_fallback: the block its four
 * channels make, else CH1-4), which is all a firmware before 1.5.5 reads (these bytes it never did): a TRACK project plays
 * there as that block. Every project before has them 0: channels 1..4, MIDI IN as its G_ROUTE says */
_Static_assert(G_COUNT == 27u, "FUN7 globals retain original IDs");
_Static_assert(sizeof(project_store_t) == 3840u, "FUN10 size");

static uint32_t proj_hash(const void *p, uint32_t n)   /* FNV-1a over n bytes */
{
    const uint8_t *b = (const uint8_t *)p;
    uint32_t i, s = 0x811C9DC5u;
    for (i = 0; i < n; i++)
        s = (s ^ b[i]) * 16777619u;
    return s;
}
static uint32_t proj_sum(const project_t *p) { return proj_hash(p, sizeof *p - 4u); }
static int proj_ok(const project_t *q) { return q->magic == PROJ_MAGIC && q->size == sizeof *q &&
    q->sum == proj_sum(q) && chain_valid(&q->chain) && motion_valid(&q->motion); }

/* every track's engine an id of the engine id space (#212): one this firmware lacks (another build's catalog, a
 * later firmware's engine) is kept as it is, and its track plays nothing and shows N/A (engines.c ENG_NONE); a byte
 * past the id space is no project */
static int proj_engines_ok(const project_t *q)
{
    uint32_t t;
    for (t = 0; t < NTRK; t++)
        if (q->t[t].engine >= ENG_ID_MAX)
            return 0;
    return 1;
}

/* DIGITAL tracks (engine 1; without FELUCCA_FM4) -> FM6 with the converted patch as the track's own (fm4_convert.c,
 * whatever format the project is: the conversion runs on every load, the stored record keeps what it holds until it
 * is saved again). Their motion events on the EDIT values or the OP ENV values go: DIGITAL's meanings do not carry
 * over to FM6's macros. Idempotent */
static void proj_fm4(project_t *q)
{
#if !FELUCCA_FM4
    uint32_t k, i, n, hit = 0;
    for (k = 0; k < NTRK; k++) {
        proj_trk_t *d = &q->t[k];
        uint8_t v[FP_SIZE + 1u];
        uint32_t pr;
        if (d->engine != ENGI_DIGITAL)
            continue;
        for (i = 0; i < P_COUNT; i++)
            d->p[i] = (int16_t)clamp(d->p[i], param_desc_of(ENGI_DIGITAL, i)->min, param_desc_of(ENGI_DIGITAL, i)->max);
        pr = fm4_convert(d->p, v);
        fm6_pack(v, q->fm6[k]);
        d->engine = ENGI_FM6;
        if (d->preset < PROJ_DEF_KEEP)
            d->preset = (uint8_t)pr;
        hit |= 1u << k;
    }
    if (!hit)
        return;
    for (i = n = 0; i < q->motion.count && i < MOTION_MAX; i++) {
        const motion_event_t *e = &q->motion.event[i];
        if (((hit >> (e->place >> 6)) & 1u) && (MOTION_ID(e) >= P_E0 || (MOTION_ID(e) >= P_FM1_ATK && MOTION_ID(e) <= P_FM4_LEVEL)))
            continue;
        q->motion.event[n++] = *e;
    }
    for (i = n; i < q->motion.count && i < MOTION_MAX; i++)
        memset(&q->motion.event[i], 0, sizeof q->motion.event[i]);
    q->motion.count = (uint8_t)n;
    q->sum = proj_sum(q);
#else
    (void)q;
#endif
}

/* SAMPLE tracks of the retired PERC set (SET 4) -> DRUM with its default kit (see the top; core.h drum_from_perc,
 * whatever format the project is: on every load, the stored record keeps what it holds until it is saved again).
 * Their motion events on the EDIT values go. Idempotent */
static void proj_perc(project_t *q)
{
    uint32_t k, i, n, hit = 0;
    for (k = 0; k < NTRK; k++) {
        proj_trk_t *d = &q->t[k];
        if (!drum_from_perc(d->engine, &d->p[P_E0]))
            continue;
        d->engine = ENGI_DRUM;
        if (d->preset < PROJ_DEF_KEEP)
            d->preset = 0;
        hit |= 1u << k;
    }
    if (!hit)
        return;
    for (i = n = 0; i < q->motion.count && i < MOTION_MAX; i++) {
        const motion_event_t *e = &q->motion.event[i];
        if (((hit >> (e->place >> 6)) & 1u) && MOTION_ID(e) >= P_E0)
            continue;
        q->motion.event[n++] = *e;
    }
    for (i = n; i < q->motion.count && i < MOTION_MAX; i++)
        memset(&q->motion.event[i], 0, sizeof q->motion.event[i]);
    q->motion.count = (uint8_t)n;
    q->sum = proj_sum(q);
}

/* 12 stored name bytes -> d (PROJ_NAME_LEN + 1): up to the first 0, upper case; a byte outside 32..126 makes it
 * no name (a damaged tail never refuses the project) */
static uint32_t proj_name_get(char *d, const uint8_t *s)   /* its length */
{
    uint32_t i;
    for (i = 0; i < PROJ_NAME_LEN && s[i]; i++) {
        if (s[i] < 32u || s[i] > 126u) { i = 0; break; }
        d[i] = (char)(s[i] >= 'a' && s[i] <= 'z' ? s[i] - 32u : s[i]);
    }
    d[i] = 0;
    return i;
}

/* MIDI IN TRACK (PROJ_MIDI_OFF): G_ROUTE TRACK is stored as the block its channels make (0 1 2 3 + 4n: CH1-4 .. CH13-16),
 * else CH1-4, and the TRACK bit */
static uint32_t proj_route_fallback(const uint8_t *mch)
{
    uint32_t k;
    for (k = 1; k < NTRK; k++)
        if (mch[k] != mch[0])
            return 0;
    return mch[0] % 4u || mch[0] >= 16u ? 0u : mch[0] ? mch[0] / 4u + 1u : 0u;
}
static void proj_midi_pack(uint8_t *b, const project_t *q)
{
    uint32_t k, v = 0;
    for (k = 0; k < NTRK; k++)
        v |= (uint32_t)(q->mch[k] < MCH_N ? q->mch[k] : 0u) << (5u * k);
    if (q->g[G_ROUTE] == ROUTE_TRACK) {
        int16_t r = (int16_t)proj_route_fallback(q->mch);
        memcpy(b + 8 + 2u * G_ROUTE, &r, 2);
        v |= 1u << 23;
    }
    b[PROJ_MIDI_OFF] = (uint8_t)v; b[PROJ_MIDI_OFF + 1u] = (uint8_t)(v >> 8); b[PROJ_MIDI_OFF + 2u] = (uint8_t)(v >> 16);
}
static void proj_midi_unpack(project_t *q, const uint8_t *b)
{
    uint32_t k, v = b[PROJ_MIDI_OFF] | (uint32_t)b[PROJ_MIDI_OFF + 1u] << 8 | (uint32_t)b[PROJ_MIDI_OFF + 2u] << 16, f;
    for (k = 0; k < NTRK; k++) {
        f = (v >> (5u * k)) & 31u;
        q->mch[k] = (uint8_t)(f < MCH_N ? f : 0u);
    }
    if (v >> 23)
        q->g[G_ROUTE] = ROUTE_TRACK;
}

/* A stable serialized schema: first header retains FUN6's fields; at byte66
 * np, format flags, then four byte-param tracks and nine-byte steps; FUN8: the patches at PROJ_FM6_OFF. */
int proj_encode(project_store_t *out, const project_t *q)
{
    uint8_t *b = out->raw; uint32_t pos = 68u, t, i; uint32_t magic = PROJ_MAGIC, size = PROJ_STORE_SIZE, sum;
    for (t = 0; t < NTRK; t++)
        for (i = 0; i < FM6_PACKED; i++)
            if (q->fm6[t][i] > 127u) return 0;
    if (!chain_valid(&q->chain) || !motion_valid(&q->motion) || P_COUNT > 127u) return 0;
    memset(out, 0, sizeof *out); memcpy(b, &magic, 4); memcpy(b + 4, &size, 4);
    memcpy(b + 8, q->g, sizeof q->g); b[62] = q->sel; b[63] = q->parts; b[64] = q->phys; b[66] = P_COUNT;
    for (t = 0; t < NTRK; t++) {
        for (i = 0; i < P_COUNT; i++) {
            if (q->t[t].p[i] < -64 || q->t[t].p[i] > 127) return 0;
            b[pos++] = (uint8_t)(q->t[t].p[i] + 64);
        }
        b[pos++] = q->t[t].engine; b[pos++] = q->t[t].preset;
        for (i = 0; i < NSTEP; i++) {
            const step_t *s = &q->t[t].step[i];
            uint32_t r = step_ratchet(s) - 1u;          /* RATCH: bit 7 of the velocity and chance bytes (see the top) */
            uint32_t nd = (uint32_t)step_nudge(s) & 15u;   /* NUDGE (FUN10): bit j in bit 7 of note j */
            if (s->n > 4u || s->time > ST_REST || (s->flags & ~(3u | SF_RATCH | SF_NUDGE)) || s->probability >= COND_FIRST + NCOND)
                return 0;
            for (uint32_t j = 0; j < 4u; j++)           /* what proj_decode checks, so a saved project always loads: */
                b[pos++] = (uint8_t)((s->note[j] > 127u ? 127u : s->note[j]) | (nd >> j & 1u) << 7);   /* notes and
                                                         * velocity 0..127, accents */
            b[pos++] = (uint8_t)(s->n | s->time << 3 | (s->flags & 3u) << 5);   /* only on hits */
            b[pos++] = (uint8_t)((s->vel > 127u ? 127u : s->vel) | (r & 1u) << 7); b[pos++] = s->hit;
            b[pos++] = s->acc & s->hit;
            b[pos++] = (uint8_t)(s->probability | (r >> 1) << 7);
        }
    }
    if (pos + sizeof q->chain + sizeof q->motion > PROJ_MIDI_OFF) return 0;
    memcpy(b + pos, &q->chain, sizeof q->chain); pos += sizeof q->chain;
    memcpy(b + pos, &q->motion, sizeof q->motion);
    proj_midi_pack(b, q);
    memcpy(b + PROJ_FM6_OFF, q->fm6, sizeof q->fm6);
    {   /* the name (0-padded; stops at the first 0) */
        char n[PROJ_NAME_LEN + 1u];
        memcpy(b + PROJ_NAME_OFF, n, proj_name_get(n, (const uint8_t *)q->name));
    }
    sum = proj_hash(b, PROJ_STORE_SIZE - 4u); memcpy(b + PROJ_STORE_SIZE - 4u, &sum, 4);
    return 1;
}

/* Every stored format, by its identification: length (= the size word), magic, FNV-1a in the last 4 bytes. The first
 * PROJ_SERIAL are serialized (the parameter count at byte 66); the first PROJ_PUT are the lengths BACKUP_PUT takes
 * (FUN6 shares FUN7's). One table for the raw export (editor_backup.c ed_raw_kind), the decode and the backup */
#define PROJ_SERIAL 4u
#define PROJ_PUT 4u
static const uint32_t PROJ_FORMATS[10][2] = {{PROJ_STORE_SIZE, PROJ_MAGIC}, {PROJ_STORE_V9, PROJ_MAGIC_V9},
    {PROJ_STORE_V8, PROJ_MAGIC_V8}, {PROJ_STORE_V7, PROJ_MAGIC_V7}, {PROJ_STORE_V6, PROJ_MAGIC_V6},
    {PROJ_STORE_V5, PROJ_MAGIC_V5}, {PROJ_STORE_V4, PROJ_MAGIC_V4}, {PROJ_STORE_V3, PROJ_MAGIC_V3},
    {PROJ_STORE_V2, PROJ_MAGIC_V2}, {PROJ_STORE_V1, PROJ_MAGIC_V1}};
uint32_t proj_classify(const void *v, uint32_t n)
{
    const uint8_t *b = (const uint8_t *)v;
    uint32_t m = 0, w = 0, s, k;
    if (n >= 8u) { memcpy(&m, b, 4); memcpy(&w, b + 4, 4); }
    for (k = 0; k < 10u; k++) {
        if (n != PROJ_FORMATS[k][0] || m != PROJ_FORMATS[k][1])
            continue;
        memcpy(&s, b + n - 4u, 4);
        if (w != n || s != proj_hash(b, n - 4u))
            return PROJ_DAMAGED;
        if (k < PROJ_SERIAL) {                          /* the count must fit the layout, as the readers check */
            uint32_t end = n - 4u - PROJ_NAME_LEN - (k == 3u ? 0u : NTRK * FM6_PACKED);
            uint32_t tail = k ? sizeof(chain_v9_t) + PROJ_MOTION_V9 : sizeof(chain_config_t) + sizeof(motion_store_t);
            if (b[66] < 8u || b[66] > P_COUNT || 68u + NTRK * (b[66] + 2u + NSTEP * 9u) + tail > end)
                return PROJ_UNKNOWN;
        }
        return k || b[66] < P_COUNT || b[63] != NPART || b[64] < PROJ_PHYS ? PROJ_LEGACY : PROJ_CURRENT;
    }
    return PROJ_UNKNOWN;
}
int proj_accepts_length(uint32_t n)
{
    uint32_t k;
    for (k = 0; k < PROJ_PUT; k++)
        if (n == PROJ_FORMATS[k][0])
            return 1;
    return 0;
}

/* the tracks of a serialized record from byte 68: np biased byte parameters (mapped by count), engine, preset, 64
 * nine-byte steps; v10: bit 7 of a note byte is a bit of the step's NUDGE (FUN10), else it refuses. The position after
 * them; 0 = a byte out of its range or an engine past the id space. Shared with project_legacy.c proj_unpack */
static uint32_t proj_unpack_tracks(project_t *q, const uint8_t *b, uint32_t np, uint32_t v10)
{
    uint32_t pos = 68u, t, i;
    for (t = 0; t < NTRK; t++) {
        const uint8_t *v = b + pos;                     /* (the values read in place: no copy on the stack) */
        int16_t *p = q->t[t].p;
        for (i = 0; i < np; i++) if (v[i] > 191u) return 0;
        pos += np;
        q->t[t].engine = b[pos++]; q->t[t].preset = b[pos++];
        if (q->t[t].engine >= ENG_ID_MAX) return 0;
        for (i = 0; i < P_COUNT; i++)                   /* by count, as core.h params_by_count: the first np - 8 in */
            p[i] = i < np - 8u && i < P_E0 ? (int16_t)(v[i] - 64) :        /* order, the last 8 at P_E0, the */
                   i >= P_E0 ? (int16_t)(v[np - 8u + i - P_E0] - 64) :    /* rest the engine's defaults */
                   param_desc_of(eng_idx(q->t[t].engine), i)->def;
        for (i = 0; i < NSTEP; i++) {
            step_t *s = &q->t[t].step[i]; uint32_t meta, nd = 0;
            for (uint32_t j = 0; j < 4u; j++) {         /* (FUN10: bit 7 of note j is bit j of the nudge) */
                if (b[pos] > 127u && !v10) return 0;
                nd |= (uint32_t)(b[pos] >> 7) << j;
                s->note[j] = b[pos++] & 127u;
            }
            meta = b[pos++];
            s->n = meta & 7u; s->time = (meta >> 3) & 3u; s->flags = (meta >> 5) & 3u;
            s->vel = b[pos] & 127u; meta |= (b[pos++] & 128u) << 1;      /* (RATCH bit 0 at bit 8 of meta) */
            s->hit = b[pos++]; s->acc = b[pos++];
            s->probability = b[pos] & 127u; meta |= (b[pos++] & 128u) << 2;   /* (bit 1 at bit 9) */
            if ((meta & 255u) > 127u || s->n > 4u || s->time > ST_REST || s->probability >= COND_FIRST + NCOND) return 0;
            if (s->acc & ~s->hit) return 0;
            step_set_ratchet(s, (meta >> 8) + 1u);
            step_set_nudge(s, (int32_t)(nd ^ 8u) - 8);
        }
    }
    return pos;
}

/* FUN10's tail after its validated chain and motion: MIDI IN TRACK, the four patches, the name, then the hash of q.
 * Shared with project_legacy.c proj_unpack (a FUN10 of fewer parameters) */
static void proj_unpack_tail(project_t *q, const uint8_t *b)
{
    uint32_t t, i;
    proj_midi_unpack(q, b);                             /* (1.5.5: 0 in every FUN10 before) */
    for (t = 0; t < NTRK; t++)
        for (i = 0; i < FM6_PACKED; i++)
            q->fm6[t][i] = b[PROJ_FM6_OFF + t * FM6_PACKED + i] & 0x7Fu;
    {
        char n[PROJ_NAME_LEN + 1u];
        memcpy(q->name, n, proj_name_get(n, b + PROJ_NAME_OFF));
    }
    q->sum = proj_sum(q);
}
/* a CURRENT record (proj_classify: magic, size, hash, P_COUNT parameters, today's header) -> q: every field read and
 * checked as proj_encode writes it, nothing converted. 0 = a field out of its range */
static int proj_unpack_current(project_t *q, const uint8_t *b)
{
    uint32_t pos;
    memset(q, 0, sizeof *q); q->magic = PROJ_MAGIC; q->size = sizeof *q;
    memcpy(q->g, b + 8, sizeof q->g); q->sel = b[62]; q->parts = b[63]; q->phys = b[64];
    pos = proj_unpack_tracks(q, b, P_COUNT, 1u);
    if (!pos) return 0;
    memcpy(&q->chain, b + pos, sizeof q->chain); pos += sizeof q->chain;
    memcpy(&q->motion, b + pos, sizeof q->motion);
    if (!chain_valid(&q->chain) || !motion_valid(&q->motion)) return 0;   /* (motion_valid: every id below P_COUNT) */
    proj_unpack_tail(q, b);
    return 1;
}

static void proj_steps(step_t *s)            /* a loaded sequence stays inside its fixed fields */
{
    uint32_t i, j;
    for (i = 0; i < NSTEP; i++) {
        if (s[i].n > 4u) s[i].n = 4;
        if (s[i].time > ST_REST) s[i].time = ST_REST;
        for (j = 0; j < 4u; j++) s[i].note[j] &= 127u;
        s[i].acc &= s[i].hit;
    }
}

/* an imported older format may hold values FUN7 cannot pack: keep them inside the fields and ranges */
static void proj_bound(project_t *q)
{
    uint32_t t, i;
    for (t = 0; t < NTRK; t++) {
        proj_steps(q->t[t].step);
        for (i = 0; i < NSTEP; i++) {
            step_t *s = &q->t[t].step[i];
            s->flags &= 3u | SF_RATCH | SF_NUDGE;
            s->vel &= 127u;
            if (s->probability >= COND_FIRST + NCOND) s->probability = 0;
        }
        for (i = 0; i < P_COUNT; i++) {
            const param_desc_t *d = param_desc_of(eng_idx(q->t[t].engine), i);
            q->t[t].p[i] = (int16_t)param_fit(d, q->t[t].p[i]);   /* (a retired KIT: the kit it plays) */
        }
    }
    q->sum = proj_sum(q);
}

/* n stored bytes -> q, everything proj_decode does but proj_bound: a CURRENT record read as it is, any other through
 * the legacy hook; the engines in the id space; DIGITAL and SAMPLE PERC tracks converted. The host tests' adapter for
 * a reader's own output (a value outside its range kept); firmware callers use proj_decode */
static int proj_import(project_t *q, const void *b, int n)
{
    if (proj_classify(b, n < 0 ? 0u : (uint32_t)n) == PROJ_CURRENT ? !proj_unpack_current(q, (const uint8_t *)b) :
        !proj_decode_legacy(q, b, n))                   /* (#456 stage 2b: CURRENT only) */
        return 0;
    if (!proj_engines_ok(q))
        return 0;
    proj_fm4(q);
    proj_perc(q);
    return 1;
}
/* n stored bytes (any format) -> q as today's, inside every field and range: the one decode of every caller
 * (proj_fetch, project_load, autosave_boot, the backup's commit, project_used, project_info, project_rename,
 * chain_prepare, persist_boot); 0 = not a project. Fixed order: read (CURRENT, or the legacy hook), proj_engines_ok,
 * proj_fm4, proj_perc, proj_bound */
int proj_decode(project_t *q, const void *b, int n)
{
    if (!proj_import(q, b, n))
        return 0;
    proj_bound(q);
    return 1;
}
/* .. of a CURRENT record only (the legacy hook never runs): what a current-schema-only upload accepts (#456) */
int proj_decode_current(project_t *q, const void *b, int n)
{
    return n >= 0 && proj_classify(b, (uint32_t)n) == PROJ_CURRENT && proj_decode(q, b, n);
}

#include "project_legacy.c"                        /* the transitional seam (#456 stage 2b deletes it) */
