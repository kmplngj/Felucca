/* SPDX-License-Identifier: GPL-3.0-only */
/* Screenshot parser/CDC-ring fixture, based on console_diagnostics.c.
 * Compile the real console without DSP, generated assets or USB SIE emulation.
 * These fixtures supply state only; command dispatch and every output byte come
 * from console.c. Keep the output ring bounded and fail rather than wait if full. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../firmware/hal/fm1_clock.h"

#ifndef FELUCCA_UAC
#define FELUCCA_UAC 1
#endif
#ifndef FELUCCA_UART
#define FELUCCA_UART 1
#endif
#define FELUCCA_FLASH 1
#define FELUCCA_VERSION "console-contract"
#define RING_PUBLISH() ((void)0)
#define CO_N 2048u
#define CI_N 128u
#define FM1_TICKS_PER_US 24u
#define FM1_GAP_BINS 8u
#define FM1_NCOL 11u
#define FM1_NENC 7u
#define FM1_CRASH_MAGIC 0x43525348u
#define G_BPM 0
#define P_COUNT 1

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


#define FELUCCA_BUILD_ID "01234567-dirty"
#define FELUCCA_BUILD_COMMIT "0123456789abcdef0123456789abcdef01234567"
#define FELUCCA_BUILD_DIRTY 1
#define FELUCCA_SOURCE_REPOSITORY "github.com/kmplngj/Felucca"
#if FELUCCA_SCREEN_CAPTURE
#include "../firmware/src/screen_capture.c"
enum { SCR_ON, SCR_OFF, SCR_WAKE, SCR_SLPOUT, SCR_SHOW };
static struct { uint32_t st, led_off, idle; } scrn = {SCR_ON, 0, 10000};
static struct { uint32_t page, home, menu; } ui = {0, 1, 1};
static uint32_t scap_input_time;
static int fixture_supported = 1;
static int scap_start(uint8_t wake)
{
    if (!scap_begin(fm1_ms)) return 0;
    scap_input_time = scrn.idle;
    if (wake) {
        if (!fixture_supported) scap.state = SCAP_UNSUPPORTED;
        else {
            scap.wake = 1;
            scrn.idle = scap_input_time = fm1_ms; scrn.led_off = 0;
            if (scrn.st != SCR_ON) { scrn.st = SCR_WAKE; scap.state = SCAP_WAKING; }
        }
    } else if (scrn.st != SCR_ON) scap.state = SCAP_ASLEEP;
    return 1;
}
/* The UI scene check has its separate real-UI fixture; this fixture supplies the
 * same main-loop boundary while testing actual command parsing and ring output. */
