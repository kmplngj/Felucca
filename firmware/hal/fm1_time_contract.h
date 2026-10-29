/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FM1_TIME_CONTRACT_H
#define FM1_TIME_CONTRACT_H

#include <stdint.h>

/* Function type only: the HAL and partial host adapters declare their own
 * static implementation before defining it. Tick units belong to the adapter. */
typedef uint32_t fm1_ticks_fn(void);

#endif
