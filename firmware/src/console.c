/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#include "isr_assert.h"                    /* FM1_ASSERT_THREAD / FM1_ISR_SIM_* (#428) */
/* Serial console on the CDC-ACM function (FELUCCA_CDC=1): read-only
 * diagnostics. Runs in the main loop (cdc_task); usb_poll moves the bytes.
 * The baud rate is ignored. Nothing here writes memory or flash; `uboot`
 * does what the SysEx soft key does. */
#ifndef FELUCCA_SCREEN_CAPTURE
#define FELUCCA_SCREEN_CAPTURE 0
#endif
#define CON_LINE 64u
#include "render_stage.h"

static struct {
    char line[CON_LINE];
    uint32_t len;
    uint8_t dtr_seen, stalled;   /* stalled: the host stopped reading, drop the rest of this reply */
} con;

static void con_putc(char c)
{
    uint32_t t0 = fm1_ms;
    while (co_w - co_r >= CO_N) {                      /* full: wait for usb_poll, briefly */
        if (!cdc.dtr || con.stalled || fm1_ms - t0 > 20u) {
            con.stalled = 1;
            return;
        }
        fm1_wdt_feed();
    }
    cdc_out[co_w % CO_N] = (uint8_t)c;
    RING_PUBLISH();
    co_w++;
}

static void con_puts(const char *s)
{
    while (*s)
        con_putc(*s++);
}

static void con_hex(uint32_t v, uint32_t digits)
{
    while (digits--)
        con_putc("0123456789ABCDEF"[(v >> (digits * 4u)) & 15u]);
}

static void con_dec(int32_t v)
{
    char b[12];
    uint32_t n = 0, u = v < 0 ? (uint32_t)-v : (uint32_t)v;
    if (v < 0)
        con_putc('-');
    do
        b[n++] = (char)('0' + u % 10u);
    while ((u /= 10u) != 0 && n < sizeof b);
    while (n)
        con_putc(b[--n]);
}

static void con_kv(const char *k, int32_t v)            /* "key value\r\n" */
{
    con_puts(k);
    con_putc(' ');
    con_dec(v);
    con_puts("\r\n");
}

static void con_kx(const char *k, uint32_t v)
{
    con_puts(k);
    con_puts(" 0x");
    con_hex(v, 8);
    con_puts("\r\n");
}

#if FELUCCA_RENDER_STAGE
static void con_render_stage(void)
{
    render_stage_t s;
    uint32_t readable = (uint32_t)render_stage_read(&s);
    con_kv("stage_schema", 1);
    con_kv("stage_readable", (int32_t)readable);
    if (!readable)
        return;
    con_kx("stage_error", s.error);
    con_kx("stage_halves", s.halves);
    con_kx("stage_blocks", s.blocks);
    con_kx("stage_rejected", s.rejected);
    con_kv("stage_available", s.valid && !s.error);
    if (!s.valid || s.error)
        return;
    con_kx("stage_mix_last_t4", s.mix_last);
    con_kx("stage_mix_max_t4", s.mix_max);
    con_kx("stage_empty_last_t4", s.empty_last);
    con_kx("stage_empty_max_t4", s.empty_max);
    con_kx("stage_window_last_t4", s.half_last);
    con_kx("stage_window_max_t4", s.half_max);
    con_kx("stage_nested_last_t4", s.nested_last);
    con_kx("stage_nested_max_t4", s.nested_max);
}
#endif

static uint32_t con_num(const char **p, int *ok)        /* decimal or 0x hex */
{
    const char *s = *p;
    uint32_t v = 0, base = 10, d, n = 0;
    while (*s == ' ')
        s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        s += 2, base = 16;
    for (;; s++, n++) {
        char c = *s;
        if (c >= '0' && c <= '9')
            d = (uint32_t)(c - '0');
        else if (base == 16 && c >= 'a' && c <= 'f')
            d = (uint32_t)(c - 'a' + 10);
        else if (base == 16 && c >= 'A' && c <= 'F')
            d = (uint32_t)(c - 'A' + 10);
        else
            break;
        v = v * base + d;
    }
    *ok = n > 0;
    *p = s;
    return v;
}

