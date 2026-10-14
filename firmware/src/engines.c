/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Engine table (order = PRESETS browsing order and the engine numbers of the editor protocol), the
 * factory patterns (SAVE > PHRASES) and the parts' sounds at power-on. */
#include "../engines/src/dsp.c"   /* Felucca-Engines (MIT): the shared DSP blocks */

/* The parts' engine memory (1.5): a part plays one engine at a time, so the engines with large per-part state
 * (engine_t.mem: PHYS's slots, GRAIN's grains and index, DRUM's lanes, FM6's notes, SLICE's reverse windows)
 * keep it in one region per part instead of an array each. The region holds the state of the engine that
 * last claimed it (eng_mem_owner); a switch to another such engine zeroes its engine_t.mem bytes, which is
 * the state each had at power-on, so a switch sounds as it did with the arrays (tests/union_test.c). State
 * that runs on across notes and switches stays outside (WHEEL's wheels, GRAIN's random numbers).
 * Sized by the largest, PHYS (3 x SYMP's slot); an engine that needs more than ENG_MEM_PART grows it for
 * every part (x NPART of the pool). Zero-initialised pool section: main.c fm1_cstart clears it. */
#define ENG_MEM_PART 12888u
static union {
    uint64_t align;
    uint8_t b[ENG_MEM_PART];
} eng_mem[NPART] __attribute__((section(".pool")));
static uint8_t eng_mem_owner[NPART];       /* engine index + 1 whose state is in the region, 0 = none (zeros) */
#define ENG_MEM(p) ((void *)eng_mem[p].b)  /* part p's region (p < NPART) */
#define ENG_MEM_FITS(name, size) _Static_assert((size) <= ENG_MEM_PART, name " state over ENG_MEM_PART")

/* Host/test-only owner check (FELUCCA_ARENA_CHECK=1; off: ENG_MEM_OF is ENG_MEM, no code or data). The arena
 * consumers (GRAIN, PHYS, DRUM, FM6, SLICE) reach their state through ENG_MEM_OF(t, engine, p): at the access it
 * checks the part (t in trk[], aligned), the engine being RENDERED (t->engine; eng_req may already name the next
 * one during a fade and is no owner), and the claimed owner (eng_mem_owner, set by eng_mem_claim). A failure
 * calls eng_arena_fail first and returns a scratch block, never the invalid pointer. Not caught: an in-arena
 * overrun or a wrong slot of the right owner. tests/arena_test.c installs a handler (default: trap). */
#define ENGI_GRAIN 8u
#define ENGI_SLICE 13u
#if FELUCCA_ARENA_CHECK
enum { ARENA_BAD_PART = 1, ARENA_BAD_ENGINE, ARENA_BAD_OWNER };
static void eng_arena_trap(uint32_t why, const track_t *t, uint32_t want) { (void)why; (void)t; (void)want; __builtin_trap(); }
static void (*eng_arena_fail)(uint32_t why, const track_t *t, uint32_t want) = eng_arena_trap;
static uint64_t eng_arena_scratch[ENG_MEM_PART / 8u + 1u];
static void *eng_mem_of(const track_t *t, uint32_t want)
{
    uint32_t p, cur;
    if ((uintptr_t)t < (uintptr_t)&trk[0] || (uintptr_t)t >= (uintptr_t)&trk[NPART] ||
        ((uintptr_t)t - (uintptr_t)&trk[0]) % sizeof(track_t)) {
        eng_arena_fail(ARENA_BAD_PART, t, want);
        return eng_arena_scratch;
    }
    p = (uint32_t)(t - trk);
    cur = t->engine < NENGINES ? t->engine : (uint32_t)NENGINES;   /* (an index; NENGINES: ENG_IDX_NONE, below) */
    if (cur != want) {
        eng_arena_fail(ARENA_BAD_ENGINE, t, want);
        return eng_arena_scratch;
    }
    if (eng_mem_owner[p] != want + 1u) {
        eng_arena_fail(ARENA_BAD_OWNER, t, want);
        return eng_arena_scratch;
    }
    return ENG_MEM(p);
}
#define ENG_MEM_OF(t, e, p) eng_mem_of((t), (e))
#else
#define ENG_MEM_OF(t, e, p) ENG_MEM(p)         /* p: the part index the caller already derived */
#endif

