/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#ifndef LDR_SCREEN_EMBEDDED
#include "ldr_screen_host.h"
#endif
static void ldr_screen_contract_tests(void)
{
    uint32_t sends, feeds, polls;
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
    ldr_screen_progress(0x47000u, 0x8F000u);
    assert(ldr_screen_percent == 49);
    ldr_screen_progress(0x8F000u, 0x8F000u);
    assert(ldr_screen_percent == 100);
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
    display_delay = 24u * 1900u;                     /* every transfer completes within its own deadline */
    feeds = display_ticks;
    polls = display_usb;
    ldr_screen_status(LDR_WRITING, 0);
    assert(ldr_lcd_failed && display_ticks - feeds < 24u * (LDR_LCD_DRAW_US + 1000u));
    assert(display_usb > polls && display_usb_gap < 24u * 600u); /* bounded protocol polling */
    display_check();
    display_reset();
    display_delay = 24u * 1900u;
    feeds = display_ticks;
    ldr_screen_init();
    assert(ldr_lcd_failed && display_ticks - feeds < 24u * LDR_LCD_INIT_US);
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
