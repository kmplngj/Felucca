/* SPDX-License-Identifier: GPL-3.0-only */
/* Independent, delayed-consumption SPI sink for the actual lcd.c + native UI.
 * Neither wait failure nor CS can release its borrowed range. Only explicit
 * completion consumes it; every subsequent call checks the original bytes. */
static uint32_t lcd_model_sent, lcd_model_waits, lcd_model_polls, lcd_model_fail_at, lcd_model_fail_cmd;
static volatile uint8_t lcd_busy;  /* actual driver's tentative definition; checked at hardware submission */
static uint32_t lcd_model_pending, lcd_model_selected, lcd_model_stuck, lcd_model_release;
static uint32_t lcd_model_cmd, lcd_model_x0, lcd_model_x1, lcd_model_y0, lcd_model_y1, lcd_model_x, lcd_model_y;
static uint32_t lcd_model_n, lcd_model_init_n, lcd_model_baud;
static uint32_t lcd_model_partial, lcd_model_consumed;
static const uint8_t *lcd_model_src;
static uint8_t lcd_model_copy[240u * 124u * 2u];
static void lcd_model_need(int ok, const char *why)
{
    if (!ok) { fprintf(stderr, "LCD fault oracle: %s (sent=%u pending=%u)\n", why, lcd_model_sent, lcd_model_pending); exit(1); }
}
static void lcd_model_owned(void)
{
    if (lcd_model_src)
        lcd_model_need(!memcmp(lcd_model_src, lcd_model_copy, lcd_model_n), "in-flight source modified");
}
static void fm1_lcd_hw_init(void)
{
    lcd_model_need(!lcd_model_pending && !lcd_model_selected, "init is not an abort");
    lcd_model_init_n++;
}
static void fm1_lcd_baud(uint32_t b)
{
    lcd_model_need(!lcd_model_pending && !lcd_model_selected, "baud while owned");
    lcd_model_baud = b;
}
static void lcd_model_submit(uint32_t kind)
{
    lcd_model_owned();
    lcd_model_need(lcd_busy, "ownership published before hardware start");
    lcd_model_need(!lcd_model_pending && !lcd_model_selected, "submission before completion/release");
    lcd_model_pending = kind; lcd_model_selected = 1;
    if (++lcd_model_sent == lcd_model_fail_at) lcd_model_stuck = 1;
}
static void fm1_lcd_send_cmd(uint8_t c)
{
    lcd_model_submit(1); lcd_model_cmd = c;
    if (lcd_model_fail_cmd == c) lcd_model_stuck = 1;
}
static void lcd_model_pixels(uint32_t end)
{
    lcd_model_need(!(end & 1u) && end <= lcd_model_n, "bounded RGB565 prefix");
    while (lcd_model_consumed < end) {
        uint16_t pixel;
        lcd_model_need(lcd_model_x <= lcd_model_x1 && lcd_model_y <= lcd_model_y1, "pixel inside window");
        memcpy(&pixel, lcd_model_src + lcd_model_consumed, sizeof pixel);
        host_put(lcd_model_y * 240u + lcd_model_x, pixel);
        if (++lcd_model_x > lcd_model_x1) { lcd_model_x = lcd_model_x0; lcd_model_y++; }
        lcd_model_consumed += 2u;
    }
}
static void fm1_lcd_send_data(const void *p, uint32_t n)
{
    lcd_model_submit(2);
    lcd_model_need(n && n <= sizeof lcd_model_copy, "bounded nonzero RAM payload");
    lcd_model_src = p; lcd_model_n = n; memcpy(lcd_model_copy, p, n);
    lcd_model_consumed = 0;
    /* DMA may read a prefix before stalling. The whole borrowed range remains
     * owned until explicit completion, which consumes only the remainder. */
    if (lcd_model_stuck && lcd_model_cmd == 0x2Cu && lcd_model_partial)
        lcd_model_pixels(lcd_model_partial < n ? lcd_model_partial : n);
}
static int fm1_lcd_complete(void)
{
    lcd_model_polls++;
    lcd_model_owned();
    lcd_model_need(lcd_model_pending && lcd_model_selected, "completion without owner");
    if (lcd_model_stuck && !lcd_model_release) return 0;
    if (lcd_model_pending == 2u) {
        if (lcd_model_cmd == 0x2Au || lcd_model_cmd == 0x2Bu) {
            uint32_t a, b;
            lcd_model_need(lcd_model_n == 4u, "window size");
            a = (uint32_t)lcd_model_src[0] * 256u + lcd_model_src[1];
            b = (uint32_t)lcd_model_src[2] * 256u + lcd_model_src[3];
            lcd_model_need(a <= b && b < 240u, "window bounds");
            if (lcd_model_cmd == 0x2Au) { lcd_model_x0 = a; lcd_model_x1 = b; }
            else { lcd_model_y0 = a; lcd_model_y1 = b; }
        } else if (lcd_model_cmd == 0x2Cu) {
            lcd_model_need(!(lcd_model_n & 1u), "RGB565 pairs");
            lcd_model_pixels(lcd_model_n);
        }
    } else if (lcd_model_cmd == 0x2Cu) {
        lcd_model_x = lcd_model_x0; lcd_model_y = lcd_model_y0;
    }
    lcd_model_pending = 0; lcd_model_src = NULL; lcd_model_n = 0;
    lcd_model_stuck = lcd_model_release = 0;
    return 1;
}
static int fm1_lcd_wait(void) { lcd_model_waits++; return fm1_lcd_complete(); }
static void fm1_lcd_deselect(void)
{
    lcd_model_owned();
    lcd_model_need(!lcd_model_pending && lcd_model_selected, "deselect is not an abort");
    lcd_model_selected = 0;
}
static void fm1_lcd_backlight(uint32_t on)
{
    lcd_model_need(!lcd_model_pending && !lcd_model_selected && on, "shared rail stays on, after completion");
}
#include "../firmware/src/lcd.c"