static int con_word(const char **p, const char *w)       /* match a whole word */
{
    const char *s = *p;
    while (*s == ' ')
        s++;
    while (*w && *s == *w)
        s++, w++;
    if (*w || (*s && *s != ' '))
        return 0;
    *p = s;
    return 1;
}

static void con_memr(const char *p)
{
    int ok, ok2;
    uint32_t a = con_num(&p, &ok), n = con_num(&p, &ok2), i;
    if (!ok) {
        con_puts("usage: memr ADDR [LEN<=256]\r\n");
        return;
    }
    if (!ok2 || !n)
        n = 64;
    if (n > 256u)
        n = 256;
    if (!fm1_mem_readable(a, n)) {
        con_puts("only RAM 01C00000-01C80000 and XIP 02000000-02100000\r\n");
        return;
    }
    for (i = 0; i < n; i++) {
        if (i % 16u == 0) {
            con_hex(a + i, 8);
            con_putc(':');
        }
        con_putc(' ');
        con_hex(fm1_peek8(a + i), 2);
        if (i % 16u == 15u || i + 1u == n)
            con_puts("\r\n");
    }
}

#if FELUCCA_FLASH
static void con_flr(const char *p)                  /* flash read over SPI (no XIP decryption) */
{
    static uint8_t b[256];
    int ok, ok2;
    uint32_t a = con_num(&p, &ok), n = con_num(&p, &ok2), i;
    if (!ok || a < 0x93000u || a >= 0x100000u) {
        con_puts("usage: flr OFFSET [LEN<=256]   (0x93000..0xFFFFF)\r\n");
        return;
    }
    if (!ok2 || !n)
        n = 64;
    if (n > 256u)
        n = 256;
    if (a + n > 0x100000u)
        n = 0x100000u - a;
    if (!flash_ok || st_read(a, b, n)) {
        con_puts("flash not available\r\n");
        return;
    }
    for (i = 0; i < n; i++) {
        if (i % 16u == 0) {
            con_hex(a + i, 6);
            con_putc(':');
        }
        con_putc(' ');
        con_hex(b[i], 2);
        if (i % 16u == 15u || i + 1u == n)
            con_puts("\r\n");
    }
}
#endif

#if FELUCCA_UAC
static void con_uac(void)                              /* USB audio input: stream state and glitches */
{
    uint32_t p = uac.pkts, base = uac.r48 ? 48u : 44u;
    con_kv("uac_alt", uac.alt);
    con_kv("uac_hz", uac.r48 ? 48000 : 44100);      /* the rate the host set (SET_CUR; 44100 until it does) */
    con_kv("uac_rate_sets", (int32_t)uac.rate_sets);
    con_kv("uac_starts", (int32_t)uac.starts);
    con_kv("uac_pkts", (int32_t)p);
    con_kv("uac_rate_hz", p ? (int32_t)base * 1000 + (int32_t)(uac.frames - base * p) * 1000 / (int32_t)p : 0);   /* < 5 h */
    con_kv("uac_underruns", (int32_t)uac.underruns);
    con_kv("uac_overruns", (int32_t)uac.overruns);
    con_kv("uac_missed", (int32_t)uac.missed);
    con_kv("uac_stalls", (int32_t)uac.stalls);
    con_kv("uac_adj_up", (int32_t)uac.adj_up);
    con_kv("uac_adj_down", (int32_t)uac.adj_down);
    con_kv("uac_fill", (int32_t)uac.fill_min);
    con_kv("uac_fill_lo", uac.fill_lo == 0xFFFFFFFFu ? -1 : (int32_t)uac.fill_lo);
    con_kv("uac_fill_hi", (int32_t)uac.fill_hi);
}
#endif

