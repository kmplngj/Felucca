/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef HOST_CLOCK_H
#define HOST_CLOCK_H

#include "../firmware/hal/fm1_time_contract.h"

/* Passive clock accessor shared by the UI and browser adapters. The consumer
 * selects its existing uint32_t state with HOST_CLOCK_TICKS and retains its
 * tick scale, advancement and reset policy. Reading never advances time.
 * Audio/rescue/input bus clocks deliberately retain their read-side effects;
 * TIMER5 and constant diagnostic/click clocks retain their specialised owners. */
static fm1_ticks_fn fm1_ticks;
static uint32_t fm1_ticks(void) { return HOST_CLOCK_TICKS; }

#endif
