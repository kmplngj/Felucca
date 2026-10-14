/* SPDX-License-Identifier: GPL-3.0-only */
/* A worker can fail before, during or after advancing parts. Its sums are unusable and its state cannot be replayed. */
#include <stdint.h>
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

static int worker_run(void (*fn)(uint32_t), uint32_t arg)
{
    submissions++;
    fn(fail_mask < 0 ? arg : (arg & ~15u) | (uint32_t)fail_mask);
    return 1;
}
static int worker_wait(void)
{
    if (fail_mask < 0)
        return 0;
    worker_on = 0;                                      /* HAL has held the worker before returning */
    for (uint32_t i = 0; i < CTL; i++)
        mx[1].l[i] = mx[1].r[i] = mx[1].c[i] = mx[1].d[i] = mx[1].v[i] = 0x10000000;
    return -1;                                         /* deliberately unfinished/poisoned sums */
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
    return !ok;
}
