/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define FELUCCA_LDR_LCD_TRACE 1
#include "ldr_screen_host.h"
#define LDR_SCREEN_EMBEDDED 1
#include "ldr_screen_test.c"
static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void reset_trace(void)
{
    assert(!ldr_trace_active);
    ldr_trace_count = ldr_trace_overflow = 0;
    memset(ldr_trace_records, 0, sizeof ldr_trace_records);
}
int main(void)
{
    uint8_t query[4] = {1, 0x34, 0x12, 0}, out[32];
    uint32_t saved[LDR_TRACE_CAP][6], sends, rows;
    ldr_screen_contract_tests();                 /* real renderer and source-lease regressions */
    display_reset(); reset_trace();
    display_ticks = 0xffff0000u;                 /* unsigned TIMER4 crossing */
    ldr_screen_init();
    assert(ldr_trace_count == 2 && !ldr_trace_overflow && !ldr_trace_active);
    assert((ldr_trace_records[0][3] & 255u) == 240u && (ldr_trace_records[0][3] >> 8) == 0);
    assert((ldr_trace_records[1][2] & 255u) == 3u && ldr_trace_records[1][3] == 0);
    assert(ldr_trace_records[0][1] - ldr_trace_records[0][0] < 250000u * 24u);
    memcpy(saved, ldr_trace_records, sizeof saved); sends = display_sends;
    assert(ldr_trace_pack(query, 4, out) == 32);
    assert(out[0] == 1 && out[1] == 0 && out[2] == 2 && out[3] == 0);
    assert(out[4] == 0x34 && out[5] == 0x12 && out[6] == 24 && out[7] == 0);
    for (uint32_t i = 0; i < 6; i++) assert(rd32(out + 8 + 4*i) == saved[0][i]);
    assert(!memcmp(saved, ldr_trace_records, sizeof saved) && sends == display_sends);
    memset(out, 0xA5, sizeof out);
    assert(ldr_trace_pack(query, 3, out) == 0 && out[0] == 0xA5);
    query[3] = 128;
    assert(ldr_trace_pack(query, 4, out) == 32 && out[3] == 4 && rd32(out + 8) == 0);
    query[3] = 255;
    assert(ldr_trace_pack(query, 4, out) == 32 && !out[3] && rd32(out + 12) == 24);
    assert(!memcmp(saved, ldr_trace_records, sizeof saved) && sends == display_sends);
    query[0] = 2;
    memset(out, 0xA5, sizeof out);
    assert(ldr_trace_pack(query, 4, out) == 0 && out[0] == 0xA5);
    query[0] = 1;
    ldr_trace_begin(1, 0, 240, display_ticks);
    query[3] = 0;
    assert(ldr_trace_pack(query, 4, out) == 32 && out[3] == 2u && rd32(out + 8) == 0);
    ldr_trace_end(0);
    display_reset(); reset_trace();
    display_ticks = 0xffff0000u;
    ldr_screen_status(LDR_VALIDATING, 0);
    assert(ldr_trace_records[0][1] < ldr_trace_records[0][0]);
    assert(ldr_trace_records[0][1] - ldr_trace_records[0][0] < 250000u * 24u);
    display_reset(); reset_trace();
    display_delay = 24u * 1900u;
    rows = display_rows; ldr_screen_status(LDR_WRITING, 0);
    assert((ldr_trace_records[0][3] & 255u) == display_rows - rows);
    assert(((ldr_trace_records[0][3] >> 8) & 255u) == 1u && !ldr_lcd_failed);
    display_reset(); reset_trace(); display_stall_at = 6; /* first pixel row submitted, not completed */
    ldr_screen_status(LDR_WRITING, 0);
    assert((ldr_trace_records[0][3] & 255u) == 0 && ((ldr_trace_records[0][3] >> 8) & 255u) == 2u);
    assert(display_active && display_cs && ldr_lcd_failed);
    ldr_screen_status(LDR_VALIDATING, 0);
    assert(((ldr_trace_records[1][3] >> 8) & 255u) == 3u);
    display_reset(); reset_trace();
    ldr_trace_count = LDR_TRACE_CAP;
    ldr_screen_status(LDR_WAITING, 0);
    assert(ldr_trace_count == LDR_TRACE_CAP && ldr_trace_overflow && !ldr_trace_active);
    query[3] = 0;
    assert(ldr_trace_pack(query, 4, out) == 32 && out[3] == 1u);
    puts("LCD trace: completed rows, aggregate/transfer/latched stops, wrap, bounded/passive readout PASS");
    return 0;
}
