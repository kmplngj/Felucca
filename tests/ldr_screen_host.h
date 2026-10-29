/* SPDX-License-Identifier: GPL-3.0-only */
/* Deterministic SPI borrowed-source model for the actual loader renderer. The
 * source is read incrementally, including during timeout, and checked before
 * every hardware interaction. Never equate timeout with source release. */
#include <assert.h>
#define FM1_TICKS_PER_US 24u
static uint32_t display_ticks, display_wdt, display_usb, display_sends, display_commands;
static uint32_t display_usb_last, display_usb_gap;
/* Measured traffic: pixel rows (480 B transfers) and bytes submitted, DISPON
 * commands and the row window (RASET) last programmed. Deltas only. */
static uint32_t display_rows, display_row_bytes, display_dispon, display_raset[2], display_last_cmd;
static uint32_t display_due, display_delay = 24u * 20u, display_stall_at;
static const uint8_t *display_borrow;
static uint8_t display_snapshot[480];
static uint32_t display_size, display_consumed, display_active, display_cs, display_init;
#ifdef LDR_SCREEN_IMAGES
static uint8_t display_frame[240u * 480u];
static uint32_t display_row, display_row_first;
#endif
static void display_check(void)
{
    if (display_active && display_borrow)
        assert(!memcmp(display_borrow, display_snapshot, display_size));
}
static uint32_t fm1_ticks(void) { display_ticks += 24u * 10u; return display_ticks; }
static void fm1_wdt_feed(void) { display_check(); display_wdt++; }
static void usb_poll(void)
{
    uint32_t gap = display_ticks - display_usb_last;
    display_check();
    if (display_usb_last && gap > display_usb_gap) display_usb_gap = gap;
    display_usb_last = display_ticks;
    display_usb++;
}
#include "../firmware/loader/ldr_service.c"
static void fm1_lcd_hw_init(void) { display_init++; }
static void display_submit(const void *p, uint32_t n)
{
    display_check();
    assert(!display_active);                        /* no command or DMA can overlap */
    display_sends++;
    if (p && n == 480u) { display_rows++; display_row_bytes += n; }
    if (p && n == 4u && display_last_cmd == 0x2Bu) {
        display_raset[0] = (uint32_t)((const uint8_t *)p)[0] << 8 | ((const uint8_t *)p)[1];
        display_raset[1] = (uint32_t)((const uint8_t *)p)[2] << 8 | ((const uint8_t *)p)[3];
#ifdef LDR_SCREEN_IMAGES
        display_row_first = display_raset[0];
#endif
    }
    display_cs = display_active = 1;
    display_borrow = p;
    display_size = n;
    display_consumed = 0;
    if (p) { assert(n <= sizeof display_snapshot); memcpy(display_snapshot, p, n); }
    display_due = display_ticks + display_delay;
}
static void fm1_lcd_send_cmd(uint8_t c)
{
#ifdef LDR_SCREEN_IMAGES
    if (c == 0x2C) display_row = display_row_first;
#endif
    display_last_cmd = c;
    if (c == 0x29) display_dispon++;
    display_commands++; display_submit(NULL, 0);
}
static void fm1_lcd_send_data(const void *p, uint32_t n) { assert(n); display_submit(p, n); }
static uint32_t fm1_lcd_done(void)
{
    display_check();
    assert(display_active);
    if (display_borrow && display_consumed < display_size) {
        /* One independently consumed byte per completion poll. */
        assert(display_borrow[display_consumed] == display_snapshot[display_consumed]);
        display_consumed++;
    }
    if (display_sends == display_stall_at || (int32_t)(display_ticks - display_due) < 0)
        return 0;
#ifdef LDR_SCREEN_IMAGES
    if (display_borrow && display_size == 480u) {
        assert(display_row < 240u);
        memcpy(display_frame + display_row++ * 480u, display_borrow, 480u);
    }
#endif
    display_active = 0;
    display_borrow = NULL;
    return 1;
}
static void fm1_lcd_deselect(void) { assert(!display_active); display_cs = 0; }
#include "../firmware/loader/ldr_screen.c"

static void display_reset(void)
{
    display_check();
    /* Simulated device reset, the only ownership reset allowed after failure. */
    display_active = display_cs = display_sends = display_commands = display_stall_at = 0;
    display_borrow = NULL;
    display_delay = 24u * 20u;
    display_usb_last = display_usb_gap = 0;
    ldr_lcd_failed = 0;
}
