/* SPDX-License-Identifier: GPL-3.0-only */
/* Project record codec (#300): the public interface of project_codec.c, the one place that turns stored project bytes
 * into a project_t and back. Include after core.h (P_COUNT, G_COUNT, NTRK, step_t, chain_config_t, motion_store_t) and
 * eng_fm6.c (FM6_PACKED); core.h has no include guard and defines state, so this header does not include it.
 *
 * Header boundary as docs/modules.md describes it for #454: the codec stays in felucca.c's single translation unit
 * (project.c includes project_codec.c), its interface functions are static (PROJ_API) and inline as before, and
 * tests/project_codec_boundary_test.py checks that no firmware file outside the codec names its private functions.
 *
 *   proj_classify(b, n)         what n stored bytes are, from their identification only (STORE_LIST's state, #456)
 *   proj_decode(q, b, n)        the one decode every caller uses: a CURRENT record through proj_decode_current, any
 *                               other through the transitional legacy hook, then the same fixed steps: the engines in
 *                               the id space (proj_engines_ok), the retired sounds in current containers (DIGITAL,
 *                               SAMPLE PERC; #299 part B), every value inside its field and range (proj_bound)
 *   proj_decode_current(q, b)   FUNA with P_COUNT parameters: its fields validated, nothing converted
 *   proj_encode(out, q)         a decoded or captured project -> FUN10 bytes (0: a value it cannot store)
 *   proj_accepts_length(n)      the stored lengths BACKUP_PUT takes for a project object (editor_backup.c)
 *
 * The legacy hook proj_decode_legacy (project_legacy.c) holds every historical reader unchanged: FUN1..FUN9, FUN10 of
 * fewer parameters, the retained .noinit slot holding a shorter older record, the pre-1.0 header bytes (parts, phys).
 * #456 stage 2b deletes project_legacy.c, its include in project_codec.c and the one call in proj_decode; nothing
 * else here depends on it. Main loop only. */
#pragma once
#include <stdint.h>

#define PROJ_API static

#define PROJ_MAGIC 0x46554E41u                 /* "FUNA" (FUN10): 104 (1.5: 111) parameters, 128 motion records, nudges */
#define PROJ_STORE_SIZE 3840u                  /* FUN10: a whole storage object (storage.c ST_PAYLOAD_MAX) */
#define PROJ_PHYS 2u                           /* project_t.phys: PHYS without DUST and DRUM (project.c, the top) */
#define PROJ_NAME_LEN 12u                      /* the name: the stored bytes PROJ_NAME_OFF.. (the reserved tail's end) */
#define PROJ_NAME_OFF (PROJ_STORE_SIZE - 4u - PROJ_NAME_LEN)
#define PROJ_FM6_OFF (PROJ_NAME_OFF - NTRK * FM6_PACKED)
#define PROJ_MIDI_OFF (PROJ_FM6_OFF - 3u)      /* 1.5.5 (#202): MIDI IN TRACK (project_codec.c proj_midi_pack) */
#define PROJ_DEF_SOUND 0xFFu                   /* preset byte: the track's power-on sound, no steps (format 1) */
#define PROJ_DEF_KEEP 0xFEu                    /* .. DRUM's kit (once SAMPLE PERC), steps and the rest kept (old drums) */

typedef struct {                               /* one track */
    int16_t p[P_COUNT];
    uint8_t engine, preset;
    step_t step[NSTEP];
} proj_trk_t;
typedef struct {
    uint32_t magic, size;
    int16_t g[G_COUNT];
    uint8_t sel;                               /* the selected track */
    uint8_t parts;                             /* NPART; 0: track 4 is the old GM drum part (project.c, the top) */
    uint8_t phys;                              /* PROJ_PHYS: PHYS MODEL values as today; 1: MODEL 4 was DRUM;
                                                * 0 (a reserved byte before 1.0): MODEL 2 was DUST */
    uint8_t rsv;
    proj_trk_t t[NTRK];
    chain_config_t chain;
    motion_store_t motion;
    uint8_t fm6[NTRK][FM6_PACKED];             /* each track's FM6 patch, packed (eng_fm6.c) */
    uint8_t mch[NTRK];                         /* 1.5.5: MIDI IN TRACK's channels, as song.mch (PROJ_MIDI_OFF) */
    char name[PROJ_NAME_LEN];                  /* the project's name: upper-case ASCII 32..126, 0-padded; "" = none */
    uint32_t sum;
} project_t;
typedef union { uint32_t align; uint8_t raw[PROJ_STORE_SIZE]; } project_store_t;

