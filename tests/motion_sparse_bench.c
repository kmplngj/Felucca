/* SPDX-License-Identifier: GPL-3.0-only */
/* Opt-in host measurement: same real source and counter as host regressions.
 * Arguments: pairs, target batch ns, pilot loops, minimum loops, maximum loops.
 * This is not a default suite test or a target/device timing budget. */
#define UI_TEST_NO_MAIN 1
#include BENCH_UI
#include <time.h>
#include <unistd.h>
#include "host_instructions.h"

static uint64_t bench_window_start, bench_window_ns;
static volatile uint64_t bench_sink;
static uint64_t bench_now(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &ts)) exit(2);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
}
static uint32_t bench_guard_begin(void)
{
    bench_window_start = bench_now();
    return 1;
}
static void bench_guard_end(uint32_t token)
{
    uint64_t end = bench_now();
    if (token != 1u) exit(3);
    bench_window_ns += end - bench_window_start;
}
#include BENCH_REFERENCE

typedef void (*bench_fn)(track_t *, const motion_store_t *);
static bench_fn volatile bench_action;
static uint32_t bench_mask[4];
static motion_store_t bench_store;

static __attribute__((noinline)) void bench_original_restore(track_t *t, const motion_store_t *m)
{ (void)m; bench_original_restore_raw(t); }
static __attribute__((noinline)) void bench_candidate_restore(track_t *t, const motion_store_t *m)
{ (void)m; motion_restore(t); }
static __attribute__((noinline)) void bench_original_unlock(track_t *t, const motion_store_t *m)
{ bench_original_unlock_raw(t, 31u, m); }
static __attribute__((noinline)) void bench_candidate_unlock(track_t *t, const motion_store_t *m)
{ motion_unlock(t, 31u, m); }
static __attribute__((noinline)) void bench_original_guard(track_t *t, const motion_store_t *m)
{ (void)m; bench_original_guard_raw(t); }
static __attribute__((noinline)) void bench_candidate_guard(track_t *t, const motion_store_t *m)
{ (void)m; bench_candidate_guard_raw(t); }
static __attribute__((noinline)) void bench_probe(track_t *t, const motion_store_t *m)
{ (void)t; (void)m; uint32_t token = bench_guard_begin(); bench_guard_end(token); }

