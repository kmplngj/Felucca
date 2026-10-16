/* SPDX-License-Identifier: GPL-3.0-only */
/* Shared host-only counter policy: missing/multiplexed counters are unavailable. */
#ifndef FELUCCA_HOST_INSTRUCTIONS_H
#define FELUCCA_HOST_INSTRUCTIONS_H
#include <stdint.h>
#include <stdio.h>
#if defined(__APPLE__)
#include <libproc.h>
#include <sys/resource.h>
#elif defined(__linux__)
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <linux/perf_event.h>
#endif
#if defined(__APPLE__)
#define CPU_SRC "proc_pid_rusage RUSAGE_INFO_V4 ri_instructions, process"
static int instr_begin(char *why, size_t n)
{
    (void)why, (void)n;
    return 1;
}
static int instr_now(uint64_t *v, char *why, size_t n)
{
    struct rusage_info_v4 ri;
    if (proc_pid_rusage(getpid(), RUSAGE_INFO_V4, (rusage_info_t *)&ri)) {
        snprintf(why, n, "proc_pid_rusage failed");
        return 0;
    }
    *v = ri.ri_instructions;
    return 1;
}
#elif defined(__linux__)
/* perf_event_open: user-space PERF_COUNT_HW_INSTRUCTIONS of the calling thread (pid 0, cpu -1; needs
 * perf_event_paranoid <= 2, no root). Opened in each child (never the parent's descriptor).
 * Multiplexed (running < enabled) is not comparable: no count. */
#define CPU_SRC "perf_event_open PERF_COUNT_HW_INSTRUCTIONS, user space, calling thread"
static int instr_fd = -1;
static int instr_begin(char *why, size_t n)
{
    struct perf_event_attr a;
    if (instr_fd >= 0)
        close(instr_fd);                                /* never a descriptor inherited from the parent */
    memset(&a, 0, sizeof a);
    a.type = PERF_TYPE_HARDWARE;
    a.size = sizeof a;
    a.config = PERF_COUNT_HW_INSTRUCTIONS;
    a.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
    a.exclude_kernel = 1;
    a.exclude_hv = 1;
    instr_fd = (int)syscall(SYS_perf_event_open, &a, 0, -1, -1, 0);
    if (instr_fd < 0) {
        snprintf(why, n, "perf_event_open failed: %s (perf_event_paranoid > 2, no PMU, or blocked by a sandbox)",
                 strerror(errno));
        return 0;
    }
    return 1;
}
static int instr_now(uint64_t *v, char *why, size_t n)
{
    uint64_t b[3];                                      /* count, time enabled, time running */
    ssize_t r;
    if (instr_fd < 0) {
        snprintf(why, n, "no counter");
        return 0;
    }
    r = read(instr_fd, b, sizeof b);
    if (r != (ssize_t)sizeof b) {
        snprintf(why, n, "counter read failed (%zd bytes: %s)", r, r < 0 ? strerror(errno) : "short");
        return 0;
    }
    if (!b[1] || b[1] != b[2]) {
        snprintf(why, n, "counter multiplexed or never scheduled (enabled %llu ns, running %llu ns)",
                 (unsigned long long)b[1], (unsigned long long)b[2]);
        return 0;
    }
    *v = b[0];
    return 1;
}
#else
#define CPU_SRC "none"
static int instr_begin(char *why, size_t n)
{
    snprintf(why, n, "no instruction counter for this OS");
    return 0;
}
static int instr_now(uint64_t *v, char *why, size_t n)
{
    (void)v;
    snprintf(why, n, "no instruction counter for this OS");
    return 0;
}
#endif
#endif