/* What a project holds: every member of project_t and of its tracks, once. project.c's project_capture,
 * autosave_sig and project_restore_runtime each handle these members; tests/persistence_test.c walks the lists and
 * fails when one of the three misses a member or a member is added here without them (the size checks below fail
 * when project_t gains a member these lists do not name). X(member) */
#define PROJ_FIELDS(X) X(magic) X(size) X(g) X(sel) X(parts) X(phys) X(rsv) X(t) X(chain) X(motion) X(fm6) X(mch) \
                       X(name) X(sum)
#define PROJ_TRK_FIELDS(X) X(p) X(engine) X(preset) X(step)
#define PROJ_FIELD_SIZE(m) + sizeof(((project_t *)0)->m)
#define PROJ_TRK_FIELD_SIZE(m) + sizeof(((proj_trk_t *)0)->m)
#define PROJ_PAD 2u                            /* project_t's padding: 2 bytes after name, before sum (proj_sum hashes
                                                * them: every writer memsets the record first) */
_Static_assert(0 PROJ_FIELDS(PROJ_FIELD_SIZE) + PROJ_PAD == sizeof(project_t), "project_t: a member PROJ_FIELDS does not list");
_Static_assert(0 PROJ_TRK_FIELDS(PROJ_TRK_FIELD_SIZE) == sizeof(proj_trk_t), "proj_trk_t: a member PROJ_TRK_FIELDS does not list");

/* proj_classify: the schema of n stored bytes, from magic, length, size word, hash and parameter count only (no field
 * is decoded). CURRENT: FUN10 as this firmware writes it, P_COUNT parameters, the header bytes as today (parts NPART,
 * phys PROJ_PHYS or above): proj_decode_current reads it. LEGACY: an older format or count, or a FUN10 whose header
 * still asks for a pre-1.0 conversion: only the legacy hook reads it. DAMAGED: a format's magic and length, but its size
 * word or hash does not match. UNKNOWN: none of these (a later format, another layout, too short) */
enum { PROJ_CURRENT, PROJ_LEGACY, PROJ_UNKNOWN, PROJ_DAMAGED };
PROJ_API uint32_t proj_classify(const void *b, uint32_t n);
PROJ_API int proj_decode(project_t *q, const void *b, int n);
PROJ_API int proj_decode_current(project_t *q, const void *b, int n);
PROJ_API int proj_encode(project_store_t *out, const project_t *q);
PROJ_API int proj_accepts_length(uint32_t n);
/* For project.c's runtime snapshot (project_capture, project_restore_runtime), not for decoding: a project_t's hash
 * (proj_sum), its own check (proj_ok: magic, size, hash, chain and motion valid), every engine an id of the id space
 * (proj_engines_ok), the 12 stored name bytes as text (proj_name_get: its length, d PROJ_NAME_LEN + 1 bytes), a
 * sequence inside its fixed fields (proj_steps: NSTEP steps) */
PROJ_API uint32_t proj_sum(const project_t *p);
PROJ_API int proj_ok(const project_t *q);
PROJ_API int proj_engines_ok(const project_t *q);
PROJ_API uint32_t proj_name_get(char *d, const uint8_t *s);
PROJ_API void proj_steps(step_t *s);
/* the transitional hook (project_legacy.c): n bytes of any older record -> q as today's, not yet bounded; 0 = none */
PROJ_API int proj_decode_legacy(project_t *q, const void *b, int n);
