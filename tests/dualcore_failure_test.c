/* SPDX-License-Identifier: GPL-3.0-only */
/* A worker can fail before, during or after advancing parts. Its sums are unusable and its state cannot be replayed. */
#include <stdint.h>
#include <setjmp.h>
struct track;
static void params_interrupted(struct track *t);
#define C1_TEST_PARAMS(t) params_interrupted(t)
static jmp_buf interrupted;
static int cut_write, writes, in_worker, saw_changed;
static int worker_on = 1, fail_mask = -1, submissions;
static int worker_run(void (*fn)(uint32_t), uint32_t arg);
static int worker_wait(void);
#define C1_ON() worker_on
#define C1_RUN(fn, arg) worker_run(fn, arg)
#define C1_WAIT() worker_wait()
#define C1_SPLIT() 10u
#define main hostsim_main
#include "hostsim.c"
#undef main
#define PROJ_HOST 1
#include "../firmware/src/project.c"

static int16_t canonical[NPART][P_COUNT];
static void params_interrupted(track_t *t)
{
    if (in_worker && t == &trk[3] && cut_write && ++writes == cut_write) {
        saw_changed = memcmp(t->p, canonical[3], sizeof t->p) != 0;
        longjmp(interrupted, 1);                       /* the held worker never resumes or unwinds its swaps */
    }
}

static int worker_run(void (*fn)(uint32_t), uint32_t arg)
{
    submissions++;
    if (!setjmp(interrupted)) {
        in_worker = 1;
        fn(cut_write || fail_mask < 0 ? arg : (arg & ~15u) | (uint32_t)fail_mask);
    }
    in_worker = 0;
    return 1;
}
static int worker_wait(void)
{
    if (fail_mask < 0 && !cut_write)
        return 0;
    worker_on = 0;                                      /* HAL has held the worker before returning */
    for (uint32_t i = 0; i < CTL; i++)
        mx[1].l[i] = mx[1].r[i] = mx[1].c[i] = mx[1].d[i] = mx[1].v[i] = 0x10000000;
    return -1;                                         /* deliberately unfinished/poisoned sums */
}

/* The real project encoder must see the same saved bytes immediately after a timeout and on serial recovery. */
static int saved(project_store_t *out)
{
    project_t q = {0};
    memcpy(q.g, song.g, sizeof q.g);
    q.parts = NPART;
    for (uint32_t k = 0; k < NPART; k++) {
        memcpy(q.t[k].p, trk[k].p, sizeof trk[k].p);
        memcpy(q.t[k].step, trk[k].step, sizeof trk[k].step);
        q.t[k].engine = trk[k].eng_req;
        q.t[k].preset = trk[k].preset;
    }
    return proj_pack(out, &q);
}

static void partial_matrix(track_t *t)              /* every slot on: VEL to PAN, DIST, RATE, E2 */
{
    static const uint8_t dst[NMSLOT] = {MD_PAN, MD_DIST, MD_RATE, MD_E1 + 1};
    for (uint32_t j = 0; j < NMSLOT; j++) {
        t->p[P_M1SRC + 3 * j] = MS_VEL;
        t->p[P_M1DST + 3 * j] = dst[j];
        t->p[P_M1AMT + 3 * j] = 40;
    }
}

static int partial_params(uint32_t matrix, uint32_t fade, int cut)
{
    int32_t out[CTL * 2];
    project_store_t before, after;
    host_tracks_init();
    fail_mask = -1;
    cut_write = cut;
    for (uint32_t k = 0; k < NPART; k++) {
        track_t *t = &trk[k];
        host_preset(t, 0, 0);
        trk_note_on(t, 60 + k, 100);
        t->p[P_CHOR] = t->p[P_DLY] = t->p[P_REV] = 0;
        if (k == 0 || k == 2) t->p[P_LEVEL] = 0;
        if (matrix)
            partial_matrix(t);
    }
    if (fade) {
        /* Capture the sounding ANALOG values as events_block does, then request LOFI with distinct values. */
        engine_block(&trk[3]);
        host_preset_req(&trk[3], 2, 0);                   /* (the production load: the MOD slots at their */
        if (matrix)                                       /* defaults, so the matrix again, as before #298) */
            partial_matrix(&trk[3]);
        trk[3].p[P_E0] = trk[3].pe_old[0] ? 0 : 1;       /* even the first swap must expose a different value */
    }
    for (uint32_t k = 0; k < NPART; k++)
        memcpy(canonical[k], trk[k].p, sizeof trk[k].p);
    int ok = saved(&before);
    mix_block(out, CTL);
    ok &= saw_changed && writes == cut && submissions == 1 && !worker_on;
    for (uint32_t i = 0; i < NELEM(out); i++) ok &= out[i] == 0;
    for (uint32_t k = 0; k < NPART; k++)
        ok &= !memcmp(canonical[k], trk[k].p, sizeof trk[k].p) && !MOD(&trk[k]).on;
    ok &= saved(&after) && !memcmp(&before, &after, sizeof before);
    /* The worker's completed first part advanced once; the interrupted last part's fade was never completed. */
    if (fade) ok &= trk[3].xf == XF_BLOCKS;
    cut_write = 0;
    mix_block(out, CTL);
    ok &= submissions == 1;
    for (uint32_t k = 0; k < NPART; k++)
        ok &= !memcmp(canonical[k], trk[k].p, sizeof trk[k].p) && !MOD(&trk[k]).on;
    ok &= saved(&after) && !memcmp(&before, &after, sizeof before);
    if (fade) ok &= trk[3].xf == XF_BLOCKS - 1;
    printf("dual-core timeout: matrix %u fade %u write %d: canonical params + saved bytes + serial recovery: %s\n",
           matrix, fade, cut, ok ? "ok" : "FAIL");
    return !ok;
}

