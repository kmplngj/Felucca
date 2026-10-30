/* SPDX-License-Identifier: GPL-3.0-only */
/* Actual lcd.c against a delayed DMA HAL: command payloads are captured when the
 * transfer completes, and every in-flight source range must remain unchanged. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { EV_CMD, EV_DATA, EV_BACKLIGHT };
typedef struct {
    uint32_t kind, n;
    uint8_t bytes[480];
} event_t;
static event_t events[1024];
static uint32_t event_n, pending_kind, selected, dma_faults;
static uint32_t hw_inits, baud, rail_on, gpio_on, gpio_off;
static const uint8_t *pending_src;
static uint8_t pending_copy[480];
static uint32_t pending_n;
enum { PENDING_NONE, PENDING_CMD, PENDING_DATA };

static void require(int ok, const char *why)
{
    if (!ok) {
        fprintf(stderr, "LCD HAL model: %s\n", why);
        exit(1);
    }
}
static event_t *event(uint32_t kind, uint32_t n)
{
    event_t *e;
    require(event_n < sizeof events / sizeof events[0], "event capacity");
    e = &events[event_n++];
    e->kind = kind;
    e->n = n;
    return e;
}
static void fm1_lcd_hw_init(void)
{
    require(!pending_kind && !selected, "init with active transfer");
    hw_inits++;
    rail_on = 1;
}
static void fm1_lcd_baud(uint32_t b)
{
    require(!pending_kind && !selected, "baud change with active transfer");
    baud = b;
}
static void fm1_lcd_send_cmd(uint8_t c)
{
    require(!pending_kind && !selected && rail_on, "command before transfer completion/deselect");
    event(EV_CMD, 1)->bytes[0] = c;
    pending_kind = PENDING_CMD;
    selected = 1;
}
static void fm1_lcd_send_data(const void *p, uint32_t n)
{
    require(!pending_kind && !selected && rail_on, "data before transfer completion/deselect");
    require(n && n <= sizeof pending_copy, "data transfer size");
    pending_src = p;
    pending_n = n;
    memcpy(pending_copy, p, n);
    pending_kind = PENDING_DATA;
    selected = 1;
}
static int fm1_lcd_wait(void)
{
    require(pending_kind != PENDING_NONE && selected, "wait without selected transfer");
    if (pending_kind == PENDING_DATA) {
        if (memcmp(pending_src, pending_copy, pending_n))
            dma_faults++;
        memcpy(event(EV_DATA, pending_n)->bytes, pending_src, pending_n);
        pending_src = NULL;
        pending_n = 0;
    }
    pending_kind = PENDING_NONE;
    return 1;
}
static int fm1_lcd_complete(void) { return fm1_lcd_wait(); }
static void fm1_lcd_deselect(void)
{
    require(!pending_kind && selected, "deselect before wait");
    selected = 0;
}
static void fm1_lcd_backlight(uint32_t on)
{
    require(!pending_kind && !selected, "GPIO change with active transfer");
    if (on) gpio_on++; else gpio_off++;
    rail_on = on != 0;
    event(EV_BACKLIGHT, 1)->bytes[0] = (uint8_t)on;
}

/* The override permits regression checks against an isolated historical driver without replacing the candidate. */
#ifndef LCD_DRIVER_SOURCE
#define LCD_DRIVER_SOURCE "../firmware/src/lcd.c"
#endif
#include LCD_DRIVER_SOURCE

static uint32_t failures;
static void check(const char *name, int ok)
{
    printf("%s: %s\n", ok ? "PASS" : "FAIL", name);
    failures += !ok;
}
static void reset(void)
{
    require(!pending_kind && !selected && !lcd_busy, "reset with active DMA");
    event_n = dma_faults = hw_inits = baud = gpio_on = gpio_off = 0;
    pending_src = NULL;
    pending_n = 0;
    rail_on = 1;
    memset(lcd_small, 0xA5, sizeof lcd_small);
}
typedef struct { uint8_t kind, byte; } one_t;
static const one_t init[] = {{EV_CMD, 0x01}, {EV_CMD, 0x11}, {EV_CMD, 0x3A}, {EV_DATA, 0x55},
                             {EV_CMD, 0x36}, {EV_DATA, 0x00}, {EV_CMD, 0x21}, {EV_CMD, 0x13}};
static const one_t sleep[] = {{EV_CMD, 0x28}, {EV_CMD, 0x10}};
static int sequence(uint32_t at, const one_t *want, uint32_t n)
{
    uint32_t i;
    if (at + n > event_n)
        return 0;
    for (i = 0; i < n; i++)
        if (events[at + i].kind != want[i].kind || events[at + i].n != 1u ||
            events[at + i].bytes[0] != want[i].byte)
            return 0;
    return 1;
}
static int complete(void)
{
    uint32_t i;
    for (i = 0; i < event_n; i++)
        if (events[i].kind == EV_CMD && (events[i].bytes[0] == 0x51u || events[i].bytes[0] == 0x53u))
            return 0;                             /* the colour A/B candidate must never enable the controller probe */
    return !pending_kind && !selected && !lcd_busy && !dma_faults && rail_on && !gpio_off;
}