static void con_status(void)
{
    const engine_t *e = eng_of(TSEL->eng_req);
    con_puts("felucca ");
    con_puts(FELUCCA_VERSION);
    con_puts("\r\n");
    con_kv("uptime_ms", (int32_t)fm1_ms);
    if (fm1_boot_clock.valid) {
        con_kx("boot_clock_10014", fm1_boot_clock.r10014);
        con_kx("boot_clock_1000c", fm1_boot_clock.r1000c);
        con_kx("boot_clock_10008", fm1_boot_clock.r10008);
        con_kx("boot_clock_119a8", fm1_boot_clock.r119a8);
        con_kx("boot_clock_119ac", fm1_boot_clock.r119ac);
        con_kx("boot_clock_119a0", fm1_boot_clock.r119a0);
        con_kx("boot_clock_119a4", fm1_boot_clock.r119a4);
    }
    con_kv("cpu_pct", (int32_t)(song.cpu_q8 * 100u / 256u));
    con_kv("audio_max_us", (int32_t)felucca_dbg.max_us);
#if FELUCCA_RENDER_STAGE
    con_render_stage();
#endif
    con_kv("audio_late", (int32_t)felucca_dbg.late);
    con_kv("voices_shed", (int32_t)shed_count);
#ifdef LCD_ASYNC_DRIVER
    con_kv("lcd_fault", lcd_fault);
    con_kv("lcd_owned", lcd_busy);
    con_kv("lcd_faults", (int32_t)lcd_faults);
    con_kv("lcd_recoveries", (int32_t)lcd_recoveries);
#endif
#if FELUCCA_CPU2
    con_kv("cpu2_set", (ui_prefs2 & (PREF_CPU2_ON >> 16)) != 0u);   /* MENU > 2ND CORE: 1 ON (from power-on), 0 OFF */
    con_kv("cpu2", fm1_c1_on);                          /* the second core renders parts (hal/fm1_cpu1.h) */
    con_kv("cpu2_gave_up", fm1_c1_gave_up);             /* 1: it misread a job, 2: one timed out (then one core) */
    con_kv("cpu2_bad", (int32_t)fm1_c1_mb.bad);
    {
        uint32_t refused;
        con_kv("cpu2_excl", (int32_t)fm1_c1g_read(&refused));   /* retained: 0 none, 1 bad job, 2 timeout, 3 core 0 fault, 4 hang
                                                         * (WDT), 5 corrupt, 15 answering; 1..5 refuse a start until MENU > 2ND CORE
                                                         * is set ON again (hal/fm1_sys.h) */
        con_kv("cpu2_refused", (int32_t)refused);        /* starts it refused (saturating at 255) */
    }
    con_kv("cpu2_blocks", (int32_t)c1_blocks);          /* blocks it took parts of (fx.c mix_block) */
    con_kv("cpu2_wait_max_us", (int32_t)(fm1_c1_wait_max / 24u));
    con_kv("cpu2_stack", (int32_t)fm1_cpu1_stack_used());
#endif
    con_kv("voices_given_up", (int32_t)voice_kills);
#if FM1_ISR_ASSERT_TARGET
    con_kv("isr_misuse", (int32_t)fm1_isr_misuse_n);    /* FELUCCA_ISR_ASSERT=1 builds (isr_assert.h) */
    con_kv("isr_misuse_pc", (int32_t)fm1_isr_misuse_pc);
#endif
#if FELUCCA_CRASH_CTX
    con_kv("crash_ctx", 1);                             /* diagnostic build: `crash` adds the registers (#428) */
#endif
#if FELUCCA_MUL64_REPRO
    con_kv("mul64_repro", 1);                           /* diagnostic build: the #425 reproducer (mul64_repro.c) */
    con_kv("mul64_runs", (int32_t)mr.runs);
    con_kv("mul64_inl_bad", (int32_t)mr.inl_bad);
    con_kv("mul64_nol_bad", (int32_t)mr.nol_bad);
    con_kv("mul64_ref_bad", (int32_t)mr.ref_bad);
    con_kv("mul64_first_var", (int32_t)mr.first_var);
    con_kv("mul64_first_run", (int32_t)mr.first_run);
    con_kx("mul64_first_xor", mr.first_xor);
#endif
    con_kv("track", (int32_t)song.sel + 1);
    con_kv("batt_raw", song.batt_raw);
    con_puts("engine ");
    con_puts(e->name);
    con_puts("\r\n");
    con_puts("preset ");
    con_puts(TSEL->preset < e->npresets ? e->presets[TSEL->preset].name : "-");
    con_puts("\r\n");
    con_kv("bpm", song.g[G_BPM]);
    con_kv("playing", song.playing);
    con_kv("boots", (int32_t)felucca_dbg.boots);
    con_kv("usb_resets", (int32_t)usb.resets);
    con_kv("usb_sof", (int32_t)usb.sof_seen);
    con_kv("usb_suspends", (int32_t)usb.suspends);
    con_kv("usb_retries", (int32_t)usb.retries);
    con_kv("usb_frame", (int32_t)usb.frame);
    con_kv("usb_frame_stalls", (int32_t)usb.frame_stalls);
    con_kv("usb_max_gap_polls", (int32_t)usb.max_gap);
    con_kv("midi_rx_pkts", (int32_t)usb.rx_pkts);
    con_kv("midi_tx_pkts", (int32_t)usb.tx_pkts);
#if FELUCCA_UAC
    con_uac();
#endif
    con_kv("uart_enabled", FELUCCA_UART);
#if FELUCCA_UART
    con_kv("uart_rx_bytes", (int32_t)um.bytes);
    con_kv("uart_rx_msgs", (int32_t)um.msgs);
    con_kv("uart_rx_drops", (int32_t)um.drops);
#endif
#if FELUCCA_FLASH
    con_kv("flash", flash_ok);
#endif
}

