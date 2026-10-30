/* SPDX-License-Identifier: GPL-3.0-only */
/* Development-only #600 causal probe. No retained arm, automatic retry or peripheral abort. */
#ifndef FELUCCA_LCD_INFLIGHT_H
#define FELUCCA_LCD_INFLIGHT_H
#ifndef FELUCCA_LCD_INFLIGHT
#define FELUCCA_LCD_INFLIGHT 0
#endif
#if FELUCCA_LCD_INFLIGHT != 0 && FELUCCA_LCD_INFLIGHT != 1
#error "FELUCCA_LCD_INFLIGHT must be 0 or 1"
#endif
#if FELUCCA_LCD_INFLIGHT
#include <stdint.h>
enum { LP_OFF, LP_C_READY, LP_SETUP, LP_TRANSFER, LP_WAITING, LP_SETTLED, LP_MISS, LP_REPAINT, LP_ABORT };
enum { LP_A_ONLY, LP_CANDIDATE, LP_CONTROL };
enum { LP_ARM=1, LP_SUBMIT, LP_SHORT_WAIT, LP_WAIT_RESULT, LP_PACK_ATTEMPT,
       LP_DENIED, LP_COPY_BEGIN, LP_COPY_END, LP_COMPLETE, LP_RELEASE, LP_HOLD_END, LP_RESET, LP_SELECTED };
#define LP_TRACE_CAP 40u
#define LP_PIXELS (240u * 124u)
#define LP_BYTES (LP_PIXELS * 2u)
#define LP_HW_MS 1000u
#define LP_HOLD_MS 30000u
static struct {
    volatile uint32_t active, hold, phase, mode, run, short_wait, selected, go_ms, arm_ms;
    uint32_t count, overflow, submits, selected_submits, stores, denied, reset;
    uint32_t a_hash, c_hash, after_hash, wait_result, pending_before_copy, released;
    uintptr_t source;
    uint32_t trace[LP_TRACE_CAP][8];
} lp; /* ordinary BSS only: reboot disarms; no .noinit or persistent state */
#define LCD_PROBE_ACTIVE() (lp.active != 0u)
static void lp_record(uint32_t event, uint32_t a, uint32_t b);
static void lp_submit(uint32_t command, const void *source, uint32_t bytes);
static uint32_t lp_wait_budget(void);
static void lp_wait_result(uint32_t result);
static uint32_t lp_pack_begin(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h);
static uint32_t lp_control_write(uint32_t probe);
static void lp_pack_denied(uint32_t probe);
static uint32_t lp_pack_ready(uint32_t probe);
static void lp_pack_end(uint32_t probe, uint32_t stores);
static void lp_step(void);
#else
#define LCD_PROBE_ACTIVE() 0
#endif
#endif