#include "engine_includes.inc"
#include "fm4_convert.c"  /* Retired DIGITAL migrations exist in every profile. */
#if FELUCCA_FM4
#include "eng_digital.c"
#endif

/* An id this build has no engine for (#212: one a build's catalog leaves out, FELUCCA_ENG_OMIT; one past this build's
 * table, a later firmware's): a sound stored with it keeps its id, its preset number and its E values (the full
 * stored range, -64..127) and plays nothing; it is never offered (eng_ok) and is shown as unavailable ("N/A").
 * eng_idx maps such an id to ENG_IDX_NONE, the table's extra last entry, never onto another engine */
static void eng_none_note_on(struct track *t, voice_t *v) { (void)t; (void)v; }
static void eng_none_render(struct track *t, voice_t *v, int32_t *out, uint32_t n, const vmod_t *m)
{
    (void)t; (void)v; (void)out; (void)n; (void)m;
}
#define ENG_NONE_E {"-", F_INT, -64, 127, 0, 0, 0}
static const engine_t ENG_NONE = {
    .name = "N/A",
    .page_title = {"N/A", "N/A"},
    .edit = {ENG_NONE_E, ENG_NONE_E, ENG_NONE_E, ENG_NONE_E, ENG_NONE_E, ENG_NONE_E, ENG_NONE_E, ENG_NONE_E},
    .note_on = eng_none_note_on,
    .render = eng_none_render,
    .knob = {P_LEVEL, P_ATK, P_DEC, P_REL},
};
#if FELUCCA_ENG_TEST14
/* host tests only (FELUCCA_ENG_TEST14=1, #212): a placeholder engine with id 14, so the stores, favourites, the
 * editor and the UI are tested with an id past the old 16-row favourites table's MIDI LEARN row. Silent */
static const preset_t TEST14_PRESETS[] = {
    {"T14 ONE", {0, 0, 0, 0, 0, 0, 0, 0}, {0, 64, 100, 40}, 0, 0, {0, 0, 0, 0}, 0},
    {"T14 TWO", {1, 1, 1, 1, 1, 1, 1, 1}, {0, 64, 100, 40}, 0, 0, {0, 0, 0, 0}, 0},
};
#define T14_E(l) {l, F_INT, 0, 127, 0, 0, 0}
static const engine_t ENG_TEST14 = {
    .name = "TEST14",
    .page_title = {"TEST", "TEST"},
    .edit = {T14_E("A"), T14_E("B"), T14_E("C"), T14_E("D"), T14_E("E"), T14_E("F"), T14_E("G"), T14_E("H")},
    .presets = TEST14_PRESETS,
    .npresets = 2,
    .note_on = eng_none_note_on,
    .render = eng_none_render,
    .knob = {P_E0, P_E0 + 1, P_E0 + 2, P_REL},
};
#endif
_Static_assert(FELUCCA_ENG_OMIT != (int)ENGI_DIGITAL, "engine 1 is reserved already");
/* engine id `id` of this build's catalog: e, or ENG_NONE where the catalog leaves it out (FELUCCA_ENG_OMIT) */
#define ENG_AT(id, e) (FELUCCA_ENG_OMIT == (id) ? &ENG_NONE : (e))

/* the editor protocol, user presets and projects store these indices: append, never reorder. The entry past the
 * last id (ENG_IDX_NONE) is ENG_NONE: what eng_idx gives for an id this build lacks */
#define ENG_IDX_NONE ((uint32_t)NENGINES)
static const engine_t *const ENGINES[] = {
#include "engine_registry.inc"
    &ENG_NONE,                   /* ENG_IDX_NONE */
};
_Static_assert(NELEM(ENGINES) == NENGINES + 1u, "ENGINES: an entry per id, then ENG_NONE");

/* a track's engine id as an index of ENGINES (the audio paths: a compare): the id itself when this build has its
 * engine (or ENG_NONE where its catalog leaves it out), else ENG_IDX_NONE (ENG_NONE: silent) -- never another engine */
static inline uint32_t eng_idx(uint32_t e) { return e < NENGINES ? e : ENG_IDX_NONE; }
#define eng_of(e) (ENGINES[eng_idx(e)])