static void con_dbg(void)
{
    const uint32_t *w = (const uint32_t *)&felucca_dbg;
    static const char *const NAMES[] = {"magic", "halves", "max_us", "nested", "in_audio", "late",
                                        "timer_irqs", "ui_frames", "last_us", "cpu_q8", "boots",
                                        "stage", "page", "home", "prev_stage", "prev_page",
                                        "prev_home", "prev_rst", "prev_frames"};
    uint32_t i;
    for (i = 0; i < sizeof NAMES / sizeof NAMES[0] && i < sizeof felucca_dbg / 4u; i++)
        con_kx(NAMES[i], w[i]);
#if FELUCCA_UAC
    con_uac();
#endif
}

/* input scan (hal/fm1_input.h fm1_in_stat) since the last `inp`, then cleared: tick gaps (= LED
 * on-time of a column), per-column LED share in 1/1000, the tick cost, the dim pulse (its average width and the
 * bits of the 595 shift it spans), encoder transitions */
static void con_inp(void)
{
    static uint32_t t_last;
    uint32_t now = fm1_ticks(), win = now - t_last, i, k;
    uint32_t win_us = win / FM1_TICKS_PER_US;
    t_last = now;
    con_kv("window_ms", (int32_t)(win_us / 1000u));
    con_kv("ticks_per_s", (int32_t)(win_us >= 1000u ? fm1_in_stat.ticks * 1000u / (win_us / 1000u) : 0u));
    con_kv("gap_max_us", (int32_t)(fm1_in_stat.gap_max / FM1_TICKS_PER_US));
    con_puts("gap_hist <.15 .3 .6 1.2 2.4 4.8 9.6 more ms:");
    for (i = 0; i < FM1_GAP_BINS; i++) {
        con_putc(' ');
        con_dec((int32_t)fm1_in_stat.gap_hist[i]);
    }
    con_puts("\r\n");
    con_kv("tick_cost_avg_ns", (int32_t)(fm1_in_stat.ticks ? fm1_in_stat.cost_sum / fm1_in_stat.ticks * 1000u / FM1_TICKS_PER_US : 0u));
    con_kv("tick_cost_max_us", (int32_t)(fm1_in_stat.cost_max / FM1_TICKS_PER_US));
    con_kv("tick_cpu_permille", (int32_t)(win >= 1000u ? fm1_in_stat.cost_sum / (win / 1000u) : 0u));
    con_kv("dim_pulse_ns", (int32_t)(fm1_in_stat.dim_n ? fm1_in_stat.dim_sum / fm1_in_stat.dim_n * 1000u / FM1_TICKS_PER_US : 0u));
    con_kv("dim_bits", (int32_t)fm1__dim_k);
    con_puts("led_on_permille:");
    for (i = 0; i < FM1_NCOL; i++) {
        con_putc(' ');
        con_dec((int32_t)(win >= 1000u ? fm1_in_stat.on[i] / (win / 1000u) : 0u));
    }
    con_puts("\r\nled_on_max_us:");
    for (i = 0; i < FM1_NCOL; i++) {
        con_putc(' ');
        con_dec((int32_t)(fm1_in_stat.on_max[i] / FM1_TICKS_PER_US));
    }
    con_puts("\r\nenc moves/lost/detent state:");
    for (k = 0; k < FM1_NENC; k++) {
        con_putc(' ');
        con_dec((int32_t)fm1_in_stat.enc_moves[k]);
        con_putc('/');
        con_dec((int32_t)fm1_in_stat.enc_lost[k]);
        con_putc('/');
        con_dec(fm1_in.enc_rest[k]);
    }
    con_puts("\r\n");
    {   /* note keys, from the first scan that saw the contact (us): debounced press, note-on, DAC out */
        uint32_t n = fm1_in_stat.press_n, m = fm1_in_stat.kb_n;
        con_kv("key_presses", (int32_t)n);
        con_kv("key_press_avg_us", (int32_t)(n ? fm1_in_stat.press_sum / n / FM1_TICKS_PER_US : 0u));
        con_kv("key_press_max_us", (int32_t)(fm1_in_stat.press_max / FM1_TICKS_PER_US));
        con_kv("key_notes", (int32_t)m);
        con_kv("key_noteon_avg_us", (int32_t)(m ? fm1_in_stat.kb_sum / m / FM1_TICKS_PER_US : 0u));
        con_kv("key_noteon_max_us", (int32_t)(fm1_in_stat.kb_max / FM1_TICKS_PER_US));
        con_kv("key_dac_avg_us", (int32_t)(m ? fm1_in_stat.dac_sum / m / FM1_TICKS_PER_US : 0u));
        con_kv("key_dac_max_us", (int32_t)(fm1_in_stat.dac_max / FM1_TICKS_PER_US));
    }
    con_kv("timer_irqs", (int32_t)felucca_dbg.timer_irqs);
    con_kv("nested", (int32_t)felucca_dbg.nested);
    {
        uint32_t k2 = fm1__lock();
        memset((void *)&fm1_in_stat.gap_max, 0, sizeof fm1_in_stat - sizeof fm1_in_stat.last);
        fm1__unlock(k2);
    }
}

