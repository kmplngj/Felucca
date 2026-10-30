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
#define LP_PROTOCOL_VERSION 2u
#define LP_TRACE_CAP 40u
#define LP_PIXELS (240u * 124u)
#define LP_BYTES (LP_PIXELS * 2u)
#define LP_HW_MS 1000u
#define LP_HOLD_MS 30000u
#define LP_REPORT_MS 100u
/* First reset cause: immutable ordinary BSS, independent of trace capacity. */
enum { LP_RST_ISSUED_BAUD=1, LP_RST_TRACE, LP_RST_SUBMIT, LP_RST_C_SETUP,
       LP_RST_SELECTION, LP_RST_HOLD, LP_RST_COMPLETE, LP_RST_HW, LP_RST_ABORT, LP_RST_BAUD_ATTEMPT };
static struct {
    volatile uint32_t active, hold, phase, mode, run, short_wait, selected, go_ms, arm_ms;
    uint32_t count, overflow, submits, selected_submits, stores, denied, reset;
    uint32_t a_hash, c_hash, after_hash, wait_result, pending_before_copy, released;
    uint32_t reset_cause, reset_phase, reset_ticks, reset_ms, reset_raw[4], reset_meta;
    uint32_t issued_submits, issued_seq, programmed_bytes, baud_epoch;
    uint32_t reset_read_mask, reset_issued_baud, reset_baud_writes, reset_attempt_valid, reset_attempt_baud;
    uintptr_t source;
    uint32_t trace[LP_TRACE_CAP][8];
} lp; /* ordinary BSS only: reboot disarms; no .noinit or persistent state */
#define LCD_PROBE_ACTIVE() (lp.active != 0u)
#define LCD_PROBE_STOPPED() (lp.active && lp.reset)
static void lp_request_reset(uint32_t cause);
static void lp_record(uint32_t event, uint32_t a, uint32_t b);
static uint32_t lp_submit(uint32_t command, const void *source, uint32_t bytes);
static void lp_issued(uint32_t command, const void *source, uint32_t bytes);
static uint32_t lp_baud_allowed(uint32_t value);
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
#define LCD_PROBE_STOPPED() 0
#endif
#endif
