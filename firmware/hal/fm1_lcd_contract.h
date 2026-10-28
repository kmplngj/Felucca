/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FM1_LCD_CONTRACT_H
#define FM1_LCD_CONTRACT_H

#include <stdint.h>

/* Function type only: real and partial host adapters declare their own static
 * implementation before defining it. Fill colours are RGB565, not 32-bit values. */
typedef void lcd_fill_fn(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t colour);

/* Pixel sources retain the panel RGB565 byte order and are read-only. */
typedef void lcd_blit_fn(uint32_t x, uint32_t y, uint32_t w, uint32_t h, const uint16_t *pixels);

#endif
