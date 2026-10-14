/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 gospodindilly-ops */
/* The second core (fx.c mix_block, hal/fm1_cpu1.h) on the host, after Jangada's tests/dualcore_test.c
 * (github.com/zednaked/jangada, GPL-3.0). Four parts of the same engine at once (every preset of every engine), and
 * mixes of different engines; every part with something that keeps state of its own while it renders: an INSERT, the
 * SLICER (part 1), SPREAD (part 2), the matrix with LFO S&H, which draws from the shared generator (parts 0 and 3),
 * ENV SYNC (part 0); and PHYS's model changed under a sounding note. Each scene is rendered on one core, and again with
 * a thread as core 1 (tests/c1_host.h) taking every split of the parts in turn, the firmware's own choice
 * (mix_split) and fixed splits. The outputs must be bit for bit the same; built with -fsanitize=thread
 * (run_tests.sh TSAN=1), nothing two parts share may be touched by both at once.
 * Identical FORMANT parts also check that random vowels and breath use different per-part streams, separately;
 * synchronized RAND-only / breath-only scenes compare the serial schedule with every threaded split.
 *   build/host/dualcore_test          SCENE=text: only the scenes whose name holds it */
#include "c1_host.h"
#define main hostsim_main
#include "hostsim.c"
#undef main

#define SECS 3u

typedef struct { const char *name; uint8_t eng[NPART], pre[NPART]; uint8_t morph, identical; } scen_t;

static int32_t peak[NPART];                         /* each part's loudest (track_t.peak), for the check */

/* Fresh identical voices must not share their note-local vowel or breath stream. Test each source separately;
 * a different vowel could otherwise conceal identical breath. Run in a child to retain boot state for scenes. */
static int formant_separation(uint32_t breath)
{
    int32_t out[NPART][CTL * 4] = {{0}};
    uint32_t k, j, i;
    vmod_t m = {0};
    host_tracks_init();
    m.inc = pitch_inc(60u * 16u);
    m.pitch16 = 60 * 16;
    m.amp0 = m.amp1 = 32768;
    m.envq15 = 32768;
    m.shape = 64 << 8;
    for (k = 0; k < NPART; k++) {
        track_t *t = &trk[k];
        voice_t *v = &t->v[0];
        host_preset(t, 5, 0);
        t->p[P_E5] = breath ? 120 : 0;
        t->p[P_E7] = breath ? 0 : 127;
        v->note = 60;
        v->vel = 96;
        v->active = v->gate = v->stage = 1;
        v->pitch16 = v->pitch_cur = 60 * 16;
        ENG_FORMANT.note_on(t, v);
        for (i = 0; i < 4; i++)
            ENG_FORMANT.render(t, v, out[k] + i * CTL, CTL, &m);
        for (j = 0; j < k; j++) {
            if (!breath && ((uint32_t)v->s[7] >> 25) == ((uint32_t)trk[j].v[0].s[7] >> 25))
                return 1;
            if (!memcmp(out[k], out[j], sizeof out[k]))
                return 1;
        }
    }
    return 0;
}

static int formant_separation_fork(uint32_t breath)
{
    pid_t pid = fork();
    int status;
    if (pid < 0)
        return 1;
    if (!pid)
        _exit(formant_separation(breath));
    if (waitpid(pid, &status, 0) != pid)
        return 1;
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}

static void part_setup(track_t *t, uint32_t k, uint32_t e)
{
    t->p[P_ITYPE] = (int16_t)((k * 4u + e) % IT_N);  /* an INSERT on most parts (its own state, ins[]) */
    t->p[P_IMIX] = 90;
    t->p[P_REV] = (int16_t)(20 + 10 * k);
    t->p[P_DLY] = (int16_t)(10 * k);
    t->p[P_CHOR] = (int16_t)(30 - 5 * k);
    if (k == 0u) {
        t->p[P_ESYNC] = 1;                          /* ENV SYNC: t->esync_k */
        t->p[P_LWAVE] = 4;                          /* S&H: lfo_rand, the shared generator (parts 0..2) */
        t->p[P_LRATE] = 110;
        t->p[P_LD_FLT] = 20;
    }
    if (k == 1u) {
        t->p[P_SLCR] = 1;                           /* the SLICER: sl[1] */
        t->p[P_SLDEPTH] = 100;
    }
    if (k == 2u)
        t->p[P_SPRD] = 100;                         /* SPREAD: t->spread_on, spread_buf[2] */
    if (k == 3u) {
        t->p[P_LWAVE] = 4;                          /* S&H (part 3: its own generator) into the matrix */
        t->p[P_LRATE] = 100;
        t->p[P_M1SRC] = MS_SH;
        t->p[P_M1DST] = MD_CUT;
        t->p[P_M1AMT] = 40;
        t->p[P_M2SRC] = MS_LFO;
        t->p[P_M2DST] = MD_RATE;                    /* (a per-block destination: t->p while it renders) */
        t->p[P_M2AMT] = 20;
    }
}

