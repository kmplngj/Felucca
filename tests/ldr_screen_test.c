/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#ifndef LDR_SCREEN_EMBEDDED
#include "ldr_screen_host.h"
#endif
static void ldr_screen_contract_tests(void)
{
    uint32_t sends, feeds, polls, rows, bytes, dispon, total;
    ldr_screen_init();
    assert(display_init == 1 && !ldr_lcd_failed && !display_active && !display_cs);
    assert(ldr_screen_state == LDR_WAITING && display_wdt && !display_usb);
    ldr_usb_started = 1;
    ldr_screen_status(LDR_VALIDATING, 0);
    assert(display_usb && ldr_screen_state == LDR_VALIDATING);
    ldr_screen_status(LDR_WRITING, 0);
    sends = display_sends;
    ldr_screen_progress(0, 0);
    ldr_screen_progress(101, 100);
    ldr_screen_progress(0, 100);
    ldr_screen_progress(1, 100);                     /* coalesced until 250ms */
    assert(display_sends == sends && ldr_screen_percent == 0);
    display_ticks += 250u * 1000u * 24u;
    ldr_screen_progress(4096u, 0x8F000u);
    assert(ldr_screen_percent == 0);
    assert(ldr_screen_framed);
    rows = display_rows; bytes = display_row_bytes;
    ldr_screen_progress(0x47000u, 0x8F000u);
    assert(ldr_screen_percent == 49);
    /* Progress repaints only the percentage strip: 18 rows, not 240. */
    assert(display_rows - rows == LDR_STRIP_END - LDR_STRIP_TOP && display_rows - rows == 18u);
    assert(display_row_bytes - bytes == 18u * 480u);
    assert(display_raset[0] == LDR_STRIP_TOP && display_raset[1] == LDR_STRIP_END - 1u);
    rows = display_rows;
    ldr_screen_progress(0x47000u, 0x8F000u);          /* unchanged percent: nothing sent */
    assert(display_rows == rows);
    display_ticks += 250u * 1000u * 24u;
    ldr_screen_progress(0x8F000u, 0x8F000u);
    assert(ldr_screen_percent == 100 && display_rows - rows == 18u);
    rows = display_rows;
    ldr_screen_status(LDR_FINISHING, 0);              /* state changes keep the full redraw */
    assert(display_rows - rows == 240u && display_raset[0] == 0 && display_raset[1] == 239u);
    ldr_screen_status(LDR_FINISHING, 0);
    ldr_screen_status(LDR_SUCCESS, 0);
    assert(ldr_screen_state == LDR_SUCCESS);
    ldr_screen_status(LDR_FAILED, -11);
    assert(ldr_screen_state == LDR_FAILED && ldr_screen_error == -11);
    ldr_screen_status(LDR_VALIDATING, 0);             /* actual attempt wrapper invokes this on retry */
    assert(ldr_screen_state == LDR_VALIDATING && !ldr_screen_percent);
    display_delay = 24u * 200u;                     /* slow but bounded hardware completion */
    feeds = display_wdt; polls = display_usb;
    ldr_screen_status(LDR_WRITING, 0);
    assert(!ldr_lcd_failed && display_wdt > feeds && display_usb > polls);
    display_reset();
    display_delay = 24u * 400u;                      /* 400us/row: a full frame outlasts the old 100ms budget */
    assert(LDR_LCD_DRAW_US >= 250000u);
    feeds = display_ticks; rows = display_rows; dispon = display_dispon;
    ldr_screen_init();
    assert(display_ticks - feeds > 24u * (350u * 1000u + 100000u)); /* delays + frame beyond 100ms */
    assert(!ldr_lcd_failed && display_rows - rows == 240u && display_dispon - dispon == 1u);
    assert(ldr_screen_framed && !display_active && !display_cs);
    rows = display_rows;
    ldr_screen_status(LDR_WRITING, 0);               /* and a state change completes at that latency too */
    assert(!ldr_lcd_failed && display_rows - rows == 240u);
    display_reset();
    display_delay = 24u * 1900u;                     /* every transfer completes within its own deadline */
    feeds = display_ticks; polls = display_usb; rows = display_rows;
    ldr_screen_status(LDR_WRITING, 0);
    /* Aggregate overrun abandons the redraw between transfers; it is not a failure. */
    assert(!ldr_lcd_failed && !display_active && !display_cs);
    assert(display_rows - rows < 240u && display_rows - rows > 100u);
    assert(display_ticks - feeds < 24u * (LDR_LCD_DRAW_US + 1000u));
    assert(display_usb > polls && display_usb_gap < 24u * 600u); /* bounded protocol polling */
    display_check();
    /* A slow panel is not asked for the whole frame again on every progress step:
     * progress stays on the strip and only a state change repaints everything. */
    rows = display_rows;
    ldr_screen_progress(0x47000u, 0x8F000u);
    assert(!ldr_lcd_failed && display_rows - rows <= LDR_STRIP_END - LDR_STRIP_TOP);
    display_delay = 24u * 20u;
    rows = display_rows;
    ldr_screen_status(LDR_WRITING, 0);
    assert(!ldr_lcd_failed && display_rows - rows == 240u);
    display_reset();
    display_delay = 24u * 1900u;                     /* first draw overruns: DISPON still gets its own deadline */
    feeds = display_ticks; rows = display_rows; dispon = display_dispon;
    ldr_screen_init();
    assert(!ldr_lcd_failed && display_rows - rows < 240u && display_dispon - dispon == 1u);
    assert(display_ticks - feeds < 24u * (LDR_LCD_INIT_US + LDR_LCD_DRAW_US + 10000u));
    display_reset();
    display_delay = 24u * 2500u;                     /* a real per-transfer timeout still latches */
    feeds = display_ticks; sends = display_sends; dispon = display_dispon;
    ldr_screen_status(LDR_WRITING, 0);
    assert(ldr_lcd_failed && display_active && display_cs && display_sends - sends == 1u);
    assert(display_ticks - feeds < 24u * 3000u);
    sends = display_sends;
    ldr_screen_progress(0x47000u, 0x8F000u);
    ldr_screen_status(LDR_VALIDATING, 0);
    assert(display_sends == sends && display_dispon == dispon);
    display_reset();
    ldr_screen_init();                               /* learn the DISPON transfer index of a clean init */
    total = display_sends;
    assert(display_dispon && !ldr_lcd_failed);
    display_reset();
    display_stall_at = total;                        /* DISPON itself never completes */
    dispon = display_dispon;
    ldr_screen_init();
    assert(ldr_lcd_failed && display_dispon - dispon == 1u && display_active && display_cs);
    /* A command, borrowed window args and an independently consumed pixel row
     * can each stall. A late completion is deliberately never treated as retry. */
    for (uint32_t at = 1; at <= 6; at++) {
        display_reset();
        display_stall_at = at;
        feeds = display_wdt; polls = display_usb;
        ldr_screen_status(LDR_WRITING, 0);
        assert(ldr_lcd_failed && display_active && display_cs);
        assert(display_wdt > feeds && display_usb > polls);
        sends = display_sends;
        ldr_screen_progress(0x8F000u, 0x8F000u);
        ldr_screen_status(LDR_FAILED, -9);
        ldr_screen_status(LDR_VALIDATING, 0);
        assert(display_sends == sends);
        for (uint32_t i = 0; i < 1000; i++) ldr_poll();
        display_check();
        assert(display_active && display_cs);        /* timeout retained source and bus */
    }
    display_reset();
    display_stall_at = 1;
    ldr_usb_started = 0;
    polls = display_usb;
    ldr_screen_init();                             /* missing LCD cannot strand startup */
    assert(ldr_lcd_failed && display_usb == polls);
    ldr_usb_started = 1;
    ldr_poll();
    for (uint32_t i = 0; i < 100; i++) ldr_poll();
    assert(display_usb > polls);
    puts("loader screen: production renderer/service, progress, retry and SPI source containment PASS");
    display_reset();
    ldr_usb_started = 0;
}
#ifndef LDR_SCREEN_EMBEDDED
int main(void) { ldr_screen_contract_tests(); return 0; }
#endif
