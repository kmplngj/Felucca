/* SPDX-License-Identifier: GPL-3.0-only */
/* Test-only instruction counter injection. DSP rendering and worker IPC remain real. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned job;
static unsigned next_job(void)
{
    unsigned n = 0;
    FILE *f = fopen(getenv("COUNTER_STATE"), "r+b");
    if (!f || fread(&n, sizeof n, 1, f) != 1)
        _exit(90);
    n++;
    rewind(f);
    if (fwrite(&n, sizeof n, 1, f) != 1 || fclose(f))
        _exit(91);
    return n;  /* CPU workers run sequentially, so no concurrent state-file writers. */
}
static int unavailable(void)
{
    return job == (unsigned)atoi(getenv("COUNTER_FAIL_JOB"));
}

#ifdef __APPLE__
#include <libproc.h>
#include <sys/resource.h>
static int fake_rusage(pid_t pid, int flavor, rusage_info_t *buffer)
{
    static unsigned calls;
    struct rusage_info_v4 *ri = (struct rusage_info_v4 *)buffer;
    (void)pid;
    if (flavor != RUSAGE_INFO_V4)
        _exit(92);
    if (!calls)
        job = next_job();
    if (unavailable()) {
        if (getenv("COUNTER_CRASH"))
            _exit(42);
        return -1;
    }
    memset(ri, 0, sizeof *ri);
    ri->ri_instructions = calls++ ? UINT64_C(1000000000000) : 0;
    return 0;
}
__attribute__((used)) static const struct { const void *replacement, *original; }
interpose __attribute__((section("__DATA,__interpose"))) = {
    (const void *)fake_rusage, (const void *)proc_pid_rusage
};
#elif defined(__linux__)
#include <dlfcn.h>
#include <errno.h>
#include <sys/syscall.h>
#define FAKE_FD 1000000
long syscall(long number, ...)
{
    /* The harness uses syscall only for perf_event_open; fail on unexpected use. */
    if (number != SYS_perf_event_open)
        _exit(92);
    job = next_job();
    return FAKE_FD;
}
ssize_t read(int fd, void *buffer, size_t size)
{
    static unsigned calls;
    uint64_t *values = buffer;
    if (fd != FAKE_FD) {
        ssize_t (*real_read)(int, void *, size_t) = dlsym(RTLD_NEXT, "read");
        return real_read(fd, buffer, size);
    }
    if (size != 3 * sizeof(uint64_t))
        _exit(93);
    if (unavailable()) {
        if (getenv("COUNTER_CRASH"))
            _exit(42);
        errno = EIO;
        return -1;
    }
    values[0] = calls++ ? UINT64_C(1000000000000) : 0;
    values[1] = values[2] = 1000;
    return (ssize_t)size;
}
#endif