static void con_crash(void)
{
    fm1_crash_t c;
    if (!fm1_crash_read(&c)) {
        con_puts("no crash record\r\n");
        return;
    }
    con_kv("count", (int32_t)c.count);
#if FELUCCA_CPU2
    con_kv("core", (int32_t)c.core);
#endif
    con_kx("vec", c.vec);
    con_kx("pc", c.pc);
    con_kx("rets", c.rets);
    con_kx("emu", c.emu);
    con_kx("sp", c.sp);
    con_kx("psr", c.psr);
    con_kv("uptime_ms", (int32_t)c.uptime_ms);
    con_kv("early", (int32_t)c.early);
#if FELUCCA_CRASH_CTX
    {   /* FELUCCA_CRASH_CTX=1 diagnostic builds (#428, hal/fm1_irq.h): the faulting core's registers, after the keys
         * above (unchanged for old reports); ctx 0 = this record carries none (written by another firmware) */
        static const char rn[16][4] = {"r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
                                       "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"};
        uint32_t i, ok = c.ctx == (FM1_CRASH_CTX_KEY ^ c.count);
        con_kv("ctx", (int32_t)ok);
        if (ok) {
            for (i = 0; i < 16u; i++)
                con_kx(rn[i], c.r[i]);
            con_kx("usp", c.usp);
            con_kx("ssp", c.ssp);
        }
    }
#endif
}

static void con_params(void)
{
    uint32_t i;
    for (i = 0; i < P_COUNT; i++) {
        con_dec((int32_t)i);
        con_putc('=');
        con_dec(TSEL->p[i]);
        con_puts(i % 8u == 7u || i + 1u == P_COUNT ? "\r\n" : " ");
    }
}

/* Screen replies reserve enough free CDC-ring space before parsing a command.
 * No screenshot transfer calls the console's wait path; the host pulls <=96 bytes. */
