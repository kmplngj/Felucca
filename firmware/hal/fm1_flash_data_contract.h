/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FM1_FLASH_DATA_CONTRACT_H
#define FM1_FLASH_DATA_CONTRACT_H

#include <stdint.h>

/* Function types only: real and partial host adapters declare their own static
 * implementation before defining it. RAM entry points take byte buffers; the
 * storage.c st_* hooks retain their separate object-buffer API. These types do
 * not model flash timing, address windows or NOR fault/return policies. */
typedef int fl_erase4k_ram_fn(uint32_t off, uint32_t *took_us);
typedef int fl_prog_ram_fn(uint32_t off, const uint8_t *src, uint32_t n, uint32_t *took_us);
typedef int fl_read_ram_fn(uint32_t off, uint8_t *dst, uint32_t n);
typedef int fl_erase4k_fn(uint32_t off, uint32_t *took_us);
typedef int fl_write_fn(uint32_t off, const uint8_t *src_ram, uint32_t n);

#endif
