/* SPDX-License-Identifier: GPL-3.0-only */
/* Actual SMK driver against the shared delayed-consumption ownership oracle. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BOARD_SMK37 1
static void fm1_padled_send(const void *p, uint32_t n);
static void fm1_padled_done(void);
static void host_put(uint32_t at, uint16_t pixel) { (void)at; (void)pixel; }
#include "lcd_fault_model.h"

static uint32_t checks, pad_sends, pad_returns, pad_route, pad_stall;
static uint8_t held_pad[PADLED_LATCH + PADLED_N * 24u];
static void need(int ok, const char *why)
{
    checks++;
    if (!ok) { fprintf(stderr, "FAIL SMK shared SPI: %s\n", why); exit(1); }
}
static void fm1_padled_send(const void *p, uint32_t n)
{
    need(!lcd_model_pending && !lcd_model_selected && !pad_route,
         "pad DMA must not replace an owned LCD/LED transfer");
    need(n == sizeof held_pad, "pad DMA includes reset and complete chain");
    lcd_model_submit(3); /* checks published ownership before real hardware start */
    pad_route = 1; pad_sends++;
    lcd_model_src = p; lcd_model_n = n;
    memcpy(lcd_model_copy, p, n);
    if (pad_stall) lcd_model_stuck = 1;
}
static void fm1_padled_done(void)
{
    need(pad_route && !lcd_model_pending, "restore pins only after genuine LED completion");
    need(lcd_busy, "ownership remains published until route restoration");
    pad_route = 0; pad_returns++;
}
static void reset(void)
{
    need(!lcd_model_pending && !lcd_model_selected && !lcd_busy && !pad_route,
         "fixture reset cannot abort an owned source");
    lcd_busy = lcd_fault = lcd_retry_armed = 0; lcd_initialized = 1;
    lcd_faults = lcd_recoveries = lcd_retry_t = 0;
    lcd_model_sent = lcd_model_waits = lcd_model_polls = lcd_model_fail_at = lcd_model_fail_cmd = 0;
    lcd_model_stuck = lcd_model_release = lcd_model_n = lcd_model_consumed = 0;
    lcd_model_partial = lcd_model_init_n = lcd_model_baud = 0;
    lcd_model_src = NULL;
    pad_sends = pad_returns = pad_stall = 0;
    memset(padled_rgb, 0, sizeof padled_rgb);
    memset(padled_buf, 0, sizeof padled_buf);
    padled_dirty = 1;
}
static void healthy_lcd_and_led(void)
{
    static const uint16_t pixels[4] = {0x1234, 0x5678, 0x9ABC, 0xDEF0};
    reset(); lcd_initialized = 0; lcd_init();
    need(lcd_initialized && !lcd_fault && !lcd_busy && lcd_model_init_n == 1u,
         "SMK initializes and completes its RGB565 frame");
    lcd_blit(0, 0, 2, 2, pixels);
    need(lcd_model_pending == 2u, "healthy LCD pixel DMA starts asynchronously");
    padled_set(8, 40, 0, 0); padled_flush();
    need(pad_sends == 1u && pad_returns == 1u && !pad_route && !lcd_busy,
         "healthy LED flush drains and deselects the LCD first");
    need(padled_buf[PADLED_LATCH + 24u + 8u + 2u] == 0xF0u,
         "bottom-left red still uses slot1 and unchanged GRB encoding");
    padled_flush(); need(pad_sends == 1u, "unchanged healthy colors do not retransmit");
    lcd_blit(0, 0, 2, 2, pixels); lcd_sync();
    need(!lcd_fault && !lcd_busy && !lcd_model_pending && !lcd_model_selected,
         "LCD resumes normally after healthy LED DMA");
}
static void blocked_lcd_source(void)
{
    static const uint16_t pixels[4] = {0x1234, 0x5678, 0x9ABC, 0xDEF0};
    uint32_t sends, waits, i;
    reset(); lcd_blit(0, 0, 2, 2, pixels);
    lcd_model_stuck = 1;
    padled_set(8, 40, 0, 0);
    memcpy(held_pad, padled_buf, sizeof held_pad);
    sends = lcd_model_sent;
    padled_flush();
    need(lcd_fault && lcd_busy && lcd_model_pending == 2u && !pad_sends && !pad_route,
         "LCD timeout retains its source and LCD routing");
    need(padled_dirty && !memcmp(held_pad, padled_buf, sizeof held_pad),
         "failed LCD acquisition cannot encode or consume queued LED state");
    waits = lcd_model_waits;
    for (i = 0; i < 20u; i++) { padled_flush(); lcd_model_owned(); }
    need(lcd_model_sent == sends && lcd_model_waits == waits && padled_dirty,
         "faulted frames do not wait again or replace the LCD lease");
    need(!lcd_service(1000u) && !lcd_service(1249u), "LCD retry retains250ms backoff");
    lcd_model_release = 1;
    need(lcd_service(1250u) && !lcd_busy && !lcd_fault && !pad_returns,
         "genuine LCD completion releases without touching LED routing");
    padled_flush();
    need(pad_sends == 1u && pad_returns == 1u && !pad_route && !lcd_busy,
         "queued LED update drains normally after LCD recovery");
}
static void led_source_and_latest(void)
{
    uint32_t sends, waits, polls, now, i;
    reset(); pad_stall = 1; padled_set(8, 40, 0, 0); padled_flush();
    need(lcd_fault && lcd_busy && pad_route && pad_sends == 1u && !pad_returns,
         "LED timeout retains source, bus selection and published ownership");
    memcpy(held_pad, padled_buf, sizeof held_pad);
    padled_set(8, 0, 255, 0); /* latest logical state may queue; encoded source stays owned */
    sends = lcd_model_sent; waits = lcd_model_waits;
    for (i = 0; i < 20u; i++) {
        padled_flush(); lcd_fill(0, 0, 2, 2, 0xFFFF); lcd_power(2);
        lcd_model_owned();
    }
    need(padled_dirty && !memcmp(held_pad, padled_buf, sizeof held_pad)
         && lcd_model_sent == sends && lcd_model_waits == waits && !pad_returns && pad_route,
         "queued RGB and LCD writers cannot modify or replace owned LED DMA");
    now = 5000u; need(!lcd_service(now), "LED recovery arms ordinary service");
    polls = lcd_model_polls;
    need(!lcd_service(now + 249u) && lcd_model_polls == polls, "no early LED completion poll");
    for (i = 0; i < 100u; i++) {
        now += 250u;
        need(!lcd_service(now), "missing LED completion stays faulted");
        padled_flush(); lcd_model_owned();
    }
    need(lcd_model_polls == polls + 100u && lcd_model_waits == waits
         && lcd_model_sent == sends && pad_route && !pad_returns && lcd_busy && lcd_fault,
         "100 missing-completion windows stay bounded and source-safe");
    pad_stall = 0; lcd_model_release = 1;
    need(lcd_service(now + 250u) && !lcd_busy && !lcd_fault && !pad_route && pad_returns == 1u,
         "late genuine LED completion restores pins before making bus available");
    padled_flush();
    need(pad_sends == 2u && pad_returns == 2u && !padled_dirty && !lcd_busy && !pad_route,
         "latest queued update is sent once after recovery");
    for (i = 0; i < 8u; i++)
        need(padled_buf[PADLED_LATCH + 24u + i] == 0xF0u
             && padled_buf[PADLED_LATCH + 32u + i] == 0xC0u,
             "queued bottom-left green uses slot1 and latest GRB bytes");
    for (i = 0; i < PADLED_LATCH; i++) need(!padled_buf[i], "reset prefix stays zero");
    padled_flush(); need(pad_sends == 2u, "unchanged queued update is not duplicated");
    lcd_power(2);
    need(!lcd_fault && !lcd_busy && !lcd_model_pending && !lcd_model_selected,
         "normal LCD traffic resumes after LED ownership release");
}
int main(void)
{
    healthy_lcd_and_led(); blocked_lcd_source(); led_source_and_latest();
    printf("PASS SMK shared SPI: actual LCD/LED ownership, bounded missing completion, late release, immutable source and latest queued RGB (%u checks)\n", checks);
    return 0;
}
