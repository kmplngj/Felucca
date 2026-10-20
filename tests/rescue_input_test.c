/* SPDX-License-Identifier: GPL-3.0-only */
/* Actual rescue entry + input HAL against a 595 and delayed matrix-row model.
 * Unlike rescue_test, buttons are never assigned by a stub. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#pragma GCC diagnostic ignored "-Wint-to-pointer-cast"
#include "../firmware/hal/fm1_time.h"
#include "../firmware/hal/fm1_gpio.h"
#include "../firmware/src/boot_policy.h"

static uint32_t ticks, physical, settle_us, changed_at, target, settled;
static uint32_t rail_on, rail_at;
static uint32_t previous_out, shifted = 0xFFFFu, latched = 0xFFFFu, feeds;
static volatile uint32_t regs[8][16];

static void gpio_sync(void)
{
    uint32_t out = regs[FM1_PA][FM1_OUT / 4u], rows = 0, p;
    if (!rail_on && !(out & (1u << 2)) && !(regs[FM1_PA][FM1_DIR / 4u] & (1u << 2))) {
        rail_on = 1;
        rail_at = ticks;
    }
    if ((uint32_t)(ticks - changed_at) >= settle_us * FM1_TICKS_PER_US)
        settled = target;
    if ((out & ~previous_out) & (1u << 3))
        shifted = ((shifted << 1) | ((out >> 4) & 1u)) & 0xFFFFu;
    if ((out & ~previous_out) & (1u << 1)) {
        latched = shifted;
        /* Physical OCT- and OCT+ share PA8 on columns 0 and 1. */
        for (p = 0; p < 2u; p++)
            if (!(latched & (1u << p)) && (physical & (1u << p)))
                rows |= 1u << 8;
        if (rows != target) {
            target = rows;
            changed_at = ticks;
        }
    }
    previous_out = out;
    /* Cold boot: no closed key reaches PA8 until PA2 is driven low as an
     * output and the shared rail has risen. ChoralRoot's device observations
     * put the first 30 ms outside the decision; model 25 ms here. */
    regs[FM1_PA][FM1_IN / 4u] = 0xFFFFFFFFu ^
        (rail_on && (uint32_t)(ticks - rail_at) >= 25000u * FM1_TICKS_PER_US ? settled : 0u);
    regs[FM1_PB][FM1_IN / 4u] = 0xFFFFFFFFu;
}
static volatile uint32_t *host_reg(uint32_t p, uint32_t r)
{
    ticks++;                                  /* finite bus time for shift edges */
    gpio_sync();
    return &regs[p][r / 4u];
}
static uint32_t host_ticks(void)
{
    ticks += FM1_TICKS_PER_US;
    gpio_sync();
    return ticks;
}
#undef FM1_PR
#define FM1_PR(p, r) (*host_reg((p), (r)))
#define fm1_ticks host_ticks
#include "../firmware/hal/fm1_input.h"
#include "../firmware/hal/fm1_lcd_hw.h"

#define FELUCCA_OTA 0
static volatile uint32_t fm1_ms;
static const int AF_M, AF_S;
static void fm1_wdt_feed(void) { feeds++; }
#define fm1_delay_ms host_delay_ms
static void fm1_delay_ms(uint32_t ms)
{
    while (ms--)
        fm1__wait(1000u);
}
static void usb_poll(void) {}
static void usb_retry(uint32_t now) { (void)now; }
static void lcd_fill(int x, int y, int w, int h, int c)
{ (void)x; (void)y; (void)w; (void)h; (void)c; }
static void draw_text_box(int x, int y, int w, const int *f, const char *s, int c, int a)
{ (void)x; (void)y; (void)w; (void)f; (void)s; (void)c; (void)a; }
#include "../firmware/src/rescue.c"

static int fails;
static void check(const char *label, int ok)
{
    printf("%-70s %s\n", label, ok ? "ok" : "FAIL");
    fails += !ok;
}
static void reset(uint32_t held, uint32_t delay, uint32_t start)
{
    memset((void *)regs, 0, sizeof regs);
    memset((void *)&fm1_in, 0, sizeof fm1_in);
    memset((void *)&fm1_in_stat, 0, sizeof fm1_in_stat);
    ticks = changed_at = start;
    rail_on = rail_at = 0;
    regs[FM1_PA][FM1_OUT / 4u] = 1u << 2;
    regs[FM1_PA][FM1_DIR / 4u] = 1u << 2;
    physical = held;
    settle_us = delay;
    target = settled = previous_out = feeds = 0;
    shifted = latched = 0xFFFFu;
    fm1__tick_col = 0;
}
int main(void)
{
    uint32_t delay, held, wrap;
    for (delay = 0; delay <= 80u; delay += 40u)
        for (held = 0; held < 4u; held++)
            for (wrap = 0; wrap < 2u; wrap++) {
                uint32_t mask, start;
                boot_policy_guard_t guard = {BOOTGUARD_MAGIC, 0, BOOT_POLICY_STARTING};
                char label[96];
                reset(held, delay, wrap ? UINT32_MAX - 12000u : 0u);
                start = ticks;
                mask = rescue_boot_buttons();
                snprintf(label, sizeof label, "actual matrix: held=%u, row delay=%u us, wrap=%u", held, delay, wrap);
                check(label, mask == held);
                check("OCT- selects rescue; OCT+ / both / neither preserve normal boot",
                      boot_policy_select(&guard, BOOT_POLICY_NORMAL, mask, 1) ==
                      (held == 1u ? BOOT_POLICY_RESCUE : BOOT_POLICY_NORMAL));
                check("rail enabled before bounded 30 ms settle + 30 ms scan; watchdog fed",
                      rail_on && feeds && (uint32_t)(ticks - start) >= 60000u * FM1_TICKS_PER_US &&
                      (uint32_t)(ticks - start) < 61000u * FM1_TICKS_PER_US);
            }
    return fails != 0;
}
