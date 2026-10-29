/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define FELUCCA_LOADER 1
#define FELUCCA_LDR_LCD_TRACE 1
#define LDR_TRACE_TEST 1
#include "ldr_screen_host.h"
#define main original_ota_contract_main
#pragma GCC diagnostic push
/* The unchanged legacy OTA harness has two signed header comparisons. Keep
 * its existing policy local to the import; new trace code retains -Werror. */
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "ota_test.c"
#pragma GCC diagnostic pop
#undef main
#include "../firmware/loader/ldr_trace_transport.c"
static void query_trace(uint8_t version, uint8_t index)
{
    uint8_t msg[11] = {0, 0x59, 0x3E, 4, 0, 0, version, 0x34, 0x12, index, 0};
    uint32_t sum = 0;
    for (uint32_t i = 6; i < 10; i++) sum += msg[i];
    msg[10] = (uint8_t)~sum;
    host_reply(msg, sizeof msg);
}
int main(void)
{
    uint32_t before[LDR_TRACE_CAP][6], ticks, feeds, sends;
    display_reset();
    ldr_screen_init();
    ldr_screen_status(LDR_WRITING, 0);
    ldr_screen_progress(1, 1);                       /* actual 18-row final progress strip */
    assert(ldr_trace_count == 4);
    memcpy(before, ldr_trace_records, sizeof before);
    query_trace(1, 0);
    ota_service();
    assert(trace_wire_replies == 1 && trace_wire_reply[0] == 1 && trace_wire_reply[2] == 4);
    assert(!trace_wire_reply[3] && trace_wire_reply[4] == 0x34 && trace_wire_reply[5] == 0x12);
    fputs("TRACE_WIRE_FIXTURE=", stdout);
    for (uint32_t i = 0; i < trace_wire_packet_len; i++) printf("%02x", trace_wire_packet[i]);
    putchar('\n');
    assert(!memcmp(before, ldr_trace_records, sizeof before));
    assert(!erases && !requests && !committed);
    query_trace(2, 0);
    ota_service();
    assert(trace_wire_replies == 1);                 /* malformed schema: no response */
    ldr_usb_started = 1;
    ticks = display_ticks; feeds = display_wdt; sends = display_sends;
    query_trace(1, 3);
    ldr_trace_read_window();
    assert(trace_wire_replies == 2 && trace_wire_reply[1] == 3);
    assert(trace_wire_reply[16] == 2 && trace_wire_reply[17] == LDR_WRITING);
    assert(trace_wire_reply[18] == 164 && trace_wire_reply[19] == 182 && trace_wire_reply[20] == 18);
    assert(trace_wire_reply[21] == 0 && trace_wire_reply[22] == 0 && trace_wire_reply[28] == 100);
    /* ldr_ms floors its start/end observations to milliseconds. */
    assert(display_ticks - ticks >= 2999000u * 24u && display_ticks - ticks < 3001000u * 24u);
    assert(display_wdt > feeds && display_usb && display_sends == sends);
    assert(!erases && !requests && !committed && !memcmp(before, ldr_trace_records, sizeof before));
    puts("LCD trace: production OTA frame dispatch/packing, passive readout and bounded watchdog/USB window PASS");
    return 0;
}