static int con_screen_pending(void)
{
    uint32_t i = 0;
    while (i < con.len && con.line[i] == ' ') i++;
    return con.len - i >= 6u && !memcmp(con.line + i, "screen", 6u);
}
static void con_screen_error(const char *code)
{
    con_puts("SCAP ERROR code="); con_puts(code); con_puts("\r\n");
}
#if FELUCCA_SCREEN_CAPTURE
static void con_screen_uint(uint32_t n)
{
    char b[10];
    uint32_t k = 0;
    do { b[k++] = (char)('0' + n % 10u); } while ((n /= 10u) != 0u);
    while (k) con_putc(b[--k]);
}
static void con_screen_idle(void)
{
    con_puts(" scr_state="); con_dec(scrn.st);
    con_puts(" led_stage="); con_dec(scrn.led_off);
    con_puts(" idle_ms="); con_screen_uint(fm1_ms - scrn.idle);
}
static void con_screen_state(void)
{
    static const char *const states[] = {"idle", "pending", "ready", "complete", "changed", "expired",
                                         "cancelled", "coverage", "asleep", "unsupported", "waking"};
    con_puts("SCAP STATE token="); con_screen_uint(scap.token);
    con_puts(" state="); con_puts(states[scap.state]);
    con_puts(" offset="); con_dec((int32_t)scap.offset);
    con_puts(" length="); con_dec(scap.state == SCAP_READY || scap.state == SCAP_PENDING ? SCAP_BYTES : 0);
    con_puts(" draw_hash="); con_hex(scap.draw_hash, 8);
    con_puts(" awake="); con_dec(scrn.st == SCR_ON);
    con_puts(" page="); con_dec(ui.page);
    con_puts(" home="); con_dec(ui.home);
    con_puts(" menu="); con_dec(ui.menu);
    con_screen_idle();
    con_puts("\r\n");
}
/* Capture arguments are strict decimal uint32; unlike memr, overflow is invalid. */
static int con_screen_num(const char **p, uint32_t *v)
{
    const char *s = *p;
    uint32_t n = 0, digits = 0;
    while (*s == ' ') s++;
    while (*s >= '0' && *s <= '9') {
        uint32_t d = (uint32_t)(*s++ - '0');
        if (n > (0xFFFFFFFFu - d) / 10u) return 0;
        n = n * 10u + d; digits++;
    }
    if (!digits || (*s && *s != ' ')) return 0;
    *p = s; *v = n; return 1;
}
#endif
static int con_screen_end(const char *p)
{
    while (*p == ' ') p++;
    return !*p;
}
static void con_screen(const char *p)
{
    if (con_word(&p, "caps") && con_screen_end(p)) {
#if FELUCCA_SCREEN_CAPTURE
        con_puts("SCAP CAPS version=2 enabled="); con_dec(FELUCCA_SCREEN_CAPTURE != 0);
        con_puts(" width=240 height=240 format=RGB565BE band_bytes=3840 max_read=96 ttl_ms=120000 build=");
#ifdef FELUCCA_BUILD_ID
        con_puts(FELUCCA_BUILD_ID);
#else
        con_puts("unknown");
#endif
        con_puts(" commit=");
#ifdef FELUCCA_BUILD_COMMIT
        con_puts(FELUCCA_BUILD_COMMIT);
#else
        con_puts("unknown");
#endif
        con_puts(" dirty=");
#ifdef FELUCCA_BUILD_DIRTY
        con_dec(FELUCCA_BUILD_DIRTY);
#else
        con_puts("unknown");
#endif
        con_puts(" source=");
#ifdef FELUCCA_SOURCE_REPOSITORY
        con_puts(FELUCCA_SOURCE_REPOSITORY);
#else
        con_puts("unknown");
#endif
        con_puts(" mode=stopped-static");
        con_screen_idle();
        con_puts("\r\n");
#else
        con_puts("SCAP CAPS version=1 enabled=0\r\n");
#endif
        return;
    }
#if FELUCCA_SCREEN_CAPTURE
    scap_scene_check();
    if (con_word(&p, "begin")) {
        int wake = con_word(&p, "wake");
        if (!con_screen_end(p)) { con_screen_error("argument"); return; }
        if (!scap_start((uint8_t)wake)) { con_screen_error("busy"); return; }
        con_screen_state();
    } else {
        uint32_t token, offset, n, i;
        int cmd = con_word(&p, "status") ? 1 : con_word(&p, "next") ? 2 :
                  con_word(&p, "read") ? 3 : con_word(&p, "cancel") ? 4 : 0;
        if (!cmd || !con_screen_num(&p, &token)) { con_screen_error("argument"); return; }
        if (!token || token != scap.token) { con_screen_error("stale"); return; }
        if (cmd == 2 || cmd == 3) {
            if (!con_screen_num(&p, &offset)) { con_screen_error("argument"); return; }
        }
        if (cmd == 3 && !con_screen_num(&p, &n)) { con_screen_error("argument"); return; }
        if (!con_screen_end(p)) { con_screen_error("argument"); return; }
        if (cmd == 2) {
            if (!scap_next(token, offset)) { con_screen_error("state"); return; }
        } else if (cmd == 4) scap_cancel(token);
        else if (cmd == 3) {
            if (scap.state != SCAP_READY) { con_screen_error("state"); return; }
            if (!n || n > 96u || offset < scap.offset || offset - scap.offset >= SCAP_BYTES ||
                n > SCAP_BYTES - (offset - scap.offset)) { con_screen_error("bounds"); return; }
            offset -= scap.offset;
            con_puts("SCAP DATA token="); con_screen_uint(token);
            con_puts(" offset="); con_dec((int32_t)(offset + scap.offset));
            con_puts(" length="); con_dec((int32_t)n);
            con_puts(" crc="); con_hex(scap_crc(scap.pixels + offset, n), 8);
            con_puts(" data=");
            for (i = 0; i < n; i++) con_hex(scap.pixels[offset + i], 2);
            con_puts("\r\n");
            return;
        }
        con_screen_state();
    }
#else
    con_screen_error("unsupported");
#endif
}

