/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef HOST_LCD_BLIT_NOOP_H
#define HOST_LCD_BLIT_NOOP_H

#include "../firmware/hal/fm1_lcd_contract.h"

/* Partial host adapters deliberately discard panel blits without reading pixels
 * or modeling panel output, DMA, synchronization or LCD observations. */
static lcd_blit_fn lcd_blit;
static void lcd_blit(uint32_t x, uint32_t y, uint32_t w, uint32_t h, const uint16_t *p)
{ (void)x; (void)y; (void)w; (void)h; (void)p; }

#endif
