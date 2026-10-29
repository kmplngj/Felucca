/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
 * Loader-screen reference: zvenson/dinghy, commit
 * 22acb9165ebc8baa712af3aff8c507e230c1e028, ldr_screen.c (zvenson;
 * illuminus5/Skiff's loader-screen idea and startup ordering), GPL-3.0-only.
 * The native Felucca/SLOOP loader and HAL remain their respective authors' work.
 * No donor artwork, branding, colours or font data is included. */
/* A single RAM scanline, no app UI/framebuffer. All transfers complete before
 * source reuse. A per-transfer deadline latches display failure forever; it
 * does NOT clear hardware pending, deselect, abort DMA or grant ownership back.
 * The static source is then retained untouched until reset. USB/watchdog
 * service continues (ldr_poll in every wait and after every row).
 * Each redraw also has a 250ms aggregate budget (a full 115200 B frame is
 * 76.8ms of 12 MHz SPI wire time plus per-row CPU), so a slow but completing
 * peripheral cannot hold a session callback indefinitely. The budget is checked
 * only between transfers: running over it abandons the redraw WITHOUT latching,
 * since every transfer completed. Only a state change repaints the frame, so
 * a panel too slow for it costs one budget per state, never one per progress
 * step; progress-only updates repaint just the percentage strip. DISPON has
 * its own per-transfer deadline, not the first draw's leftover budget.
 * A completion bit establishes SPI source release, not visible panel acceptance. */
#include "ldr_status.h"
#include "ldr_font.h"

#define LDR_LCD_WAIT_US 2000u
#define LDR_LCD_DRAW_US 250000u
#define LDR_LCD_INIT_US 500000u
#define LDR_STRIP_TOP 164u                         /* percentage/number text rows */
#define LDR_STRIP_END (LDR_STRIP_TOP + 18u)        /* 9-row face at scale 2 */
static uint8_t ldr_lcd_failed;
static uint8_t ldr_screen_framed;                  /* this state's full frame has been attempted */
static uint8_t ldr_line[480] __attribute__((aligned(4)));
static uint8_t ldr_args[4] __attribute__((aligned(4)));
static uint32_t ldr_screen_state, ldr_screen_percent, ldr_screen_next;
static int32_t ldr_screen_error;
static uint32_t ldr_lcd_budget_start, ldr_lcd_budget_us;
#include "ldr_screen_trace.h"

static void ldr_lcd_arm(uint32_t us)
{
    ldr_lcd_budget_start = fm1_ticks();
    ldr_lcd_budget_us = us;
}
/* Aggregate time only stops starting more transfers; it never latches. */
static int ldr_lcd_budget_ok(void)
{
    return fm1_ticks() - ldr_lcd_budget_start < ldr_lcd_budget_us * FM1_TICKS_PER_US;
}

static int ldr_lcd_wait(void)
{
    uint32_t start = fm1_ticks();
    while (!fm1_lcd_done()) {
        ldr_poll();
        if (fm1_ticks() - start >= LDR_LCD_WAIT_US * FM1_TICKS_PER_US) {
            ldr_lcd_failed = 1;
            return 0;
        }
    }
    fm1_lcd_deselect();
    return 1;
}
static int ldr_lcd_cmd(uint8_t c)
{
    if (ldr_lcd_failed || !ldr_lcd_budget_ok())
        return 0;
    fm1_lcd_send_cmd(c);
    return ldr_lcd_wait();
}
static int ldr_lcd_data(const void *p, uint32_t n)
{
    if (ldr_lcd_failed || !ldr_lcd_budget_ok())
        return 0;
    fm1_lcd_send_data(p, n);
    return ldr_lcd_wait();
}
static void ldr_lcd_delay(uint32_t ms)
{
    uint32_t start = ldr_ms();
    while (ldr_ms() - start < ms)
        ldr_poll();
}
static int ldr_lcd_axis(uint8_t cmd, uint32_t first, uint32_t end)
{
    /* Previous synchronous transfer has released args, or this call is skipped. */
    if (!ldr_lcd_cmd(cmd))
        return 0;
    ldr_args[0] = (uint8_t)(first >> 8);
    ldr_args[1] = (uint8_t)first;
    ldr_args[2] = (uint8_t)(end >> 8);
    ldr_args[3] = (uint8_t)end;
    return ldr_lcd_data(ldr_args, 4);
}
static void ldr_pixel(uint32_t x, uint16_t c)
{
    ldr_line[x * 2u] = (uint8_t)(c >> 8);
    ldr_line[x * 2u + 1u] = (uint8_t)c;
}
static void ldr_row_text(uint32_t y, uint32_t top, uint32_t face, uint32_t scale, const char *t)
{
    uint32_t len = 0, x, row, i, k, dot, width = face ? 9u : 6u;
    uint32_t height = face ? 9u : 7u;
    if (y < top || y >= top + height * scale)
        return;
    while (t[len]) len++;
    if (len * width * scale > 240u) return;
    x = (240u - len * width * scale) / 2u;
    row = (y - top) / scale;
    for (; *t; t++, x += width * scale) {
        for (k = 0; LDR_CH[k] && LDR_CH[k] != *t; k++) ;
        if (!LDR_CH[k]) continue;                     /* space; fixture checks all copy */
        dot = face ? LDR_FONT_M[k][row] : LDR_FONT_S[k][row];
        for (i = 0; i < 8u; i++)
            if (dot & (0x80u >> i))
                for (uint32_t j = 0; j < scale; j++)
                    ldr_pixel(x + i * scale + j, 0xFFFFu);
    }
}
/* Repaint rows [first, last) of the 240x240 frame; the full frame is 0..240. */
static void ldr_screen_draw(uint32_t first, uint32_t last)
{
    static const char *const title[] = {
        "UPDATE MODE", "CHECKING PACKAGE", "WRITING APP", "APP VERIFIED", "APP VERIFIED", "UPDATE STOPPED"
    };
    static const char *const hint[] = {
        "START INSTALL ON HOST", "KEEP USB CONNECTED", "DO NOT SWITCH OFF", "FINISHING UPDATE", "RESTARTING", "RETRY INSTALL ON HOST"
    };
    char number[8];
    uint32_t n = 0, y, x, v;
    if (ldr_lcd_failed) return;
    ldr_lcd_arm(LDR_LCD_DRAW_US);
    if (first == 0 && last == 240u)
        ldr_screen_framed = 1;                     /* a slow panel is not asked for the frame again */
    if (ldr_screen_state == LDR_WRITING) {
        v = ldr_screen_percent;
        if (v >= 100u) number[n++] = '1';
        if (v >= 10u) number[n++] = (char)('0' + v / 10u % 10u);
        number[n++] = (char)('0' + v % 10u);
        number[n++] = '%';
    } else if (ldr_screen_state == LDR_FAILED) {
        /* Native loader errors are small negative integers; no formatting libc. */
        number[n++] = '-';
        v = (uint32_t)-ldr_screen_error;
        if (v >= 10u) number[n++] = (char)('0' + v / 10u % 10u);
        number[n++] = (char)('0' + v % 10u);
    }
    number[n] = 0;
    if (!ldr_lcd_axis(0x2A, 0u, 239u) || !ldr_lcd_axis(0x2B, first, last - 1u) || !ldr_lcd_cmd(0x2C)) return;
    for (y = first; y < last; y++) {
        /* The previous row completed; failure returns before this source write. */
        for (x = 0; x < 240u; x++) ldr_pixel(x, 0x0841u); /* native GREY background */
        ldr_row_text(y, 36, 1, 2, "FELUCCA");
        if (y == 76u) for (x = 12; x < 228u; x++) ldr_pixel(x, 0xEF5Du);
        ldr_row_text(y, 100, 1, 1, title[ldr_screen_state]);
        ldr_row_text(y, 124, 0, 1, hint[ldr_screen_state]);
        ldr_row_text(y, 164, 1, 2, number);
        if (ldr_screen_state == LDR_WRITING)
            ldr_row_text(y, 196, 0, 1, "VERIFIED APP SECTORS");
        if (ldr_screen_state == LDR_FAILED)
            ldr_row_text(y, 212, 0, 1, "KEEP POWER AND USB ON");
        if (!ldr_lcd_data(ldr_line, sizeof ldr_line)) return;
        LDR_TRACE_ROW();
        ldr_poll();
    }
}
static void ldr_screen_status(uint32_t state, int32_t code)
{
    LDR_TRACE_T0;
    LDR_TRACE_BEGIN(1u, 0u, 240u);
    ldr_screen_state = state;
    ldr_screen_error = code;
    ldr_screen_percent = 0;
    if (ldr_lcd_failed) { LDR_TRACE_END(-1); return; }
    ldr_screen_next = ldr_ms() + 250u;
    ldr_screen_draw(0, 240u);
    LDR_TRACE_END(-1);
}
static void ldr_screen_progress(uint32_t done, uint32_t total)
{
    uint32_t percent;
    LDR_TRACE_T0;
    if (ldr_lcd_failed || !total || done > total) return;
    percent = done * 100u / total;                   /* app span is < 2^32 / 100 */
    if (percent == ldr_screen_percent || (done < total && (int32_t)(ldr_ms() - ldr_screen_next) < 0)) return;
    LDR_TRACE_BEGIN(2u, ldr_screen_state == LDR_WRITING && ldr_screen_framed ? LDR_STRIP_TOP : 0u,
                    ldr_screen_state == LDR_WRITING && ldr_screen_framed ? LDR_STRIP_END : 240u);
    ldr_screen_percent = percent;
    ldr_screen_next = ldr_ms() + 250u;
    if (ldr_screen_state == LDR_WRITING && ldr_screen_framed)
        ldr_screen_draw(LDR_STRIP_TOP, LDR_STRIP_END);   /* only the number changed */
    else
        ldr_screen_draw(0, 240u);
    LDR_TRACE_END(-1);
}
static void ldr_screen_init(void)
{
    ldr_lcd_arm(LDR_LCD_INIT_US);
    fm1_lcd_hw_init();
    ldr_lcd_delay(80);
    if (!ldr_lcd_cmd(0x01)) return;                  /* native ST7789 sequence */
    ldr_lcd_delay(150);
    if (!ldr_lcd_cmd(0x11)) return;
    ldr_lcd_delay(120);
    if (!ldr_lcd_cmd(0x3A)) return;
    ldr_args[0] = 0x55;
    if (!ldr_lcd_data(ldr_args, 1) || !ldr_lcd_cmd(0x36)) return;
    ldr_args[0] = 0;
    if (!ldr_lcd_data(ldr_args, 1) || !ldr_lcd_cmd(0x21) || !ldr_lcd_cmd(0x13)) return;
    ldr_screen_status(LDR_WAITING, 0);
#if FELUCCA_LDR_LCD_TRACE
    {
        int completed;
        LDR_TRACE_T0;
        LDR_TRACE_BEGIN(3u, 0u, 0u);
        ldr_lcd_arm(LDR_LCD_WAIT_US);
        completed = ldr_lcd_cmd(0x29);
        LDR_TRACE_END(completed);
    }
#else
    ldr_lcd_arm(LDR_LCD_WAIT_US);                    /* not the first draw's leftover budget */
    ldr_lcd_cmd(0x29);
#endif
}
