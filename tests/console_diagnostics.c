/* SPDX-License-Identifier: GPL-3.0-only */
/* Compile the real console without DSP, generated assets or USB SIE emulation.
 * These fixtures supply state only; command dispatch and every output byte come
 * from console.c. Keep the output ring bounded and fail rather than wait if full. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef FELUCCA_UAC
#define FELUCCA_UAC 1
#endif
#ifndef FELUCCA_UART
#define FELUCCA_UART 1
#endif
#define FELUCCA_FLASH 1
#define FELUCCA_VERSION "console-contract"
static void observer_barrier(void);
#define RING_PUBLISH() observer_barrier()
#define CO_N 16384u
#define CI_N 128u
#define FM1_TICKS_PER_US 24u
#define FM1_GAP_BINS 8u
#define FM1_NCOL 11u
#define FM1_NENC 7u
#define FM1_CRASH_MAGIC 0x43525348u
#define G_BPM 0
#define P_COUNT 1
#define MQ 64u

static uint8_t cdc_out[CO_N], cdc_in[CI_N];
static uint32_t co_w, co_r, ci_w, ci_r;
static struct { uint8_t dtr; } cdc = {1};
static uint32_t fm1_ms = 10000;
static uint32_t shed_count = 12, voice_kills = 13;
static struct { uint32_t cpu_q8, sel, batt_raw, g[1], playing; } song = {64, 0, 620, {120}, 0};
static struct { uint32_t eng_req, preset; int32_t p[P_COUNT]; } track;
#define TSEL (&track)
typedef struct { const char *name; } preset_t;
typedef struct { const char *name; uint32_t npresets; const preset_t *presets; } engine_t;
static const preset_t presets[] = {{"BRASS ENSEMBLE"}};
static const engine_t engine = {"FM6", 1, presets};
static const engine_t *eng_of(uint32_t id) { (void)id; return &engine; }

/* Layout consumed by con_dbg, matching audio.c's 19 uint32_t words. */
static struct {
    uint32_t magic, halves, max_us, nested, in_audio, late, timer_irqs, ui_frames;
    uint32_t last_us, cpu_q8, boots, stage, page, home;
    uint32_t prev_stage, prev_page, prev_home, prev_rst, prev_frames;
} felucca_dbg = {0x44424731u, 8192, 900, 64, 0, 7, 4096, 100, 800, 64, 4, 9, 0, 0, 0, 0, 0, 0, 0};
static struct {
    uint32_t resets, sof_seen, suspends, retries, frame, frame_stalls, max_gap;
    uint32_t rx_pkts, tx_pkts, uboot_req;
} usb = {1, 8000, 2, 3, 42, 4, 5, 6, 7, 0};
#if FELUCCA_UAC
static struct {
    uint32_t pkts, r48, alt, rate_sets, starts, frames, underruns, overruns;
    uint32_t missed, stalls, adj_up, adj_down, fill_min, fill_lo, fill_hi;
} uac = {100, 1, 1, 2, 3, 4800, 4, 5, 6, 7, 8, 9, 10, 11, 12};
#endif
#if FELUCCA_UART
static struct { uint32_t bytes, msgs, drops; } um = {17, 18, 19};
#endif
static struct { uint8_t enc_rest[FM1_NENC]; } fm1_in;
/* last must precede the fields cleared by con_inp. */
static volatile struct {
    uint32_t last, gap_max, gap_hist[FM1_GAP_BINS];
    uint32_t on[FM1_NCOL], on_max[FM1_NCOL];
    uint32_t cost_sum, cost_max, ticks;
    uint32_t enc_moves[FM1_NENC], enc_lost[FM1_NENC];
    uint32_t press_n, press_sum, press_max, kb_n, kb_sum, kb_max, dac_sum, dac_max;
    uint32_t dim_n, dim_sum;
} fm1_in_stat = {.gap_max = 3120, .cost_sum = 1680000, .cost_max = 240, .ticks = 10000};
static uint32_t fm1__dim_k = 4;
typedef struct {
    uint32_t magic, count, vec, pc, rets, emu, dbg, sp, psr, icfg, uptime_ms;
    uint32_t etm[4], early;
#if FELUCCA_CRASH_CTX
    uint32_t ctx, r[16], usp, ssp;       /* hal/fm1_irq.h, FELUCCA_CRASH_CTX=1 diagnostic builds */
#endif
} fm1_crash_t;
static fm1_crash_t fm1_crash = {.magic = FM1_CRASH_MAGIC, .count = 2, .vec = 4, .pc = 0x02001234,
               .sp = 0x01C60000, .uptime_ms = 50};
