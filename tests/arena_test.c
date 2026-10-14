/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Engine-arena owner checks (engines.c ENG_MEM_OF, FELUCCA_ARENA_CHECK=1), next to tests/union_test.c's hashes.
 *   build/host/arena_test [SEEDS]      (run_tests.sh builds it with -DFELUCCA_ARENA_CHECK=1, also under ASan/UBSan)
 *
 * 1. Negative fixtures: a wrong engine, an unclaimed (or foreign) owner and an invalid part make the checker
 *    report BEFORE the access (the handler runs; the caller gets scratch memory, never the bad pointer); the old
 *    engine's access during a fade and the new engine's after the switch succeed, eng_req is no owner.
 * 2. Random runs (fixed seeds, kept in SEED0..): notes, note-offs, retriggers, rapid eng_req switches, notes
 *    inside a fade, PHYS MODEL changes, all four parts at once, every arena access checked (no failure), the
 *    output bounded, every voice released and the mix silent in the end. A failing seed is reproducible.
 * Without the define the fixtures are skipped and the random runs still play. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include <sys/wait.h>

static void blocks(uint32_t n)
{
    int32_t o[2 * CTL];
    while (n--)
        mix_block(o, CTL);
}

#if FELUCCA_ARENA_CHECK
static uint32_t af_n, af_why, af_want;
static const track_t *af_t;
static void af_handler(uint32_t why, const track_t *t, uint32_t want)
{
    af_n++;
    af_why = why;
    af_want = want;
    af_t = t;
}
static uint32_t af_bad;
#define EXPECT(c)                                                                                                      \
    do {                                                                                                               \
        if (!(c)) {                                                                                                    \
            printf("arena_test: FAIL line %d: %s\n", __LINE__, #c);                                                    \
            af_bad++;                                                                                                  \
        }                                                                                                              \
    } while (0)
static int in_arena(const void *p) { return (const uint8_t *)p >= (const uint8_t *)eng_mem && (const uint8_t *)p < (const uint8_t *)(eng_mem + NPART); }
static int in_scratch(const void *p) { return (const uint8_t *)p >= (const uint8_t *)eng_arena_scratch && (const uint8_t *)p < (const uint8_t *)(eng_arena_scratch + 1) + sizeof eng_arena_scratch - sizeof eng_arena_scratch[0]; }

static int fixtures(void)
{
    track_t *t = &trk[1];
    static track_t fake;
    void *r;
    uint32_t e;
    af_bad = 0;
    eng_arena_fail = af_handler;
    host_tracks_init();
    memset(eng_mem, 0, sizeof eng_mem);
    memset(eng_mem_owner, 0, sizeof eng_mem_owner);

    /* wrong engine: the part renders ANALOG, the region is PHYS's */
    t->engine = 0;
    eng_mem_owner[1] = ENGI_PHYS + 1u;
    af_n = 0;
    r = (void *)gr_of(t);
    EXPECT(af_n == 1 && af_why == ARENA_BAD_ENGINE && af_want == ENGI_GRAIN && af_t == t && in_scratch(r) && !in_arena(r));
    af_n = 0;
    r = phys_slot_of(t, &t->v[0]);
    EXPECT(af_n == 1 && af_why == ARENA_BAD_ENGINE && af_want == ENGI_PHYS && in_scratch(r));

    /* unclaimed owner (none, then another engine's) of the rendered engine */
    for (e = 0; e < NENGINES; e++) {
        if (!eng_ok(e) || !eng_of(e)->mem) continue;
        t->engine = e;
        eng_mem_owner[1] = 0;
        af_n = 0;
        r = eng_mem_of(t, e);
        EXPECT(af_n == 1 && af_why == ARENA_BAD_OWNER && af_want == e && in_scratch(r));
        eng_mem_owner[1] = (uint8_t)((e + 1u) % NENGINES + 1u);
        af_n = 0;
        r = eng_mem_of(t, e);
        EXPECT(af_n == 1 && af_why == ARENA_BAD_OWNER && in_scratch(r));
        eng_mem_owner[1] = (uint8_t)(e + 1u);               /* claimed: succeeds, the part's own region */
        af_n = 0;
        r = eng_mem_of(t, e);
        EXPECT(af_n == 0 && r == ENG_MEM(1));
    }

    /* invalid part: past the table, off a track boundary, a copy outside trk[] (the accessors with their own
     * range guard return 0 first; GRAIN's gr_of and the checker itself get there) */
    {
        const track_t *bad[3] = {&trk[NPART], (const track_t *)((const uint8_t *)&trk[0] + 1), &fake};
        uint32_t i;
        for (i = 0; i < 3u; i++) {
            af_n = 0;
            r = eng_mem_of(bad[i], ENGI_PHYS);
            EXPECT(af_n == 1 && af_why == ARENA_BAD_PART && af_t == bad[i] && in_scratch(r));
        }
        af_n = 0;
        r = (void *)gr_of(&fake);
        EXPECT(af_n == 1 && af_why == ARENA_BAD_PART && in_scratch(r));
        EXPECT(phys_slot_of(&fake, &fake.v[0]) == 0 && fm6_note_of(&fake, &fake.v[0]) == 0 && drum_kit_of(&fake) == 0 &&
               slc_rb(&fake, &fake.v[0]) == 0);
    }

    /* a fade: PHYS sounding on part 1, eng_req names FM6. The old engine's access succeeds while it fades,
     * FM6's does not (eng_req is no owner); after the switch the roles are exchanged */
    host_tracks_init();
    memset(eng_mem, 0, sizeof eng_mem);
    memset(eng_mem_owner, 0, sizeof eng_mem_owner);
    host_preset(t, ENGI_PHYS, 0);
    input_on(t, 60, 100);
    blocks(8);
    host_preset_req(t, ENGI_FM6, 0);
    input_on(t, 64, 100);                                       /* waits inside the fade */
    af_n = 0;
    blocks(1);
    EXPECT(t->xf_on && t->engine == ENGI_PHYS && t->eng_req == ENGI_FM6);
    EXPECT(af_n == 0);                                          /* the fade rendered with the old engine's state */
    EXPECT(phys_slot_of(t, &t->v[0]) == (phys_slot_t *)ENG_MEM(1) && af_n == 0);
    r = fm6_note_of(t, &t->v[0]);
    EXPECT(af_n == 1 && af_why == ARENA_BAD_ENGINE && af_want == ENGI_FM6 && in_scratch(r));
    blocks(XF_BLOCKS + 2u);
    EXPECT(!t->xf_on && t->engine == ENGI_FM6 && eng_mem_owner[1] == ENGI_FM6 + 1u);
    af_n = 0;
    EXPECT(fm6_note_of(t, &t->v[0]) == (fm6_note_t *)ENG_MEM(1) && af_n == 0);
    r = phys_slot_of(t, &t->v[0]);
    EXPECT(af_n == 1 && af_why == ARENA_BAD_ENGINE && in_scratch(r));
    printf("arena_test: negative fixtures: %s\n", af_bad ? "FAIL" : "ok");
    eng_arena_fail = eng_arena_trap;
    return af_bad != 0;
}
#endif

/* ---- random runs */
#ifndef TAIL_S
#define TAIL_S 20u
#endif
static uint32_t rs;
static uint32_t rnd(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 17;
    rs ^= rs << 5;
    return rs;
}
/* Random switching covers every selectable engine, including new arena consumers. */
#define NRE NENG_SHOWN
#define RE_AT(k) eng_vis(k)

#if FELUCCA_ARENA_CHECK
static void run_handler(uint32_t why, const track_t *t, uint32_t want)
{
    printf("arena_test: arena access failed (why %u, part %ld, engine %u)\n", why, (long)(t - trk), want);
    fflush(stdout);
    _exit(3);
}
#endif

static int rrun(uint32_t seed)
{
    int32_t o[2 * CTL];
    uint32_t step, i, p, mx = 0, held[NPART][8] = {{0}}, nheld[NPART] = {0}, sw = 0, nblk;
    host_tracks_init();
    rs = seed * 2654435761u + 1u;
    for (step = 0; step < 500u; step++) {
        uint32_t a = rnd() % 16u;
        track_t *t = &trk[rnd() % NPART];
        p = (uint32_t)(t - trk);
        if (a < 5u) {                                               /* note on (a retrigger when held) */
            uint32_t n = 36u + rnd() % 48u;
            input_on(t, n, 20u + rnd() % 108u);
            if (nheld[p] < 8u)
                held[p][nheld[p]++] = n;
        } else if (a < 8u && nheld[p]) {                            /* note off */
            uint32_t k = rnd() % nheld[p];
            input_off(t, held[p][k]);
            held[p][k] = held[p][--nheld[p]];
        } else if (a < 10u) {                                       /* rapid switches */
            host_preset_req(t, RE_AT(rnd() % NRE), rnd() % 8u);
            sw++;
            if (rnd() & 1u)
                host_preset_req(t, RE_AT(rnd() % NRE), rnd() % 8u);
            if (rnd() & 1u) {                                       /* a note inside the fade */
                uint32_t n = 36u + rnd() % 48u;
                input_on(t, n, 100);
                if (nheld[p] < 8u)
                    held[p][nheld[p]++] = n;
            }
        } else if (a < 11u && t->eng_req == ENGI_PHYS) {            /* PHYS MODEL change under sounding notes */
            t->p[P_E0] = (int16_t)(rnd() % 4u);
        } else if (a < 12u) {                                       /* a note-off of nothing held, a chord */
            input_off(t, 36u + rnd() % 48u);
            input_on(t, 48u + rnd() % 24u, 90);
            input_on(t, 55u + rnd() % 24u, 90);
        }
        for (nblk = rnd() % 24u; nblk--;) {
            mix_block(o, CTL);
            for (i = 0; i < 2u * CTL; i++) {
                uint32_t m = (uint32_t)(o[i] < 0 ? -o[i] : o[i]);
                mx = m > mx ? m : mx;
            }
        }
        if (mx > 65536u * 4u) {
            printf("arena_test: seed %u: output %u out of bounds\n", seed, mx);
            return 1;
        }
    }
    for (p = 0; p < NPART; p++) {                                   /* release everything, let the fades finish */
        blocks(XF_BLOCKS + 2u);
        for (i = 0; i < 128u; i++)
            input_off(&trk[p], i);
    }
    blocks(TAIL_S * FS / CTL);                                  /* the release tails */
    for (p = 0; p < NPART; p++)
        for (i = 0; i < NVOICE; i++)
            if (trk[p].v[i].active) {
                printf("arena_test: seed %u: part %u voice %u still active (engine %u req %u gate %u stage %u env %d xf %u)\n", seed, p, i,
                       trk[p].engine, trk[p].eng_req, trk[p].v[i].gate, trk[p].v[i].stage, (int)trk[p].v[i].env, trk[p].xf_on);
                return 1;
            }
    mx = 0;
    for (i = 0; i < 40u; i++) {
        uint32_t k;
        mix_block(o, CTL);
        for (k = 0; k < 2u * CTL; k++)
            mx = (uint32_t)(o[k] < 0 ? -o[k] : o[k]) > mx ? (uint32_t)(o[k] < 0 ? -o[k] : o[k]) : mx;
    }
    if (mx > 8u) {
        printf("arena_test: seed %u: not silent after the release (%u)\n", seed, mx);
        return 1;
    }
    (void)sw;
    return 0;
}

#define SEED0 1u
int main(int argc, char **argv)
{
    uint32_t n = argc > 1 ? (uint32_t)atoi(argv[1]) : 24u, s, bad = 0;
    int rc = 0;
#if FELUCCA_ARENA_CHECK
    rc |= fixtures();
#else
    printf("arena_test: negative fixtures skipped (build with -DFELUCCA_ARENA_CHECK=1)\n");
#endif
    for (s = 0; s < n; s++) {
        pid_t pid;
        fflush(stdout);
        pid = fork();
        int st = 0;
        if (!pid) {
#if FELUCCA_ARENA_CHECK
            eng_arena_fail = run_handler;
#endif
            { int r = rrun(SEED0 + s); fflush(stdout); _exit(r); }
        }
        waitpid(pid, &st, 0);
        if (!WIFEXITED(st) || WEXITSTATUS(st)) {
            printf("arena_test: seed %u FAIL (status %d)\n", SEED0 + s, st);
            bad++;
        }
    }
    printf("arena_test: %u random runs (seeds %u..%u), %u failed: %s\n", n, SEED0, SEED0 + n - 1u, bad,
           bad || rc ? "FAIL" : "ok");
    return bad || rc;
}
