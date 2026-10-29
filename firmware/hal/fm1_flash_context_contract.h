/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FM1_FLASH_CONTEXT_CONTRACT_H
#define FM1_FLASH_CONTEXT_CONTRACT_H

#include <stdint.h>

/* Function types only: real and partial host adapters declare their own static
 * implementation before defining it. These types do not model IRQ state or
 * flash timing; the real flash guard requires IRQs enabled at entry. */
typedef uint32_t irq_save_fn(void);
typedef void irq_restore_fn(uint32_t flags);
typedef uint32_t fl_jedec_ram_fn(void);
typedef void fl_plain_window_init_fn(void);

#endif