static uint64_t bench_checksum(void)
{
    uint64_t sum = 1469598103934665603ull;
    for (uint32_t id = 0; id < P_COUNT; id++) sum = (sum ^ (uint16_t)trk[0].p[id]) * 1099511628211ull;
    for (uint32_t w = 0; w < 4u; w++) {
        sum = (sum ^ motion_active[0][w]) * 1099511628211ull;
        sum = (sum ^ motion_locked[0][w]) * 1099511628211ull;
    }
    return sum;
}
static void bench_input(uint32_t density, uint32_t records)
{
    static const uint8_t sparse[] = {0, 31, 32, 63, 64, 95, 96, 110};
    memset(bench_mask, 0, sizeof bench_mask);
    if (density == 1u) bench_mask[110u / 32u] = 1u << (110u % 32u);
    if (density == 2u)
        for (uint32_t i = 0; i < NELEM(sparse); i++) bench_mask[sparse[i] / 32u] |= 1u << (sparse[i] % 32u);
    if (density == 3u) { for (uint32_t w = 0; w < 3u; w++) bench_mask[w] = ~0u; bench_mask[3] = 0x7fffu; }
    memset(&bench_store, 0, sizeof bench_store);
    bench_store.count = (uint8_t)records; bench_store.on = 1;
    for (uint32_t i = 0; i < records; i++)
        bench_store.event[i] = (motion_event_t){(uint8_t)(i % 64u), (uint8_t)((i < 64u ? P_REV : P_E7) | (i % 3u ? 0u : MOTION_LOCK)), (int8_t)(i % 128u)};
    memcpy(trk[0].p, motion_base[0], sizeof trk[0].p);
}
typedef struct { uint64_t elapsed, instructions, window, sink; int counter; } bench_result;
static bench_result bench_run(bench_fn fn, uint32_t loops, int count)
{
    uint64_t before = 0, after = 0, start, end;
    char why[256] = {0};
    bench_action = fn; bench_window_ns = 0;
    int available = count && instr_now(&before, why, sizeof why);
    start = bench_now();
    for (uint32_t i = 0; i < loops; i++) {
        memcpy(motion_active[0], bench_mask, sizeof bench_mask);
        memcpy(motion_locked[0], bench_mask, sizeof bench_mask);
        __asm__ volatile("" ::: "memory");
        bench_action(&trk[0], &bench_store);
        __asm__ volatile("" ::: "memory");
    }
    end = bench_now();
    available = available && instr_now(&after, why, sizeof why) && after > before;
    uint64_t checksum = bench_checksum(); bench_sink ^= checksum;
    return (bench_result){end - start, available ? after - before : 0, bench_window_ns, checksum, available};
}
int main(int argc, char **argv)
{
    _Static_assert(P_COUNT == 111u && MOTION_MAX == 128u, "review current domain");
    if (argc != 6) return 2;
    uint32_t pairs = (uint32_t)strtoul(argv[1], 0, 0);
    uint64_t target_ns = strtoull(argv[2], 0, 0);
    uint32_t pilot_loops = (uint32_t)strtoul(argv[3], 0, 0);
    uint32_t minimum = (uint32_t)strtoul(argv[4], 0, 0), maximum = (uint32_t)strtoul(argv[5], 0, 0);
    if (!pairs || !target_ns || !pilot_loops || !minimum || minimum > maximum) return 2;
    ui_power_on();
    set_engine_of(&trk[0], 0); apply_preset_to(&trk[0], 1);
    memcpy(motion_base[0], trk[0].p, sizeof trk[0].p);
    char why[256] = {0}; int counter = instr_begin(why, sizeof why);
    printf("{\"kind\":\"environment\",\"counter_available\":%d,\"counter_source\":\"%s\",\"counter_reason\":\"%s\"}\n", counter, CPU_SRC, why);
    bench_fn actions[3][2] = {{bench_original_restore, bench_candidate_restore},
                             {bench_original_unlock, bench_candidate_unlock},
                             {bench_original_guard, bench_candidate_guard}};
    for (uint32_t mode = 0; mode < 3u; mode++) for (uint32_t density = 0; density < 4u; density++) for (uint32_t records = 0; records <= 128u; records += 128u) {
        bench_input(density, records);
        bench_result pilot = bench_run(actions[mode][0], pilot_loops, 0);
        double desired = (double)target_ns * pilot_loops / (double)(pilot.elapsed ? pilot.elapsed : 1);
        uint32_t loops = desired > maximum ? maximum : desired < minimum ? minimum : (uint32_t)desired;
        bench_run(actions[mode][0], loops, 0); bench_run(actions[mode][1], loops, 0);
        printf("{\"kind\":\"calibration\",\"mode\":%u,\"density\":%u,\"records\":%u,\"loops\":%u,\"pilot_ns\":%llu}\n", mode, density, records, loops, (unsigned long long)pilot.elapsed);
        for (uint32_t pair = 0; pair < pairs; pair++) {
            bench_result result[2];
            for (uint32_t j = 0; j < 2u; j++) {
                uint32_t variant = (pair + j) % 2u;
                result[variant] = bench_run(actions[mode][variant], loops, counter);
            }
            if (result[0].sink != result[1].sink) { fprintf(stderr, "unequal observable sinks\n"); return 4; }
            for (uint32_t variant = 0; variant < 2u; variant++) {
                bench_result r = result[variant];
                printf("{\"kind\":\"sample\",\"mode\":%u,\"density\":%u,\"records\":%u,\"pair\":%u,\"first\":%u,\"variant\":%u,\"loops\":%u,\"elapsed_ns\":%llu,\"window_ns\":%llu,\"counter_available\":%d,\"instructions\":%llu,\"sink\":\"%016llx\"}\n", mode, density, records, pair, pair % 2u, variant, loops, (unsigned long long)r.elapsed, (unsigned long long)r.window, r.counter, (unsigned long long)r.instructions, (unsigned long long)r.sink);
            }
            fflush(stdout);
        }
    }
    bench_input(0, 0);
    uint32_t probe_loops = maximum < 100000u ? maximum : 100000u;
    for (uint32_t pair = 0; pair < pairs; pair++) {
        bench_result r = bench_run(bench_probe, probe_loops, counter);
        printf("{\"kind\":\"bookend-probe\",\"pair\":%u,\"loops\":%u,\"elapsed_ns\":%llu,\"window_ns\":%llu}\n", pair, probe_loops, (unsigned long long)r.elapsed, (unsigned long long)r.window);
    }
    printf("{\"kind\":\"final\",\"sink\":\"%016llx\"}\n", (unsigned long long)bench_sink);
    return 0;
}