/* part t's engine memory goes to its engine (t->engine; voice.c engine_block, once a block: on a switch, after
 * the old engine's fade, before any note on the new one): zeroed (its engine_t.mem bytes) when another
 * engine's state is in it. An engine without memory leaves it as it is: a switch back finds its state. */
static void eng_mem_claim(const track_t *t)
{
    uint32_t p = (uint32_t)(t - trk), e, k, n;
    uint32_t *w;
    if (p >= NPART)
        return;
    e = eng_idx(t->engine);
    n = ENGINES[e]->mem;
    if (!n || eng_mem_owner[p] == e + 1u)
        return;
    w = (uint32_t *)ENG_MEM(p);
    for (k = 0; k < (n + 3u) / 4u; k++)
        w[k] = 0;
    eng_mem_owner[p] = (uint8_t)(e + 1u);
}

/* the sample source a track's sound plays that has no data (SAMPLE's SET, GRAIN's SRC, SLICE's SRC: an empty or
 * invalid user slot, a set or PIANO this build lacks): its name (it plays a sine: eng_sample.c smp_sine), 0 = none;
 * *code a small number for it (1.., per engine and source) so the UI says it once (ui_input.c sample_notice) */
static uint8_t snd_said[NTRK];   /* per track: the code last said, 0 = none (a project load clears them: said again) */
static const char *snd_missing(const track_t *t, uint32_t *code)
{
    const engine_t *e = ENGINES[eng_idx(t->eng_req)];
    uint32_t si = (uint32_t)t->p[P_E0] % SMP_NALL;
#if FELUCCA_SLICE
    if (e == &ENG_SLICE) {
        si = slc_src_of(t->p);
        *code = 64u + si;
        return slc_get(si) ? 0 : N_SLC_SRC[si];
    }
#endif
    if (e != &ENG_SAMPLE && e != &ENG_GRAIN)
        return 0;
    *code = (e == &ENG_GRAIN ? 32u : 1u) + si % 32u;
    return smp_set_missing(si) ? SMP_ALL_NAMES[si] : 0;
}

/* the order the engines are shown in (PRESETS browsing and its ENG knob, the EDIT layer's keys, the editor's list):
 * engine indices, never DIGITAL's reserved 1 (with FELUCCA_FM4 it follows FM6). The indices stay as they are (the
 * stores and the protocol hold them); only this table orders them */
static const uint8_t ENGINE_ORDER[NENG_SHOWN] = {
#include "engine_order.inc"
};
_Static_assert(NELEM(ENGINE_ORDER) == NENG_SHOWN, "ENGINE_ORDER: every engine one can pick, once");

/* the engines one can pick (engine 1 only with FELUCCA_FM4), in ENGINE_ORDER: eng_ok(e), the n-th of them
 * eng_vis(n), e's place among them eng_rank(e), the next / previous one eng_step(e, dir) (wraps) */
static int eng_ok(uint32_t e) { return e < NENGINES && ENGINES[e] != &ENG_NONE && (FELUCCA_FM4 || e != ENGI_DIGITAL); }
static uint32_t eng_vis(uint32_t n) { return ENGINE_ORDER[n % NENG_SHOWN]; }
static uint32_t eng_rank(uint32_t e)
{
    uint32_t n;
    if (e == ENGI_DIGITAL && !FELUCCA_FM4)
        e = ENGI_FM6;                            /* (DIGITAL without FELUCCA_FM4: its sounds play as FM6) */
    for (n = 0; n < NENG_SHOWN && ENGINE_ORDER[n] != e; n++)
        ;
    return n < NENG_SHOWN ? n : 0u;
}
static uint32_t eng_step(uint32_t e, int32_t dir)
{
    if (!eng_ok(e) && !(e == ENGI_DIGITAL && !FELUCCA_FM4))   /* an unavailable id: the first / last one (a step from it
                                                               * is the user's choice of another engine, not a remap) */
        return eng_vis(dir > 0 ? 0u : NENG_SHOWN - 1u);
    return eng_vis((eng_rank(e) + (dir > 0 ? 1u : NENG_SHOWN - 1u)) % NENG_SHOWN);
}