#if FELUCCA_CRASH_CTX
#define FM1_CRASH_CTX_KEY 0x43545852u
#endif
#if FELUCCA_MUL64_REPRO
/* The counters of firmware/src/mul64_repro.c that `status` prints (fixed values; the kernel has its own test). */
static struct { uint32_t runs, inl_bad, nol_bad, ref_bad, first_var, first_run, first_xor; } mr =
    {4000000000u, 1, 0, 0, 1, 1234, 0x00800000u};
#endif

/* The console consumes a validated snapshot through the HAL accessor. The
 * fixture supplies fixed host state; retained-RAM publication has its own tests. */
static int fm1_crash_read(fm1_crash_t *copy)
{
    if (fm1_crash.magic != FM1_CRASH_MAGIC) return 0;
    *copy = fm1_crash;
    return 1;
}

static uint32_t fm1_ticks(void) { return 24000000u; }
static uint32_t fm1__lock(void) { return 0; }
static void fm1__unlock(uint32_t key) { (void)key; }
static void fm1_wdt_feed(void) { fputs("console output exceeded fixture ring\n", stderr); exit(2); }
static int fm1_mem_readable(uint32_t a, uint32_t n) { (void)a; (void)n; return 0; }
static uint8_t fm1_peek8(uint32_t a) { (void)a; abort(); }
static int flash_ok;
static int st_read(uint32_t a, void *b, uint32_t n) { (void)a; (void)b; (void)n; abort(); }

#include "../firmware/src/console.c"

#if FELUCCA_MIDI_QUEUE
static uint32_t observer_interrupt;
#endif
static void observer_barrier(void)
{
    __asm__ volatile("" ::: "memory");
#if FELUCCA_MIDI_QUEUE
    if (observer_interrupt && !--observer_interrupt) {
        midi_queue_seq++;
        midi_queue_finish(0, 0, 0, 0, 0, 1, 0); /* Complete an audio publication mid-copy. */
    }
#endif
}

int main(int argc, char **argv)
{
    size_t n;
#if FELUCCA_MIDI_QUEUE
    midi_queue_seq = 1;
    midi_queue_age(1, 0x90, 100, 0);
    midi_queue_age(2, 0x90, 0, 0x70000000u);
    midi_queue_finish(63, 2, 64, 0, 1, 0x70000001u, 0);
#endif
    if (argc < 2 || argc > 3 ||
        (strcmp(argv[1], "status") && strcmp(argv[1], "dbg") &&
         strcmp(argv[1], "inp") && strcmp(argv[1], "crash")))
        return 2;
#if FELUCCA_CRASH_CTX
    {
        uint32_t i;
        for (i = 0; i < 16u; i++)
            fm1_crash.r[i] = 0x01C60000u + i;
        fm1_crash.r[5] = 0x00800012u;        /* the donor's one-bit loop index */
        fm1_crash.usp = 0x01C40000u;
        fm1_crash.ssp = 0x01C7E000u;
        fm1_crash.ctx = FM1_CRASH_CTX_KEY ^ fm1_crash.count;
    }
#endif
    if (argc == 3) {
        if (!strcmp(argv[2], "no-crash"))
            fm1_crash.magic = 0;
#if FELUCCA_MIDI_QUEUE
        else if (!strcmp(argv[2], "mq-active")) midi_queue_seq++;
        else if (!strcmp(argv[2], "mq-error")) midi_queue.error = MIDI_QUEUE_COUNT;
        else if (!strcmp(argv[2], "mq-unsampled")) midi_queue.calls = 0;
        else if (!strcmp(argv[2], "mq-interrupt1") || !strcmp(argv[2], "mq-interrupt2")) {
            midi_queue_t s;
            observer_interrupt = !strcmp(argv[2], "mq-interrupt1") ? 1u : 2u;
            if (midi_queue_read(&s) || !midi_queue_read(&s) || s.calls != 2u) return 3;
        }
#endif
#if FELUCCA_CRASH_CTX
        else if (!strcmp(argv[2], "stale-ctx"))
            fm1_crash.ctx = 0;               /* a record another firmware left: no registers */
#endif
        else
            return 2;
    }
    /* Skip only the connection banner, not command echo or dispatch. */
    con.dtr_seen = 1;
    n = strlen(argv[1]);
    memcpy(cdc_in, argv[1], n);
    cdc_in[n] = '\r';
    ci_w = (uint32_t)n + 1u;
    cdc_task();
    if (con.stalled || co_w >= CO_N)
        return 2;
    return fwrite(cdc_out, 1, co_w, stdout) == co_w ? 0 : 2;
}
