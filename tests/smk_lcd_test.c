/* SPDX-License-Identifier: GPL-3.0-only */
/* Real SMK LCD/pad driver against the shared delayed-DMA LCD fixture. */
#include <stdint.h>
#define BOARD_SMK37 1
static void fm1_padled_send(const void *p, uint32_t n);
static void fm1_padled_done(void);
#define main fm1_lcd_fixture_main
#include "lcd_power_test.c"
#undef main

static uint32_t pad_sends, pad_returns;
static const uint8_t *pad_src;
static void fm1_padled_send(const void *p, uint32_t n)
{
    require(!pending_kind && !selected && !lcd_busy, "pad DMA must drain/deselect LCD first");
    require(n == PADLED_LATCH + 16u * 24u, "pad DMA includes reset and full chain");
    pad_sends++;
    pad_src = p;
    /* The pad SPI transfer is completed by the common wait helper. */
    pending_kind = PENDING_CMD;
    selected = 1;
}
static void fm1_padled_done(void)
{
    require(!pending_kind, "LCD bus cannot return before pad DMA completes");
    selected = 0;
    pad_returns++;
}
int main(void)
{
    uint32_t i;
    static const uint16_t px[4] = {0x1234, 0x5678, 0x9ABC, 0xDEF0};
    reset();
    lcd_init();
    check("SMK panel initializes with RGB565 and completes its frame", complete() && hw_inits == 1u);
    lcd_blit(0, 0, 2, 2, px);
    require(pending_kind == PENDING_DATA, "pending LCD pixel DMA before pad flush");
    padled_set(8, 40, 0, 0);
    padled_flush();
    check("pad flush drains LCD DMA before borrowing SPI1", !dma_faults && pad_sends == 1u && pad_returns == 1u);
    for (i = 0; i < PADLED_LATCH; i++)
        require(pad_src[i] == 0u, "WS2812 reset bytes are zero");
    check("bottom-left pad uses slot 1 with GRB encoded red", pad_src[PADLED_LATCH + 24u + 8u + 2u] == 0xF0u);
    padled_flush();
    check("unchanged pad colours do not transmit again", pad_sends == 1u);
    lcd_blit(0, 0, 2, 2, px);
    lcd_sync();
    check("LCD resumes with unchanged pixel DMA after pads", complete());
    return failures ? 1 : 0;
}