/* factory sequence patterns: SAVE > PHRASES loads one into the selected track (ui.c pat_load); a preset
 * only suggests one with PAT(n), loading a sound never touches the steps. Absolute notes, loaded as they
 * are (DRUM plays them as GM drums, SLICE as slices; SCL TRANS and OCT transpose): 0 = rest;
 * flags 1 = accent, 2 = slide, 4 = tie (holds the previous note). Names: at most 8 characters */
#define T_ 4
static const struct {
    const char *name;
    uint8_t note[16], flags[16];
} PATTERNS[] = {
    {"ACID", {45, 45, 57, 45, 0, 48, 45, 55, 45, 0, 57, 52, 45, 48, 0, 50},          /* 1 */
     {1, 0, 2, 0, 0, 0, 1, 2, 0, 0, 1, 0, 0, 2, 0, 1}},
    {"OFFBEAT", {0, 36, 0, 36, 0, 36, 0, 48, 0, 36, 0, 36, 0, 39, 0, 43},          /* 2 bass */
     {0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0}},
    {"MELODY", {60, 0, 67, 0, 72, 67, 0, 64, 62, 0, 69, 0, 74, 69, 0, 67},         /* 3 pluck */
     {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0}},
    {"LEAD", {72, 0, 0, 74, 0, 0, 76, 0, 79, 0, 76, 0, 74, 0, 0, 0},               /* 4 */
     {1, T_, 0, 2, T_, 0, 0, 0, 1, 0, 2, 0, 0, T_, T_, 0}},
    {"PAD", {60, 0, 0, 0, 0, 0, 0, 0, 57, 0, 0, 0, 55, 0, 0, 0},                   /* 5 long notes */
     {0, T_, T_, T_, T_, T_, T_, 0, 0, T_, T_, 0, 0, T_, T_, 0}},
    {"KEYS", {0, 0, 60, 0, 0, 63, 0, 0, 0, 0, 60, 0, 0, 65, 0, 63},                /* 6 offbeat stabs */
     {0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0}},
    {"BELL", {72, 0, 0, 79, 0, 0, 84, 0, 0, 0, 76, 0, 0, 0, 0, 0},                 /* 7 sparse */
     {1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"SUB", {36, 0, 0, 0, 0, 0, 0, 36, 0, 0, 34, 0, 0, 0, 0, 0},                   /* 8 low, held */
     {1, T_, T_, T_, 0, 0, 0, 0, 0, 0, 0, T_, T_, T_, 0, 0}},
    /* SLICE (eng_slice.c): note = C4 + slice */
    {"CHOP", {60, 61, 62, 67, 64, 65, 60, 69, 68, 70, 62, 67, 72, 72, 74, 64},     /* 9 16 slices re-ordered */
     {1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0}},
    {"STUTTER", {60, 60, 61, 61, 62, 0, 63, 63, 64, 65, 65, 0, 66, 66, 66, 67},    /* 10 8 slices, repeats */
     {1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0}},
    {"SLICES", {60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75},   /* 11 in order */
     {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0}},
    /* DRUM (General MIDI: 36 kick, 38 snare, 42 closed / 46 open hi-hat) */
    {"BEAT", {36, 42, 42, 42, 38, 42, 36, 42, 36, 42, 42, 36, 38, 42, 46, 42},     /* 12 */
     {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0}},
    /* 16ths up a C minor arpeggio, twice: the line the ARP presets (RAVE, ARP 8BIT, ARP LEAD) suggest
     * now that the arpeggiator is the track's and a preset no longer switches it on */
    {"ARP", {48, 51, 55, 60, 63, 67, 72, 75, 48, 51, 55, 60, 63, 67, 72, 75},       /* 13 */
     {1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0}},
};
#undef T_
#define NPATTERNS (sizeof PATTERNS / sizeof PATTERNS[0])

/* the parts at power-on (engine, preset, PATTERNS[n - 1] in the sequencer, 0 = empty: all are): bass, pad, lead, drums */
static const uint8_t TRK_DEF[NPART][3] = {{0, 4, 0}, {ENGI_FM6, 4, 0}, {3, 0, 0}, {ENGI_DRUM, 0, 0}}; /* ANALOG ACID,
                                                                       * FM6 PAD (was DIGITAL PAD), LOFI PULSE LD, DRUM KIT */
static uint32_t trk_def_engine(uint32_t i) { return TRK_DEF[i % NPART][0]; }
