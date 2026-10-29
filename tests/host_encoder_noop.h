/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef HOST_ENCODER_NOOP_H
#define HOST_ENCODER_NOOP_H

#include "../firmware/hal/fm1_input_contract.h"

/* Partial host adapters always report no encoder steps, without accumulating
 * input or modeling encoder timing. */
static fm1_enc_take_fn fm1_enc_take;
static int32_t fm1_enc_take(uint32_t e) { (void)e; return 0; }

#endif