#if FELUCCA_LCD_INFLIGHT
static void lp_label(uint32_t mode, uint32_t run)
{
    char label[] = "LCD600 CANDIDATE 00000000";
    const char *name = mode == LP_CONTROL ? "CONTROL  " : mode == LP_A_ONLY ? "A ONLY   " : "CANDIDATE";
    uint32_t i;
    for (i = 0; i < 9u; i++) label[7u + i] = name[i];
    for (i = 0; i < 8u; i++) label[17u + i] = "0123456789ABCDEF"[(run >> (28u - 4u*i)) & 15u];
    draw_text_line(0, 4, 240, &AF_S, label, 0xFFFFu, 0u, 1);
}
static void con_lcd_probe(const char *p)
{
    int ok, run_ok;
    if (con_word(&p, "arm")) {
        uint32_t mode = con_num(&p, &ok), run = con_num(&p, &run_ok);
        uint32_t backup = con_word(&p, "backup-restore-ok") && !*p;
        con_kv("lcdprobe_arm", ok && run_ok && lp_arm(mode, run, backup));
    } else if (con_word(&p, "go")) con_kv("lcdprobe_go", !*p && lp_go());
    else if (con_word(&p, "finish")) con_kv("lcdprobe_finish", !*p && lp_finish());
    else if (con_word(&p, "abort")) {
        if (lp.active && !*p) lp.reset = 1;
        con_kv("lcdprobe_reset_requested", lp.reset);
    } else if (con_word(&p, "trace")) {
        uint32_t i = con_num(&p, &ok), word;
        if (!ok || *p || i >= lp.count || (lp.selected && !lp.released && !lp.reset)) {
            con_puts("lcdprobe_trace unavailable\r\n"); return;
        }
        con_puts("lcdprobe_trace "); con_dec((int32_t)i);
        for (word = 0; word < 8u; word++) { con_putc(' '); con_hex(lp.trace[i][word], 8u); }
        con_puts("\r\n");
    } else {
        con_kv("lcdprobe_active", lp.active); con_kv("lcdprobe_hold", lp.hold);
        con_kv("lcdprobe_phase", lp.phase); con_kv("lcdprobe_mode", lp.mode);
        con_kx("lcdprobe_run", lp.run); con_kv("lcdprobe_records", lp.count);
        con_kv("lcdprobe_overflow", lp.overflow); con_kv("lcdprobe_selected", lp.selected_submits);
        con_kv("lcdprobe_setup_and_hold_submits", lp.submits);
        con_kv("lcdprobe_stores_pixels", lp.stores); con_kv("lcdprobe_denied", lp.denied);
        con_kv("lcdprobe_wait_result", lp.wait_result);
        con_kv("lcdprobe_pending_before_copy", lp.pending_before_copy);
        con_kv("lcdprobe_released", lp.released); con_kv("lcdprobe_reset_requested", lp.reset);
        con_kx("lcdprobe_source", (uint32_t)lp.source); con_kv("lcdprobe_programmed_bytes", LP_BYTES);
        con_kx("lcdprobe_C_hash", lp.c_hash); con_kx("lcdprobe_A_hash", lp.a_hash);
        con_kx("lcdprobe_after_hash", lp.after_hash);
        con_puts("lcdprobe_optical_result UNQUALIFIED_REQUIRES_OWNER_OBSERVATION\r\n");
    }
}
#endif