int main(int argc, char **argv)
{
    static const uint16_t pixels[4] = {0x0123, 0x4567, 0x89AB, 0xCDEF};
    uint32_t i, j, at, fills;
    int ok;

    if (argc == 2 && !strcmp(argv[1], "--dma-negative")) {
        reset();
        lcd_data(lcd_small, 1);
        lcd_small[0] ^= 0xFF;
        lcd_sync();
        check("negative control: in-flight scratch mutation must fail DMA ownership", !dma_faults);
        return failures ? 1 : 0;
    }
    if (argc != 1) return 2;
    if (lcd_service(0)) return 1;

    reset();
    lcd_data(lcd_small, 4);
    lcd_power(0);
    check("sleep drains unchanged scratch DMA before DISPOFF/SLPIN; no controller brightness commands",
          event_n == 3u && events[0].kind == EV_DATA && events[0].n == 4u &&
          events[0].bytes[0] == 0xA5 && events[0].bytes[3] == 0xA5 && sequence(1, sleep, 2) && complete());

    reset();
    lcd_blit(0, 0, 2, 2, pixels);
    at = event_n;
    require(pending_kind == PENDING_DATA, "blit must leave pixel DMA pending");
    lcd_power(2);
    check("DISPON drains pending pixel DMA without changing RGB565 bytes or sending 0x51/0x53",
          event_n == at + 2u && events[at].kind == EV_DATA && events[at].n == sizeof pixels &&
          !memcmp(events[at].bytes, pixels, sizeof pixels) && events[at + 1u].kind == EV_CMD &&
          events[at + 1u].bytes[0] == 0x29 && complete());

    reset();
    lcd_power(0);
    check("sleep sends only DISPOFF/SLPIN; shared PA2 remains enabled",
          event_n == 2u && sequence(0, sleep, 2) && complete());

    reset();
    lcd_power(1);
    ok = event_n == 1u && events[0].kind == EV_CMD && events[0].bytes[0] == 0x11 && complete();
    lcd_blit(0, 0, 2, 2, pixels);
    at = event_n;
    lcd_power(2);
    check("normal wake preserves SLPOUT/redraw/DISPON order and exact pixels, with no 0x51/0x53",
          ok && event_n == at + 2u && events[at].kind == EV_DATA && events[at].n == sizeof pixels &&
          !memcmp(events[at].bytes, pixels, sizeof pixels) && events[at + 1u].kind == EV_CMD &&
          events[at + 1u].bytes[0] == 0x29 && complete());

    reset(); rail_on = 0;
    lcd_init();
    fills = 0; ok = 1;
    for (i = 0; i < event_n; i++)
        if (events[i].kind == EV_DATA && events[i].n == 480u) {
            fills++;
            for (j = 0; j < events[i].n; j++)
                ok &= events[i].bytes[j] == 0u;
        }
    check("boot preserves RGB565/COLMOD55, MADCTL00, inversion, black fill and DISPON; no 0x51/0x53",
          ok && fills == 240u && hw_inits == 1u && baud == LCD_BAUD && !gpio_on && event_n == 254u &&
          sequence(0, init, sizeof init / sizeof init[0]) && events[event_n - 1u].kind == EV_CMD &&
          events[event_n - 1u].bytes[0] == 0x29 && complete());

    reset();
    lcd_power(0); event_n = 0;
    lcd_wake_now();
    check("emergency/update wake sends SLPOUT/DISPON and enables PA2 without controller brightness writes",
          event_n == 3u && events[0].kind == EV_CMD && events[0].bytes[0] == 0x11 &&
          events[1].kind == EV_CMD && events[1].bytes[0] == 0x29 &&
          events[2].kind == EV_BACKLIGHT && events[2].bytes[0] == 1u && gpio_on == 1u && complete());

    reset(); ok = 1;
    for (i = 0; i < 32u; i++) {
        lcd_power(0); lcd_power(1);
        lcd_blit(0, 0, 2, 2, pixels);
        lcd_power(2);
        ok &= complete();
        event_n = 0;
    }
    check("32 sleep/redraw/wake cycles retain transfer ownership and never disable PA2", ok);

    reset();
    lcd_data(lcd_small, 1);
    lcd_small[0] ^= 0xFF;
    lcd_sync();
    check("DMA oracle detects an intentional in-flight scratch write", dma_faults == 1u);

    return failures ? 1 : 0;
}