static uint64_t render(const scen_t *sc, int dual, const char *mask)
{
    static const uint8_t CH[3] = {0, 7, 12};
    uint64_t h = 0xCBF29CE484222325ull;
    uint32_t f, k, i;
    int32_t o[2 * CTL];
    host_tracks_init();
    c1h_off = !dual;
    if (mask)
        setenv("C1_MASK", mask, 1);
    for (k = 0; k < NPART; k++) {
        host_preset(&trk[k], sc->eng[k], sc->pre[k]);
        if (sc->identical) {
            /* Same patch, pitch, velocity and event times: RNG separation cannot hide behind track settings. */
            trk[k].p[P_CHOR] = trk[k].p[P_DLY] = trk[k].p[P_REV] = 0;
            trk[k].p[P_ATK] = 0;
            trk[k].p[P_E5] = sc->identical == 2 ? 120 : 0;
            trk[k].p[P_E7] = sc->identical == 2 ? 0 : 127;
        } else {
            part_setup(&trk[k], k, sc->eng[k]);
        }
    }
    for (f = 0; f < SECS * FS; f += CTL) {
        uint32_t ms = f / (FS / 1000u);
        for (k = 0; k < NPART; k++) {
            uint32_t on = 100u + (sc->identical ? 0 : 330u * k), off = on + 1400u;
            uint32_t base = sc->identical ? 60u : 48u + 5u * k;
            if (ms == on || ms == on + 700u)
                for (i = 0; i < 2u; i++)
                    trk_note_on(&trk[k], base + CH[i + (ms != on)], sc->identical ? 100 : 90 + 10 * k);
            if (ms == off)
                for (i = 0; i < 3u; i++)
                    trk_note_off(&trk[k], base + CH[i]);
        }
        if (sc->morph && ms == 600u)                /* PHYS: MODEL changed under a sounding note (phys_render) */
            trk[0].p[P_E0] = (int16_t)((trk[0].p[P_E0] + 1) % PM_COUNT);
        mix_block(o, CTL);
        for (k = 0; k < NPART; k++)
            if (trk[k].peak > peak[k])
                peak[k] = trk[k].peak;
        for (i = 0; i < 2u * CTL; i++) {
            uint32_t u = (uint32_t)o[i];
            for (k = 0; k < 4u; k++) {
                h ^= (u >> (8u * k)) & 0xFFu;
                h *= 0x100000001B3ull;
            }
        }
    }
    return h;
}

/* in a child of its own: every render starts from the state at boot */
static uint64_t render_fork(const scen_t *sc, int dual, const char *mask, uint32_t *taken)
{
    int fd[2];
    uint64_t h = 0;
    pid_t pid;
    if (pipe(fd))
        return 0;
    pid = fork();
    if (!pid) {
        h = render(sc, dual, mask);
        if (write(fd[1], &h, sizeof h) != sizeof h || write(fd[1], peak, sizeof peak) != sizeof peak ||
            write(fd[1], &c1h_taken, sizeof c1h_taken) != sizeof c1h_taken)
            _exit(2);
        _exit(0);
    }
    close(fd[1]);
    if (read(fd[0], &h, sizeof h) != sizeof h || read(fd[0], peak, sizeof peak) != sizeof peak ||
        read(fd[0], taken, sizeof *taken) != sizeof *taken)
        h = 0;
    close(fd[0]);
    waitpid(pid, 0, 0);
    return h;
}