static int partial_child(uint32_t matrix, uint32_t fade, int cut)
{
    fflush(stdout);
    pid_t pid = fork();
    int status;
    if (pid < 0) exit(2);
    if (!pid) { int bad = partial_params(matrix, fade, cut); fflush(stdout); _exit(bad); }
    waitpid(pid, &status, 0);
    return status == 0;
}

typedef struct { track_t initial[NPART], first[NPART], second[NPART]; int zero, calls; } result_t;
static result_t render(int mask)
{
    result_t r;
    int32_t out[CTL * 2];
    host_tracks_init();
    fail_mask = mask;
    for (uint32_t k = 0; k < NPART; k++) {
        host_preset(&trk[k], 0, 0);
        trk_note_on(&trk[k], 60 + k, 100);
        trk[k].p[P_CHOR] = trk[k].p[P_DLY] = trk[k].p[P_REV] = 0;
        if (k == 0 || k == 2)
            trk[k].p[P_LEVEL] = 0;                     /* the completed core-0 parts contribute no sound */
    }
    memcpy(r.initial, trk, sizeof trk);
    mix_block(out, CTL);
    memcpy(r.first, trk, sizeof trk);
    r.zero = 1;
    for (uint32_t i = 0; i < 2 * CTL; i++)
        r.zero &= out[i] == 0;
    mix_block(out, CTL);
    memcpy(r.second, trk, sizeof trk);
    r.calls = submissions;
    return r;
}
static result_t child(int mask)
{
    result_t r;
    int fd[2], status;
    if (pipe(fd)) exit(2);
    pid_t pid = fork();
    if (pid < 0) exit(2);
    if (!pid) {
        close(fd[0]);
        r = render(mask);
        const char *p = (const char *)&r;
        size_t left = sizeof r;
        while (left) { ssize_t n = write(fd[1], p, left); if (n <= 0) _exit(2); p += n; left -= (size_t)n; }
        _exit(0);
    }
    close(fd[1]);
    char *p = (char *)&r;
    size_t left = sizeof r;
    while (left) { ssize_t n = read(fd[0], p, left); if (n <= 0) exit(2); p += n; left -= (size_t)n; }
    close(fd[0]);
    waitpid(pid, &status, 0);
    if (status) exit(2);
    return r;
}
int main(void)
{
    result_t reference = child(-1);
    int ok = reference.calls == 2;
    const int masks[] = {0, 2, 10};                     /* before the job, after one part, after both */
    for (uint32_t m = 0; m < NELEM(masks); m++) {
        result_t r = child(masks[m]);
        ok &= r.zero && r.calls == 1;
        for (uint32_t k = 0; k < NPART; k++) {
            int advanced = k == 0 || k == 2 || ((uint32_t)masks[m] >> k & 1u);
            const voice_t *first = advanced ? reference.first[k].v : r.initial[k].v;
            const voice_t *second = advanced ? reference.second[k].v : reference.first[k].v;
            ok &= !memcmp(r.first[k].v, first, sizeof r.first[k].v);
            ok &= !memcmp(r.second[k].v, second, sizeof r.second[k].v);
        }
    }
    puts(ok ? "dual-core failure: poisoned sums dropped, voices never replayed, next block serial: ok" : "dual-core failure: FAIL");
    /* Every canonical matrix destination and all eight fade parameters occur exactly once in the snapshot. */
    uint32_t covered[P_COUNT] = {0};
    for (uint32_t j = 0; j < C1_PARAM_N; j++) covered[mod_param(MD_PAN + j)]++;
    for (uint32_t d = MD_PAN; d < MD_DEPTH; d++) ok &= covered[mod_param(d)] == 1;
    static const uint8_t common[] = {P_PAN, P_DIST, P_CHOR, P_DLY, P_REV, P_LRATE, P_LD_PIT};
    for (uint32_t j = 0; j < NELEM(common); j++) ok &= covered[common[j]] == 1;
    for (uint32_t j = P_E0; j <= P_E7; j++) ok &= covered[j] == 1;
    for (int cut = 1; cut <= 4; cut++) ok &= partial_child(1, 0, cut);
    for (int cut = 1; cut <= 8; cut++) ok &= partial_child(0, 1, cut);
    for (int cut = 1; cut <= 12; cut++) ok &= partial_child(1, 1, cut);
    return !ok;
}