static void scap_scene_check(void)
{
    scap_tick(fm1_ms);
    if (scap_live()) {
        if (scrn.st != SCR_ON && scap.state != SCAP_WAKING) scap.state = SCAP_ASLEEP;
        else if (scrn.idle != scap_input_time) scap.state = SCAP_CHANGED;
        else if (!fixture_supported || (!ui.menu && !ui.home)) scap.state = SCAP_UNSUPPORTED;
    }
}
#endif
#include "../firmware/src/console.c"

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static char output[CO_N + 1];
static const char *command(const char *s)
{
    size_t n = strlen(s), i;
    co_w = co_r = ci_w = ci_r = 0;
    con.len = con.stalled = 0;
    con.dtr_seen = 1;
    memcpy(cdc_in, s, n); cdc_in[n] = '\r'; ci_w = (uint32_t)n + 1u;
    cdc_task();
    CHECK(ci_r == ci_w && !con.stalled && co_w < CO_N);
    CHECK(co_w < 768u);                              /* screenshot reservation includes echo/prompt */
    for (i = 0; i < co_w; i++) output[i] = (char)cdc_out[i];
    output[co_w] = 0;
    CHECK(strncmp(output, s, n) == 0);
    CHECK(strstr(output, "\r\nSCAP "));
    CHECK(co_w >= 2u && !strcmp(output + co_w - 2u, "> "));
    return output;
}
static void expect(const char *s, const char *needle)
{
    const char *out = command(s);
    if (!strstr(out, needle)) { fprintf(stderr, "missing %s in %s\n", needle, out); exit(1); }
}
static void slow_reader(void)
{
    static const char s[] = "screen caps\r";
    uint32_t prior;
    co_r = ci_r = 0; co_w = CO_N; ci_w = sizeof s - 1u;
    con.len = con.stalled = 0; con.dtr_seen = 1;
    memcpy(cdc_in, s, sizeof s - 1u);
    cdc_task();
    CHECK(!ci_r && !con.stalled);                    /* even prefix echo cannot wait */
    co_r = co_w - (CO_N - 700u);                            /* enough echo, insufficient reply reservation */
    cdc_task();
    CHECK(ci_r == sizeof s - 2u && !con.stalled);
    prior = ci_r;
    cdc_task(); CHECK(ci_r == prior);                /* bounded polling, leave newline queued */
    co_r = co_w;
    cdc_task(); CHECK(ci_r == ci_w && !con.stalled);
}
int main(void)
{
    slow_reader();
#if FELUCCA_SCREEN_CAPTURE
    expect("screen caps", "SCAP CAPS version=2 enabled=1 width=240 height=240 format=RGB565BE band_bytes=3840 max_read=96 ttl_ms=120000 build=01234567-dirty commit=0123456789abcdef0123456789abcdef01234567 dirty=1 source=github.com/kmplngj/Felucca mode=stopped-static scr_state=0 led_stage=0 idle_ms=0");
    expect("screen begin", "SCAP STATE token=1 state=pending offset=0 length=3840 draw_hash=00000000 awake=1 page=0 home=1 menu=1 scr_state=0 led_stage=0 idle_ms=0");
    expect("screen begin", "SCAP ERROR code=busy");
    expect("screen status 0", "SCAP ERROR code=stale");
    expect("screen status 2", "SCAP ERROR code=stale");
    expect("screen status 4294967296", "SCAP ERROR code=argument");
    expect("screen status -1", "SCAP ERROR code=argument");
    expect("screen status 0x1", "SCAP ERROR code=argument");
    expect("screen read 1 0 96", "SCAP ERROR code=state");
    scap_render_begin(); scap_fill(0, 0, 240, 240, 0xF800); scap_render_end();
    CHECK(scap.state == SCAP_READY);
    /* Emit the real data wire line for an independent Python/zlib oracle. */
    fputs(command("screen read 1 0 96"), stdout);
    expect("screen read 1 0 0", "SCAP ERROR code=bounds");
    expect("screen read 1 0 97", "SCAP ERROR code=bounds");
    expect("screen read 1 3840 1", "SCAP ERROR code=bounds");
    expect("screen read 1 3839 2", "SCAP ERROR code=bounds");
    expect("screen read 1 4294967295 96", "SCAP ERROR code=bounds");
    expect("screen read 1 0 96 trailing", "SCAP ERROR code=argument");
    expect("screen next 1 7680", "SCAP ERROR code=state");
    expect("screen next 1 3840", "state=pending offset=3840 length=3840");
    expect("screen cancel 1", "state=cancelled offset=3840 length=0");
    expect("screen begin", "token=2 state=pending offset=0");
    {
        uint32_t band;
        char next[64];
        for (band = 0; band < 30u; band++) {
            scap_render_begin(); scap_fill(0, 0, 240, 240, 0xF800); scap_render_end();
            CHECK(scap.state == SCAP_READY);
            snprintf(next, sizeof next, "screen next 2 %u", (band + 1u) * SCAP_BYTES);
            expect(next, band == 29u ? "state=complete offset=115200 length=0" : "state=pending");
        }
        expect("screen status 2", "state=complete offset=115200 length=0");
    }
    expect("screen begin", "token=3 state=pending offset=0");
    fm1_ms += SCAP_TTL;
    expect("screen status 3", "state=expired");
    scrn.st = SCR_OFF;
    expect("screen begin", "token=4 state=asleep");
    CHECK(scrn.st == SCR_OFF && scrn.idle == 10000u); /* diagnostic never wakes/touches */
    scrn.st = SCR_ON;
    /* Real command boundaries must reject data/completion after the UI boundary
     * reports a newly unsupported external transport state, even without input. */
    expect("screen begin", "token=5 state=pending");
    scap.offset = SCAP_W * SCAP_H * 2u - SCAP_BYTES;
    scap_render_begin(); scap_fill(0, 0, 240, 240, 0xF800);
    scap.draw_hash = scap.hash; scap_render_end();
    CHECK(scap.state == SCAP_READY);
    fixture_supported = 0;
    expect("screen read 5 111360 96", "SCAP ERROR code=state");
    expect("screen next 5 115200", "SCAP ERROR code=state");
    expect("screen status 5", "state=unsupported offset=111360 length=0");
    fixture_supported = 1;
    expect("screen begin", "token=6 state=pending");
    scap.offset = SCAP_W * SCAP_H * 2u;
    scap.state = SCAP_COMPLETE;
    fixture_supported = 0;
    expect("screen status 6", "state=unsupported offset=115200 length=0");
    fixture_supported = 1;
    ui.menu = 0; ui.home = 1;
    expect("screen begin", "token=7 state=pending");
    scap_render_begin(); scap_fill(0, 0, 240, 240, 0xF800); scap_render_end();
    expect("screen status 7", "state=ready offset=0 length=3840");
    expect("screen status 7", "awake=1 page=0 home=1 menu=0");
    ui.home = 0;                                    /* another non-MENU page is unsupported */
    expect("screen status 7", "state=unsupported");
    ui.menu = 1;
    scap.token = 0xFFFFFFFEu;
    fm1_ms = 0xFFFFFFFFu; scrn.idle = 0;
    expect("screen begin", "token=4294967295 state=pending");
    expect("screen caps", "idle_ms=4294967295");
    expect("screen cancel 4294967295", "token=4294967295 state=cancelled");
    expect("screen begin", "token=1 state=pending");
    expect("screen status 4294967295", "SCAP ERROR code=stale");
    expect("screen cancel 1", "state=cancelled");
    scrn.st = SCR_OFF;
    expect("screen begin wake trailing", "SCAP ERROR code=argument");
    CHECK(scrn.st == SCR_OFF && !scap.wake);
    expect("screen begin wake", "token=2 state=waking offset=0 length=0");
    CHECK(scrn.st == SCR_WAKE && scap_holding(fm1_ms));
    expect("screen begin wake", "SCAP ERROR code=busy");
    expect("screen status 2", "state=waking");
    expect("screen read 2 0 96", "SCAP ERROR code=state");
    expect("screen cancel 2", "state=cancelled");
    CHECK(!scap_holding(fm1_ms));
    fixture_supported = 0; scrn.st = SCR_OFF;
    expect("screen begin wake", "state=unsupported");
    CHECK(scrn.st == SCR_OFF && !scap_holding(fm1_ms));
#else
    expect("screen caps", "SCAP CAPS version=1 enabled=0\r\n");
    expect("screen begin", "SCAP ERROR code=unsupported");
    expect("screen begin wake", "SCAP ERROR code=unsupported");
    expect("screen read 1 0 96", "SCAP ERROR code=unsupported");
#endif
    puts("screen capture console checks passed");
    return 0;
}