int main(void)
{
    static scen_t sc[256];
    static char names[256][40];
    static const char *const MASKS[] = {"rot", "auto", "5", "10", "3", "12", "1"};
    uint32_t n = 0, e, i, k, g, fail = 0;
    for (i = 0; i < 2; i++) {
        uint32_t bad = (uint32_t)formant_separation_fork(i);
        printf("dualcore: identical VOICE parts, %-6s streams separated   %s\n", i ? "breath" : "RAND", bad ? "FAIL" : "ok");
        fail += bad;
    }
    for (e = 0; e < NENGINES; e++) {                    /* every preset: four parts at a time */
        if (!eng_ok(e))                                 /* (a retired number: DIGITAL without FELUCCA_FM4) */
            continue;
        for (g = 0; g * NPART < ENGINES[e]->npresets; g++) {
            snprintf(names[n], sizeof names[n], "4 x %s %u..%u", ENGINES[e]->name, g * NPART, g * NPART + NPART - 1u);
            sc[n].name = names[n];
            for (k = 0; k < NPART; k++) {
                sc[n].eng[k] = (uint8_t)e;
                sc[n].pre[k] = (uint8_t)((g * NPART + k) % ENGINES[e]->npresets);
            }
            sc[n++].morph = 0;
        }
    }
    sc[n++] = (scen_t){"PHYS FM6 ANALOG DRUM", {ENGI_PHYS, ENGI_FM6, 0, ENGI_DRUM}, {1, 4, 7, 0}, 0};
    sc[n++] = (scen_t){"GRAIN NOISE VOICE LOFI", {8, 11, 5, 3}, {1, 4, 7, 10}, 0};
    sc[n++] = (scen_t){"TRIO WHEEL PHASE FM6", {6, 7, 2, ENGI_FM6}, {1, 4, 7, 10}, 0};
    sc[n++] = (scen_t){"PHYS morph + DRUM GRAIN ANALOG", {ENGI_PHYS, ENGI_DRUM, 8, 0}, {2, 1, 3, 5}, 1};
    sc[n++] = (scen_t){"VOICE identical RAND", {5, 5, 5, 5}, {0, 0, 0, 0}, 0, 1};
    sc[n++] = (scen_t){"VOICE identical breath", {5, 5, 5, 5}, {0, 0, 0, 0}, 0, 2};
#if FELUCCA_SLICE
    sc[n++] = (scen_t){"SAMPLE SLICE GRAIN PHASE", {ENGI_SAMPLE, 13, 8, 2}, {2, 1, 3, 5}, 0};
    sc[n++] = (scen_t){"SLICE FM6 SAMPLE DRUM", {13, ENGI_FM6, ENGI_SAMPLE, ENGI_DRUM}, {0, 2, 3, 4}, 0};
#else
    sc[n++] = (scen_t){"SAMPLE FM6 GRAIN PHASE", {ENGI_SAMPLE, ENGI_FM6, 8, 2}, {2, 1, 3, 5}, 0};
#endif
    for (i = 0; i < n; i++) {
        uint64_t ref;
        uint32_t m, bad = 0, quiet = 0, taken = 0, took = 0;
        if (getenv("SCENE") && !strstr(sc[i].name, getenv("SCENE")))
            continue;
        ref = render_fork(&sc[i], 0, 0, &taken);
        for (k = 0; k < NPART; k++)
            quiet += peak[k] < 200;
        if (quiet) {                                    /* a silent part proves nothing */
            printf("dualcore: %-34s %u part(s) silent: peaks %d %d %d %d   FAIL\n", sc[i].name, quiet, peak[0],
                   peak[1], peak[2], peak[3]);
            fail++;
            continue;
        }
        for (m = 0; m < sizeof MASKS / sizeof MASKS[0]; m++) {
            uint64_t h = render_fork(&sc[i], 1, MASKS[m], &taken);
            took += taken != 0;
            if (h != ref || !h) {
                printf("dualcore: %-34s split %-4s FAIL (%016llx, one core %016llx)\n", sc[i].name, MASKS[m],
                       (unsigned long long)h, (unsigned long long)ref);
                bad++;
            }
        }
        if (took < 2u) {                                /* the thread must have rendered parts (auto may hand none) */
            printf("dualcore: %-34s the second core never took parts   FAIL\n", sc[i].name);
            bad++;
        }
        if (!bad)
            printf("dualcore: %-34s the same on two cores, every split   ok\n", sc[i].name);
        fail += bad != 0;
    }
    printf("dualcore: %u of %u scenes differ\n", fail, n);
    return fail != 0;
}
