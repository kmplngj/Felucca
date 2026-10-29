/* SPDX-License-Identifier: GPL-3.0-only */
/* Diagnostic projection only. No transport or flash operation in this module.
 * Single loader main-loop owner; queries must run outside draw callbacks. */
#ifndef FELUCCA_LDR_LCD_TRACE
#define FELUCCA_LDR_LCD_TRACE 0
#endif
#if FELUCCA_LDR_LCD_TRACE
#define LDR_TRACE_CAP 128u
/* Six wire words: start/end ticks; kind/state/first/last bytes;
 * completed rows/stop reason/failed/reserved bytes; signed code; percent.
 * Stop: 0 complete, 1 aggregate budget, 2 new transfer failure, 3 old latch.
 * Kind: 1 status callback, 2 admitted progress callback, 3 DISPON. */
static uint32_t ldr_trace_records[LDR_TRACE_CAP][6];
static uint32_t ldr_trace_count, ldr_trace_overflow, ldr_trace_active;
static uint32_t ldr_trace_first, ldr_trace_last, ldr_trace_rows, ldr_trace_old_failure;
static void ldr_trace_begin(uint32_t kind, uint32_t first, uint32_t last, uint32_t start)
{
    if (ldr_trace_active || ldr_trace_count >= LDR_TRACE_CAP) {
        ldr_trace_overflow = 1;
        return;
    }
    ldr_trace_records[ldr_trace_count][0] = start;
    ldr_trace_records[ldr_trace_count][2] = kind | first << 16 | last << 24;
    ldr_trace_first = first;
    ldr_trace_last = last;
    ldr_trace_rows = 0;
    ldr_trace_old_failure = ldr_lcd_failed;
    ldr_trace_active = 1;
}
static void ldr_trace_row(void)
{
    if (ldr_trace_active)
        ldr_trace_rows++;
}
static void ldr_trace_end(int complete_hint)
{
    uint32_t end, stop, complete, *record;
    if (!ldr_trace_active)
        return;
    end = fm1_ticks();
    complete = complete_hint < 0 ? ldr_trace_rows == ldr_trace_last - ldr_trace_first : (uint32_t)complete_hint;
    stop = ldr_trace_old_failure ? 3u : ldr_lcd_failed ? 2u : complete ? 0u : 1u;
    record = ldr_trace_records[ldr_trace_count];
    record[1] = end;
    record[2] |= ldr_screen_state << 8;
    record[3] = ldr_trace_rows | stop << 8 | (uint32_t)ldr_lcd_failed << 16;
    record[4] = (uint32_t)ldr_screen_error;
    record[5] = ldr_screen_percent;
    __asm__ volatile("" ::: "memory");
    ldr_trace_count++;
    ldr_trace_active = 0;
}
static void ldr_trace_put32(uint8_t *p, uint32_t value)
{
    for (uint32_t i = 0; i < 4u; i++) p[i] = (uint8_t)(value >> (8u * i));
}
/* Request: version1, nonce low/high, index. Reply32: version/index/count/flags,
 * nonce low/high, declared ticks/us, reserved0, followed by six LE words.
 * Flags: bit0 overflow, bit1 busy, bit2 invalid index. Reject any nonzero flag.
 * Index255 samples the raw timer in word0; word1 repeats its declared ticks/us.
 * This frequency is a source assumption, NOT an actual-session calibration. */
static uint32_t ldr_trace_pack(const uint8_t *request, uint32_t n, uint8_t out[32])
{
    uint32_t index, flags;
    if (n != 4u || request[0] != 1u)
        return 0;
    index = request[3];
    flags = (ldr_trace_overflow ? 1u : 0u) | (ldr_trace_active ? 2u : 0u);
    if (index != 255u && index >= ldr_trace_count) flags |= 4u;
    for (uint32_t i = 0; i < 32u; i++) out[i] = 0;
    out[0] = 1; out[1] = (uint8_t)index; out[2] = (uint8_t)ldr_trace_count; out[3] = (uint8_t)flags;
    out[4] = request[1]; out[5] = request[2]; out[6] = FM1_TICKS_PER_US;
    if (!flags && index == 255u) {
        uint32_t sampled = fm1_ticks();
        ldr_trace_put32(out + 8, sampled);
        ldr_trace_put32(out + 12, FM1_TICKS_PER_US);
    } else if (!flags) {
        for (uint32_t i = 0; i < 6u; i++)
            ldr_trace_put32(out + 8u + i * 4u, ldr_trace_records[index][i]);
    }
    return 32;
}
#define LDR_TRACE_T0 uint32_t ldr_trace_start = fm1_ticks()
#define LDR_TRACE_BEGIN(k, f, l) ldr_trace_begin(k, f, l, ldr_trace_start)
#define LDR_TRACE_ROW() ldr_trace_row()
#define LDR_TRACE_END(h) ldr_trace_end(h)
#else
#define LDR_TRACE_T0 ((void)0)
#define LDR_TRACE_BEGIN(k, f, l) ((void)0)
#define LDR_TRACE_ROW() ((void)0)
#define LDR_TRACE_END(h) ((void)0)
#endif
