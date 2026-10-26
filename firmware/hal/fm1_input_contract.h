/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FM1_INPUT_CONTRACT_H
#define FM1_INPUT_CONTRACT_H

#include <stdint.h>

/* Function type only: each adapter declares its own static implementation with
 * this type before defining it. Partial host adapters need no unused prototypes. */
typedef uint32_t fm1_input_edges_fn(uint32_t *released);

#endif