static void con_exec(const char *p)
{
    FM1_ASSERT_THREAD();                                /* formatted replies: main loop only (#428) */
#if FELUCCA_LCD_INFLIGHT
    if (con_word(&p, "lcdprobe")) { con_lcd_probe(p); return; }
    if (lp.active) {
        if (con_word(&p, "status")) con_status();
        else if (con_word(&p, "dbg")) con_dbg();
        else if (con_word(&p, "inp")) con_inp();
        else if (con_word(&p, "crash")) con_crash();
        else con_puts("lcdprobe active: read-only diagnostics or lcdprobe abort\r\n");
        return; /* no screen capture, UBOOT, memory command or hidden writer */
    }
#endif
    if (con_word(&p, "help") || con_word(&p, "?"))
        con_puts("status  dbg  inp  crash  params  memr ADDR [LEN]  flr OFF [LEN]  uboot yes\r\n");
    else if (con_word(&p, "screen"))
        con_screen(p);
    else if (con_word(&p, "status"))
        con_status();
    else if (con_word(&p, "dbg"))
        con_dbg();
    else if (con_word(&p, "crash"))
        con_crash();
    else if (con_word(&p, "inp"))
        con_inp();
    else if (con_word(&p, "params"))
        con_params();
    else if (con_word(&p, "memr"))
        con_memr(p);
#if FELUCCA_FLASH
    else if (con_word(&p, "flr"))
        con_flr(p);
#endif
    else if (con_word(&p, "uboot")) {
        if (con_word(&p, "yes")) {
            con_puts("entering UBOOT\r\n");
            usb.uboot_req = 1;                         /* main loop: same path as the SysEx key */
        } else {
            con_puts("type 'uboot yes'\r\n");
        }
    } else if (*p)
        con_puts("? (help)\r\n");
}

static void cdc_task(void)                              /* main loop */
{
    if (cdc.dtr && !con.dtr_seen) {
        con_puts("\r\nFelucca ");
        con_puts(FELUCCA_VERSION);
        con_puts(" console - 'help'\r\n> ");
    }
    con.dtr_seen = cdc.dtr;
    while (ci_r != ci_w) {
        char c;
        /* Echo is also host-paced: do not wait for a slow reader before reaching
         * the screenshot newline reservation (or while typing its prefix). */
        if (co_w - co_r > CO_N - 8u) return;
        RING_PUBLISH();                                /* usb_poll (producer) can preempt us */
        c = (char)cdc_in[ci_r % CI_N];
        RING_PUBLISH();
        if ((c == '\r' || c == '\n') && con_screen_pending() &&
            co_w - co_r > CO_N - 768u) return;
        ci_r++;
        if (c == '\r' || c == '\n') {
            if (c == '\n' && con.len == 0)
                continue;                              /* the LF of a CR LF */
            con_puts("\r\n");
            con.line[con.len] = 0;
            con.stalled = 0;
            con_exec(con.line);
            con.len = 0;
            con_puts("> ");
        } else if (c == 0x7F || c == 0x08) {
            if (con.len) {
                con.len--;
                con_puts("\b \b");
            }
        } else if (c >= ' ' && c < 0x7F && con.len + 1u < CON_LINE) {
            con.line[con.len++] = c;
            con_putc(c);
        }
    }
}
