/* SPDX-License-Identifier: GPL-3.0-only
 * SMK-37 Pro port: Copyright (C) 2026 M. Geisler (genkigenki/makkuro)
 * Drift timing adapted from zvenson/dinghy firmware/src/smk_wheel.h,
 * commit 7c31bb25c90cc11b2a94f1a10f549d0817884ac1 (GPL-3.0-only). */
#pragma once
#include <stdint.h>

/* Reference policy, not a measured SMK calibration: at most one raw centre
 * count per 250 ms in the dead band. Delayed polls never catch up in a jump.
 * The caller resets at_ms outside the dead band; d is strictly within it. */
#define SMK_WHEEL_DRIFT_MS 250u
static int32_t smk_wheel_drift(int32_t d, uint32_t now_ms, uint32_t *at_ms)
{
    if ((uint32_t)(now_ms - *at_ms) < SMK_WHEEL_DRIFT_MS) return 0;
    *at_ms = now_ms;
    return d > 0 ? 1 : d < 0 ? -1 : 0;
}
